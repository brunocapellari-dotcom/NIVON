import sqlite3
import unittest
from copy import deepcopy
from nivon.conab_store import abrir_series, salvar_edicao, consulta_na_data, ErroSerie


def registros(sha="a"*64,tempo="2026-10-18T13:00:00Z",prod=100.0):
    base={"origem_sha256":sha,"arquivo":"SojaSerieHist.xls","produto":"SOJA",
          "subdivisao_safra":"TOTAL","coletado_em":tempo,
          "regiao_uf":"MT","safra":"2025/2026","indicador":"PRODUCAO",
          "unidade":"T","valor":prod,"classificacao":"INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO",
          "rotulo_coluna_original":"2025/26","rotulo_coluna_inferido":False}
    return [base]


class TestArmazenamentoConab(unittest.TestCase):
    def setUp(self):
        self.db=abrir_series(":memory:")
        self.addCleanup(self.db.close)

    def test_edicao_nova_com_consulta_temporal(self):
        out=salvar_edicao(self.db,registros(),publicado_em="2026-10-15")
        self.assertTrue(out["nova_edicao"])
        self.assertEqual(out["observacoes"],1)
        self.assertIsNone(consulta_na_data(self.db,corte_coleta_utc="2026-10-17T12:00:00Z",
                                           arquivo="SojaSerieHist.xls",uf="MT",
                                           indicador="PRODUCAO",safra="2025/2026"))
        r=consulta_na_data(self.db,corte_coleta_utc="2026-10-19T12:00:00Z",
                           arquivo="SojaSerieHist.xls",uf="MT",
                           indicador="PRODUCAO",safra="2025/2026")
        self.assertEqual(r["valor"],100.0)

    def test_duas_coletas_mesma_edicao_uma_versao(self):
        salvar_edicao(self.db,registros())
        out=salvar_edicao(self.db,registros(tempo="2026-10-19T12:00:00Z"))
        self.assertFalse(out["nova_edicao"])
        self.assertTrue(out["nova_coleta"])
        self.assertEqual(self.db.execute("select count(*) from conab_edicoes").fetchone()[0],1)
        self.assertEqual(self.db.execute("select count(*) from conab_coletas").fetchone()[0],2)

    def test_idempotencia_mesmo_instante(self):
        salvar_edicao(self.db,registros())
        out=salvar_edicao(self.db,registros())
        self.assertFalse(out["nova_coleta"])

    def test_revisionamento_separa_hash_antigo_e_novo(self):
        salvar_edicao(self.db,registros())
        salvar_edicao(self.db,registros(sha="b"*64,tempo="2026-10-20T08:00:00Z",prod=110.0))
        args={"arquivo":"SojaSerieHist.xls","uf":"MT","indicador":"PRODUCAO","safra":"2025/2026"}
        old=consulta_na_data(self.db,corte_coleta_utc="2026-10-19T00:00:00Z",**args)
        new=consulta_na_data(self.db,corte_coleta_utc="2026-10-21T00:00:00Z",**args)
        self.assertEqual(old["valor"],100)
        self.assertEqual(new["valor"],110)

    def test_rejeitar_lista_vazia(self):
        with self.assertRaises(ErroSerie): salvar_edicao(self.db,[])

    def test_nao_misturar_arquivos_nem_fontes(self):
        xs=registros()
        xs.append(dict(xs[0],arquivo="MilhoTotalSerieHist.xls"))
        with self.assertRaises(ErroSerie): salvar_edicao(self.db,xs)

    def test_fonte_dupla_mesma_serie_na_edicao_erro(self):
        xs=registros()
        xs.append(dict(xs[0]))
        with self.assertRaises(ErroSerie): salvar_edicao(self.db,xs)

    def test_coleta_sem_fuso_rejeitada(self):
        with self.assertRaises(ErroSerie): salvar_edicao(self.db,registros(tempo="2026-10-18T13:00:00"))

if __name__=="__main__": unittest.main()


    def test_hash_igual_valor_diferente_nao_muda_coletas(self):
        salvar_edicao(self.db,registros())
        with self.assertRaises(ErroSerie):
            salvar_edicao(self.db,registros(tempo="2026-10-19T12:00:00Z",prod=110))
        self.assertEqual(self.db.execute("SELECT count(*) FROM conab_coletas").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT valor FROM conab_observacoes").fetchone()[0],100)

    def test_hash_igual_unidade_diferente_bloqueada(self):
        salvar_edicao(self.db,registros())
        rows=registros(tempo="2026-10-19T12:00:00Z")
        rows[0]["unidade"]="KG"
        with self.assertRaises(ErroSerie):
            salvar_edicao(self.db,rows)

    def test_publicacao_futura_rejeitada(self):
        with self.assertRaises(ErroSerie):
            salvar_edicao(self.db,registros(),publicado_em="2026-10-22")

    def test_transacao_externa_nao_comitada_pelo_store(self):
        self.db.execute("SAVEPOINT teste_externo")
        salvar_edicao(self.db,registros())
        self.db.execute("ROLLBACK TO SAVEPOINT teste_externo")
        self.db.execute("RELEASE SAVEPOINT teste_externo")
        self.assertEqual(self.db.execute("SELECT count(*) FROM conab_edicoes").fetchone()[0],0)

    def test_falha_de_insercao_reverte_edicao_e_coleta(self):
        self.db.execute("""CREATE TRIGGER injetar_falha BEFORE INSERT ON conab_observacoes
                           BEGIN SELECT RAISE(ABORT,'falha sintética'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            salvar_edicao(self.db,registros())
        self.assertEqual(self.db.execute("SELECT count(*) FROM conab_edicoes").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM conab_coletas").fetchone()[0],0)
