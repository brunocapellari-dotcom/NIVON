import json
import unittest
from hashlib import sha256
from decimal import Decimal

from nivon.composicao_pam_sidra import montar_pam_municipal,ErroComposicaoPAM
from nivon.agregacao_pam_ibge import agregar_municipios_pam


def inputs(municipio="5107925",area="100",prod="300",yield_="3000"):
    codes={"AREA_COLHIDA_HA":("216","Hectares",area),
           "PRODUCAO_T":("214","Toneladas",prod),
           "RENDIMENTO_KG_HA":("112","Quilogramas por Hectare",yield_)}
    raws={}
    for kind,(code,unit,value) in codes.items():
        header={"D1C":"Município (Código)","D2C":"Variável (Código)",
                "D3C":"Ano (Código)","D4C":"Produto das lavouras temporárias (Código)",
                "V":"Valor","MN":"Unidade de Medida"}
        row={"D1C":municipio,"D2C":code,"D3C":"2025","D4C":"2702",
             "V":value,"MN":unit}
        raws[kind]=json.dumps([header,row],sort_keys=True).encode()
    return dict(raws=raws,coletas={k:"2026-10-20T12:00:00Z" for k in raws},
                municipio_ibge=municipio,ano=2025,cultura="SOJA",codigo_c81="2702",
                prova_categoria_url="https://sidra.ibge.gov.br/tabela/1612",
                resolucoes_oficiais={k:"1" for k in raws},
                prova_resolucoes_sha256=sha256(b"proof fixture").hexdigest())


class TestComposicaoPAM(unittest.TestCase):
    def test_pacote_exato_mais_ponderacao_fisica(self):
        a=montar_pam_municipal(**inputs())
        self.assertEqual(Decimal(a["registro_agregavel"]["quantidade_produzida_t"]),300)
        self.assertIsNone(a["publicado_em"])
        self.assertFalse(a["vintage_asof_permitida"])
        inp=inputs(municipio="5101001",area="50",prod="100",yield_="2000")
        b=montar_pam_municipal(**inp)
        # Pacotes não garantem que estes dois municípios pertençam à mesma
        # edição: o agregador precisa de identidade externa homogênea.
        with self.assertRaises(Exception):
            agregar_municipios_pam(registros=[a["registro_agregavel"],
                b["registro_agregavel"]],uf_ibge=51,cultura="SOJA",ano=2025)

    def test_sigilo_ou_arredondamento_nao_converte_zero(self):
        for marcador in ("X","..","...","0"):
            i=inputs(area=marcador)
            with self.assertRaises(ErroComposicaoPAM):
                montar_pam_municipal(**i)

    def test_unidade_uma_variavel_incompativel(self):
        i=inputs()
        payload=json.loads(i["raws"]["PRODUCAO_T"])
        payload[1]["MN"]="Milhares de reais"
        i["raws"]["PRODUCAO_T"]=json.dumps(payload).encode()
        with self.assertRaises(ErroComposicaoPAM):
            montar_pam_municipal(**i)

    def test_faixa_temporal_entre_consultas_bloqueada(self):
        i=inputs();i["coletas"]["AREA_COLHIDA_HA"]="2026-10-20T12:45:00Z"
        with self.assertRaises(ErroComposicaoPAM):
            montar_pam_municipal(**i)

    def test_variavel_safra_ou_municipio_divergente(self):
        i=inputs();payload=json.loads(i["raws"]["RENDIMENTO_KG_HA"])
        payload[1]["D2C"]="214"
        i["raws"]["RENDIMENTO_KG_HA"]=json.dumps(payload).encode()
        with self.assertRaises(Exception):montar_pam_municipal(**i)

    def test_prova_metodologica_obrigatoria(self):
        i=inputs();i["prova_resolucoes_sha256"]="123"
        with self.assertRaises(ErroComposicaoPAM):
            montar_pam_municipal(**i)

    def test_zero_absoluto_requer_coerencia_produtividade(self):
        i=inputs(area="-",prod="300",yield_="3000")
        result=montar_pam_municipal(**i)
        self.assertEqual(result["registro_agregavel"]["area_colhida_ha"],"0")
        with self.assertRaises(Exception):
            agregar_municipios_pam(registros=[result["registro_agregavel"],
                result["registro_agregavel"]],uf_ibge=51,cultura="SOJA",ano=2025)

if __name__=="__main__": unittest.main()
