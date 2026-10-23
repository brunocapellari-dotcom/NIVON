import unittest

from nivon.cadeias_adicionais import ObservacaoCadeia
from nivon.motores import DadoInvalido
from nivon.pecuaria_sidra_abate import auditar_agregados_sidra_abate, UF_IBGE

FONTE_FAKE = "fixture sintetica; nao comprova presenca de UF no IBGE"
SHA_FAKE = "a"*64
TABELAS = {"BOVINO": "1092", "SUINO": "1093", "FRANGO": "1094"}


def obs(uf, indicador, valor, especie):
    return ObservacaoCadeia(
        produto=especie, uf=uf, calendario="TRIMESTRE",
        competencia="2026-T2", indicador=indicador, valor=valor,
        unidade="CABECAS" if indicador == "ABATE_CABECAS" else "KG",
        classificacao="INFORMADO", fonte_id="IBGE", referencia="2026-06-30",
        publicacao="2026-09-21T12:00:00-03:00",
        coleta="2026-10-20T15:00:00-04:00", origem_sha256="b"*64)


def cobertura(especie, ufs):
    return {"2026-T2": {"especie": especie, "tabela_sidra": TABELAS[especie],
        "ufs": list(ufs), "fonte_evidencia": FONTE_FAKE,
        "origem_sha256": SHA_FAKE}}


def snap(especie="BOVINO", ufs=None, delta_br=0):
    ufs = list(UF_IBGE.values()) if ufs is None else list(ufs)
    dados = [obs("BR", "ABATE_CABECAS", len(ufs)*10+delta_br, especie),
             obs("BR", "PESO_CARCACAS_KG", len(ufs)*1000, especie)]
    for uf in ufs:
        dados.extend([obs(uf, "ABATE_CABECAS", 10, especie),
                      obs(uf, "PESO_CARCACAS_KG", 1000, especie)])
    return {"especie": especie, "tabela_sidra": TABELAS[especie],
            "classificacao": "NORMALIZACAO_OFFLINE_NAO_HOMOLOGADA",
            "observacoes": dados}


class TestAuditoriaSIDRA(unittest.TestCase):
    def test_sem_cobertura_completa_nao_presume_27_ufs(self):
        valores = auditar_agregados_sidra_abate(resultado=snap())
        self.assertEqual({x["status"] for x in valores}, {"COBERTURA_NAO_VERIFICADA"})
        self.assertTrue(all(x["soma_ufs"] is None for x in valores))
        self.assertTrue(all(x["ufs_esperadas"] is None for x in valores))

    def test_bovino_27_ufs_com_cobertura_declarada(self):
        ufs = list(UF_IBGE.values())
        valores = auditar_agregados_sidra_abate(
            resultado=snap(), cobertura_por_competencia=cobertura("BOVINO", ufs))
        self.assertEqual(len(valores), 2)
        self.assertEqual({x["status"] for x in valores}, {"CONSISTENTE_COM_COBERTURA_DECLARADA"})
        self.assertTrue(all(not x["homologado"] for x in valores))
        self.assertEqual({x["ufs_esperadas"] for x in valores}, {27})
        self.assertEqual({x["residuo_brasil_menos_ufs"] for x in valores}, {0.0})

    def test_26_ufs_frango_suino_nao_exigem_27(self):
        # Excluida uma UF arbitraria APENAS nesta fixture sintetica.
        # Nao supor que esta seja a UF excluida em tabelas reais do IBGE.
        ufs = list(UF_IBGE.values())[:-1]
        for especie in ("FRANGO", "SUINO"):
            resultado = auditar_agregados_sidra_abate(
                resultado=snap(especie, ufs),
                cobertura_por_competencia=cobertura(especie, ufs))
            self.assertEqual({r["ufs_esperadas"] for r in resultado}, {26})
            self.assertEqual({r["status"] for r in resultado},
                             {"CONSISTENTE_COM_COBERTURA_DECLARADA"})

    def test_diferenca_sinalizada_sem_ajuste(self):
        ufs = list(UF_IBGE.values())
        valores = auditar_agregados_sidra_abate(
            resultado=snap(delta_br=1),
            cobertura_por_competencia=cobertura("BOVINO", ufs))
        abate = next(x for x in valores if x["indicador"] == "ABATE_CABECAS")
        self.assertEqual(abate["status"], "DIVERGENCIA_A_INVESTIGAR")
        self.assertEqual(abate["residuo_brasil_menos_ufs"], 1)
        self.assertEqual(abate["valor_brasil"], 271)

    def test_cobertura_uf_incompleta_nao_imputa(self):
        ufs = list(UF_IBGE.values())
        valores = auditar_agregados_sidra_abate(
            resultado=snap(ufs=ufs[:-1]),
            cobertura_por_competencia=cobertura("BOVINO", ufs))
        self.assertEqual({x["status"] for x in valores}, {"INCOMPLETO_SEM_IMPUTACAO"})
        self.assertEqual({x["ufs_faltantes"][-1] for x in valores}, {ufs[-1]})
        self.assertTrue(all(x["soma_ufs"] is None for x in valores))

    def test_uf_extra_bloqueia_comparacao(self):
        ufs = list(UF_IBGE.values())
        valores = auditar_agregados_sidra_abate(
            resultado=snap(),
            cobertura_por_competencia=cobertura("BOVINO", ufs[:-1]))
        self.assertEqual({x["status"] for x in valores},
                         {"COBERTURA_DIVERGENTE_SEM_IMPUTACAO"})
        self.assertTrue(all(x["soma_ufs"] is None for x in valores))

    def test_rejeita_evidencia_ou_lista_invalida(self):
        ufs = list(UF_IBGE.values())
        for update in (
            {"ufs": [ufs[0], ufs[0]]},
            {"ufs": [*ufs, "XX"]},
            {"origem_sha256": "invalid"},
            {"fonte_evidencia": ""},
            {"especie": "SUINO"},
            {"tabela_sidra": "1093"},
        ):
            cov = cobertura("BOVINO", ufs)
            cov["2026-T2"].update(update)
            with self.assertRaises(DadoInvalido):
                auditar_agregados_sidra_abate(
                    resultado=snap(), cobertura_por_competencia=cov)

    def test_cobertura_pode_mudar_por_periodo(self):
        # A auditoria nao congela 26/27 como regra global de qualquer ano.
        ufs = list(UF_IBGE.values())[:-2]
        v = auditar_agregados_sidra_abate(
            resultado=snap("SUINO", ufs),
            cobertura_por_competencia=cobertura("SUINO", ufs))
        self.assertEqual({x["ufs_esperadas"] for x in v}, {25})
        self.assertEqual({x["status"] for x in v}, {"CONSISTENTE_COM_COBERTURA_DECLARADA"})

    def test_sem_brasil_nao_calcula_soma(self):
        ufs = list(UF_IBGE.values())
        s = snap()
        s["observacoes"] = [o for o in s["observacoes"] if o.uf != "BR"]
        v = auditar_agregados_sidra_abate(
            resultado=s, cobertura_por_competencia=cobertura("BOVINO", ufs))
        self.assertEqual({x["status"] for x in v}, {"INCOMPLETO_SEM_IMPUTACAO"})
        self.assertTrue(all(x["soma_ufs"] is None for x in v))


if __name__ == "__main__":
    unittest.main()
