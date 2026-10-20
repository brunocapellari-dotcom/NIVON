import io
import sqlite3
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from nivon.antaq_historico_offline import (
    ErroAntaq, importar_arquivos, resumo_por_porto
)


def zips(mercadoria="SOJA", numero="12.500,750", *, bad_fk=False, data="15/10/2026 08:20:00",
         ano="2026", duplo=False):
    atr=("IDAtracacao;Porto Atracação;Terminal;Data Atracação;Ano;Mes;SGUF\n"
         f"ATR01;Porto de Santarém;Terminal Agro;{data};{ano};Outubro;PA\n")
    carga=("IDCarga;IDAtracacao;CDMercadoria;Sentido;VLPesoCargaBruta\n"
           f"CARGA1;{'OUTRA' if bad_fk else 'ATR01'};10059010;Embarcados;{numero}\n")
    if duplo:
        carga += "CARGA2;ATR01;10059010;Embarcados;100,500\n"
    merc=("CDMercadoria;Nomenclatura Simplificada Mercadoria\n"
          f"10059010;{mercadoria}\n")
    def compactar(membros):
        buffer=io.BytesIO()
        with ZipFile(buffer,"w",ZIP_DEFLATED) as z:
            for file,content in membros.items():
                z.writestr(file,content.encode("utf-8-sig"))
        return buffer.getvalue()
    return (compactar({"2026Atracacao.txt":atr,"2026Carga.txt":carga}),
            compactar({"Mercadoria.txt":merc}))


class TestAntaqHistoricoOffline(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(":memory:")

    def tearDown(self):
        self.con.close()

    def importar(self, a=None, m=None):
        if a is None or m is None:
            a,m=zips()
        return importar_arquivos(a,m,ano=2026,
                                coletado_em="2026-10-19T22:00:00-03:00",
                                conexao=self.con)

    def test_historico_mensal_observado_nao_lineup(self):
        x=self.importar(*zips(duplo=True))
        self.assertEqual(x["cargas"],2)
        self.assertFalse(x["publicavel"])
        r=resumo_por_porto(self.con,x["edicao_sha256"])
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]["escalas_distintas"],1)
        self.assertEqual(r[0]["cargas"],2)
        self.assertAlmostEqual(r[0]["toneladas_realizadas"],12601.25)
        self.assertEqual(r[0]["competencia"],"2026-10")
        self.assertFalse(r[0]["publicavel"])

    def test_mesma_edicao_idempotente(self):
        a,m=zips()
        x=self.importar(a,m)
        y=self.importar(a,m)
        self.assertEqual(x["edicao_sha256"],y["edicao_sha256"])
        self.assertEqual(y["estado"],"EDICAO_JA_IMPORTADA")
        self.assertEqual(len(resumo_por_porto(self.con,x["edicao_sha256"])),1)

    def test_revisao_arquivo_nao_sobrescreve_original(self):
        a,m=zips(mercadoria="SOJA")
        x=self.importar(a,m)
        a2,m2=zips(mercadoria="MILHO")
        y=self.importar(a2,m2)
        self.assertNotEqual(x["edicao_sha256"],y["edicao_sha256"])
        self.assertEqual(resumo_por_porto(self.con,x["edicao_sha256"])[0]["mercadoria"],"SOJA")
        self.assertEqual(resumo_por_porto(self.con,y["edicao_sha256"])[0]["mercadoria"],"MILHO")

    def test_falha_referencial_reverte_transacao(self):
        with self.assertRaises(ErroAntaq):
            self.importar(*zips(bad_fk=True))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM antaq_cargas").fetchone()[0],0)

    def test_ano_mes_nao_coerentes_rejeitados(self):
        with self.assertRaises(ErroAntaq):
            self.importar(*zips(ano="2025"))

    def test_zip_sem_assinatura_rejeita(self):
        with self.assertRaises(ErroAntaq):
            self.importar(b"<html>WAF block</html>", zips()[1])

    def test_peso_negativo_nao_aceita(self):
        with self.assertRaises(ErroAntaq):
            self.importar(*zips(numero="-10,50"))

    def test_tabelas_sem_fonte_nao_aceita(self):
        with self.assertRaises(ErroAntaq):
            resumo_por_porto(self.con,"NAO_SHA256")

    def test_fuso_da_coleta_obrigatorio(self):
        with self.assertRaises(ValueError):
            a,m=zips()
            importar_arquivos(a,m,ano=2026,coletado_em="2026-10-19T22:00:00",
                            conexao=self.con)


if __name__ == "__main__":
    unittest.main()
