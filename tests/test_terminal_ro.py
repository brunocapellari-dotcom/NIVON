import json
import unittest
from nivon.terminal_ro import Terminal, contrato, ErroTerminal

def fixture():
    return {"estado":"PAINEL_MULTIMODAL_2025_DADOS_SEPARADOS_COM_PROVENIENCIA",
        "ano":2025, "escopo_top16_rodoviario_toneladas":"98170287",
        "escopo_top16_e_total_nacional":False,
        "totais_das_modalidades_somaveis":False,
        "transbordos_efetivos_identificados":False,
        "rodovia_rgi_fluxos_top16":[{"origem_rgi":"Sorriso","origem_uf":"MT","destino_rgi":"Rondonopolis","destino_uf":"MT","toneladas_top16":"10"} for i in range(16)],
        "polos":[{"nome_polo":"Rondonópolis","uf":"MT","ferrovia_origem_ton_2025":None,"ferrovia_escopo":"SEM_DADO_FERROVIARIO_NESTE_RECORTE"} for i in range(9)],
        "fontes":[{"fonte":"ANTT_SIADE","modal":"FERROVIA"}],
        "avisos":["Nao somar modais"]}

def get(app,path="/api/v1/painel",method="GET",query=""):
    out={}
    def start(code,headers):
        out["code"]=code;out["headers"]=dict(headers)
    body=b"".join(app({"PATH_INFO":path,"REQUEST_METHOD":method,"QUERY_STRING":query},start))
    return out,body

class TestTerminal(unittest.TestCase):
    def test_sem_credenciais_nao_le_dados(self):
        calls=[]
        app=Terminal(reader=lambda:calls.append(1),enable_data=False)
        s,b=get(app)
        self.assertTrue(s["code"].startswith("503"))
        self.assertEqual(calls,[])
        self.assertEqual(json.loads(b)["status"],"LEITURA_DESABILITADA")

    def test_recorte_fechado_e_cache(self):
        calls=[];time=[0]
        def reader():
            calls.append(1);return fixture()
        app=Terminal(reader=reader,enable_data=True,clock=lambda:time[0])
        s,b=get(app);d=json.loads(b)
        self.assertEqual(d["ano_referencia"],2025)
        self.assertEqual(d["escopo_top16_rodoviario_toneladas"],"98170287")
        self.assertFalse(d["publicavel"])
        self.assertFalse(d["hidrovia_oficial_homologada"])
        get(app);self.assertEqual(len(calls),1)
        time[0]=301;get(app);self.assertEqual(len(calls),2)

    def test_contrato_invalido_bloqueia(self):
        bad=fixture();bad["totais_das_modalidades_somaveis"]=True
        with self.assertRaises(ErroTerminal):
            contrato(bad)
        s,b=get(Terminal(reader=lambda:bad,enable_data=True))
        self.assertTrue(s["code"].startswith("503"))
        self.assertNotIn(b"Traceback",b)

    def test_http_and_assets(self):
        app=Terminal(reader=fixture,enable_data=True)
        for method,query in [("POST",""),("GET","tamper=true")]:
            s,b=get(app,method=method,query=query)
            self.assertTrue(s["code"].startswith(("400","405")))
        s,b=get(app,path="/healthz")
        self.assertFalse(json.loads(b)["publicacao_homologada"])
        for path in ["/","/assets/terminal.css","/assets/terminal.js"]:
            s,b=get(app,path=path)
            self.assertTrue(s["code"].startswith("200"))
            self.assertGreater(len(b),150)
        self.assertIn("default-src 'none'",s["headers"]["Content-Security-Policy"])

if __name__=="__main__":
    unittest.main()
