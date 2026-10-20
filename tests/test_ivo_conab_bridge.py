import unittest
from datetime import datetime, timezone

from nivon.conab_store import abrir_series, salvar_edicao
from nivon.ivo_conab_bridge import ErroPonteConab, consultar_safras_conab

UTC=timezone.utc

def linhas(sha="a"*64,coleta="2026-10-18T13:00:00Z",
           safra="2025/2026",valor=100.,classe="INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO",
           arquivo="SojaSerieHist.xls",produto="SOJA",sub="TOTAL"):
    return [{
        "origem_sha256":sha,"arquivo":arquivo,"produto":produto,
        "subdivisao_safra":sub,"coletado_em":coleta,
        "regiao_uf":"MT","safra":safra,
        "indicador":"PRODUCAO","unidade":"T","valor":valor,
        "classificacao":classe,"rotulo_coluna_original":safra,
        "rotulo_coluna_inferido":False,
    }]

def dt(iso):
    return datetime.fromisoformat(iso.replace("Z","+00:00"))

class TestIVOConabBridge(unittest.TestCase):
    def setUp(self):
        self.db=abrir_series(":memory:")
        self.addCleanup(self.db.close)

    def ver(self,**kw):
        p=dict(arquivo="SojaSerieHist.xls",uf="MT",indicador="PRODUCAO",
            corte=dt("2026-10-21T00:00:00Z"))
        p.update(kw)
        return consultar_safras_conab(self.db,**p)

    def test_serie_informada_nao_se_disfarca_de_resultado_final(self):
        salvar_edicao(self.db,linhas(),publicado_em="2026-10-15")
        saida=self.ver()
        self.assertEqual(saida["safras"],1)
        self.assertEqual(saida["observacoes"][0]["valor"],100.)
        self.assertEqual(saida["calendario"],"SAFRA")
        self.assertFalse(saida["observacoes"][0]["observado_final_certificado"])
        self.assertFalse(saida["observacoes"][0]["autorizado_para_treino_supervisionado"])
        self.assertFalse(saida["treinamento_supervisionado_habilitado"])
        self.assertEqual(saida["rótulos_realizados_disponiveis"],0)

    def test_projetado_preservado_como_projecao(self):
        salvar_edicao(self.db,linhas(classe="PROJETADO_CONAB"),publicado_em="2026-10-15")
        self.assertEqual(self.ver()["observacoes"][0]["classificacao"],"PROJETADO_CONAB")

    def test_revisao_futura_nao_altera_asof_antigo(self):
        salvar_edicao(self.db,linhas(),publicado_em="2026-10-15")
        salvar_edicao(self.db,linhas(sha="b"*64,coleta="2026-10-20T13:00:00Z",
                                    valor=120.),publicado_em="2026-10-20")
        old=self.ver(corte=dt("2026-10-19T23:00:00Z"))
        new=self.ver()
        self.assertEqual(old["observacoes"][0]["valor"],100.)
        self.assertEqual(new["observacoes"][0]["valor"],120.)
        self.assertEqual(old["observacoes"][0]["fonte_sha256"],"a"*64)
        self.assertEqual(new["observacoes"][0]["fonte_sha256"],"b"*64)

    def test_muitas_safras_sem_dupla_contagem_edicao(self):
        linhas_duplas=linhas()+linhas(safra="2024/2025")
        salvar_edicao(self.db,linhas_duplas,publicado_em="2026-10-15")
        res=self.ver()
        self.assertEqual([x["safra"] for x in res["observacoes"]],["2024/2025","2025/2026"])
        self.assertEqual(res["safras"],2)

    def test_sem_publicacao_nunca_vira_publico_asof(self):
        salvar_edicao(self.db,linhas(),publicado_em=None)
        self.assertEqual(self.ver()["safras"],0)

    def test_sem_coleta_anterior_ao_corte_nao_aparece(self):
        salvar_edicao(self.db,linhas(),publicado_em="2026-10-15")
        self.assertEqual(self.ver(corte=dt("2026-10-18T12:59:59Z"))["safras"],0)

    def test_sem_mistura_milho_total_soja(self):
        salvar_edicao(self.db,linhas(),publicado_em="2026-10-15")
        salvar_edicao(self.db,linhas(sha="c"*64,
            arquivo="MilhoTotalSerieHist.xls",produto="MILHO"),publicado_em="2026-10-15")
        self.assertEqual(self.ver()["safras"],1)
        self.assertEqual(self.ver(arquivo="MilhoTotalSerieHist.xls")["safras"],1)

    def test_limitacao_de_safras_explicita(self):
        salvar_edicao(self.db,linhas()+linhas(safra="2024/2025"),publicado_em="2026-10-15")
        with self.assertRaises(ErroPonteConab):
            self.ver(limite_safras=1)

    def test_fuso_e_contratos_invalidos(self):
        for kw in ({"corte":datetime(2026,10,20)},
                   {"arquivo":"arquivo_inventado.xls"},
                   {"uf":"INEXISTENTE"},{"indicador":"PRECO"},
                   {"limite_safras":True}):
            with self.subTest(kw=kw),self.assertRaises(ErroPonteConab):
                self.ver(**kw)

    def test_data_de_publicacao_futura_em_relacao_corte(self):
        salvar_edicao(self.db,linhas(coleta="2026-10-21T13:00:00Z"),
                     publicado_em="2026-10-21")
        self.assertEqual(self.ver()["safras"],0)

if __name__=="__main__":
    unittest.main()
