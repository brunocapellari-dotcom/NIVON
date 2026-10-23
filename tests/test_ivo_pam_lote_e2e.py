"""E2E PAM em lote: dados sintéticos -> quarentena -> auditoria -> fila de revisão.

Teste de integração entre módulos reais, sem internet ou credenciais.
"""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from nivon.ivo_pam_operacao_lote import (
    ErroLotePAM, PedidoPAM, executar_lote_pam_offline,
)
from nivon.ivo_pam_gate_promocao import ErroRevisaoPAM, preparar_fila_revisao_pam
from nivon.sidra_pam import planejar_pam_1612

T = datetime(2026, 10, 21, 15, tzinfo=timezone.utc)
CAT = {"datasets": [{"id": "IBGE_PAM", "source_id": "IBGE",
                    "enabled": True, "collection_authorized": True,
                    "training_authorized": False}]}
RIGHTS = {"operacoes": frozenset({"COLETA", "ARMAZENAMENTO"}),
          "evidencia_ref": "TERMO_FICTICIO_TESTE_ISOLADO"}


def pedido(m="5107958", ano=2021, produto="2713", variavel="214", **kw):
    return PedidoPAM(m, ano, produto, variavel, **kw)


def sidra(p, valor="150"):
    return json.dumps([
        {"D1C": "Município (Código)", "D2C": "Variável (Código)",
         "D3C": "Ano (Código)",
         "D4C": "Produto das lavouras temporárias (Código)",
         "V": "Valor", "MN": "Unidade de Medida"},
        {"D1C": p.municipio_ibge, "D2C": p.variavel, "D3C": str(p.ano),
         "D4C": p.categoria_c81, "V": valor,
         "MN": "Toneladas" if p.variavel == "214" else "Hectares"},
    ], ensure_ascii=False).encode("utf-8")


def url(p):
    return planejar_pam_1612(
        municipio_ibge=p.municipio_ibge, ano=p.ano,
        codigo_produto_c81=p.categoria_c81, codigo_variavel=p.variavel,
    )["url"]


class TestOperacaoPAMLoteIntegrado(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "quarentena"
        self.a = pedido()
        self.b = pedido("3503109", 2020, "2714")
        self.responses = {
            url(self.a): (sidra(self.a), "application/json"),
            url(self.b): (sidra(self.b, "345"), "application/json"),
        }
        self.calls = []

    def transport(self, uri, maximum, timeout):
        self.calls.append(uri)
        return self.responses[uri]

    def run_batch(self, pedidos=None, **kwargs):
        opts = dict(
            pedidos=[self.a, self.b] if pedidos is None else pedidos,
            catalogo=CAT, direitos=RIGHTS, raiz=self.root,
            coletado_em=T, transporte=self.transport,
        )
        opts.update(kwargs)
        return executar_lote_pam_offline(**opts)

    def test_fluxo_multirrecorte_completo_ate_fila_sem_promocao(self):
        manifest = self.run_batch()
        self.assertEqual(manifest["solicitados"], 2)
        self.assertEqual(manifest["processados"], 2)
        self.assertEqual(manifest["auditorias"], 2)
        self.assertEqual(manifest["falhas"], 0)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(set(self.calls), {url(self.a), url(self.b)})
        self.assertFalse(manifest["ledger_canonico_modificado"])
        self.assertFalse(manifest["homologacao_externa_comprovada"])
        self.assertEqual(manifest["promocoes_realizadas"], 0)
        self.assertFalse(manifest["treino_executado"])
        self.assertNotIn("valor_candidato_nao_certificado", str(manifest))
        fila = preparar_fila_revisao_pam(manifest)
        self.assertEqual(fila["quantidade_pendente"], 2)
        self.assertEqual(fila["quantidade_falhas_na_coleta"], 0)
        self.assertFalse(fila["registro_canonico_autorizado"])
        self.assertFalse(fila["provas_externas_verificadas"])
        self.assertEqual(len(list((self.root / "objetos_sha256").iterdir())), 2)
        self.assertEqual(len(list((self.root / "recibos").iterdir())), 2)

    def test_repeticao_idempotente_preserva_hashes_e_recibos(self):
        first = self.run_batch()
        second = self.run_batch()
        self.assertEqual(first, second)
        self.assertEqual(
            preparar_fila_revisao_pam(first),
            preparar_fila_revisao_pam(second),
        )
        self.assertEqual(len(list((self.root / "objetos_sha256").iterdir())), 2)
        self.assertEqual(len(list((self.root / "recibos").iterdir())), 2)
        # O transporte de teste ainda é invocado a cada execução.
        self.assertEqual(len(self.calls), 4)

    def test_marcador_sigilo_e_auditado_sem_virar_numero_realizado(self):
        self.responses[url(self.a)] = (sidra(self.a, "X"), "application/json")
        manifest = self.run_batch(pedidos=[self.a])
        self.assertEqual(manifest["auditorias"], 1)
        self.assertEqual(manifest["resultados"][0]["estado_valor"], "SUPRIMIDO_SIGILO")
        self.assertIn("VALOR_SIDRA_MARCADOR_NAO_EXATO",
                      manifest["resultados"][0]["bloqueios"])
        self.assertFalse(preparar_fila_revisao_pam(manifest)["treinamento_autorizado"])

    def test_falha_de_um_municipio_nao_anula_outro_mas_nunca_promove(self):
        self.responses[url(self.b)] = (b"<html>falha</html>", "text/html")
        manifest = self.run_batch()
        self.assertEqual(manifest["auditorias"], 1)
        self.assertEqual(manifest["falhas"], 1)
        self.assertEqual(manifest["processados"], 2)
        self.assertEqual(manifest["resultados"][1]["estado"], "ERRO_OPERACIONAL_ISOLADO")
        self.assertEqual(manifest["resultados"][1]["erro_classe"], "ErroColetaPAM")
        fila = preparar_fila_revisao_pam(manifest)
        self.assertEqual(fila["quantidade_pendente"], 1)
        self.assertEqual(fila["quantidade_falhas_na_coleta"], 1)
        self.assertFalse(fila["registro_canonico_autorizado"])

    def test_politica_de_falha_interrompe_depois_da_primeira(self):
        self.responses[url(self.a)] = (b"{}", "application/json")
        manifest = self.run_batch(continuar_apos_falha=False)
        self.assertEqual(manifest["processados"], 1)
        self.assertEqual(manifest["solicitados"], 2)
        self.assertEqual(manifest["falhas"], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(preparar_fila_revisao_pam(manifest)["quantidade_pendente"], 0)

    def test_pdf_sintetico_anexado_nao_prova_valor_ou_licenca(self):
        pdf = "https://biblioteca.ibge.gov.br/visualizacao/pam/anexo.pdf"
        self.responses[pdf] = (b"%PDF-1.4\nsynthetic example", "application/pdf")
        manifest = self.run_batch(
            pedidos=[replace(self.a, pdf_url=pdf,
                             publicacao_declarada="2026-09-17")],
        )
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(manifest["auditorias"], 1)
        self.assertIsNotNone(manifest["resultados"][0]["recibo_pdf_sha256"])
        fila = preparar_fila_revisao_pam(manifest)
        self.assertFalse(fila["pode_publicar"])
        self.assertIn("DATA_DE_PUBLICACAO_E_VINTAGE_ATESTADOS",
                      fila["itens_pendentes"][0]["provas_independentes_pendentes"])

    def test_pdf_falho_preserva_candidato_parcial_na_quarentena(self):
        pdf = "https://biblioteca.ibge.gov.br/visualizacao/pam/anexo.pdf"
        self.responses[pdf] = (b"<html>", "text/html")
        manifest = self.run_batch(pedidos=[replace(self.a, pdf_url=pdf)])
        self.assertEqual(manifest["falhas"], 1)
        self.assertEqual(manifest["auditorias"], 0)
        self.assertTrue(manifest["resultados"][0]["dados_parciais_em_quarentena_possiveis"])
        self.assertEqual(len(list((self.root / "objetos_sha256").iterdir())), 1)
        self.assertEqual(preparar_fila_revisao_pam(manifest)["quantidade_pendente"], 0)

    def test_quota_atingida_falha_sem_promover(self):
        raw = sidra(self.a) + b" " * 1500
        self.responses[url(self.a)] = (raw, "application/json")
        manifest = self.run_batch(pedidos=[self.a], limite_total_bytes=1024)
        self.assertEqual(manifest["falhas"], 1)
        self.assertEqual(manifest["auditorias"], 0)
        self.assertEqual(manifest["promocoes_realizadas"], 0)

    def test_sem_transporte_real_e_sem_direitos_nao_toca_disco(self):
        for override in (
            {"transporte": None},
            {"direitos": {}},
            {"catalogo": {"datasets": [dict(CAT["datasets"][0], enabled=False)]}},
            {"coletado_em": T.replace(tzinfo=None)},
        ):
            with self.subTest(override=override):
                with self.assertRaises(ErroLotePAM):
                    self.run_batch(**override)
                self.assertFalse(self.root.exists())
        self.assertEqual(self.calls, [])

    def test_preflight_nega_lote_inteiro_duplicado_ou_invalido(self):
        invalid = (
            [self.a, self.a],
            [self.a, pedido(variavel="999")],
            [self.a, pedido("510795", 2021, "2713")],
            [self.a, replace(self.b, pdf_url="https://evil.test/a.pdf")],
            [self.a, replace(self.b, versao_anterior_sha256="fake")],
            [self.a, replace(self.b, publicacao_declarada="2026-13-01")],
            [self.a] * 26,
        )
        for pedidos in invalid:
            with self.subTest(pedidos=repr(pedidos)[:80]):
                with self.assertRaises(ErroLotePAM):
                    self.run_batch(pedidos=pedidos)
                self.assertFalse(self.root.exists())
        self.assertEqual(self.calls, [])

    def test_manifesto_tamper_hash_recusado_na_fila(self):
        manifest = self.run_batch()
        manifest["resultados"][0]["recibo_sha256"] = "0" * 64
        with self.assertRaises(ErroRevisaoPAM):
            preparar_fila_revisao_pam(manifest)

    def test_manifesto_ressinado_pelo_usuario_nao_finge_homologacao(self):
        manifest = self.run_batch()
        manifest["promocoes_realizadas"] = 1
        copy = dict(manifest)
        copy.pop("manifesto_sha256")
        manifest["manifesto_sha256"] = hashlib.sha256(
            json.dumps(copy, ensure_ascii=False, sort_keys=True,
                       allow_nan=False, separators=(",", ":")).encode(),
        ).hexdigest()
        with self.assertRaises(ErroRevisaoPAM):
            preparar_fila_revisao_pam(manifest)

    def test_usuario_nao_pode_mudar_estado_para_aprovado(self):
        manifest = self.run_batch()
        manifest["resultados"][0]["passivel_promocao"] = True
        copy = dict(manifest)
        copy.pop("manifesto_sha256")
        manifest["manifesto_sha256"] = hashlib.sha256(
            json.dumps(copy, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode(),
        ).hexdigest()
        with self.assertRaises(ErroRevisaoPAM):
            preparar_fila_revisao_pam(manifest)

    def test_nao_ha_sqlite_canonico_gerado_pelo_lote(self):
        self.run_batch()
        self.assertEqual(list(self.root.rglob("*.sqlite")), [])
        self.assertEqual(list(self.root.rglob("*.db")), [])
        self.assertEqual(list(self.root.rglob("*.csv")), [])


if __name__ == "__main__":
    unittest.main()
