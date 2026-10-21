"""E2E do benchmark anual IVO usando exclusivamente edições PAM sintéticas."""
import json
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256

from nivon.ivo_pam_publicacoes import EventoPAM
from nivon.ivo_pam_benchmark_anual import (
    ErroBenchmarkAnual, benchmark_pam_anual_sintetico,
)
from nivon.registro_snapshots import abrir_registro, registrar_snapshot
from nivon.sidra_pam import planejar_pam_1612

UTC=timezone.utc
CAT={"datasets":[{"id":"IBGE_PAM","source_id":"IBGE",
                 "enabled":False,"collection_authorized":False,
                 "training_authorized":False}]}


def instante(y,m,d):
    return datetime(y,m,d,12,tzinfo=UTC)


def json_sidra(ano,valor):
    return json.dumps([
        {"D1C":"Município (Código)","D2C":"Variável (Código)",
         "D3C":"Ano (Código)",
         "D4C":"Produto das lavouras temporárias (Código)",
         "V":"Valor","MN":"Unidade de Medida"},
        {"D1C":"5107925","D2C":"214","D3C":str(ano),
         "D4C":"2713","V":str(valor),"MN":"Toneladas"},
    ],ensure_ascii=False).encode()


class TestIVOBenchmarkPAMAnual(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro()
        self.addCleanup(self.db.close)

    def edicao(self,ano,valor,*,tipo="DIVULGACAO",
               publicado=None,coletado=None):
        pub=publicado or date(ano+1,1,10)
        col=coletado or instante(pub.year,pub.month,pub.day+1)
        raw=json_sidra(ano,valor)
        eid=f"PAM_{ano}_{tipo}_{pub.isoformat()}"
        pdf=("%PDF-1.4\n"+eid+" Documento sintetico rastreavel 000000000000").encode()
        p=planejar_pam_1612(municipio_ibge="5107925",ano=ano,
                              codigo_produto_c81="2713",codigo_variavel="214")
        for blob,mime,schema in ((raw,"application/json","sidra_pam_1612_v1"),
                                 (pdf,"application/pdf","ivo_pam_release_doc_v1")):
            registrar_snapshot(
                self.db,CAT,dataset_id="IBGE_PAM",
                sha256=sha256(blob).hexdigest(),tamanho=len(blob),
                mime=mime,schema_versao=schema,
                coletado_em=col.isoformat(),
                competencia=str(ano),referencia=f"{ano}-12-31",
                publicacao=pub.isoformat(),tipo="SINTETICO")
        return EventoPAM(
            id=eid.replace("-","_"),tipo=tipo,plano=p,
            json_original=raw,json_coletado_em=col,
            documento_pdf=pdf,
            documento_url="https://www.ibge.gov.br/pam/dados_anuais.pdf",
            documento_sha256=sha256(pdf).hexdigest(),
            publicado_em=pub,documento_coletado_em=col,
            revisor_id="AUDITOR_TESTE",revisado_em=col)

    def serie(self):
        return {ano:(self.edicao(ano,100+(ano-2015)*10),)
                for ano in range(2015,2026)}

    def rodar(self,series,**extra):
        opts=dict(registro_db=self.db,inicio=2021,fim=2025,
                  corte_avaliacao=instante(2026,12,20),
                  variavel="214",produto="2713",
                  autoriza_experimento=True)
        opts.update(extra)
        return benchmark_pam_anual_sintetico(series,**opts)

    def test_cinco_anos_anual_sem_lookahead(self):
        r=self.rodar(self.serie())
        self.assertEqual(r["folds_validos"],5)
        self.assertEqual(r["calendario"],"ANO_CIVIL")
        self.assertEqual(r["municipio_ibge"],"5107925")
        self.assertEqual(r["mae_baseline"],20.)
        self.assertEqual(r["mae_candidato"],0.)
        self.assertEqual(r["ganho_mae_relativo"],1.)
        self.assertTrue(all(f["horizonte_anos"]==2 for f in r["folds"]))
        self.assertTrue(all(f["ultimo_ano_conhecido"]==f["ano"]-2
                            for f in r["folds"]))
        self.assertTrue(all(f["rotulo_classe"]==
            "ESTATISTICA_PAM_INFORMADA_NAO_CERTIFICADA" for f in r["folds"]))
        self.assertFalse(r["modelo_homologado"])
        self.assertFalse(r["dados_reais_autorizados"])

    def test_errata_tardia_nao_muda_features_da_previsao_antiga(self):
        x=self.serie()
        base=self.rodar(x)
        errata=self.edicao(2020,999.,tipo="ERRATA",
                         publicado=date(2026,6,1),coletado=instante(2026,6,2))
        x[2020]+=(errata,)
        depois=self.rodar(x)
        for a,b in zip(base["folds"],depois["folds"]):
            self.assertEqual(a["labels_treino_shas"],b["labels_treino_shas"])
            self.assertEqual(a["previsao_tendencia_mediana"],
                             b["previsao_tendencia_mediana"])

    def test_primeira_publicacao_e_ultima_revisao_nao_se_confundem(self):
        x=self.serie()
        x[2023]+=(self.edicao(2023,999.,tipo="ERRATA",
                            publicado=date(2026,5,1),
                            coletado=instante(2026,5,2)),)
        primeiro=self.rodar(x)
        ultima=self.rodar(x,verdade="ULTIMA_REVISAO_ATE_CORTE")
        um=next(f for f in primeiro["folds"] if f["ano"]==2023)
        dois=next(f for f in ultima["folds"] if f["ano"]==2023)
        self.assertEqual(um["resultado_publicado"],180.)
        self.assertEqual(dois["resultado_publicado"],999.)
        self.assertEqual(um["previsao_tendencia_mediana"],
                         dois["previsao_tendencia_mediana"])
        self.assertNotEqual(um["erro_candidato"],dois["erro_candidato"])
        self.assertNotEqual(um["rotulo_sha256"],dois["rotulo_sha256"])

    def test_nao_avalia_alvo_sem_liberacao_ate_corte(self):
        x=self.serie()
        r=self.rodar(x,corte_avaliacao=instante(2024,7,1),
                     inicio=2021,fim=2025)
        self.assertEqual([f["ano"] for f in r["folds"]],[2021,2022,2023])
        self.assertTrue(any(p["ano"]==2024 for p in r["folds_ignorados"]))

    def test_treino_com_lacuna_anual_nao_interpolado(self):
        x=self.serie()
        del x[2018]
        r=self.rodar(x,inicio=2021,fim=2021)
        self.assertEqual(r["folds_validos"],0)
        self.assertEqual(r["folds_ignorados"][0]["motivo"],
                         "lacuna entre anos de treino; sem interpolação")

    def test_ausencia_de_treino_e_reportada_sem_chute(self):
        x={2025:(self.edicao(2025,999.),)}
        r=self.rodar(x)
        self.assertEqual(r["folds_validos"],0)
        self.assertIsNone(r["mae_candidato"])
        self.assertIsNone(r["wape_baseline"])

    def test_autorizacao_explicita_obrigatoria(self):
        x=self.serie()
        with self.assertRaises(PermissionError):
            self.rodar(x,autoriza_experimento=False)

    def test_fonte_municipio_diferente_bloqueado(self):
        x=self.serie()
        p=planejar_pam_1612(municipio_ibge="5105259",ano=2025,
                           codigo_produto_c81="2713",codigo_variavel="214")
        x[2025]=(replace(x[2025][0],plano=p),)
        with self.assertRaises(ErroBenchmarkAnual):
            self.rodar(x)

    def test_fonte_cultura_diferente_bloqueada(self):
        x=self.serie()
        p=planejar_pam_1612(municipio_ibge="5107925",ano=2024,
                           codigo_produto_c81="100",codigo_variavel="214")
        x[2024]=(replace(x[2024][0],plano=p),)
        with self.assertRaises(ErroBenchmarkAnual):
            self.rodar(x)

    def test_ano_reclassificado_bloqueado(self):
        x=self.serie()
        outra=planejar_pam_1612(municipio_ibge="5107925",ano=2021,
                                 codigo_produto_c81="2713",codigo_variavel="214")
        x[2020]=(replace(x[2020][0],plano=outra),)
        with self.assertRaises(ErroBenchmarkAnual):
            self.rodar(x)

    def test_tipo_real_em_snapshot_rejeitado(self):
        x=self.serie()
        # Fixture insegura: altera a classe no banco sem mudar o arquivo.
        self.db.execute("""UPDATE nivon_snapshots SET tipo='REAL_AUTORIZADO',
                            evidencia_direitos='SIMULACAO' WHERE competencia='2020'""")
        with self.assertRaises(PermissionError):
            self.rodar(x)

    def test_artefato_real_futuro_nao_pode_ficar_oculto_no_pacote(self):
        x=self.serie()
        # Errata posterior ao corte: mesmo sem entrar em fold, a presença
        # de artefato REAL deve invalidar o experimento sintético inteiro.
        futura=self.edicao(2024,999.,tipo="ERRATA",
                          publicado=date(2027,1,1),
                          coletado=instante(2027,1,2))
        x[2024]+=(futura,)
        self.db.execute(
            "UPDATE nivon_snapshots SET tipo='REAL_AUTORIZADO', "
            "evidencia_direitos='NAO_HOMOLOGADO' WHERE sha256=?",
            (futura.documento_sha256,))
        with self.assertRaises(PermissionError):
            self.rodar(x)

    def test_snapshot_futuro_ausente_bloqueia_pacote(self):
        x=self.serie()
        futura=self.edicao(2024,999.,tipo="ERRATA",
                           publicado=date(2027,1,1),
                           coletado=instante(2027,1,2))
        x[2024]+=(futura,)
        self.db.execute(
            "UPDATE nivon_snapshots SET sha256=? WHERE sha256=?",
            ("f"*64,futura.documento_sha256))
        with self.assertRaises(PermissionError):
            self.rodar(x)

    def test_rejeita_corte_sem_timezone(self):
        x=self.serie()
        with self.assertRaises(ErroBenchmarkAnual):
            self.rodar(x,corte_avaliacao=datetime(2026,12,20))

    def test_rejeita_verdade_nao_suportada(self):
        x=self.serie()
        with self.assertRaises(ErroBenchmarkAnual):
            self.rodar(x,verdade="REVISAO_FUTURA")

    def test_menor_amostra_minima_rejeitada(self):
        x=self.serie()
        with self.assertRaises(ErroBenchmarkAnual):
            self.rodar(x,minimo_anos_treino=2)

    def test_futuro_nao_pode_entrar_no_treino(self):
        x=self.serie()
        x[2022]+=(self.edicao(2022,999.,tipo="ERRATA",
                      publicado=date(2026,9,1),
                      coletado=instante(2026,9,2)),)
        a=self.rodar(self.serie())
        b=self.rodar(x)
        self.assertEqual([f["labels_treino_shas"] for f in a["folds"]],
                         [f["labels_treino_shas"] for f in b["folds"]])


if __name__=="__main__":
    unittest.main()
