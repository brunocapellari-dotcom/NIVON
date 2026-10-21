import hashlib
import json
import sqlite3
import unittest

from nivon.ptax_plano import planejar_consultas_ptax
from nivon.ptax_briefing import LICENCA
from nivon.pipeline_briefing import gerar_edicao_offline, ErroPipelineBriefing


def configuracao(*,boletim="Fechamento", approved=True):
    plano=planejar_consultas_ptax(moeda="USD",inicio="2026-10-19",fim="2026-10-20")[0]
    body=json.dumps({"value":[{"cotacaoCompra":5.1,"cotacaoVenda":5.12,
       "dataHoraCotacao":"2026-10-19 13:00:00","tipoBoletim":boletim}]}).encode()
    return {
        "plano":plano,
        "snapshot":{"fonte_id":"BCB_PTAX","url":plano["url"],
                    "mime":"application/json","conteudo":body,
                    "capturado_em":"2026-10-20T08:30:00-03:00",
                    "sha256":hashlib.sha256(body).hexdigest()},
        "dataset":{"id":"BCB_PTAX","enabled":approved,
                   "collection_authorized":approved,
                   "commercial_redistribution_authorized":approved},
        "direitos":{"status":"APROVADA","licenca":LICENCA,
                    "evidencia_id":"DOCUMENTO_FICTICIO_TESTE_20261020",
                    "attribution_reviewed":True,"share_alike_reviewed":True,
                    "operacoes":["LEITURA","ARMAZENAMENTO",
                               "PUBLICACAO_DERIVADA","REDISTRIBUICAO"]},
    }


class TestPipelinePTAX(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")

    def tearDown(self):
        self.db.close()

    def run_pipeline(self,**extra):
        kwargs={"db":self.db,"feeds":[],"snapshots_xml":{},
                "gerado_em":"2026-10-20T09:00:00-03:00",
                "ptax_snapshots":[configuracao()]}
        kwargs.update(extra)
        return gerar_edicao_offline(**kwargs)

    def test_fechamento_entra_na_secao_cotacao_sem_noticia_falsa(self):
        r=self.run_pipeline()
        self.assertEqual(r["indicadores_incluidos"],1)
        self.assertIn("PTAX fechamento",r["texto"])
        self.assertIn("5.1200",r["texto"])
        self.assertEqual(r["evidencias_cambio"][0]["licenca"],"ODbL-1.0")
        self.assertEqual(len(r["evidencias_cambio"]),1)
        self.assertFalse(r["enviado"])
        self.assertIn("Nenhuma notícia elegível",r["texto"])

    def test_ptax_nao_eleva_boletim_raw_a_ultima_sessao_homologada(self):
        r=self.run_pipeline()
        candidatos=r["evidencias_editoriais"]["cotacoes"]
        self.assertEqual(len(candidatos),1)
        p=candidatos[0]
        self.assertEqual(p["fonte_id"],"BCB_PTAX")
        self.assertEqual(p["grupo"],"CAMBIO")
        self.assertEqual(p["valor"],"5.12")
        self.assertEqual(p["unidade"],"R$/USD")
        self.assertEqual(p["natureza"],"OBSERVADO")
        self.assertEqual(p["competencia"],"2026-10-19")
        self.assertEqual(p["coletado_em"],"2026-10-20T08:30:00-03:00")
        self.assertEqual(p["sha256_origem"],configuracao()["snapshot"]["sha256"])
        self.assertEqual(p["evidencia_direitos_id"],"DOCUMENTO_FICTICIO_TESTE_20261020")
        self.assertEqual(p["sessao_fechamento"],"2026-10-19")
        self.assertIsNone(p["ultima_sessao_concluida"])
        self.assertFalse(p["fechamento_confirmado"])
        self.assertIsNone(p["publicado_em"])
        self.assertIn("R$/USD",r["texto"])
        self.assertFalse(r["preflight_editorial"]["apto_revisao"])
        self.assertTrue(any(x.startswith("COTACAO_0:")
                            for x in r["preflight_editorial"]["bloqueios"]))

    def test_sem_fechamento_nao_publica_interbancario(self):
        with self.assertRaisesRegex(Exception,"Fechamento"):
            self.run_pipeline(ptax_snapshots=[configuracao(boletim="Fechamento Interbancário")])

    def test_dataset_canonicamente_desativado_nao_publica(self):
        with self.assertRaises(PermissionError):
            self.run_pipeline(ptax_snapshots=[configuracao(approved=False)])

    def test_snapshot_corrompido_nao_gera_edicao(self):
        c=configuracao()
        c["snapshot"]["conteudo"]+=b"j"
        with self.assertRaises(Exception):
            self.run_pipeline(ptax_snapshots=[c])

    def test_duas_ptax_mesma_moeda_nao_duplicam(self):
        with self.assertRaises(ErroPipelineBriefing):
            self.run_pipeline(ptax_snapshots=[configuracao(),configuracao()])

    def test_indicadores_do_chamador_permanecem_inalterados(self):
        indices=[]
        self.run_pipeline(indicadores=indices)
        self.assertEqual(indices,[])

    def test_fonte_ptax_manual_mais_auto_nao_passa(self):
        with self.assertRaises(ErroPipelineBriefing):
            self.run_pipeline(fontes_indicadores={"BCB_PTAX":{}})

    def test_sem_ptax_continua_briefing_vazio(self):
        result=self.run_pipeline(ptax_snapshots=[])
        self.assertEqual(result["evidencias_cambio"],[])
        self.assertEqual(result["indicadores_incluidos"],0)


if __name__=="__main__":
    unittest.main()
