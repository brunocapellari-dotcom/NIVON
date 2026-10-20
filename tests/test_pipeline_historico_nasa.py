"""Integração sintética e local sem rede — NASA POWER, RAW e retrocarga."""
import json
import unittest
from datetime import date
from hashlib import sha256

from nivon.pipeline_historico_nasa import planejar_retrocarga, HistoricoNASA
from nivon.qualidade_cientifica import ErroCientifico


def raw():
    return json.dumps({
        "type":"Feature","geometry":{"coordinates":[-55.6,-12.4]},
        "properties":{"parameter":{
            "PRECTOTCORR":{"20250101":2.0,"20250102":-999.0,"20250103":6.0},
            "T2M":{"20250101":25.0,"20250102":26.5,"20250103":27.0},
        }}},sort_keys=True).encode("utf-8")


def lote():
    return planejar_retrocarga(
        latitudes_longitudes=[(-12.4,-55.6)],
        inicio=date(2025,1,1),fim=date(2025,1,3),
        parametros=("PRECTOTCORR","T2M"),
    )["lotes"][0]


class TestPlanejamentoNASA(unittest.TestCase):
    def test_historico_desde_1981_e_paginacao_limitada(self):
        a=planejar_retrocarga(latitudes_longitudes=[(-12.4,-55.6),(-12.4,-55.6)],
            inicio=date(1981,1,1),fim=date(2025,12,31),limite_lotes=3,
            parametros=("PRECTOTCORR",))
        self.assertEqual(a["total_lotes"],45)
        self.assertEqual(a["localizacoes_unicas"],1)
        self.assertEqual(len(a["lotes"]),3)
        self.assertEqual(a["proximo_cursor"],3)
        self.assertEqual(a["calls_executadas"],0)
        self.assertIn("time-standard=UTC",a["lotes"][0]["url"])
        b=planejar_retrocarga(latitudes_longitudes=[(-12.4,-55.6)],
            inicio=date(1981,1,1),fim=date(2025,12,31),
            cursor=3,limite_lotes=4,parametros=("PRECTOTCORR",))
        self.assertEqual(b["lotes"][0]["inicio"],"1984-01-01")

    def test_falhas_de_janela_ou_muitos_pontos(self):
        for pts in ([(-12.4,-55.6)]*4,[(200.0,-55.6)],[]):
            with self.assertRaises(ErroCientifico):
                planejar_retrocarga(latitudes_longitudes=pts,
                    inicio=date(2025,1,1),fim=date(2025,1,3))
        with self.assertRaises(ErroCientifico):
            planejar_retrocarga(latitudes_longitudes=[(-12.4,-55.6)],
                inicio=date(2025,1,1),fim=date(2025,1,3),limite_lotes=20)


class TestIngestaoNASA(unittest.TestCase):
    def setUp(self):self.db=HistoricoNASA()
    def tearDown(self):self.db.fechar()

    def importar(self,**kw):
        kwargs=dict(lote=lote(),resposta_json=raw(),
            coletado_em="2026-10-20T12:00:00+00:00")
        kwargs.update(kw)
        return self.db.importar_raw(**kwargs)

    def test_raw_integral_e_idempotencia(self):
        out=self.importar()
        self.assertEqual(out["raw_sha256"],sha256(raw()).hexdigest())
        self.assertFalse(out["permite_backtest_vintage"])
        self.assertEqual(self.db.contagem(),{"raw":1,"observacoes":6})
        self.assertEqual(self.importar()["status"],"RAW_IDEMPOTENTE")
        self.assertEqual(self.db.contagem(),{"raw":1,"observacoes":6})

    def test_cobertura_e_ausencia_de_estimativa(self):
        sha=self.importar()["raw_sha256"]
        q=self.db.qualidade(raw_sha256=sha,inicio=date(2025,1,1),fim=date(2025,1,3),
                           parametros=("PRECTOTCORR","T2M"))
        self.assertEqual(q["por_variavel"]["PRECTOTCORR"]["dias_validos"],2)
        self.assertEqual(q["por_variavel"]["PRECTOTCORR"]["dias_com_faltante"],1)
        self.assertAlmostEqual(q["por_variavel"]["PRECTOTCORR"]["cobertura_valida"],2/3)
        self.assertFalse(q["permite_backtest_vintage"])

    def test_lote_trocado_e_payload_corrompido_sem_persistencia(self):
        bad=lote()
        bad["latitude"]=-5.0
        with self.assertRaises(ErroCientifico):self.importar(lote=bad)
        with self.assertRaises(ErroCientifico):self.importar(resposta_json=b"<script>")
        with self.assertRaises(ErroCientifico):self.importar(resposta_json=b"x"*(4_000_001))
        self.assertEqual(self.db.contagem(),{"raw":0,"observacoes":0})

    def test_geo_de_outro_local_e_chuva_negativa(self):
        obj=json.loads(raw())
        obj["geometry"]["coordinates"]=[-48.,-12.4]
        with self.assertRaises(ErroCientifico):
            self.importar(resposta_json=json.dumps(obj).encode())
        obj=json.loads(raw())
        obj["properties"]["parameter"]["PRECTOTCORR"]["20250101"]=-10
        with self.assertRaises(ErroCientifico):
            self.importar(resposta_json=json.dumps(obj).encode())

    def test_sem_autorizacao_nao_persiste_arquivos(self):
        with self.assertRaises(ErroCientifico):
            HistoricoNASA("historico_nasa.db",modo="FIXTURE_OFFLINE")
        with self.assertRaises(ErroCientifico):
            HistoricoNASA(":memory:",modo="IMPORTACAO_AUTORIZADA")
        self.assertEqual(self.db.contagem()["raw"],0)

    def test_coleta_futura_e_marcacao_real_recusadas(self):
        with self.assertRaises(ErroCientifico):
            self.importar(coletado_em="2099-01-01T00:00:00Z")
        with self.assertRaises(ErroCientifico):
            self.importar(direitos={"coleta_permitida":True})

    def test_revisao_de_payload_pode_coexistir_com_raw_original(self):
        first=self.importar()
        obj=json.loads(raw())
        obj["properties"]["parameter"]["T2M"]["20250101"]=24.2
        second=self.importar(resposta_json=json.dumps(obj,sort_keys=True).encode())
        self.assertNotEqual(first["raw_sha256"],second["raw_sha256"])
        self.assertEqual(self.db.contagem()["raw"],2)
        self.assertEqual(self.db.contagem()["observacoes"],12)
        self.assertFalse(second["permite_backtest_vintage"])


if __name__=="__main__":unittest.main()
