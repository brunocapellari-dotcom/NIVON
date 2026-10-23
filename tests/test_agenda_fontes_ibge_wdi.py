"""Agenda de IBGE e Banco Mundial, isolada de rede e Cloud."""
import datetime
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load_ops():
    script=Path(__file__).resolve().parents[1]/"scripts"/"operar_fontes_reais.py"
    spec=importlib.util.spec_from_file_location("nivon_operar_fontes_reais",script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgendaAgroTest(unittest.TestCase):
    def test_fontes_brasil_argentina_uf_e_anual(self):
        ops=load_ops()
        calls=[]
        def stub(tipo):
            def f(*args,**kwargs):
                calls.append((tipo,kwargs))
                return {"novas_observacoes":1,"sha256":"a"*64}
            return f
        with tempfile.TemporaryDirectory() as base:
            with patch.object(ops,"coletar_bcra",stub("bcra")),\
                 patch.object(ops,"coletar_granos_ar",stub("granos")),\
                 patch.object(ops,"coletar_ibge_pam",stub("ibge")),\
                 patch.object(ops,"coletar_wdi",stub("wdi")):
                resposta=ops.operar(base=base,hoje=datetime.date(2026,10,23),
                     coletar_ibge=True,coletar_banco_mundial=True)
            self.assertEqual(resposta["sucesso"],8)
            self.assertEqual(resposta["falhas"],0)
            ibge=[c[1] for c in calls if c[0]=="ibge"]
            wdi=[c[1] for c in calls if c[0]=="wdi"]
            self.assertEqual({r["uf"] for r in ibge},{"MT","PR"})
            self.assertEqual({r["ano"] for r in ibge},{2025})
            self.assertEqual({r["pais"] for r in wdi},{"BRA","ARG"})
            self.assertEqual({r["indicador"] for r in wdi},
                {"AG.YLD.CREL.KG","AG.CON.FERT.ZS"})
            self.assertEqual({(r["inicio"],r["fim"]) for r in wdi},{(2019,2025)})

    def test_coletas_agro_desativadas_ate_flag(self):
        ops=load_ops()
        calls=[]
        def stub(tipo):
            def f(*args,**kwargs):
                calls.append(tipo)
                return {"novas_observacoes":0,"sha256":"b"*64}
            return f
        with tempfile.TemporaryDirectory() as base:
            with patch.object(ops,"coletar_bcra",stub("bcra")),\
                 patch.object(ops,"coletar_granos_ar",stub("granos")),\
                 patch.object(ops,"coletar_ibge_pam",stub("ibge")),\
                 patch.object(ops,"coletar_wdi",stub("wdi")):
                result=ops.operar(base=base,hoje=datetime.date(2026,10,23))
            self.assertEqual(calls,["bcra","granos"])
            self.assertEqual(result["sucesso"],2)

if __name__=="__main__":
    unittest.main()
