import unittest

from nivon.cadeias_adicionais import ObservacaoCadeia
from nivon.pecuaria_sidra_abate import auditar_agregados_sidra_abate, UF_IBGE

def obs(uf, indicador, valor):
    return ObservacaoCadeia(
        produto="BOVINO", uf=uf, calendario="TRIMESTRE",
        competencia="2026-T2", indicador=indicador, valor=valor,
        unidade="CABECAS" if indicador == "ABATE_CABECAS" else "KG",
        classificacao="INFORMADO", fonte_id="IBGE", referencia="2026-06-30",
        publicacao="2026-09-21T12:00:00-03:00",
        coleta="2026-10-20T15:00:00-04:00", origem_sha256="a"*64)


def snap(menos_ultima=False, delta_br=0):
    ufs=list(UF_IBGE.values())
    if menos_ultima:
        ufs=ufs[:-1]
    dados=[obs("BR","ABATE_CABECAS",270+delta_br),
           obs("BR","PESO_CARCACAS_KG",27000)]
    for uf in ufs:
        dados.extend([obs(uf,"ABATE_CABECAS",10),
                      obs(uf,"PESO_CARCACAS_KG",1000)])
    return {"especie":"BOVINO", "classificacao":"NORMALIZACAO_OFFLINE_NAO_HOMOLOGADA",
            "observacoes":dados}


class TestAuditoriaSIDRA(unittest.TestCase):
    def test_27_ufs_e_brasil_conciliados(self):
        valores=auditar_agregados_sidra_abate(resultado=snap())
        self.assertEqual(len(valores),2)
        self.assertEqual({x["status"] for x in valores},{"CONSISTENTE"})
        self.assertEqual({x["residuo_brasil_menos_ufs"] for x in valores},{0.0})

    def test_diferenca_nao_corrigida(self):
        valores=auditar_agregados_sidra_abate(resultado=snap(delta_br=1))
        abate=next(v for v in valores if v["indicador"]=="ABATE_CABECAS")
        self.assertEqual(abate["status"],"DIVERGENCIA_A_INVESTIGAR")
        self.assertEqual(abate["residuo_brasil_menos_ufs"],1)
        self.assertEqual(abate["valor_brasil"],271)

    def test_uf_incompleta_nao_imputa(self):
        valores=auditar_agregados_sidra_abate(resultado=snap(menos_ultima=True))
        self.assertEqual({x["status"] for x in valores},{"INCOMPLETO_SEM_IMPUTACAO"})
        self.assertTrue(all(x["soma_ufs"] is None for x in valores))

if __name__=="__main__":
    unittest.main()
