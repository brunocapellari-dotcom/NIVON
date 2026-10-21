import unittest
from datetime import datetime, timezone

from nivon.eventos_editoriais import mesmo_evento, deduplicar_eventos
from nivon.briefing_diario import selecionar_noticias


class TestEventosEditoriais(unittest.TestCase):
    def noticia(self, titulo, url, pub="2026-10-19T08:00:00-03:00"):
        return {"titulo": titulo, "resumo": "Resumo de teste.",
                "categoria": "SAFRA E PRODUÇÃO", "fonte": "Teste",
                "fonte_id": "LEGAL", "url": url, "publicado_em": pub}

    def test_duas_fontes_plantio_mesmo_evento(self):
        a = {"titulo": "Plantio de milho verao chega a 58 por cento da area"}
        b = {"titulo": "Safras registra 58 por cento no plantio de milho verao"}
        self.assertTrue(mesmo_evento(a,b))

    def test_numeros_diferentes_nao_apagam_revisao(self):
        a = {"titulo": "Plantio milho verao chega a 58 por cento"}
        b = {"titulo": "Plantio milho verao chega a 65 por cento"}
        self.assertFalse(mesmo_evento(a,b))

    def test_colheita_nao_e_plantio(self):
        a = {"titulo": "Plantio milho verao chega a 58 por cento"}
        b = {"titulo": "Colheita milho verao chega a 58 por cento"}
        self.assertFalse(mesmo_evento(a,b))

    def test_soja_nao_e_milho(self):
        a = {"titulo": "Plantio milho verao chega a 58 por cento"}
        b = {"titulo": "Plantio soja chega a 58 por cento"}
        self.assertFalse(mesmo_evento(a,b))

    def test_integracao_briefing(self):
        fontes={"LEGAL":{"status_direitos":"APROVADA",
                         "operacoes":["LEITURA","RESUMO","PUBLICACAO_DERIVADA"]}}
        a,b=selecionar_noticias([
            self.noticia("Plantio de milho verao chega a 58 por cento da area",
                         "https://portal-a.example/noticia"),
            self.noticia("Safras registra 58 por cento no plantio de milho verao",
                         "https://portal-b.example/outra"),
        ],fontes,gerado_em="2026-10-19T12:00:00-03:00")
        self.assertEqual(len(a),1)
        self.assertTrue(any("mesmo acontecimento" in x["motivo"] for x in b))


if __name__=="__main__":
    unittest.main()
