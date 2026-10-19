import copy
import unittest

from nivon.catalogo_fontes import ErroCatalogo, carregar_catalogo
from nivon.cobertura import carregar_matriz, validar_matriz, diagnostico_matriz


class TestCoberturaNivon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = carregar_catalogo()
        cls.m = carregar_matriz(catalogo=cls.c)

    def test_dez_mercados_e_frentes_transversais(self):
        r = validar_matriz(self.m, self.c)
        self.assertEqual(r["frentes"],28)
        self.assertGreaterEqual(r["indicadores"],115)

    def test_nenhuma_frente_finge_prontidao_operacional(self):
        estado=diagnostico_matriz(self.m,self.c)
        self.assertEqual(len(estado),28)
        self.assertTrue(all(not x["apto_producao"] for x in estado))

    def test_soja_milho_tem_conab_e_comex(self):
        for id_ in ("SOJA","MILHO"):
            d=next(x for x in self.m["systems"] if x["id"]==id_)
            self.assertIn("CONAB_GRAOS_SERIES",d["data"])
            self.assertIn("MDIC_COMEX_NCM",d["data"])

    def test_diesel_vincula_precos_importacoes_e_cambio(self):
        d=next(x for x in self.m["systems"] if x["id"]=="DIESEL")
        self.assertTrue({"ANP_PRECO_REVENDA_DIESEL","ANP_IMPORTACAO_DIESEL",
                         "BCB_PTAX"}.issubset(set(d["data"])))

    def test_gado_bezerro_e_fertilizantes_nao_sao_esquecidos(self):
        idset={s["id"] for s in self.m["systems"]}
        self.assertTrue({"BOI","BEZERRO","FERTILIZANTES","CANA","GERGELIM","FRANGO","SUINO"} <= idset)

    def test_dataset_nao_registrado_reprovado(self):
        m=copy.deepcopy(self.m)
        m["systems"][0]["data"].append("FONTE_MILAGROSA")
        with self.assertRaises(ErroCatalogo):
            validar_matriz(m,self.c)

    def test_frente_sem_ressalva_reprovada(self):
        m=copy.deepcopy(self.m)
        m["systems"][0]["risks"]=[]
        with self.assertRaises(ErroCatalogo):
            validar_matriz(m,self.c)

    def test_indicador_repetido_reprovado(self):
        m=copy.deepcopy(self.m)
        m["systems"][0]["indicators"].append(m["systems"][0]["indicators"][0])
        with self.assertRaises(ErroCatalogo):
            validar_matriz(m,self.c)

    def test_whatsapp_separado_do_briefing_nivon(self):
        b=next(s for s in self.m["systems"] if s["id"]=="BRIEFING_DIARIO")
        l=next(s for s in self.m["systems"] if s["id"]=="LOGISTICA_INTERMODAL")
        self.assertNotIn("FRETES_WHATSAPP_AUTORIZADO",b["data"])
        self.assertIn("FRETES_WHATSAPP_AUTORIZADO",l["data"])

    def test_pontos_criticos_massa_e_licenca_em_riscos(self):
        milho=next(s for s in self.m["systems"] if s["id"]=="MILHO")
        self.assertIn("CEPEA", " ".join(milho["risks"]))
        boi=next(s for s in self.m["systems"] if s["id"]=="BOI")
        self.assertGreater(len(boi["risks"]),0)


if __name__ == "__main__":
    unittest.main()
