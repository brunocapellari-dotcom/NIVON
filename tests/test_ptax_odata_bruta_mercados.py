"""Fixtures OData BCB sintéticas: NÃO são cotações coletadas ao vivo."""
from hashlib import sha256
import json
import unittest

from nivon.ptax_odata_bruta_mercados import ErroPTAXBruto, verificar_ptax_odata_bruta
from nivon.ptax_plano import planejar_consultas_ptax

AS_OF="2026-10-20T18:00:00Z"
COLETA="2026-10-20T17:30:00Z"


def url(moeda="USD"):
    return planejar_consultas_ptax(moeda=moeda,inicio="2026-10-19",fim="2026-10-20")[0]["url"]


def ponto(preco_compra=5.1234, preco_venda=5.1240, *,
          hora="2026-10-20 13:06:30.123",tipo=None):
    item={"cotacaoCompra":preco_compra,"cotacaoVenda":preco_venda,
          "dataHoraCotacao":hora}
    if tipo is not None:
        item["tipoBoletim"]=tipo
    return item


def raw(value=None):
    values=value if value is not None else [ponto()]
    return json.dumps({"@odata.context":"https://olinda.bcb.gov.br/metadata",
                       "value":values},separators=(",",":")).encode()


def verificar(dados=None,moeda="USD",consulta_url=None,corte=AS_OF,
              coletado=COLETA,sha=None):
    buf=dados if dados is not None else raw()
    return verificar_ptax_odata_bruta(
        buf,consulta_url=consulta_url or url(moeda),
        moeda=moeda,as_of=corte,coletado_em=coletado,
        raw_sha256_esperado=sha or sha256(buf).hexdigest())


class TestPTAXODATABruta(unittest.TestCase):
    def test_usd_sem_tipo_nao_alega_fechamento(self):
        r=verificar()
        self.assertEqual(r["status"],"PTAX_ODATA_RAW_CONFERIDO_OFFLINE")
        self.assertEqual(r["boletins_distintos"],1)
        b=r["boletins"][0]
        self.assertEqual(b["cotacao_compra_decimal"],"5.1234")
        self.assertEqual(b["cotacao_venda_decimal"],"5.124")
        self.assertEqual(b["ponteiro_json"],"/value/0")
        self.assertIsNone(b["tipo_boletim"])
        self.assertFalse(b["boletim_fechamento_confirmado"])
        self.assertFalse(r["publicacao_independente_comprovada"])
        self.assertFalse(r["apto_backtest_por_publicacao"])
        self.assertFalse(r["publicavel"])

    def test_decimal_preserva_zeros_textuais_sem_float(self):
        data=(b'{"value":[{"cotacaoCompra":5.10000,"cotacaoVenda":5.10010,'
              b'"dataHoraCotacao":"2026-10-20 13:06:30"}]}')
        b=verificar(dados=data)["boletins"][0]
        self.assertEqual(b["cotacao_compra_decimal"],"5.10000")
        self.assertEqual(b["cotacao_venda_decimal"],"5.10010")

    def test_eur_multiplos_boletins_explicitos(self):
        r=verificar(dados=raw([
            ponto(5.10,5.11,hora="2026-10-20 10:05:00",tipo="Intermediário"),
            ponto(5.20,5.21,hora="2026-10-20 13:05:00",tipo="Fechamento"),
        ]),moeda="EUR")
        self.assertEqual(len(r["boletins"]),2)
        self.assertTrue(r["boletins"][-1]["boletim_fechamento_confirmado"])
        self.assertEqual(r["boletins"][0]["unidade"],"BRL/EUR")

    def test_publicacao_e_licenca_nao_inventadas(self):
        r=verificar()
        self.assertIsNone(r["boletins"][0]["publicacao_em"])
        self.assertFalse(r["origem_http_autenticada"])
        self.assertFalse(r["direitos_redistribuicao_homologados"])

    def test_coleta_apos_corte(self):
        with self.assertRaisesRegex(ErroPTAXBruto,"posterior"):
            verificar(corte="2026-10-20T16:00:00Z")

    def test_cotacao_apos_coleta(self):
        with self.assertRaisesRegex(ErroPTAXBruto,"depois da captura"):
            verificar(coletado="2026-10-20T14:00:00Z")

    def test_boletim_fora_periodo(self):
        with self.assertRaisesRegex(ErroPTAXBruto,"fora do intervalo"):
            verificar(dados=raw([ponto(hora="2026-10-18 13:06:00")]))

    def test_hash_bruto_adulterado(self):
        with self.assertRaisesRegex(ErroPTAXBruto,"SHA256 bruto"):
            verificar(sha="a"*64)

    def test_chave_json_duplicada(self):
        buf=(b'{"value":[{"cotacaoCompra":5.0,"cotacaoCompra":9.0,'
             b'"cotacaoVenda":5.1,"dataHoraCotacao":"2026-10-20 13:00:00"}]}')
        with self.assertRaisesRegex(ErroPTAXBruto,"duplicada"):
            verificar(dados=buf)

    def test_nextlink_nao_pode_parecer_completo(self):
        buf=(b'{"value":[{"cotacaoCompra":5.0,"cotacaoVenda":5.1,'
             b'"dataHoraCotacao":"2026-10-20 13:00:00"}],'
             b'"@odata.nextLink":"https://evil.example/p2"}')
        with self.assertRaisesRegex(ErroPTAXBruto,"envelope"):
            verificar(dados=buf)

    def test_nan_negativo_venda_menor(self):
        for buf in (
            b'{"value":[{"cotacaoCompra":NaN,"cotacaoVenda":5.2,'
            b'"dataHoraCotacao":"2026-10-20 13:00:00"}]}',
            raw([ponto(-1,5.2)]),raw([ponto(5.2,5.1)]),
        ):
            with self.subTest(buf=buf),self.assertRaises(ErroPTAXBruto):
                verificar(dados=buf)

    def test_boletim_duplicado(self):
        with self.assertRaisesRegex(ErroPTAXBruto,"duplicado"):
            verificar(dados=raw([ponto(),ponto()]))

    def test_url_injetada_ou_parametros_duplicados(self):
        u=url()
        bad=(u.replace("olinda.bcb.gov.br","evil.example.org"),
             u+"&$top=500",u+"&$orderby=foo",
             u.replace("CotacaoDolarPeriodo","CotacaoMoedaPeriodo"),
             u.replace("%24top=500","%24top=999").replace("$top=500","$top=999"))
        for v in bad:
            with self.subTest(url=v),self.assertRaises(ErroPTAXBruto):
                verificar(consulta_url=v)

    def test_fuso_sao_paulo(self):
        b=verificar()["boletins"][0]
        self.assertTrue(b["referencia_em"].endswith("-03:00"))
        self.assertEqual(b["data_referencia"],"2026-10-20")

    def test_tipo_desconhecido_ou_paridade_parcial(self):
        for rows in ([ponto(tipo="Desconhecido")],
                     [dict(ponto(),paridadeCompra=0.91)]):
            with self.subTest(rows=rows),self.assertRaises(ErroPTAXBruto):
                verificar(dados=raw(rows))

    def test_ordenacao_nao_muda_json_pointer(self):
        d=raw([ponto(5.2,5.21,hora="2026-10-20 13:10:00"),
               ponto(5.1,5.11,hora="2026-10-20 10:10:00")])
        r=verificar(dados=d)
        self.assertEqual(r["boletins"][0]["ponteiro_json"],"/value/1")
        self.assertEqual(r["boletins"][1]["ponteiro_json"],"/value/0")

    def test_ptax_nao_e_cotacao_de_soja(self):
        r=verificar()
        self.assertEqual(r["boletins"][0]["fonte_id"],"BCB_PTAX")
        self.assertNotIn("contrato",r["boletins"][0])
        self.assertEqual(r["licenca_catalogo"],"ODbL")


if __name__=="__main__":
    unittest.main()
