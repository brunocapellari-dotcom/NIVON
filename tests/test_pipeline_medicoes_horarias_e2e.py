"""Aceitação E2E das fontes horárias INMET e ANA no mesmo acervo.

Demonstra RAW -> parsers originais -> transação SQLite -> vintages por captura
-> revisão -> backup/restore -> CLI. Fontes sintéticas; rede proibida.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nivon.pipeline_medicoes_horarias import (
    ErroPipelineAmbiental, preparar_arquivo_medicoes, abrir_banco_medicoes,
    importar_ciclo_medicoes, consultar_medicoes_asof, auditar_acervo_medicoes,
    relatorio_revisoes_medicoes,
)
from nivon.pipeline_medicoes_cli import (
    executar_manifesto_medicoes, exportar_backup_medicoes, validar_backup_medicoes,
)
from test_inmet_horario_qc import fixture as inmet_fixture
from test_ana_hidrowebservice import amostra as ana_amostra, pack as ana_pack

T1="2026-10-21T12:00:00Z"
T2="2026-10-22T12:00:00Z"
CUT1="2026-10-21T13:00:00Z"
CUT2="2026-10-22T13:00:00Z"
CUT_BEFORE="2026-10-20T13:00:00Z"
DATA_INMET="2025-01-02T00:00:00Z"
DATA_ANA="2024-01-02T03:00:00Z"


def build_inmet(*, raw=None, visto=T1, estacao="A904"):
    return preparar_arquivo_medicoes(
        formato="INMET_HORARIO_CSV",raw=inmet_fixture() if raw is None else raw,
        estacao_id=estacao,ano=2025,zona=None,
        coletado_em=visto,classe="SINTETICO",observado_nivon_em=visto)


def build_ana(*, raw=None, visto=T1):
    return preparar_arquivo_medicoes(
        formato="ANA_ADOTADA_JSON",raw=ana_pack([ana_amostra()]) if raw is None else raw,
        estacao_id="15400000",ano=None,zona="America/Manaus",
        coletado_em=visto,classe="SINTETICO",observado_nivon_em=visto)


def files_manifest(folder):
    (folder/"inmet_2025.csv").write_bytes(inmet_fixture())
    (folder/"ana_2024.json").write_bytes(ana_pack([ana_amostra()]))
    src={
        "schema":"1.0","projeto":"NIVON","lotes":[
            {"arquivo":"inmet_2025.csv","formato":"INMET_HORARIO_CSV",
             "estacao_id":"A904","ano":2025,"zona":None,
             "coletado_em":T1,"classe":"SINTETICO"},
            {"arquivo":"ana_2024.json","formato":"ANA_ADOTADA_JSON",
             "estacao_id":"15400000","ano":None,"zona":"America/Manaus",
             "coletado_em":T1,"classe":"SINTETICO"},
        ],
    }
    path=folder/"lotes.json"
    path.write_text(json.dumps(src),encoding="utf-8")
    return path


class TestPipelineINMETANAE2E(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.dbpath=self.folder/"ambiental.sqlite"
        self.raw=self.folder/"raw"
        self.db=abrir_banco_medicoes(self.dbpath)
        self.addCleanup(self.db.close)

    def test_ciclo_duas_fontes_51_medicoes_preserva_suporte(self):
        result=importar_ciclo_medicoes(
            self.db,raw_dir=self.raw,edicoes=[build_inmet(),build_ana()])
        self.assertEqual(result["estado"],"CICLO_INMET_ANA_ATOMICO_LOCAL")
        self.assertEqual(result["arquivos_processados"],2)
        self.assertEqual(result["auditoria"]["edicoes_auditadas"],2)
        self.assertEqual(result["auditoria"]["medidas_auditadas"],51)
        self.assertEqual(result["http"],0)
        self.assertFalse(result["modelo_preditivo_homologado"])
        rain=consultar_medicoes_asof(
            self.db,raw_dir=self.raw,dataset_id="INMET_ESTACOES",
            estacao_id="A904",metrica="CHUVA_HORA_MM",
            inicio_utc=DATA_INMET,fim_utc="2025-01-02T23:00:00Z",
            corte_nivon=CUT1)
        self.assertEqual(len(rain),24)
        self.assertEqual(sum(row["valor"] for row in rain),36.0)
        self.assertEqual(
            {x["suporte_temporal"] for x in rain},
            {"HORA_ROTULADA_SEM_CONVENCAO"})
        self.assertTrue(all(not row["qc_externo_homologado"] for row in rain))
        hydro=consultar_medicoes_asof(
            self.db,raw_dir=self.raw,dataset_id="ANA_HIDRO",
            estacao_id="15400000",metrica="VAZAO_M3_S",
            inicio_utc=DATA_ANA,fim_utc=DATA_ANA,corte_nivon=CUT1)
        self.assertEqual(len(hydro),1)
        self.assertEqual(hydro[0]["valor"],13225.42)
        self.assertIn("NAO_HOMOLOGADO",hydro[0]["suporte_temporal"])
        self.assertFalse(hydro[0]["disponibilidade_passada_certificada"])

    def test_inmet_23_horas_nao_pode_virar_chuva_diaria(self):
        package=build_inmet(raw=inmet_fixture(hours=23))
        self.assertEqual(len(package["registros"]),46)
        self.assertNotIn("CHUVA_DIA_MM",{row[1] for row in package["registros"]})
        self.assertNotIn("VAZAO_MEDIA_DIA_M3_S",{row[1] for row in package["registros"]})

    def test_ana_qc_suspeito_e_ruim_ficam_separados(self):
        raw=ana_pack([ana_amostra(estado="1")])
        pacote=build_ana(raw=raw)
        cols={x[1]:x[4] for x in pacote["registros"]}
        self.assertEqual(cols["COTA_CM"],"SUSPEITO")
        self.assertEqual(cols["VAZAO_M3_S"],"APROVADO")
        self.assertTrue(all(x[5].startswith("INSTANTANEO") for x in pacote["registros"]))
        self.assertFalse(pacote["completude_qc_homologada"])

    def test_consulta_nao_retroage_ingestao_para_medicao_antiga(self):
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,
                                edicoes=[build_inmet()])
        def query(cut):
            return consultar_medicoes_asof(
                self.db,raw_dir=self.raw,dataset_id="INMET_ESTACOES",
                estacao_id="A904",metrica="CHUVA_HORA_MM",
                inicio_utc=DATA_INMET,fim_utc="2025-01-02T23:00:00Z",
                corte_nivon=cut)
        self.assertEqual(query(CUT_BEFORE),[])
        self.assertEqual(len(query(CUT1)),24)

    def test_revisao_incremental_sem_substituir_historico(self):
        first=build_inmet()
        revised=build_inmet(
            raw=inmet_fixture().replace(b"1,5",b"2,5",1),visto=T2)
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[first])
        result=importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[revised])
        self.assertEqual(result["edicoes"][0]["estado"],"NOVA_EDICAO")
        def query(cut):
            return consultar_medicoes_asof(
                self.db,raw_dir=self.raw,dataset_id="INMET_ESTACOES",
                estacao_id="A904",metrica="CHUVA_HORA_MM",
                inicio_utc=DATA_INMET,fim_utc=DATA_INMET,corte_nivon=cut)
        self.assertEqual(query(CUT1)[0]["valor"],1.5)
        self.assertEqual(query(CUT2)[0]["valor"],2.5)
        self.assertEqual(len(list(self.raw.glob("*.raw"))),2)

    def test_replay_e_reinicio_do_banco(self):
        raw=build_inmet()
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[raw])
        again=importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[raw])
        self.assertEqual(again["edicoes"][0]["estado"],"REPLAY_SEM_MUDANCA")
        self.assertEqual(again["auditoria"]["capturas_auditadas"],1)
        other=abrir_banco_medicoes(self.dbpath)
        self.addCleanup(other.close)
        self.assertEqual(auditar_acervo_medicoes(other,raw_dir=self.raw)["medidas_auditadas"],48)

    def test_falha_depois_primeiro_arquivo_desfaz_todos(self):
        a,b=build_inmet(),build_ana()
        invalid=dict(b)
        invalid["estacao_id"]="15400001"
        invalid["sha256"]=a["sha256"]
        invalid["raw"]=a["raw"]
        # Força conflito de identidade entre duas edições com mesmo SHA.
        with self.assertRaises(ErroPipelineAmbiental):
            importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[a,invalid])
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM medidas_edicoes").fetchone()[0],0)
        self.assertFalse(list(self.raw.glob("*.raw")))

    def test_adulteracao_de_raw_e_de_sqlite_detectadas(self):
        edition=build_inmet()
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[edition])
        raw_path=self.raw/(edition["sha256"]+".raw")
        contents=raw_path.read_bytes()
        raw_path.write_bytes(b"CORROMPIDO")
        with self.assertRaises(ErroPipelineAmbiental):
            auditar_acervo_medicoes(self.db,raw_dir=self.raw)
        raw_path.write_bytes(contents)
        with self.db:
            self.db.execute(
                "UPDATE medidas_registros SET valor=55 WHERE sha256=?",
                (edition["sha256"],))
        with self.assertRaisesRegex(ErroPipelineAmbiental,"divergem"):
            auditar_acervo_medicoes(self.db,raw_dir=self.raw)

    def test_backup_completo_e_bloqueio_de_backup_corrompido(self):
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,
                                edicoes=[build_inmet(),build_ana()])
        bkp=self.folder/"backup"
        x=exportar_backup_medicoes(self.db,raw_dir=self.raw,destino=bkp)
        self.assertEqual(x["edicoes"],2)
        self.assertEqual(validar_backup_medicoes(caminho=bkp)["medidas"],51)
        with self.assertRaises(ErroPipelineAmbiental):
            exportar_backup_medicoes(self.db,raw_dir=self.raw,destino=bkp)
        raw_one=next((bkp/"raw").glob("*.raw"))
        raw_one.write_bytes(b"FALSO")
        with self.assertRaises(ErroPipelineAmbiental):
            validar_backup_medicoes(caminho=bkp)

    def test_relatorio_distingue_revisao_de_tendencia_de_chuva(self):
        first=build_inmet()
        revised=build_inmet(
            raw=inmet_fixture().replace(b"1,5",b"2,5",1),visto=T2)
        importar_ciclo_medicoes(
            self.db,raw_dir=self.raw,edicoes=[first,revised])
        before=relatorio_revisoes_medicoes(
            self.db,raw_dir=self.raw,dataset_id="INMET_ESTACOES",
            estacao_id="A904",corte_em=CUT1)
        after=relatorio_revisoes_medicoes(
            self.db,raw_dir=self.raw,dataset_id="INMET_ESTACOES",
            estacao_id="A904",corte_em=CUT2)
        self.assertIsNone(before["snapshot_anterior_sha256"])
        self.assertEqual(before["medidas_revisadas"],0)
        self.assertEqual(after["medidas_revisadas"],1)
        self.assertEqual(after["medidas_novas"],0)
        self.assertEqual(after["medidas_ausentes_na_nova_edicao"],0)
        self.assertEqual(after["revisoes_amostradas"][0]["anterior"],1.5)
        self.assertEqual(after["revisoes_amostradas"][0]["atual"],2.5)
        self.assertFalse(after["tendencia_clima_ou_vazao_inferida"])
        self.assertFalse(after["homologado"])

    def test_relatorio_ana_preserva_qc_e_detecta_mudanca_status(self):
        original=build_ana(raw=ana_pack([ana_amostra(estado="1")]))
        revised=build_ana(raw=ana_pack([ana_amostra(estado="0")]),visto=T2)
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[original,revised])
        report=relatorio_revisoes_medicoes(
            self.db,raw_dir=self.raw,dataset_id="ANA_HIDRO",
            estacao_id="15400000",corte_em=CUT2)
        self.assertEqual(report["mudancas_qc_declarado"],1)
        self.assertEqual(report["medidas_revisadas"],1)
        self.assertFalse(report["evidencia_regime_temporal_validada"])
        self.assertFalse(report["reconstrucao_publicacao_historica"])
        self.assertFalse(report["homologado"])

    def test_relatorio_cli_usa_corte_sem_criar_alegacao_de_homologacao(self):
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,
                                edicoes=[build_inmet()])
        cmd=[sys.executable,"-m","nivon.pipeline_medicoes_cli","relatorio",
             "--banco",str(self.dbpath),"--raw-dir",str(self.raw),
             "--dataset-id","INMET_ESTACOES","--estacao-id","A904",
             "--corte-em",CUT1]
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        out=json.loads(result.stdout)
        self.assertEqual(out["total_medidas_atuais"],48)
        self.assertFalse(out["tendencia_clima_ou_vazao_inferida"])
        self.assertFalse(out["homologado"])

    def test_cli_processa_tudo_num_unico_lote_e_gera_backup(self):
        inputs=self.folder/"entrada"
        inputs.mkdir()
        manifest=files_manifest(inputs)
        dry=executar_manifesto_medicoes(manifesto=manifest)
        self.assertEqual(dry["estado"],"PREFLIGHT_INMET_ANA_OK")
        self.assertEqual(dry["medidas"],51)
        self.assertEqual(dry["gravacoes"],0)
        with self.assertRaises(PermissionError):
            executar_manifesto_medicoes(
                manifesto=manifest,modo="executar",
                banco=self.dbpath,raw_dir=self.raw)
        cmd=[sys.executable,"-m","nivon.pipeline_medicoes_cli"]
        def run(*parts):
            p=subprocess.run([*cmd,*parts],capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stderr+p.stdout)
            return json.loads(p.stdout)
        # Fecha handle do banco de teste antes de abrir outro processo.
        self.db.close()
        self.db=abrir_banco_medicoes(self.dbpath)
        data=run("executar","--manifesto",str(manifest),
                 "--banco",str(self.dbpath),"--raw-dir",str(self.raw),
                 "--confirmar-gravacao")
        self.assertEqual(data["auditoria"]["medidas_auditadas"],51)
        check=run("auditar","--banco",str(self.dbpath),
                  "--raw-dir",str(self.raw))
        self.assertEqual(check["edicoes_auditadas"],2)
        backup=self.folder/"exportacao_cli"
        x=run("backup","--banco",str(self.dbpath),
              "--raw-dir",str(self.raw),"--destino-backup",str(backup))
        self.assertEqual(x["medidas"],51)
        verified=run("validar-backup","--destino-backup",str(backup))
        self.assertEqual(verified["estado"],"BACKUP_INMET_ANA_RESTAURAVEL")

    def test_rede_nao_foi_incluida_como_requisito(self):
        # Nenhum transport HTTP no pipeline; entradas são bytes de arquivos.
        import inspect
        from nivon import pipeline_medicoes_horarias as p
        src=inspect.getsource(p)
        self.assertNotIn("urlopen(",src)
        self.assertNotIn("opener.open(",src)


if __name__=="__main__":
    unittest.main()
