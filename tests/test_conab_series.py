import unittest
from copy import deepcopy
from nivon.conab_series import normalizar_livro, conferir_total_milho, ErroConab, safra_normalizada


class AbaFalsa:
    def __init__(self,nome, unidade):
        self.name=nome;self.nrows=15;self.ncols=22
        self.celulas=[["" for _ in range(self.ncols)] for _ in range(self.nrows)]
        self.celulas[4][0]="Em "+unidade
        self.celulas[5][0]="REGIÃO/UF"
        for i in range(21):
            ano=1980+i
            self.celulas[5][i+1]=f"{ano}/{str((ano+1)%100).zfill(2)}"
        self.celulas[6][0]="MT"
        self.celulas[7][0]="BRASIL"
        for i in range(1,22):
            self.celulas[6][i]=10.0
            self.celulas[7][i]=50.0
    def cell_value(self,r,c):return self.celulas[r][c]


class LivroFalso:
    def __init__(self):
        self.abas={"Área":AbaFalsa("Área","mil hectares"),
                   "Produtividade":AbaFalsa("Produtividade","kg/ha"),
                   "Produção":AbaFalsa("Produção","mil toneladas")}
    def sheet_names(self):return list(self.abas)
    def sheet_by_name(self,nome):return self.abas[nome]


class TestSeriesConab(unittest.TestCase):
    def ler(self,arquivo="SojaSerieHist.xls",livro=None):
        return normalizar_livro(livro or LivroFalso(),arquivo,sha256="f"*64,
                               capturado_em="2026-10-18T13:00:00+00:00")

    def test_três_abas_convertidas_em_registros(self):
        out=self.ler()
        self.assertEqual(len(out),3*2*21)
        self.assertEqual({r["indicador"] for r in out},{"AREA","PRODUCAO","PRODUTIVIDADE"})

    def test_fatores_unidades_nao_confundem_kg_t(self):
        out=self.ler()
        mt_producao=next(r for r in out if r["regiao_uf"]=="MT" and r["indicador"]=="PRODUCAO")
        mt_area=next(r for r in out if r["regiao_uf"]=="MT" and r["indicador"]=="AREA")
        mt_produtividade=next(r for r in out if r["regiao_uf"]=="MT" and r["indicador"]=="PRODUTIVIDADE")
        self.assertEqual((mt_producao["valor"],mt_producao["unidade"]),(10000,"T"))
        self.assertEqual((mt_area["valor"],mt_area["unidade"]),(10000,"HA"))
        self.assertEqual((mt_produtividade["valor"],mt_produtividade["unidade"]),(10,"KG_HA"))

    def test_nulo_nao_virou_zero(self):
        livro=LivroFalso()
        livro.abas["Produção"].celulas[6][1]=""
        result=self.ler(livro=livro)
        self.assertEqual(len(result),125)

    def test_safra_com_anos_errados_bloqueada(self):
        with self.assertRaises(ErroConab):
            safra_normalizada("2026/29")

    def test_aba_em_unidade_errada_bloqueada(self):
        livro=LivroFalso()
        livro.abas["Produção"].celulas[4][0]="Em sacas"
        with self.assertRaises(ErroConab):
            self.ler(livro=livro)

    def test_produto_milho_separado_de_total(self):
        x=self.ler("Milho2aSerieHist.xls")
        self.assertTrue(all(r["subdivisao_safra"]=="SEGUNDA" for r in x))

    def test_milho_total_conferido_sem_dupla_contagem(self):
        base={"produto":"MILHO","indicador":"PRODUCAO","regiao_uf":"MT",
              "safra":"2024/2025"}
        dados=[dict(base,subdivisao_safra=tipo,valor=v) for tipo,v in
               (("TOTAL",120),("PRIMEIRA",20),("SEGUNDA",90),("TERCEIRA",10))]
        result=conferir_total_milho(dados)
        self.assertEqual(result[0]["status"],"CONCILIADO")
        dados[-1]["valor"]=4
        self.assertEqual(conferir_total_milho(dados)[0]["status"],"DIVERGENTE")

    def test_produtividade_2009_corrompida_exige_aba_area(self):
        livro=LivroFalso()
        # Cabeçalho sintético da coluna 35 corresponde 2013/14 no mock.
        # Valor "200.9" só é reparável quando a safra de referência é 2009/10.
        livro.abas["Produtividade"].celulas[5][1]="200.9"
        with self.assertRaises(ErroConab):
            self.ler(livro=livro)

    def test_serie_informada_nao_e_realizacao(self):
        self.assertTrue(all(r["classificacao"].startswith("INFORMADO")
                            for r in self.ler()))

if __name__=="__main__":
    unittest.main()
