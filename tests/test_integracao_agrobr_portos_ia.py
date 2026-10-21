"""Regressão de integração agrobr + portos + previsões + IA, sem rede."""
import asyncio
import hashlib
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from nivon.conab_agrobr import (
    normalizar_progresso, coletar_progresso, descobrir_semanas, ErroProgresso
)
from nivon.coleta_web import FonteWeb
from nivon.portos_automaticos import (
    ContratoPorto, processar_documento_porto, ErroPorto,
)
from nivon.previsoes_bibliotecas import (
    prever_mensal, backtest_mensal, ErroPrevisao,
)
from nivon.briefing_composto import montar_briefing, solicitar_entrega, DireitoEntrega
from nivon.agentes_nivon import (
    SolicitacaoAgente, consultar_ia, CoordenadorNivon
)

AGORA = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
CONAB_URL = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra"
FONTES = {
    "BCB": {"status_direitos": "APROVADA",
            "operacoes": ["LEITURA", "RESUMO", "PUBLICACAO_DERIVADA"]},
    "WHATSAPP": {"status_direitos": "APROVADA",
                 "operacoes": ["PUBLICACAO_DERIVADA"]},
    "CME": {"status_direitos": "PENDENTE", "operacoes": []},
}
LINHA = {
    "cultura": "Soja", "safra": "2026/27", "operacao": "Semeadura",
    "uf": "MT", "semana_atual": "2026-10-16",
    "pct_semana_atual": 0.39, "pct_semana_anterior": 0.30,
    "pct_ano_anterior": 0.42, "pct_media_5_anos": 0.45,
}


class TestConabAgrobr(unittest.TestCase):
    def test_semanas_realizadas_e_quatro_datas(self):
        d = normalizar_progresso([LINHA], fonte_url=CONAB_URL, coletado_em=AGORA)
        self.assertEqual(d[0]["pct_semana_atual"], 0.39)
        self.assertIsNone(d[0]["publicacao"])
        self.assertEqual(d[0]["competencia"], "2026-10-16")
        self.assertEqual(d[0]["uf"], "MT")

    def test_media_estados_nao_virou_brasil(self):
        d = normalizar_progresso(
            [{**LINHA, "uf": "MEDIA_ESTADOS", "n_estados": 12,
              "cobertura_area_pct": 0.96}], fonte_url=CONAB_URL, coletado_em=AGORA)
        self.assertEqual(d[0]["uf"], "MEDIA_ESTADOS")
        self.assertEqual(d[0]["n_estados"], 12)

    def test_rejeita_fracoes_incorretas_e_duplicadas(self):
        with self.assertRaises(ErroProgresso):
            normalizar_progresso([{**LINHA, "pct_semana_atual": 39.0}],
                                 fonte_url=CONAB_URL, coletado_em=AGORA)
        with self.assertRaises(ErroProgresso):
            normalizar_progresso([LINHA, LINHA], fonte_url=CONAB_URL, coletado_em=AGORA)

    def test_bloqueia_rede_antes_de_chamar_provedor(self):
        class Provedor:
            async def progresso_safra(self, **kw):
                raise AssertionError("não pode acessar fonte")
        with self.assertRaises(PermissionError):
            asyncio.run(coletar_progresso(agrobr_api=Provedor()))

    def test_injecao_agrobr_sem_rede(self):
        class Provedor:
            async def progresso_safra(self, **kw):
                return [LINHA], SimpleNamespace(source_url=CONAB_URL)
            async def semanas_disponiveis(self, **kw):
                return [{"url": CONAB_URL, "descricao": "semana de teste"}]
        r = asyncio.run(coletar_progresso(
            agrobr_api=Provedor(), direitos_confirmados=True, capturado_em=AGORA))
        self.assertEqual(len(r), 1)
        semanas = asyncio.run(descobrir_semanas(
            agrobr_api=Provedor(), direitos_confirmados=True))
        self.assertEqual(len(semanas), 1)


class TestPortosReuso(unittest.TestCase):
    def contrato(self, modo="HTML_SANTOS_SCHEDULE"):
        url = "https://www.portodesantos.com.br/exemplo.html"
        return ContratoPorto("SANTOS", FonteWeb(
            "LINEUP_SANTOS", url, "www.portodesantos.com.br", "HTML",
            status_direitos="APROVADA",
            operacoes_permitidas=frozenset({"COLETA"})), modo)

    def documento(self, texto):
        payload = texto.encode()
        return {"conteudo": payload, "sha256": hashlib.sha256(payload).hexdigest(),
                "url": "https://www.portodesantos.com.br/exemplo.html",
                "capturado_em": "2026-10-19T12:00:00+00:00"}

    def test_santos_parser_agrolog_nao_promove_programado(self):
        html = ("<table><tr><th>Navio</th><th>IMO</th><th>ETA</th><th>DUV</th>"
                "<th>Evento</th></tr><tr><td>TESTE A</td><td>1234567</td>"
                "<td>20/10/2026</td><td>D-1</td><td>ATRACACAO</td></tr></table>")
        data = processar_documento_porto(self.contrato(), self.documento(html))
        self.assertEqual(data["registros"][0].status, "PROGRAMADO")
        self.assertEqual(data["escalas"]["escalas_distintas_identificadas"], 1)
        self.assertEqual(data["status"], "EXTRAIDO_AGUARDA_HOMOLOGACAO")

    def test_outro_host_e_modo_rejeitados(self):
        with self.assertRaises(ErroPorto):
            self.contrato("HTML_CDP_BERTH_TABLE").validar()
        with self.assertRaises(ErroPorto):
            ContratoPorto("TUBARAO", self.contrato().fonte,
                          "HTML_SANTOS_SCHEDULE").validar()

    def test_documento_sem_metadados_rejeitado(self):
        with self.assertRaises(ErroPorto):
            processar_documento_porto(self.contrato(), {"conteudo": b"x"})


    def test_documento_com_hash_falso_bloqueado_antes_do_parser(self):
        doc=self.documento("<table><tr><td>teste</td></tr></table>")
        doc["sha256"]="0"*64
        with self.assertRaisesRegex(ErroPorto,"SHA-256 divergente"):
            processar_documento_porto(self.contrato(),doc)

    def test_documento_mutado_apos_hash_rejeitado(self):
        doc=self.documento("<html>conteudo original</html>")
        doc["conteudo"]+=b"\ntexto alterado"
        with self.assertRaisesRegex(ErroPorto,"SHA-256 divergente"):
            processar_documento_porto(self.contrato(),doc)

    def test_documento_tamanho_ou_fonte_divergente_reprovado(self):
        doc=self.documento("<html>sem parser ainda</html>")
        doc["bytes"]=len(doc["conteudo"])+1
        with self.assertRaisesRegex(ErroPorto,"tamanho declarado"):
            processar_documento_porto(self.contrato(),doc)
        doc["bytes"]=len(doc["conteudo"])
        doc["fonte_id"]="LINEUP_OUTRO"
        with self.assertRaisesRegex(ErroPorto,"fonte_id divergente"):
            processar_documento_porto(self.contrato(),doc)

    def test_documento_nao_tem_fuso_ou_mime_correto(self):
        doc=self.documento("<html>teste</html>")
        doc["capturado_em"]="2026-10-19T12:00:00"
        with self.assertRaisesRegex(ErroPorto,"timezone"):
            processar_documento_porto(self.contrato(),doc)
        doc["capturado_em"]="2026-10-19T12:00:00Z"
        doc["mime"]="application/pdf"
        with self.assertRaisesRegex(ErroPorto,"MIME"):
            processar_documento_porto(self.contrato(),doc)



class TestPrevisoesBiblio(unittest.TestCase):
    def serie(self, n=30):
        return [
            ("%04d-%02d" % (2024 + i // 12, 1 + i % 12), float(i + 1))
            for i in range(n)
        ]

    def test_previsao_opcional_sem_biblioteca(self):
        p = prever_mensal(self.serie(), horizonte=2,
                          backend=lambda s, h: [s[-1][1] + x for x in range(1, h + 1)])
        self.assertEqual(p["previsoes"][0]["periodo"], "2026-07")
        self.assertEqual(p["estado"], "CENARIO_NAO_HOMOLOGADO")

    def test_walk_forward_nao_declara_modelo_validado(self):
        b = backtest_mensal(self.serie(), folds=3,
                            backend=lambda s, h: [s[-1][1]])
        self.assertEqual(len(b["folds"]), 3)
        self.assertFalse(b["publicar_como_previsao_validada"])

    def test_lacuna_bloqueante(self):
        dados = self.serie()
        dados[4] = ("2024-07", dados[4][1])
        with self.assertRaises(ErroPrevisao):
            prever_mensal(dados, backend=lambda s, h: [1]*h)


class TestBriefingAgentes(unittest.TestCase):
    def indicador(self, fonte):
        return {"fonte_id": fonte, "secao": "BOLSAS" if fonte == "CME" else "CAMBIO",
                "titulo": "Dólar" if fonte == "BCB" else "CBOT",
                "valor": "R$ 5,00", "fonte": fonte,
                "referencia": "2026-10-19T11:00:00+00:00"}

    def test_dolar_permitido_e_cbot_sem_licenca_bloqueado(self):
        a = montar_briefing(noticias=[], fontes=FONTES, data=AGORA.isoformat(),
                            indicadores=[self.indicador("BCB"), self.indicador("CME")])
        self.assertIn("Dólar", a["texto"])
        self.assertNotIn("• CBOT", a["texto"])
        self.assertEqual(a["indicadores_incluidos"], 1)
        self.assertTrue(a["rejeicoes"])

    def test_frete_anunciado_e_nao_realizado(self):
        a = montar_briefing(noticias=[], fontes=FONTES, data=AGORA.isoformat(),
           indicadores=[], fretes=[{
               "fonte_id": "WHATSAPP", "origem": "Sinop", "uf_origem": "MT",
               "destino": "Miritituba", "uf_destino": "PA", "valor_rs_t": 210.0,
               "referencia": AGORA.isoformat(), "tipo": "FRETE_ANUNCIADO",
               "pickup_entity_id": "ARMAZEM_SINOP_TESTE",
               "ponto_embarque": "Armazém de teste Sinop",
               "transportadora": "Transportadora Sintética",
               "produto": "SOJA", "equipamento": "BITREM",
               "regime_pf_pj": "PJ", "condicao_pedagio": "INCLUSO"
           }])
        self.assertIn("SINOP/MT → MIRITITUBA/PA", a["texto"])
        self.assertIn("não são viagens realizadas", a["texto"])

    def test_envio_default_bloqueado(self):
        b = montar_briefing(noticias=[], fontes=FONTES,
                            data=AGORA.isoformat(), indicadores=[])
        chamado = []
        r = solicitar_entrega(b, DireitoEntrega(),
                  remetente=lambda *args: chamado.append(True))
        self.assertEqual(r["status"], "BLOQUEADO_ENTREGA")
        self.assertFalse(chamado)

    def test_agente_nao_recebe_poder_executivo(self):
        r = consultar_ia(SolicitacaoAgente(
            "EDITOR", "SUGERIR_TEXTO", "snap1", "Sugestão documental"),
            executor=lambda req: "Título a conferir")
        self.assertEqual(r["status"], "SUGESTAO_NAO_CANONICA")
        self.assertFalse(r["autorizacao_para_publicar"])
        with self.assertRaises(PermissionError):
            consultar_ia(SolicitacaoAgente("EDITOR", "ENVIAR_WHATSAPP",
                                          "snap1", "x"))

    def test_pipeline_offline_termina_sem_enviar(self):
        c = CoordenadorNivon(auditor=lambda b: True)
        r = c.executar(noticias=[], fontes=FONTES,
                       data=AGORA.isoformat(), indicadores=[])
        self.assertEqual(r["entrega"]["status"], "BLOQUEADO_ENTREGA")
        self.assertEqual(r["fases"][-1]["fase"], "ENTREGA")


if __name__ == "__main__":
    unittest.main()
