"""Regressão editorial: auditor não libera fretes/cotações inválidas."""
import unittest

from nivon.briefing_composto import montar_briefing
from nivon.outbox_briefing import abrir_outbox
from nivon.rotina_diaria import preparar_rotina

AGORA="2026-10-20T12:00:00+00:00"
RECENTE="2026-10-20T10:00:00+00:00"
VELHO="2026-10-16T10:00:00+00:00"
FONTES={
    "CME":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "BCB":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
    "WHATSAPP_FRETE":{"status_direitos":"APROVADA","operacoes":["LEITURA","PUBLICACAO_DERIVADA"]},
}
BASIC=[
    {"fonte_id":"CME","secao":"BOLSAS","titulo":"CBOT somente fixture",
     "valor":"R$ 1.000/teste","referencia":RECENTE,"fonte":"fonte simulada"},
    {"fonte_id":"BCB","secao":"CAMBIO","titulo":"PTAX somente fixture",
     "valor":"R$ 5/teste","referencia":RECENTE,"fonte":"fonte simulada"},
]


def anuncio(**changes):
    v={
        "origem":"Sinop","uf_origem":"MT",
        "destino":"Itaituba","uf_destino":"PA",
        "tipo":"FRETE_ANUNCIADO","valor_rs_t":250.0,
        "fonte_id":"WHATSAPP_FRETE","referencia":RECENTE,
    }
    v.update(changes)
    return v


def pacote(*, indicadores=None, fretes=None, fontes=None):
    return {"noticias":[],"indicadores":BASIC if indicadores is None else indicadores,
            "fretes":[] if fretes is None else fretes,
            "fontes":FONTES if fontes is None else fontes}


class TestGatePublicacao(unittest.TestCase):
    def setUp(self):
        self.db=abrir_outbox()

    def tearDown(self):
        self.db.close()

    def envio(self,p):
        return preparar_rotina(
            pacote=p,gerado_em=AGORA,
            auditor=lambda _:True,db=self.db,
            destinatario_hmac="f"*64,agendar=True)

    def n_rows(self):
        return self.db.execute("SELECT count(*) FROM briefing_outbox").fetchone()[0]

    def test_aprovacao_irrestrita_nao_libera_frete_antigo(self):
        r=self.envio(pacote(fretes=[anuncio(referencia=VELHO)]))
        self.assertEqual(r["status"],"BLOQUEADO_PRE_PUBLICACAO")
        self.assertIn("frete anunciado fora da janela",str(r["rejeicoes_criticas"]))
        self.assertEqual(self.n_rows(),0)

    def test_fonte_nao_autorizada_nao_libera_frete(self):
        fontes={k:dict(v) for k,v in FONTES.items()}
        fontes["WHATSAPP_FRETE"]["status_direitos"]="PENDENTE"
        r=self.envio(pacote(fretes=[anuncio()],fontes=fontes))
        self.assertEqual(r["status"],"BLOQUEADO_PRE_PUBLICACAO")
        self.assertEqual(self.n_rows(),0)

    def test_cotacao_extra_nao_autorizada_bloqueia_envio(self):
        bad={
            "fonte_id":"FONTE_NAO_REGISTRADA","secao":"PRECOS",
            "titulo":"Preço inventado","valor":"R$ 999",
            "referencia":RECENTE,"fonte":"fixture",
        }
        r=self.envio(pacote(indicadores=BASIC+[bad]))
        self.assertEqual(r["status"],"BLOQUEADO_PRE_PUBLICACAO")
        self.assertIn("INDICADOR",{x["tipo"] for x in r["rejeicoes_criticas"]})
        self.assertEqual(self.n_rows(),0)

    def test_cotacao_antiga_de_outra_bolsa_bloqueia_envio(self):
        # Um indicador válido no grupo BOLSAS não mascara outro vencido.
        bad={**BASIC[0],"titulo":"Trigo expirado","referencia":"2026-10-01T00:00:00+00:00"}
        r=self.envio(pacote(indicadores=BASIC+[bad]))
        self.assertEqual(r["status"],"BLOQUEADO_PRE_PUBLICACAO")
        self.assertIn("FRESCURA",{x["tipo"] for x in r["rejeicoes_criticas"]})
        self.assertEqual(self.n_rows(),0)

    def test_itaituba_normaliza_para_terminal_miritituba(self):
        r=montar_briefing(
            noticias=[],fontes=FONTES,data=AGORA,
            indicadores=BASIC,fretes=[anuncio()])
        self.assertEqual(r["fretes_incluidos"],1)
        self.assertIn("SINOP/MT → MIRITITUBA/PA",r["texto"])
        self.assertNotIn("ITAITUBA/PA",r["texto"])
        self.assertEqual(r["rejeicoes"],[])

    def test_acentos_rondonopolis_normalizados(self):
        item=anuncio(origem="Sorriso",destino="Rondonópolis",uf_destino="MT")
        r=montar_briefing(
            noticias=[],fontes=FONTES,data=AGORA,
            indicadores=BASIC,fretes=[item])
        self.assertEqual(r["fretes_incluidos"],1)
        self.assertIn("SORRISO/MT → RONDONOPOLIS/MT",r["texto"])

    def test_outros_itaituba_nao_sao_mapeados_implicitamente(self):
        item=anuncio(origem="Sorriso",destino="Itaituba",uf_destino="PA")
        r=montar_briefing(
            noticias=[],fontes=FONTES,data=AGORA,
            indicadores=BASIC,fretes=[item])
        self.assertEqual(r["fretes_incluidos"],0)
        self.assertIn("FRETE",{x["tipo"] for x in r["rejeicoes"]})

    def test_frete_valido_permite_agendar_sem_enviar(self):
        r=self.envio(pacote(fretes=[anuncio()]))
        self.assertEqual(r["status"],"AGENDADO_NA_OUTBOX_SEM_ENVIO")
        self.assertEqual(self.n_rows(),1)

    def test_dry_run_nao_grava_mas_revela_rejeicao(self):
        r=preparar_rotina(
            pacote=pacote(fretes=[anuncio(referencia=VELHO)]),
            gerado_em=AGORA,auditor=lambda _:True)
        self.assertEqual(r["status"],"VALIDADO_DRY_RUN")
        self.assertEqual(self.n_rows(),0)

    def test_frete_do_futuro_ou_sem_unidade_rejeitado(self):
        for changes in (
            {"referencia":"2026-10-21T10:00:00+00:00"},
            {"valor_rs_t":-1},
            {"valor_rs_t":float("nan")},
            {"tipo":"VIAGEM_REALIZADA"},
        ):
            with self.subTest(changes=changes):
                r=montar_briefing(
                    noticias=[],fontes=FONTES,data=AGORA,
                    indicadores=BASIC,fretes=[anuncio(**changes)])
                self.assertEqual(r["fretes_incluidos"],0)
                self.assertGreater(len(r["rejeicoes"]),0)


if __name__=="__main__":
    unittest.main()
