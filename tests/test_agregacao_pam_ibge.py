import unittest
from hashlib import sha256
from decimal import Decimal
from nivon.agregacao_pam_ibge import (agregar_municipios_pam,comparar_total_oficial_uf,
                                     ErroAgregacaoIBGE)


def rows():
    digest=sha256(b"fixtures ibge 2025").hexdigest()
    def row(code,area,prod):
        return {"municipio_ibge":code,"ano":2025,"cultura":"SOJA",
                "produto_ibge":"SOJA_GRAO","codigo_categoria_c81":"2713",
                "area_colhida_ha":area,
                "quantidade_produzida_t":prod,"rendimento_reportado_kg_ha":prod*1000/area,
                "resolucao_area_ha":"1","resolucao_producao_t":"1",
                "resolucao_rendimento_kg_ha":"1","edicao_id":"SIDRA_2025_FIXTURE",
                "raw_sha256":digest}
    return [row("5101001",10,10),row("5101002",90,270)]


class TestAgregacaoPAM(unittest.TestCase):
    def call(self,r=None,**kwargs):
        p=dict(registros=rows() if r is None else r,uf_ibge=51,cultura="SOJA",ano=2025)
        p.update(kwargs)
        return agregar_municipios_pam(**p)

    def test_produtividade_e_area_ponderadas(self):
        x=self.call()
        self.assertEqual(Decimal(x["producao_total_t"]),280)
        self.assertEqual(Decimal(x["area_colhida_ha"]),100)
        self.assertEqual(Decimal(x["rendimento_ponderado_kg_ha"]),2800)
        self.assertNotEqual(Decimal(x["rendimento_ponderado_kg_ha"]),2000)
        self.assertFalse(x["habilita_modelo"])

    def test_universo_parcial_nao_confronta(self):
        agg=self.call()
        r=comparar_total_oficial_uf(agregado=agg,
            area_oficial_ha=200,producao_oficial_t=500,
            tolerancia_area_ha=1,tolerancia_producao_t=1)
        self.assertIsNone(r["residuo_area_ha"])
        self.assertFalse(r["habilita_publicacao"])

    def test_conservacao_e_residuo_explicito(self):
        x=self.call()
        r=comparar_total_oficial_uf(agregado=x,
           area_oficial_ha=100,producao_oficial_t=281,
           tolerancia_area_ha=0,tolerancia_producao_t=0,
           cobertura_integral_auditada=True)
        self.assertFalse(r["conservacao_consistente"])
        self.assertEqual(r["residuo_producao_t"],"-1")

    def test_igualdade_c81_obrigatoria_no_agregador(self):
        agregado=self.call()
        self.assertEqual(agregado["codigo_categoria_c81"],"2713")
        falsas=rows()
        falsas[0]["codigo_categoria_c81"]="2702"  # FEIJÃO, não SOJA
        with self.assertRaisesRegex(ErroAgregacaoIBGE,"C81"):
            self.call(falsas)
        sem_codigo=rows()
        del sem_codigo[0]["codigo_categoria_c81"]
        with self.assertRaisesRegex(ErroAgregacaoIBGE,"C81"):
            self.call(sem_codigo)

    def test_nao_mistura_algodao_caroco_pluma(self):
        r=rows()
        for x in r:x["cultura"]="ALGODAO";x["produto_ibge"]="ALGODAO_PLUMA"
        with self.assertRaises(ErroAgregacaoIBGE):
            self.call(r,cultura="ALGODAO")

    def test_nao_inventa_pam_gergelim_antes_2025(self):
        r=rows()
        for x in r:x["cultura"]="GERGELIM";x["produto_ibge"]="GERGELIM_SEMENTE";x["ano"]=2024
        with self.assertRaises(ErroAgregacaoIBGE):
            self.call(r,cultura="GERGELIM",ano=2024)

    def test_falha_municipio_uf_e_vintage_misto(self):
        r=rows();r[0]["municipio_ibge"]="3101001"
        with self.assertRaises(ErroAgregacaoIBGE):self.call(r)
        r=rows();r[1]["edicao_id"]="ANOTHER_EDITION"
        with self.assertRaises(ErroAgregacaoIBGE):self.call(r)

    def test_resolucao_inconsistente_marca_reprovado(self):
        r=rows();r[0]["rendimento_reportado_kg_ha"]=6000
        a=self.call(r)
        self.assertEqual(a["municipios_reprovados_arredondamento"],["5101001"])
        with self.assertRaises(ErroAgregacaoIBGE):
            comparar_total_oficial_uf(agregado=a,area_oficial_ha=100,
                producao_oficial_t=280,tolerancia_area_ha=1,tolerancia_producao_t=1,
                cobertura_integral_auditada=True)

    def test_nao_aceita_produtividade_extrema_ou_boolean(self):
        r=rows();r[0]["quantidade_produzida_t"]=10000
        with self.assertRaises(ErroAgregacaoIBGE):self.call(r)
        r=rows();r[0]["quantidade_produzida_t"]=True
        with self.assertRaises(ErroAgregacaoIBGE):self.call(r)

    def test_producao_sem_area_rejeitada(self):
        r=rows();r[0]["area_colhida_ha"]=0
        with self.assertRaises(ErroAgregacaoIBGE):self.call(r)

if __name__=="__main__":unittest.main()
