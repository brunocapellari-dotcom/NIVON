"""Regressoes integradas: consulta IVO nao e direito de publicar/entregar.

Sem rede, LLM, coleta real ou remessa. Os grants e fontes sao apenas fixtures.
"""
import unittest
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from nivon.briefing_composto import DireitoEntrega, montar_briefing, solicitar_entrega
from nivon.ivo_conhecimento_adapter import ClaimCurado
from nivon.ivo_pacote_evidencias import ContextoAcessoIVO, montar_pacote_evidencias

T = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
DOC = sha256(b"fixture-only-annual-record").hexdigest()
SRC = "IBGE_PAM_FIXTURE"


def claim():
    return ClaimCurado(
        claim_id="PAM-1", texto="Soja em estudo anual por municipio",
        dominio="AGRICULTURA", fonte_id=SRC,
        fonte_url="https://www.ibge.gov.br",
        documento_sha256=DOC, competencia="2025",
        referencia_em=T-timedelta(days=8),
        publicado_em=T-timedelta(days=7),
        coletado_em=T-timedelta(days=6),
        validado_em=T-timedelta(days=5),
        aprovado_por="AUDITORIA_FIXTURE", auditoria_id="AUD-1",
        tipo="DADO_OBSERVADO", status="APROVADO",
        direitos_aprovados=True,
    )


def consultar():
    # Retorno consultivo meramente simulado, NAO autoriza publicacao.
    return montar_pacote_evidencias(
        pergunta="soja estudo anual",
        contexto=ContextoAcessoIVO(
            tenant="TENANT", projeto="NIVON", ator="actor", corte=T
        ),
        claims=[claim()],
        autorizador=lambda ctx, c, action: action == "CONSULTAR_EVIDENCIA",
        planejador=lambda _: {"frentes": [{"id": "SOJA"}], "intencao": "CONSULTA"},
    )


def briefing(operacoes, *, referencia=None):
    return montar_briefing(
        noticias=[], fontes={
            SRC: {"status_direitos": "APROVADA", "operacoes": list(operacoes)}
        },
        data=T.isoformat(), indicadores=[{
            "fonte_id": SRC, "secao": "SAFRA",
            "titulo": "Producao anual de soja (dado sintetico)",
            "valor": "100", "fonte": "IBGE fixture",
            "referencia": (referencia or (T-timedelta(days=8))).isoformat(),
        }],
    )


class TestIntegracaoIVOBriefing(unittest.TestCase):
    def test_consulta_nao_da_direito_de_publicacao(self):
        pacote = consultar()
        self.assertEqual(pacote["status"], "PACOTE_CONSULTIVO_SEM_RESPOSTA_GERADA")
        self.assertEqual(len(pacote["evidencias"]), 1)
        self.assertTrue(pacote["evidencias"][0]["direito_apenas_consulta"])
        res = briefing({"LEITURA"})
        self.assertEqual(res["indicadores_incluidos"], 0)
        self.assertNotIn("Producao anual", res["texto"])
        self.assertTrue(any("publicação não autorizada" in item["motivo"]
                            for item in res["rejeicoes"]))

    def test_publicacao_somente_com_direito_explicito_e_frescor(self):
        res = briefing({"LEITURA", "PUBLICACAO_DERIVADA"})
        self.assertEqual(res["indicadores_incluidos"], 1)
        self.assertIn("Producao anual", res["texto"])
        self.assertEqual(res["status"], "PREPARADO_SEM_ENVIO")

    def test_permissao_de_publicar_nao_ressuscita_dado_vencido(self):
        pacote = consultar()
        self.assertTrue(pacote["evidencias"])
        res = briefing({"LEITURA", "PUBLICACAO_DERIVADA"},
                       referencia=T-timedelta(days=46))
        self.assertEqual(res["indicadores_incluidos"], 0)
        self.assertTrue(any("indicador vencido" in item["motivo"]
                            for item in res["rejeicoes"]))

    def test_boletim_preparado_nao_permite_envio_sem_opt_in(self):
        res = briefing({"LEITURA", "PUBLICACAO_DERIVADA"})
        calls = []
        response = solicitar_entrega(
            res, DireitoEntrega(), remetente=lambda *args: calls.append(args)
        )
        self.assertEqual(response["status"], "BLOQUEADO_ENTREGA")
        self.assertFalse(response["envio_realizado"])
        self.assertEqual(calls, [])

    def test_direitos_somente_consulta_nao_publicam_frete(self):
        res = montar_briefing(
            noticias=[], data=T.isoformat(), indicadores=[],
            fontes={SRC: {"status_direitos": "APROVADA",
                          "operacoes": ["LEITURA"]}},
            fretes=[{
                "fonte_id": SRC, "origem": "Sorriso", "uf_origem": "MT",
                "destino": "Dom Aquino", "uf_destino": "MT",
                "valor_rs_t": 165, "referencia": T.isoformat(),
                "tipo": "FRETE_ANUNCIADO",
            }],
        )
        self.assertEqual(res["fretes_incluidos"], 0)
        self.assertNotIn("Sorriso/MT", res["texto"])
        self.assertTrue(any(e["tipo"] == "FRETE" for e in res["rejeicoes"]))


if __name__ == "__main__":
    unittest.main()
