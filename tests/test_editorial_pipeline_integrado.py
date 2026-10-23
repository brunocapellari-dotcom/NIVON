"""E2E offline: extração + curadoria + evidências + preflight sem rede/envio."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nivon.curadoria_radar import hash_documento_candidato
from nivon.editorial_evidencias_pipeline import conciliar_complementos
from nivon.pipeline_briefing import gerar_edicao_offline
from nivon.rss_radar import ler_feed_xml

AGORA = "2026-10-20T10:00:00-03:00"
COLETA = "2026-10-20T08:30:00-03:00"
XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><item><title>Plantio de soja avanca em Mato Grosso</title>
<guid>original-plantio</guid>
<link>https://portal.example.org/noticias/plantio</link>
<pubDate>Tue, 20 Oct 2026 08:00:00 -0300</pubDate>
<description>Plantio de soja avanca no estado em outubro.</description>
</item></channel></rss>"""


def feed():
    extraido = ler_feed_xml(
        XML, fonte_id="PORTAL_EXEMPLO",
        dominios_artigos={"portal.example.org"},
        coletado_em=COLETA,
        url_feed="https://portal.example.org/rss",
    )
    c = extraido["candidatos"][0]
    return {
        "fonte_id": "PORTAL_EXEMPLO",
        "url_feed": "https://portal.example.org/rss",
        "dominios_artigos": ["portal.example.org"],
        "coletado_em": COLETA,
        "politica": {
            "fonte_id": "PORTAL_EXEMPLO", "nome": "Portal sintético",
            "status_direitos": "APROVADA",
            "operacoes": ["LEITURA", "COLETA", "ARMAZENAMENTO",
                         "RESUMO", "PUBLICACAO_DERIVADA"],
            "licenca_id": "LICENCA_TESTE_0001",
        },
        "avaliacoes": {
            hashlib.sha256(c["guid"].encode()).hexdigest(): {
                "fonte_id": "PORTAL_EXEMPLO", "status": "APROVADO",
                "evidencia_id": "DECISAO_EDIT_TESTE_001",
                "documento_sha256": hash_documento_candidato(c),
                "categoria": "SAFRA E PRODUÇÃO",
                "resumo": "O plantio de soja avançou no estado, conforme registro sintético."
            }
        },
    }


def gerar():
    with sqlite3.connect(":memory:") as db:
        return gerar_edicao_offline(
            gerado_em=AGORA, feeds=[feed()],
            snapshots_xml={"PORTAL_EXEMPLO": XML}, db=db,
        )


class TestEditorialPipelineIntegrado(unittest.TestCase):
    def test_evidencia_realmente_captura_raw_feed_ja_processado(self):
        ed = gerar()
        self.assertEqual(ed["estado"], "EDICAO_OFFLINE_PREPARADA_SEM_ENVIO")
        self.assertFalse(ed["enviado"])
        self.assertIn("RESUMO ESTRATÉGICO", ed["texto"])
        pacote = ed["evidencias_editoriais"]
        self.assertEqual(pacote["sha256_edicao"], ed["sha256"])
        self.assertEqual(pacote["estado"], "CANDIDATOS_NAO_HOMOLOGADOS")
        self.assertEqual(len(pacote["noticias"]), 1)
        n = pacote["noticias"][0]
        self.assertEqual(n["sha256_origem"], hashlib.sha256(XML).hexdigest())
        self.assertEqual(n["coletado_em"], COLETA)
        self.assertEqual(n["evidencia_direitos_id"], "LICENCA_TESTE_0001")
        self.assertFalse(n["publicacao_original_verificada"])
        self.assertIsNone(n["evento_id"])
        self.assertEqual(ed["preflight_editorial"]["modo"], "OFFLINE_SEM_ENVIO")
        self.assertFalse(ed["preflight_editorial"]["apto_revisao"])
        self.assertTrue(any("data original" in x
                            for x in ed["preflight_editorial"]["bloqueios"]))

    def test_json_e_cli_consumem_pacote_automatico_sem_segundo_manifesto(self):
        ed = gerar()
        from importlib.util import spec_from_file_location, module_from_spec
        path = Path(__file__).resolve().parents[1] / "scripts" / "validar_briefing_offline.py"
        spec = spec_from_file_location("cli_preflight_test", path)
        modulo = module_from_spec(spec)
        spec.loader.exec_module(modulo)
        with tempfile.TemporaryDirectory() as temp:
            txt, audit = Path(temp)/"briefing.txt", Path(temp)/"auditoria.json"
            txt.write_text(ed["texto"]+"\n", encoding="utf-8")
            audit.write_text(json.dumps({k:v for k,v in ed.items() if k != "texto"},
                                        ensure_ascii=False), encoding="utf-8")
            r = modulo.executar(texto=txt, auditoria=audit)
            self.assertEqual(r["modo"], "OFFLINE_SEM_ENVIO")
            self.assertFalse(r["apto_revisao"])
            self.assertIn("SEM_COTACOES_AUDITADAS", r["bloqueios"])
            self.assertEqual(r["sha256_texto"], ed["sha256"])

    def test_complemento_de_publicacao_original_exige_prova(self):
        pacote = gerar()["evidencias_editoriais"]
        complemento = {
            "sha256_edicao": pacote["sha256_edicao"],
            "noticias": [{"evento_id": "PLANTIO_MT_20261020",
                          "evidencia_evento_id": "REVISAO_EDITORIAL_123",
                          "publicacao_original_verificada": True}],
            "cotacoes": [], "fretes": [],
        }
        with self.assertRaisesRegex(ValueError, "prova externa"):
            conciliar_complementos(pacote, complemento)
        complemento["noticias"][0]["evidencia_publicacao_original_id"] = "FONTE_PUBLISHED_TESTE"
        with self.assertRaisesRegex(ValueError, "ID isolado"):
            conciliar_complementos(pacote, complemento)

    def test_suplemento_nao_substitui_snapshot_de_noticia(self):
        pacote = gerar()["evidencias_editoriais"]
        origem = pacote["noticias"][0]
        complemento = {
            "sha256_edicao": pacote["sha256_edicao"],
            "noticias": [{"titulo": origem["titulo"],
                          "sha256_origem": "e"*64}],
            "cotacoes": [], "fretes": [],
        }
        with self.assertRaisesRegex(ValueError, "imutável"):
            conciliar_complementos(pacote, complemento)

    def test_suplemento_nao_pode_adicionar_noticias_sem_hash(self):
        pacote = gerar()["evidencias_editoriais"]
        with self.assertRaisesRegex(ValueError, "SHA da edição"):
            conciliar_complementos(pacote, {
                "sha256_edicao": "f"*64, "noticias": [{}],
                "cotacoes": [], "fretes": [],
            })
        with self.assertRaisesRegex(ValueError, "tamanho"):
            conciliar_complementos(pacote, {
                "sha256_edicao": pacote["sha256_edicao"],
                "noticias": [{}, {}], "cotacoes": [], "fretes": [],
            })

    def test_registro_excluido_do_briefing_nao_gera_prova_editorial(self):
        ed = gerar()
        self.assertEqual(len(ed["evidencias_editoriais"]["noticias"]), 1)
        # Sem editor externo validando dado de mercado, nenhum preço surge.
        self.assertEqual(ed["evidencias_editoriais"]["cotacoes"], [])
        self.assertEqual(ed["evidencias_editoriais"]["fretes"], [])


if __name__ == "__main__":
    unittest.main()
