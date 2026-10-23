import unittest
from types import SimpleNamespace
from nivon.corredores_multimodais_2025 import montar_relatorio,consultar
from nivon.transporte_multimodal import ErroTransporte

def rod():
    out=[]
    for i in range(16):
        out.append(SimpleNamespace(
            ano=2025,sha256="a"*64,granularidade="RGI",
            escopo="TOP_16_FLUXOS_GERAIS_ANUAIS",
            origem_uf="MT",origem_rgi=f"Outra RGI {i}",
            destino_uf="SP",destino_rgi=f"Outra Regiao {i}",
            toneladas=1_000_000))
    out[0].origem_rgi="Rondonópolis"
    out[0].toneladas=9_946_350
    out[1].origem_uf="PA"
    out[1].origem_rgi="Itaituba"
    out[1].destino_uf="MT"
    out[1].destino_rgi="Sinop"
    out[1].toneladas=6_350_618
    out[2].toneladas=98_170_287-sum(r.toneladas for j,r in enumerate(out) if j!=2)
    return out

def fer():
    return [SimpleNamespace(polo_id="MT_RONDONOPOLIS_FERRO",tu="24258027"),
            SimpleNamespace(polo_id="MT_ITIQUIRA_FERRO",tu="742649"),
            SimpleNamespace(polo_id="MT_ALTO_ARAGUAIA_FERRO",tu="1458596")]

class FakeSDK:
    class QueryJobConfig:
        def __init__(self,**kw):self.__dict__.update(kw)

class FakeClient:
    def __init__(self):self.sqls=[]
    def query(self,sql,job_config):
        self.sqls.append((sql,job_config.maximum_bytes_billed))
        return SimpleNamespace(result=lambda timeout:rod() if "vw_antt_rodovia_rgi" in sql else fer())

class Comparacao(unittest.TestCase):
    def test_camadas_separadas_e_mesmo_nome_rgi(self):
        r=montar_relatorio(rod(),fer())
        self.assertFalse(r["totais_das_modalidades_somaveis"])
        self.assertEqual(r["escopo_top16_rodoviario_toneladas"],"98170287")
        ro=next(p for p in r["polos"] if p["polo_id"]=="MT_RONDONOPOLIS_FERRO")
        self.assertEqual(ro["ferrovia_origem_ton_2025"],"24258027")
        self.assertEqual(ro["rodovia_rgi_top16_saidas"][0]["toneladas_top16"],"9946350")
        self.assertFalse(ro["transbordo_confirmado"])
        it=next(p for p in r["polos"] if p["polo_id"]=="MT_ITIQUIRA_FERRO")
        self.assertEqual(it["rodovia_rgi_top16_saidas"],[])
        self.assertEqual(it["ferrovia_origem_ton_2025"],"742649")
        mir=next(p for p in r["polos"] if p["polo_id"]=="PA_MIRITITUBA_HIDRO")
        self.assertEqual(mir["rodovia_rgi_top16_saidas"][0]["origem_rgi"],"Itaituba")
        self.assertIsNone(mir["ferrovia_origem_ton_2025"])
        self.assertFalse(mir["somar_ferrovia_rodovia_hidrovia"])

    def test_rejeitar_duplicados_rev_ou_tonelagem_alterada(self):
        cases=[
            (rod()[:-1],fer()),
            ([*rod()[:-1],rod()[0]],fer()),
            ([*rod()[:1],SimpleNamespace(**{**vars(rod()[1]),"sha256":"b"*64}),*rod()[2:]],fer()),
            (rod(),fer()[:-1]),
        ]
        for ro,fe in cases:
            with self.subTest(rows=len(ro),ferro=len(fe)):
                with self.assertRaises(ErroTransporte):montar_relatorio(ro,fe)

    def test_consulta_2_fontes_somente_readonly_com_limite(self):
        cli=FakeClient()
        v=consultar(cliente=cli,sdk=FakeSDK)
        self.assertEqual(len(cli.sqls),2)
        self.assertTrue(all(sql.startswith("SELECT ") for sql,_ in cli.sqls))
        self.assertTrue(all(limite==70_000_000 for _,limite in cli.sqls))
        self.assertEqual(v["ano"],2025)

if __name__=="__main__":
    unittest.main()
