"""Reconstrução de candidatos AIS por geocerca, sem publicar fila real."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import json,sqlite3,tempfile,unittest
from pathlib import Path

from nivon.maritime.ais_ledger import ErroAIS,registrar_lote
from nivon.maritime.ais_geofence_inference import inferir_permanencias
from nivon.ponte_painel_fontes import analisar_fontes

AS_OF="2026-10-25T12:00:00Z"
WINDOW={"inicio":"2026-10-25T09:00:00Z",
        "fim":"2026-10-25T12:00:00Z"}
SQUARE=[[-27.01,-48.01],[-27.01,-47.99],[-26.99,-47.99],[-26.99,-48.01]]


def pos(mins,mmsi="123456789",lat=-27.0000,lon=-48.0000):
    obs=datetime(2026,10,25,10,0,tzinfo=timezone.utc)+timedelta(minutes=mins)
    raw={"MessageType":"PositionReport",
         "MetaData":{"MMSI":int(mmsi),"time_utc":obs.isoformat(),
                    "latitude":lat,"longitude":lon},
         "Message":{"PositionReport":{"UserID":int(mmsi),"Sog":0.5}}}
    return {"raw_json":json.dumps(raw,sort_keys=True,separators=(",",":")),
            "received_at":(obs+timedelta(minutes=1)).isoformat()}


def criar(db,rows):
    return registrar_lote(banco=db,porto_id="ITACOATIARA",
                         mensagens=rows,as_of=AS_OF)


def consultar(db,areas=None,**opts):
    return inferir_permanencias(banco=db,porto_id="ITACOATIARA",
        as_of=AS_OF,areas=areas or {"FUNDEIO":SQUARE},**(WINDOW|opts))


class GeofenceInferenceTests(unittest.TestCase):
    def test_tres_posicoes_lentas_geram_hipotese_nao_fila_real(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.db"
            criar(db,[pos(0),pos(35,lat=-27.0001),pos(80,lat=-27.0002)])
            r=consultar(db)
            self.assertEqual(r["eventos_auditados"],3)
            self.assertEqual(len(r["candidatos"]),1)
            c=r["candidatos"][0]
            self.assertEqual(c["tipo"],"PRESENCA_EM_FUNDEIO_INFERIDA")
            self.assertEqual(c["pontos_distintos"],3)
            self.assertEqual(c["permanencia_minutos_minima_inferida"],80)
            self.assertFalse(r["geocercas_homologadas"])
            self.assertIsNone(r["navios_aguardando_observados"])
            self.assertIsNone(r["tonelagem_realizada"])
            self.assertFalse(r["vqi_alimentado"])
            self.assertFalse(r["publicavel"])

    def test_tres_posicoes_na_area_de_berco_nao_viram_atracacao(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.db"
            criar(db,[pos(0),pos(35),pos(80)])
            r=consultar(db,areas={"BERCO":SQUARE})
            self.assertEqual(r["candidatos"][0]["tipo"],"PRESENCA_EM_BERCO_INFERIDA")
            self.assertFalse(r["candidatos"][0]["atracacao_confirmada"])

    def test_ponto_unico_gap_extenso_ou_entrada_saida_bloqueiam(self):
        for series in (
            [pos(0)],
            [pos(0),pos(15)],
            [pos(0),pos(15,lat=-27.02),pos(80)],
        ):
            with self.subTest(n=len(series)),tempfile.TemporaryDirectory() as d:
                db=Path(d)/"ais.db"
                criar(db,series)
                self.assertEqual(consultar(db)["candidatos"],[])

    def test_alta_velocidade_quarentena_nao_e_navio_aguardando(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.db"
            criar(db,[pos(0),pos(35,lat=10.0),pos(80)])
            r=consultar(db)
            self.assertGreaterEqual(r["mensagens_em_quarentena"],1)
            self.assertEqual(r["candidatos"],[])
            self.assertIsNone(r["navios_atracados_observados"])

    def test_areas_sobrepostas_levantam_erro(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.db"
            criar(db,[pos(0),pos(35),pos(80)])
            with self.assertRaises(ErroAIS):
                consultar(db,areas={"FUNDEIO":SQUARE,"BERCO":SQUARE})

    def test_geocercas_invalidas_nao_sao_consideradas_oficiais(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.db"
            criar(db,[pos(0)])
            for polygon in (
                [[-27.0,-48.0],[-27.0,-48.0],[-27.0,-48.0]],
                [[-27.0,-48.0],[-27.0,-47.0],[-27.0,-46.0]],
                [[100.0,-48.0],[-27.0,-48.0],[-27.0,-47.0]],
            ):
                with self.subTest(polygon=polygon),self.assertRaises(ErroAIS):
                    consultar(db,areas={"FUNDEIO":polygon})

    def test_raw_adulterado_bloqueia_todo_o_replay(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.db"
            criar(db,[pos(0),pos(35),pos(80)])
            with sqlite3.connect(db) as con:
                con.execute("UPDATE maritime_ais SET source_payload_json='{}'")
            with self.assertRaises(ValueError):
                consultar(db)

    def test_integracao_painel_nao_afeta_outros_indices(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.db"
            criar(db,[pos(0),pos(35),pos(80)])
            req={"inferencias_ais_geocerca":[{
                "banco":str(db),"porto_id":"ITACOATIARA",
                "inicio":WINDOW["inicio"],"fim":WINDOW["fim"],
                "areas":{"FUNDEIO":SQUARE},
            }]}
            p=analisar_fontes(req,as_of=AS_OF)
            self.assertEqual(len(p["candidatos_geocercas_ais"][0]["candidatos"]),1)
            self.assertEqual(p["maritimo"],[])
            self.assertEqual(p["fontes_maritimas_bigquery"],[])
            self.assertFalse(p["executou_bigquery"])


if __name__=="__main__":
    unittest.main()
