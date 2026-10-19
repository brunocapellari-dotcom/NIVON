import unittest

from nivon.cotacoes_externas import cotacao_para_briefing, ErroMercado


class TestCotacoesExternas(unittest.TestCase):
    def quote(self):
        return {"fonte":"CME","tipo":"FECHAMENTO","produto":"SOJA",
                "contrato":"X26","preco":"1120.25","unidade":"USC/LB",
                "referencia_em":"2026-10-16T15:00:00-05:00",
                "fonte_url":"https://www.cmegroup.com/"}

    def direito(self):
        return {"fonte":"CME","status":"APROVADA",
                "id_aprovacao":"DOCUMENTO_TESTE_SINTETICO",
                "valida_ate":"2026-12-31",
                "operacoes":["LEITURA","ARMAZENAMENTO","PUBLICACAO_DERIVADA","REDISTRIBUICAO"]}

    def test_apenas_licenciado_com_data(self):
        x=cotacao_para_briefing(self.quote(),self.direito(),
                               gerado_em="2026-10-19T12:00:00-03:00")
        self.assertIn("2026-10-16",x["referencia"])
        self.assertIn("SOJA",x["titulo"])

    def test_sem_direito_proibido(self):
        d=self.direito()
        d["status"]="PENDENTE"
        with self.assertRaises(ErroMercado):
            cotacao_para_briefing(self.quote(),d,gerado_em="2026-10-19T12:00:00-03:00")

    def test_sem_preco_real_nao_inventa(self):
        q=self.quote()
        q.pop("preco")
        with self.assertRaises(ErroMercado):
            cotacao_para_briefing(q,self.direito(),gerado_em="2026-10-19T12:00:00-03:00")

    def test_futuro_sem_contrato_nao_aceita(self):
        q=self.quote()
        q["contrato"]=None
        with self.assertRaises(ErroMercado):
            cotacao_para_briefing(q,self.direito(),gerado_em="2026-10-19T12:00:00-03:00")

if __name__=="__main__":
    unittest.main()
