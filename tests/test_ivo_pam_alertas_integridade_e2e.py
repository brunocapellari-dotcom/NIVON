"""Radar de revisões PAM vinculado à integridade de SQLite/bytes, offline."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.ivo_pam_alertas import ErroAlertasPAM, alertas_revisoes_pam
from nivon.ivo_pam_operacao import abrir_operacao_pam, processar_captura_pam
from nivon.sidra_pam import planejar_pam_1612

T = datetime(2026, 10, 23, 13, tzinfo=timezone.utc)


def payload(plano, value):
    return json.dumps([
        {"D1C":"Município (Código)","D2C":"Variável (Código)",
         "D3C":"Ano (Código)",
         "D4C":"Produto das lavouras temporárias (Código)",
         "V":"Valor","MN":"Unidade de Medida"},
        {"D1C":plano["municipio_ibge"],"D2C":plano["variavel"],
         "D3C":str(plano["ano"]),"D4C":plano["categoria_c81"],
         "V":str(value),"MN":"Toneladas"},
    ], ensure_ascii=False).encode()


class TestPAMAlertasIntegridadeE2E(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name)
        self.db=abrir_operacao_pam(self.base/"operacional.sqlite")
        self.addCleanup(self.db.close)
        self.cofre=self.base/"cofre"
        self.soja=planejar_pam_1612(municipio_ibge="5107958",ano=2021,
                  codigo_produto_c81="2713",codigo_variavel="214")
        self.milho=planejar_pam_1612(municipio_ibge="5105259",ano=2021,
                  codigo_produto_c81="2714",codigo_variavel="214")

    def put(self,plan,valor,instante):
        return processar_captura_pam(
            db=self.db,raiz=self.cofre,plano=plan,
            payload=payload(plan,valor),coletado_em=instante,
            origem="TRANSPORTE_TESTE")

    def radar(self,after=T-timedelta(minutes=1),until=T+timedelta(hours=3)):
        return alertas_revisoes_pam(
            self.db,raiz=self.cofre,desde_exclusivo=after,
            ate_inclusivo=until)

    def test_revisao_do_mesmo_recorte_traz_delta_sem_homologacao(self):
        self.put(self.soja,100,T)
        self.put(self.soja,130,T+timedelta(hours=1))
        self.put(self.milho,300,T+timedelta(hours=1))
        res=self.radar()
        self.assertEqual(res["alteracoes_relevantes"],1)
        self.assertEqual(res["eventos"][0]["tipo"],"VALOR_ALTERADO")
        self.assertEqual(res["eventos"][0]["variacao_absoluta"],30)
        self.assertEqual(res["eventos"][0]["variacao_pct"],30)
        self.assertEqual(res["eventos"][0]["municipio_ibge"],"5107958")
        self.assertFalse(res["publicacao_autorizada"])
        self.assertFalse(res["captura_equivale_a_publicacao"])
        self.assertTrue(res["integridade_local_verificada"])

    def test_primeira_captura_da_janela_compara_o_passado(self):
        self.put(self.soja,100,T)
        self.put(self.soja,130,T+timedelta(hours=1))
        r=self.radar(after=T+timedelta(minutes=5))
        self.assertEqual(r["capturas_analisadas"],1)
        self.assertEqual(r["alteracoes_relevantes"],1)

    def test_repeticao_sem_mudanca_nao_alerta(self):
        self.put(self.soja,100,T)
        self.put(self.soja,100,T+timedelta(hours=1))
        r=self.radar()
        self.assertEqual(r["alteracoes_relevantes"],0)
        self.assertEqual(r["contagens"]["SEM_ALTERACAO"],1)

    def test_corte_historico_nao_antecipa_revisao(self):
        self.put(self.soja,100,T)
        self.put(self.soja,130,T+timedelta(hours=2))
        r=self.radar(until=T+timedelta(hours=1))
        self.assertEqual(r["alteracoes_relevantes"],0)

    def test_tamper_sqlite_ou_bytes_bloqueia_qualquer_alerta(self):
        self.put(self.soja,100,T)
        self.db.execute("UPDATE pam_vintages SET valor=999")
        self.db.commit()
        with self.assertRaises(ErroAlertasPAM):
            self.radar()
        self.db.execute("UPDATE pam_vintages SET valor=100")
        self.db.commit()
        item=self.db.execute("SELECT sha256 FROM pam_vintages").fetchone()[0]
        (self.cofre/"objetos_sha256"/(item+".bin")).write_bytes(b"tampered")
        with self.assertRaises(ErroAlertasPAM):
            self.radar()

    def test_fuso_de_tempo_exigido(self):
        with self.assertRaises(ErroAlertasPAM):
            self.radar(after=T.replace(tzinfo=None))


if __name__=="__main__":
    unittest.main()
