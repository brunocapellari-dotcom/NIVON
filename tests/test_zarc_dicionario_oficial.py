"""Testes do dicionário ZARC: classificação vs risco e IDs territoriais."""
import unittest
from nivon.zarc_dicionario_oficial import (
    CICLOS, SOLOS, MANEJOS, CLIMAS, NIVEIS_MANEJO,
    ErroDicionarioZarc, interpretar_metadados_linha,
)

def row():
    r={"geocodigo":"5105259","Cod_Munic":"12345","Cod_Ciclo":"20",
       "Cod_Solo":"2","Cod_Outros_Manejos":"1","Cod_Clima":"7",
       "Cod_NM":"1","UF":"MT"}
    r.update({f"dec{i}":("0" if i%2 else "") for i in range(1,37)})
    return r

class DicionarioZarcTest(unittest.TestCase):
    def test_traducoes_autenticadas(self):
        self.assertEqual(CICLOS["20"],"Grupo I")
        self.assertEqual(SOLOS["2"],"Textura Média")
        self.assertEqual(SOLOS["11"],"AD1")
        self.assertEqual(MANEJOS["1"],"Sequeiro")
        self.assertEqual(CLIMAS["7"],"Clima Tropical")
        self.assertEqual(NIVEIS_MANEJO["1"],"NM1")
    def test_cod_sicor_nao_iguala_ibge(self):
        out=interpretar_metadados_linha(row())
        self.assertEqual(out["municipio_ibge"],"5105259")
        self.assertEqual(out["municipio_sicor"],"12345")
        self.assertFalse(out["codigos_sicor_igualmente_ibge"])
        self.assertEqual(out["codigos_originais_e_rotulos"]["Cod_Solo"]["descricao_oficial"],"Textura Média")
        self.assertEqual(out["decendios_valores_brutos"]["dec1"],"0")
        self.assertEqual(out["decendios_valores_brutos"]["dec2"],"")
        self.assertFalse(out["decendios_interpretados_como_risco"])
        self.assertFalse(out["pode_recomendar_plantio"])
    def test_codigo_novo_nao_inventa_legendagem(self):
        r=row()
        r["Cod_Solo"]="99"
        out=interpretar_metadados_linha(r)
        self.assertIsNone(out["codigos_originais_e_rotulos"]["Cod_Solo"]["descricao_oficial"])
        self.assertEqual(out["codigos_originais_e_rotulos"]["Cod_Solo"]["mapeamento"],"NAO_MAPEADO")
        self.assertEqual(out["codigos_originais_e_rotulos"]["Cod_Solo"]["codigo_original"],"99")
    def test_exclusao_uf_and_invalid_ids(self):
        for name,value in (("geocodigo","51"),("UF","GO"),("Cod_Munic","CODE")):
            r=row()
            r[name]=value
            with self.subTest(name=name),self.assertRaises(ErroDicionarioZarc):
                interpretar_metadados_linha(r)
    def test_dec_incompleto_recusado(self):
        r=row()
        del r["dec36"]
        with self.assertRaises(ErroDicionarioZarc):
            interpretar_metadados_linha(r)
    def test_sicor_vazio_nao_cria_crosswalk(self):
        r=row()
        r["Cod_Munic"]=""
        out=interpretar_metadados_linha(r)
        self.assertIsNone(out["municipio_sicor"])
if __name__=="__main__":
    unittest.main()
