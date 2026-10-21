"""Teste de conciliação territorial do IVO, somente grandezas aditivas."""
import unittest
from dataclasses import replace
from hashlib import sha256
from math import inf, nan

from nivon.ivo_hierarquias import (
    ErroHierarquia, FolhaPrevisao, consolidar_bottom_up,
)

SHA=sha256(b"fixture-additive-only").hexdigest()


def folha(id, valor, **kwargs):
    default=dict(
        id=id, valor=valor, indicador="PRODUCAO_T", produto="SOJA",
        unidade="t", calendario="SAFRA", periodo="2026/2027",
        versao_modelo="V1", evidencia_sha256=SHA)
    default.update(kwargs)
    return FolhaPrevisao(**default)


def normal(**kw):
    dados=dict(
        folhas=[folha("MT_SORRISO",10), folha("MT_SINOP",20), folha("GO_JATAI",30)],
        grupos={"MT":("MT_SORRISO","MT_SINOP"), "BR":("MT","GO_JATAI")},
        raiz="BR",
    )
    dados.update(kw)
    return consolidar_bottom_up(**dados)


class TestIVOHierarquias(unittest.TestCase):
    def test_mais_de_um_nivel_com_evidencia(self):
        r=normal()
        self.assertEqual(r["valores_por_no"]["MT"],30.)
        self.assertEqual(r["valores_por_no"]["BR"],60.)
        self.assertEqual(r["folhas"],3)
        self.assertEqual(r["agregados"],2)
        self.assertFalse(r["modelo_homologado"])
        self.assertFalse(r["completude_universo_geografico_homologada"])
        self.assertFalse(r["intervalos_agregados_disponiveis"])
        self.assertEqual(len(r["hash_proveniencia"]),64)

    def test_ordem_das_folhas_nao_altera_hash_ou_total(self):
        a=normal()
        b=normal(folhas=list(reversed([folha("MT_SORRISO",10),
                                       folha("MT_SINOP",20),folha("GO_JATAI",30)])))
        self.assertEqual(a["hash_proveniencia"],b["hash_proveniencia"])
        self.assertEqual(a["total"],b["total"])

    def test_folha_desconhecida_e_bloqueada(self):
        with self.assertRaises(ErroHierarquia):
            normal(grupos={"BR":("MISSING","GO_JATAI"),"MT":("MT_SORRISO","MT_SINOP")})

    def test_nao_soma_preco_ou_produtividade(self):
        for metrica in ("PRECO_RS_SACA","PRODUTIVIDADE_KG_HA","COLHEITA_PCT"):
            with self.subTest(metrica=metrica):
                with self.assertRaises(ErroHierarquia):
                    normal(folhas=[folha("MT_SORRISO",10,indicador=metrica),
                                   folha("MT_SINOP",20,indicador=metrica),
                                   folha("GO_JATAI",30,indicador=metrica)])

    def test_safras_diferentes_nao_somadas(self):
        with self.assertRaises(ErroHierarquia):
            normal(folhas=[folha("MT_SORRISO",10,periodo="2026/2027"),
                           folha("MT_SINOP",20,periodo="2025/2026"),
                           folha("GO_JATAI",30)])

    def test_mistura_unidades_e_modelos_bloqueada(self):
        for mudança in ({"unidade":"kg"},{"versao_modelo":"V2"},{"produto":"MILHO"}):
            with self.subTest(mudança=mudança):
                with self.assertRaises(ErroHierarquia):
                    normal(folhas=[folha("MT_SORRISO",10),
                                   folha("MT_SINOP",20,**mudança),
                                   folha("GO_JATAI",30)])

    def test_folha_duplicada_bloqueada(self):
        with self.assertRaises(ErroHierarquia):
            normal(folhas=[folha("MT_SORRISO",10),folha("MT_SORRISO",10),
                           folha("MT_SINOP",20),folha("GO_JATAI",30)])

    def test_filhos_duplicados_bloqueados(self):
        with self.assertRaises(ErroHierarquia):
            normal(grupos={"MT":("MT_SORRISO","MT_SORRISO","MT_SINOP"),
                           "BR":("MT","GO_JATAI")})

    def test_mesmo_municipio_em_dois_pais_bloqueado(self):
        with self.assertRaises(ErroHierarquia):
            normal(grupos={"MT":("MT_SORRISO","MT_SINOP"),
                           "GO":("MT_SORRISO","GO_JATAI"),
                           "BR":("MT","GO")})

    def test_grupo_ciclico_bloqueado(self):
        with self.assertRaises(ErroHierarquia):
            normal(grupos={"MT":("MT","MT_SORRISO","MT_SINOP"),
                           "BR":("MT","GO_JATAI")})

    def test_no_independente_ou_faltando_bloqueado(self):
        with self.assertRaises(ErroHierarquia):
            normal(grupos={"MT":("MT_SORRISO","MT_SINOP"),
                           "BR":("MT",)})

    def test_negativo_nan_inf_bool_bloqueados(self):
        for value in (-1, nan, inf, True):
            with self.subTest(valor=value):
                with self.assertRaises(ErroHierarquia):
                    normal(folhas=[folha("MT_SORRISO",value),folha("MT_SINOP",20),
                                   folha("GO_JATAI",30)])

    def test_ano_civil_e_mensal_validos(self):
        for cal,comp in (("ANO_CIVIL","2026"),("MENSAL","2026-01")):
            with self.subTest(cal=cal):
                r=normal(folhas=[folha("MT_SORRISO",10,calendario=cal,periodo=comp),
                                 folha("MT_SINOP",20,calendario=cal,periodo=comp),
                                 folha("GO_JATAI",30,calendario=cal,periodo=comp)])
                self.assertEqual(r["total"],60.)

    def test_calendario_invalido_bloqueado(self):
        for period in ("2026/2028","2026/2025","2027-13"):
            with self.subTest(period=period):
                with self.assertRaises(ErroHierarquia):
                    normal(folhas=[folha("MT_SORRISO",10,periodo=period),
                                   folha("MT_SINOP",20,periodo=period),
                                   folha("GO_JATAI",30,periodo=period)])

    def test_abate_cabecas_e_area_ha_somaveis(self):
        for indicador,unidade in (("ABATE_CABECAS","cabecas"),("AREA_HA","ha")):
            with self.subTest(indicador=indicador):
                r=normal(folhas=[folha("MT_SORRISO",10,indicador=indicador,unidade=unidade),
                                 folha("MT_SINOP",20,indicador=indicador,unidade=unidade),
                                 folha("GO_JATAI",30,indicador=indicador,unidade=unidade)])
                self.assertEqual(r["total"],60.)

    def test_hash_muda_quando_valor_muda(self):
        a=normal()
        b=normal(folhas=[folha("MT_SORRISO",11),folha("MT_SINOP",20),
                         folha("GO_JATAI",30)])
        self.assertNotEqual(a["hash_proveniencia"],b["hash_proveniencia"])


if __name__=="__main__":
    unittest.main()
