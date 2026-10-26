"""Contrato de go-live interno: fonte real declarada, falha fechada, sem rede."""
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from nivon.portal_interno import ErroPortal, montar_snapshot, criar_app, validar_snapshot, carregar_snapshot
from scripts.gerar_painel_interno import gerar

CUT="2026-10-25T18:00:00Z"


def amostra():
    return {
        "status": "ANALISE_SHADOW_NAO_HOMOLOGADA", "executou_bigquery": True,
        "ferrovia": {
            "executado": True, "publicavel": False,
            "estado": "REVISAO_ATUAL_CONSULTADA_NAO_HOMOLOGADA",
            "fonte": "ANTT_SIADE_ORIGEM_DESTINO", "competencia": "2026-08",
            "as_of": CUT, "historico_pit_reconstruido": False,
            "transbordo_confirmado": False, "linhas_view": 2,
            "arquivos_sha256": ["a"*64],
            "polos_ferroviarios": [
                {"polo": {"id":"MT_RONDONOPOLIS_FERRO"},
                 "toneladas_ferroviarias": "10000.5"},
                {"polo": {"id":"MT_ITIQUIRA_FERRO"},
                 "toneladas_ferroviarias": "200.25"},
            ],
        },
        "fontes_maritimas_bigquery": [{
            "executado": True, "publicavel": False, "as_of": CUT,
            "fonte": "imbituba", "passagem": None,
            "estado": "PROGRAMACAO_HISTORICA_READONLY_SHADOW",
            "ids_programacao_distintos": 2, "revisoes_visiveis": 3,
            "inicio": "2026-10-01", "fim": "2026-10-25",
            "navios_operados_confirmados": None,
        }],
    }


def request(app, path):
    response = {}
    def send(status, headers):
        response["status"] = status
        response["headers"] = dict(headers)
    body = b"".join(app({"PATH_INFO":path,"REQUEST_METHOD":"GET"},send))
    return response["status"], response["headers"], body


class PortalTests(unittest.TestCase):
    def test_shadow_real_vira_painel_mas_nao_publicacao(self):
        r = montar_snapshot(amostra(), gerado_em=CUT)
        self.assertEqual(r["estado"], "DADOS_REAIS_EM_REVISAO_INTERNA_NAO_HOMOLOGADOS")
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["go_live_publico"])
        self.assertFalse(r["redistribuicao_autorizada"])
        d = {p["id"]:p for p in r["indicadores"]}
        self.assertEqual(d["ferrovia_tu"]["valor"], "10200.75")
        self.assertEqual(d["lineup_imbituba"]["valor"], "2")
        self.assertIn("nao", d["lineup_imbituba"]["ressalva"].lower())
        self.assertEqual(d["ferrovia_tu"]["referencia"], "2026-08")
        self.assertTrue(all(not p["publicavel"] for p in r["indicadores"]))

    def test_sem_readback_ou_observacoes_inventadas_nao_entra(self):
        x = amostra()
        x["executou_bigquery"] = False
        with self.assertRaises(ErroPortal):
            montar_snapshot(x, gerado_em=CUT)
        x = amostra()
        x["ferrovia"]["arquivos_sha256"] = ["nao-prova"]
        with self.assertRaises(ErroPortal):
            montar_snapshot(x, gerado_em=CUT)
        x = amostra()
        x["ferrovia"]["transbordo_confirmado"] = True
        with self.assertRaises(ErroPortal):
            montar_snapshot(x, gerado_em=CUT)
        x = amostra()
        x["fontes_maritimas_bigquery"][0]["publicavel"] = True
        with self.assertRaises(ErroPortal):
            montar_snapshot(x, gerado_em=CUT)
        x = amostra()
        x["fontes_maritimas_bigquery"][0]["ids_programacao_distintos"] = 5
        with self.assertRaises(ErroPortal):
            montar_snapshot(x, gerado_em=CUT)

    def test_ausencia_nao_equivale_a_zero(self):
        x = amostra()
        x["ferrovia"]["estado"] = "SEM_REGISTROS_NAO_SIGNIFICA_ZERO"
        del x["ferrovia"]["polos_ferroviarios"]
        r = montar_snapshot(x, gerado_em=CUT)
        self.assertNotIn("ferrovia_tu", [i["id"] for i in r["indicadores"]])
        self.assertTrue(any("nao presumir zero" in s for s in r["avisos"]))

    def test_snapshot_atomico_e_duplicatas_json(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            (root/"origem.json").write_text(json.dumps(amostra()),encoding="utf-8")
            result = gerar(entrada=root/"origem.json",saida=root/"painel.json",gerado_em=CUT)
            self.assertEqual(result["indicadores"],3)
            self.assertFalse(result["publicavel"])
            self.assertEqual(len(carregar_snapshot(root/"painel.json")["indicadores"]),3)
            bad=amostra()
            bad["ferrovia"]["arquivos_sha256"]=[]
            (root/"origem.json").write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ErroPortal):
                gerar(entrada=root/"origem.json",saida=root/"painel.json",gerado_em=CUT)
            self.assertEqual(len(carregar_snapshot(root/"painel.json")["indicadores"]),3)
            (root/"origem.json").write_text('{"status":"A","status":"B"}',encoding="utf-8")
            with self.assertRaises(ErroPortal):
                gerar(entrada=root/"origem.json",saida=root/"painel.json",gerado_em=CUT)

    def test_wsgireadonly_security_health_freshness_e_ausencia(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"snapshot.json"
            app=criar_app(path)
            self.assertEqual(request(app,"/healthz")[0],"200 OK")
            self.assertEqual(request(app,"/readyz")[0],"503 Service Unavailable")
            self.assertEqual(request(app,"/api/v1/painel")[0],"503 Service Unavailable")
            self.assertEqual(request(app,"/")[0],"200 OK")
            self.assertEqual(request(app,"/assets/portal.js")[0],"200 OK")
            snapshot=montar_snapshot(amostra(),gerado_em=CUT)
            snapshot["gerado_em"] = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
            path.write_text(json.dumps(snapshot),encoding="utf-8")
            code, hdr, body = request(app,"/api/v1/painel")
            self.assertEqual(code,"200 OK")
            self.assertEqual(json.loads(body)["frescor_snapshot"],"DEFASADO")
            self.assertEqual(request(app,"/readyz")[0],"503 Service Unavailable")
            self.assertIn("default-src 'none'",hdr["Content-Security-Policy"])
            self.assertEqual(hdr["X-Frame-Options"],"DENY")
            self.assertEqual(request(app,"/etc/passwd")[0],"404 Not Found")
            fresh = montar_snapshot(amostra(),gerado_em=CUT)
            fresh["gerado_em"] = datetime.now(timezone.utc).isoformat()
            path.write_text(json.dumps(fresh),encoding="utf-8")
            self.assertEqual(request(app,"/readyz")[0],"200 OK")
            self.assertEqual(json.loads(request(app,"/api/v1/painel")[2])["frescor_snapshot"],"ATUAL")

    def test_snapshots_publicaveis_e_dados_sinteticos_rejeitados(self):
        x=montar_snapshot(amostra(),gerado_em=CUT)
        x["publicavel"]=True
        with self.assertRaises(ErroPortal):
            validar_snapshot(x)
        x=montar_snapshot(amostra(),gerado_em=CUT)
        x["indicadores"][0]["publicavel"]=True
        with self.assertRaises(ErroPortal):
            validar_snapshot(x)


if __name__=="__main__":
    unittest.main()
