"""Testes offline do briefing NIVON: nenhum serviço ou notícia externa."""
import unittest
from datetime import datetime, timezone
from nivon.briefing_diario import gerar_texto, selecionar_noticias, ErroBriefing

AGORA = "2026-10-19T12:00:00-03:00"
FONTES = {"OFICIAL": {"status_direitos": "APROVADA",
                      "operacoes": ["LEITURA", "RESUMO", "PUBLICACAO_DERIVADA"]}}


def noticia(*, publicado="2026-10-19T11:00:00-03:00", url="https://example.org/a",
            titulo="Safra de soja", fonte_id="OFICIAL", resumo="Fato verificado."):
    return {"titulo": titulo, "resumo": resumo, "fonte_id": fonte_id,
            "fonte": "Fonte de teste", "url": url,
            "categoria": "SAFRA E PRODUÇÃO", "publicado_em": publicado}


class TestBriefingDiario(unittest.TestCase):
    def escolher(self, noticias, fontes=None):
        return selecionar_noticias(noticias, FONTES if fontes is None else fontes,
                                  gerado_em=AGORA)

    def test_noticia_24h_aceita(self):
        a, rejeitadas = self.escolher([noticia(publicado="2026-10-18T12:00:00-03:00")])
        self.assertEqual(len(a), 1)
        self.assertFalse(rejeitadas)

    def test_noticia_24h_e_um_segundo_rejeitada(self):
        a, rejeitadas = self.escolher([noticia(publicado="2026-10-18T11:59:59-03:00")])
        self.assertEqual(a, [])
        self.assertIn("mais de 24h", rejeitadas[0]["motivo"])

    def test_publicacao_futura_rejeitada(self):
        a, rejeitadas = self.escolher([noticia(publicado="2026-10-19T12:01:00-03:00")])
        self.assertFalse(a)
        self.assertIn("futura", rejeitadas[0]["motivo"])

    def test_data_sem_hora_rejeitada(self):
        a, rejeitadas = self.escolher([noticia(publicado="2026-10-19")])
        self.assertFalse(a)
        self.assertIn("sem hora", rejeitadas[0]["motivo"])

    def test_data_sem_fuso_rejeitada(self):
        a, rejeitadas = self.escolher([noticia(publicado="2026-10-19T11:00:00")])
        self.assertFalse(a)
        self.assertIn("timezone", rejeitadas[0]["motivo"])

    def test_fonte_sem_direitos_nao_entra(self):
        fonte = {"OFICIAL": {"status_direitos": "PENDENTE", "operacoes": []}}
        a, rejeitadas = self.escolher([noticia()], fonte)
        self.assertFalse(a)
        self.assertIn("direitos pendentes", rejeitadas[0]["motivo"])

    def test_fonte_sem_operacao_de_publicacao_nao_entra(self):
        fonte = {"OFICIAL": {"status_direitos": "APROVADA",
                              "operacoes": ["LEITURA", "RESUMO"]}}
        a, rejeitadas = self.escolher([noticia()], fonte)
        self.assertFalse(a)
        self.assertIn("não autorizadas", rejeitadas[0]["motivo"])

    def test_url_republicada_nao_rejuvenesce_noticia(self):
        entradas = [
            noticia(publicado="2026-10-18T08:00:00-03:00"),
            noticia(publicado="2026-10-19T10:00:00-03:00",
                    url="https://example.org/a?utm_source=whatsapp"),
        ]
        a, rejeitadas = self.escolher(entradas)
        self.assertFalse(a)
        self.assertEqual(len(rejeitadas), 2)

    def test_titulo_repetido_em_outra_url_deduplicado(self):
        a, rejeitadas = self.escolher([
            noticia(titulo="Safra de soja", url="https://example.org/a"),
            noticia(titulo="Safra de soja", url="https://example.org/b"),
        ])
        self.assertEqual(len(a), 1)
        self.assertEqual(len(rejeitadas), 1)

    def test_cotacao_mais_antiga_preserva_data_da_fonte(self):
        texto, rejeitadas = gerar_texto([], FONTES, gerado_em=AGORA,
            cotacoes=[{"titulo": "Soja", "valor": "R$ 120", "fonte": "Fonte sintética",
                       "referencia": "2026-10-16"}])
        self.assertIn("2026-10-16", texto)
        self.assertIn("Nenhuma notícia elegível", texto)
        self.assertFalse(rejeitadas)

    def test_gerador_nao_inventa_noticias_ou_cotacoes(self):
        texto, _ = gerar_texto([], FONTES, gerado_em=AGORA)
        self.assertNotIn("R$ 120", texto)
        self.assertIn("Notícias elegíveis: 0", texto)

    def test_titulo_editorial_padrao_e_sem_secoes_de_impactos(self):
        item=noticia()
        item["impacto_brasil"]="TEXTO INTERNO QUE NAO DEVE SER PUBLICADO"
        item["impacto_produtor"]="SEGUNDA ANALISE NAO CONTRATADA"
        texto,rejeicoes=gerar_texto([item],FONTES,gerado_em=AGORA)
        self.assertTrue(texto.startswith("*RESUMO ESTRATÉGICO DO AGRONEGÓCIO*"))
        self.assertIn("Fato verificado.",texto)
        self.assertNotIn("TEXTO INTERNO",texto)
        self.assertNotIn("SEGUNDA ANALISE",texto)
        self.assertNotIn("Possível impacto",texto)
        self.assertEqual(rejeicoes,[])

    def test_noticia_antiga_nao_retorna_por_ter_analise_nova(self):
        item=noticia(publicado="2026-10-15T10:00:00-03:00")
        item["impacto_brasil"]="Atualizado hoje"
        texto,rejeicoes=gerar_texto([item],FONTES,gerado_em=AGORA)
        self.assertNotIn("Safra de soja",texto)
        self.assertNotIn("Atualizado hoje",texto)
        self.assertIn("Nenhuma notícia elegível",texto)
        self.assertEqual(len(rejeicoes),1)

    def test_url_http_rejeitada(self):
        a, rejeitadas = self.escolher([noticia(url="http://example.org/a")])
        self.assertFalse(a)
        self.assertIn("HTTPS público", rejeitadas[0]["motivo"])


if __name__ == "__main__":
    unittest.main()
