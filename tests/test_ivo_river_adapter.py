import unittest
from datetime import datetime,timezone

from nivon.ivo_river_adapter import ErroOnline, replay_river

UTC=timezone.utc


def t(y,m,d):
    return datetime(y,m,d,12,tzinfo=UTC).isoformat()


def rows(n=9,all_late=False):
    ps=[]
    for i in range(1,n+1):
        y,m=2025,i
        iy,im=(2024,12) if i==1 else (2025,i-1)
        oy,om=(2025,i+1) if i<12 else (2026,1)
        ps.append({
            "modelo_id":"MILHO_ML","versao_modelo":"V1",
            "indicador":"VOLUME","geografia":"MT","unidade":"t",
            "fonte_verdade":"CONAB","horizonte_meses":1,
            "previsao_id":f"P{i}","observacao_id":f"O{i}",
            "periodo":f"{y}-{m:02d}",
            "previsao_emitida_em":t(iy,im,14),
            "previsao_registrada_em":t(iy,im,15),
            "vintage_publicada_em":t(oy,om,3),
            "observacao_registrada_em":t(2026,2,4) if all_late else t(oy,om,4),
            "previsto":110., "observado":100., "baseline":105.,
        })
    return ps


def aval(ps=None,modo="BACKTEST"):
    return {"status":"AVALIACAO_DESCRITIVA_NAO_HOMOLOGADA",
            "agregacao_comparavel":True,"verdade":"PRIMEIRA_PUBLICACAO",
            "modo":modo,"avaliacoes":ps if ps is not None else rows()}


class MediaOnline:
    def __init__(self):
        self.n=0;self.total=0.
    def predict_one(self,features):
        return self.total/self.n if self.n else 0.
    def learn_one(self,features,y):
        self.total+=y;self.n+=1


class TestIVORiver(unittest.TestCase):
    def test_replay_aprende_so_de_rotulos_ja_publicados(self):
        result=replay_river(aval(),factory=MediaOnline)
        self.assertEqual(result["estado"],"REPLAY_INCREMENTAL_NAO_HOMOLOGADO")
        self.assertEqual(result["avaliadas"],9)
        self.assertFalse(result["autopromocao"])
        self.assertFalse(result["modelo_homologado"])
        self.assertEqual(result["replay"][0]["resultado_conhecido_para_treino"],0)
        self.assertEqual(result["replay"][1]["resultado_conhecido_para_treino"],0)
        self.assertGreater(result["replay"][-1]["resultado_conhecido_para_treino"],0)
        self.assertLess(result["mae_proposta_online"],result["mae_original"])

    def test_publicacao_tardia_impede_aprender_resultado_futuro(self):
        x=replay_river(aval(rows(all_late=True)),factory=MediaOnline)
        self.assertTrue(all(r["resultado_conhecido_para_treino"]==0 for r in x["replay"]))
        self.assertEqual(x["mae_original"],x["mae_proposta_online"])

    def test_sem_fonte_primaria_bloqueia(self):
        a=aval()
        a["verdade"]="ULTIMA_ATE_CORTE"
        with self.assertRaises(ErroOnline):
            replay_river(a,factory=MediaOnline)

    def test_dados_com_unidades_mistas_bloqueia(self):
        p=rows()
        p[1]["unidade"]="kg"
        with self.assertRaises(ErroOnline):
            replay_river(aval(p),factory=MediaOnline)

    def test_duplicatas_bloqueadas(self):
        p=rows()
        p[1]["previsao_id"]=p[0]["previsao_id"]
        with self.assertRaises(ErroOnline):
            replay_river(aval(p),factory=MediaOnline)

    def test_publicacao_anterior_emissao_bloqueia(self):
        p=rows()
        p[0]["vintage_publicada_em"]=t(2024,11,1)
        with self.assertRaises(ErroOnline):
            replay_river(aval(p),factory=MediaOnline)

    def test_fabrica_nao_autorizada_bloqueada(self):
        with self.assertRaises(ErroOnline):
            replay_river(aval(),factory=lambda:object())

    def test_nao_confunde_modos(self):
        x=replay_river(aval(modo="LIVE"),factory=MediaOnline)
        self.assertEqual(x["modo"],"LIVE")
        self.assertFalse(x["modelo_homologado"])

    def test_maximo_de_registros_e_limites(self):
        with self.assertRaises(ErroOnline):
            replay_river(aval(),factory=MediaOnline,max_linhas=3)
        with self.assertRaises(ErroOnline):
            replay_river(aval(),factory=MediaOnline,max_linhas=True)

    def test_variavel_observada_nao_vaza_do_proprio_fold(self):
        ps=rows()
        ps[0]["observado"]=10.
        x=replay_river(aval(ps),factory=MediaOnline)
        self.assertEqual(x["replay"][0]["original"],x["replay"][0]["proposta_online"])


if __name__=="__main__":
    unittest.main()
