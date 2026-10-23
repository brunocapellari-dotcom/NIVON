"""Ensaios ponta a ponta para ZIP anual INMET e resposta adotada ANA simulada.

Percurso: ZIP seguro -> CSV WMO -> parser horário -> RAW SHA/SQLite -> nova
captura e ZIP lineage -> audit/backup; ANA SSO fake request -> JSON ->
QC e suporte temporal preservados. Nenhum HTTP real.
"""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from nivon.fontes_hidro_entrada import (
    preparar_inmet_zip_local, preparar_ana_consulta_adotada, _exigir_ana_permitida,
)
from nivon.pipeline_medicoes_horarias import (
    ErroPipelineAmbiental, abrir_banco_medicoes, importar_ciclo_medicoes,
    auditar_acervo_medicoes, consultar_medicoes_asof,
)
from nivon.pipeline_medicoes_cli import (
    executar_manifesto_medicoes,exportar_backup_medicoes,validar_backup_medicoes,
)
from test_inmet_horario_qc import fixture as inmet_fixture
from test_ana_hidrowebservice import amostra as ana_amostra, pack as ana_pack

T1="2026-10-21T12:00:00Z"
T2="2026-10-22T12:00:00Z"


class FakeResponse:
    status=200
    def __init__(self, raw): self.raw=raw
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.raw[:n]


class FakeTransport:
    def __init__(self,raw):self.raw=raw;self.calls=0;self.url=""
    def open(self,request,timeout):
        self.calls+=1
        self.url=request.full_url
        self.authorization=request.get_header("Authorization")
        return FakeResponse(self.raw)


class TestIntegracaoOrigensINMETANAE2E(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.zip=self.root/"2025.zip"
        self.dbpath=self.root/"medicoes.sqlite"
        self.raw=self.root/"raw"
        self.db=abrir_banco_medicoes(self.dbpath)
        self.addCleanup(self.db.close)

    def gerar_zip(self,*,filename="A904_2025.csv",csv=None):
        with zipfile.ZipFile(self.zip,"w",compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(filename,inmet_fixture() if csv is None else csv)
        return self.zip

    def zip_edition(self,*,capture=T1, observed=T1):
        self.gerar_zip()
        return preparar_inmet_zip_local(
            caminho_zip=self.zip,ano=2025,membro_csv="A904_2025.csv",
            estacao_id="A904",coletado_em=capture,classe="SINTETICO",
            observado_nivon_em=observed)

    def ana_mock(self,*,estado="1"):
        fake=FakeTransport(ana_pack([ana_amostra(estado=estado)]))
        token="T"*60
        edition=preparar_ana_consulta_adotada(
            estacao_id="15400000",zona_estacao="America/Manaus",
            token=token,data_busca="2024-01-01",coletado_em=T1,
            simular=True,transporte=fake,observado_nivon_em=T1)
        self.assertEqual(fake.calls,1)
        self.assertIn("CodigoDaEstacao=15400000",fake.url)
        self.assertEqual(fake.authorization,"Bearer "+token)
        self.assertNotIn(token,str(edition))
        return edition

    def test_zip_e_ana_mock_ate_storage_versionado(self):
        station=self.zip_edition()
        self.assertEqual(station["dataset_id"],"INMET_ESTACOES")
        self.assertEqual(station["container_origem"]["membro_sha256"],station["sha256"])
        self.assertEqual(station["container_origem"]["parent_sha256"],
                         hashlib.sha256(self.zip.read_bytes()).hexdigest())
        hydro=self.ana_mock()
        self.assertEqual(hydro["consulta_api"]["token_armazenado"],False)
        result=importar_ciclo_medicoes(
            self.db,raw_dir=self.raw,edicoes=[station,hydro])
        self.assertEqual(result["arquivos_processados"],2)
        self.assertEqual(result["auditoria"]["medidas_auditadas"],51)
        self.assertEqual(result["auditoria"]["origens_zip_registradas"],1)
        self.assertTrue(result["auditoria"]["integridade_zip_pai_verificavel_pelo_acervo"])
        self.assertEqual(result["auditoria"]["arquivos_zip_integrais_conferidos"],1)
        self.assertEqual(
            hashlib.sha256((self.raw/"origens"/(
                station["container_origem"]["parent_sha256"]+".zip")).read_bytes()).hexdigest(),
            station["container_origem"]["parent_sha256"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM medidas_containers_origem").fetchone()[0],1)
        self.assertEqual(len(list(self.raw.glob("*.raw"))),2)
        rain=consultar_medicoes_asof(
            self.db,raw_dir=self.raw,dataset_id="INMET_ESTACOES",
            estacao_id="A904",metrica="CHUVA_HORA_MM",
            inicio_utc="2025-01-02T00:00:00Z",fim_utc="2025-01-02T23:00:00Z",
            corte_nivon="2026-10-21T13:00:00Z")
        self.assertEqual(len(rain),24)
        self.assertEqual({x["suporte_temporal"] for x in rain},
                         {"HORA_ROTULADA_SEM_CONVENCAO"})
        measures=consultar_medicoes_asof(
            self.db,raw_dir=self.raw,dataset_id="ANA_HIDRO",
            estacao_id="15400000",metrica="COTA_CM",
            inicio_utc="2024-01-02T03:00:00Z",fim_utc="2024-01-02T03:00:00Z",
            corte_nivon="2026-10-21T13:00:00Z")
        self.assertEqual(measures[0]["qualidade_origem"],"SUSPEITO")
        self.assertFalse(measures[0]["qc_externo_homologado"])

    def test_mesmo_csv_em_outra_coleta_e_outra_zip_nao_cria_nova_edicao(self):
        old=self.zip_edition()
        first=importar_ciclo_medicoes(
            self.db,raw_dir=self.raw,edicoes=[old])
        self.assertEqual(first["edicoes"][0]["estado"],"NOVA_EDICAO")
        # CSV identico, container com nome adicional para alterar SHA.
        with zipfile.ZipFile(self.zip,"a",compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("metadados.txt","versao posterior")
        next_version=preparar_inmet_zip_local(
            caminho_zip=self.zip,ano=2025,membro_csv="A904_2025.csv",
            estacao_id="A904",coletado_em=T2,classe="SINTETICO",
            observado_nivon_em=T2)
        self.assertEqual(next_version["sha256"],old["sha256"])
        self.assertNotEqual(
            next_version["container_origem"]["parent_sha256"],
            old["container_origem"]["parent_sha256"])
        result=importar_ciclo_medicoes(
            self.db,raw_dir=self.raw,edicoes=[next_version])
        self.assertEqual(result["edicoes"][0]["estado"],
                         "NOVA_CAPTURA_EDICAO_EXISTENTE")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM medidas_edicoes").fetchone()[0],1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM medidas_containers_origem").fetchone()[0],2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM medidas_capturas").fetchone()[0],2)

    def test_operacao_por_manifesto_zip_ana_json_e_backup_cli(self):
        self.gerar_zip()
        (self.root/"ana.json").write_bytes(ana_pack([ana_amostra()]))
        manifest=self.root/"lotes.json"
        manifest.write_text(json.dumps({
            "schema":"1.0","projeto":"NIVON",
            "lotes":[
                {"arquivo":"2025.zip","formato":"INMET_ANUAL_ZIP",
                 "estacao_id":"A904","ano":2025,"zona":None,
                 "coletado_em":T1,"classe":"SINTETICO",
                 "membro_csv":"A904_2025.csv"},
                {"arquivo":"ana.json","formato":"ANA_ADOTADA_JSON",
                 "estacao_id":"15400000","ano":None,"zona":"America/Manaus",
                 "coletado_em":T1,"classe":"SINTETICO"},
            ]}),encoding="utf-8")
        dry=executar_manifesto_medicoes(manifesto=manifest)
        self.assertEqual(dry["arquivos"],2)
        self.assertEqual(dry["medidas"],51)
        self.assertFalse(self.raw.exists())
        out=executar_manifesto_medicoes(
            manifesto=manifest,modo="executar",banco=self.dbpath,
            raw_dir=self.raw,confirmar_gravacao=True)
        self.assertEqual(out["auditoria"]["origens_zip_registradas"],1)
        again=executar_manifesto_medicoes(
            manifesto=manifest,modo="executar",banco=self.dbpath,
            raw_dir=self.raw,confirmar_gravacao=True)
        self.assertTrue(all(y["estado"]=="REPLAY_SEM_MUDANCA"
                            for y in again["edicoes"]) is False)
        backup=self.root/"bkp"
        result=exportar_backup_medicoes(
            self.db,raw_dir=self.raw,destino=backup)
        self.assertEqual(result["edicoes"],2)
        check=validar_backup_medicoes(caminho=backup)
        self.assertEqual(check["medidas"],51)
        restore=abrir_banco_medicoes(backup/"medicoes.sqlite")
        try:
            self.assertEqual(auditar_acervo_medicoes(
                restore,raw_dir=backup/"raw")["origens_zip_registradas"],1)
        finally:
            restore.close()

    def test_zip_malicioso_ou_estacao_diferente_falha_antes_de_gravar(self):
        with zipfile.ZipFile(self.zip,"w") as z:
            z.writestr("../A904_2025.csv",inmet_fixture())
        with self.assertRaises(Exception):
            preparar_inmet_zip_local(
                caminho_zip=self.zip,ano=2025,membro_csv="../A904_2025.csv",
                estacao_id="A904",coletado_em=T1,classe="SINTETICO",
                observado_nivon_em=T1)
        self.gerar_zip(csv=inmet_fixture(station="A905"))
        with self.assertRaises(Exception):
            preparar_inmet_zip_local(
                caminho_zip=self.zip,ano=2025,membro_csv="A904_2025.csv",
                estacao_id="A904",coletado_em=T1,classe="SINTETICO",
                observado_nivon_em=T1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM medidas_edicoes").fetchone()[0],0)

    def test_corrupcao_do_zip_pai_e_detectada_mesmo_com_csv_raw_intacto(self):
        package=self.zip_edition()
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[package])
        parent=self.raw/"origens"/(package["container_origem"]["parent_sha256"]+".zip")
        parent.write_bytes(b"FALSO_QUE_NAO_E_ZIP")
        with self.assertRaises(ErroPipelineAmbiental):
            auditar_acervo_medicoes(self.db,raw_dir=self.raw)
        self.assertTrue((self.raw/(package["sha256"]+".raw")).exists())

    def test_rollback_da_origem_zip_preserva_acervo_sem_residuos(self):
        station=self.zip_edition()
        wrong=dict(station)
        wrong["visto_nivon_utc"]="2026-10-20T12:00:00+00:00"
        wrong["raw"]=station["raw"]+b"adulterado"
        # Falha detectada antes da cópia, não deixa arquivo original no acervo.
        with self.assertRaises(ErroPipelineAmbiental):
            importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[station,wrong])
        self.assertFalse(self.raw.exists())
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM medidas_edicoes").fetchone()[0],0)

    def test_backup_guarda_zip_original_e_rejeita_adulteracao(self):
        station=self.zip_edition()
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[station])
        folder=self.root/"backup_origem"
        exportar_backup_medicoes(self.db,raw_dir=self.raw,destino=folder)
        zips=list((folder/"raw"/"origens").glob("*.zip"))
        self.assertEqual(len(zips),1)
        self.assertEqual(validar_backup_medicoes(caminho=folder)["edicoes"],1)
        zips[0].write_bytes(b"ZIP_ADULTERADO")
        with self.assertRaises(ErroPipelineAmbiental):
            validar_backup_medicoes(caminho=folder)

    def test_replay_mesma_captura_registra_novo_zip_sem_duplicar_medicao(self):
        original=self.zip_edition()
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[original])
        with zipfile.ZipFile(self.zip,"a",compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("complemento.txt","novo container mesma medicao")
        later=preparar_inmet_zip_local(
            caminho_zip=self.zip,ano=2025,membro_csv="A904_2025.csv",
            estacao_id="A904",coletado_em=T1,
            classe="SINTETICO",observado_nivon_em=T1)
        replay=importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[later])
        self.assertEqual(replay["edicoes"][0]["estado"],"REPLAY_SEM_MUDANCA")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM medidas_containers_origem").fetchone()[0],2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM medidas_capturas").fetchone()[0],1)
        self.assertEqual(auditar_acervo_medicoes(
            self.db,raw_dir=self.raw)["arquivos_zip_integrais_conferidos"],2)

    def test_ana_real_esta_desabilitada_mesmo_com_token_aparentemente_valido(self):
        with self.assertRaises(PermissionError):
            _exigir_ana_permitida()
        with self.assertRaises(PermissionError):
            preparar_ana_consulta_adotada(
                estacao_id="15400000",zona_estacao="America/Manaus",
                token="a"*60,data_busca="2024-01-01",
                coletado_em=T1,simular=False)
        with self.assertRaises(PermissionError):
            preparar_ana_consulta_adotada(
                estacao_id="15400000",zona_estacao="America/Manaus",
                token="a"*60,data_busca="2024-01-01",
                coletado_em=T1,simular=True)
        self.assertFalse(self.raw.exists())

    def test_zip_parent_e_valores_banco_corrompidos_nao_viram_verificados(self):
        edition=self.zip_edition()
        importar_ciclo_medicoes(self.db,raw_dir=self.raw,edicoes=[edition])
        orig=self.db.execute(
            "SELECT parent_sha256 FROM medidas_containers_origem").fetchone()[0]
        self.assertEqual(orig,hashlib.sha256(self.zip.read_bytes()).hexdigest())
        with self.db:
            self.db.execute(
                "UPDATE medidas_containers_origem SET membro_sha256=?",
                ("0"*64,))
        with self.assertRaises(ErroPipelineAmbiental):
            auditar_acervo_medicoes(self.db,raw_dir=self.raw)

if __name__=="__main__":
    unittest.main()
