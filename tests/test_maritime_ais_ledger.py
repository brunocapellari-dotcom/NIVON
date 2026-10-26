"""AIS RAW → ledger SQLite → replay RO → painel, com evidências falsas bloqueadas."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3,subprocess,sys,tempfile,unittest

from nivon.maritime.ais_ledger import ErroAIS,registrar_lote
from nivon.adaptadores_operacionais import ler_replay_ais_sqlite
from nivon.ponte_painel_fontes import analisar_fontes
from nivon.painel_operacional import ErroMotor

CUTOFF="2026-10-25T12:00:00Z"


def _item(minuto,mmsi="123456789",lat=-27.000,lon=-48.000,received_delta=1):
    o=datetime(2026,10,25,10,0,tzinfo=timezone.utc)+timedelta(minutes=minuto)
    r=o+timedelta(minutes=received_delta)
    raw={"MessageType":"PositionReport",
         "MetaData":{"MMSI":int(mmsi),"time_utc":o.isoformat(),
                     "latitude":lat,"longitude":lon},
         "Message":{"PositionReport":{"UserID":int(mmsi),"Sog":2.0}}}
    return {"raw_json":json.dumps(raw,sort_keys=True,separators=(",",":")),
            "received_at":r.isoformat()}


def _insert(db,rows,**kwargs):
    return registrar_lote(banco=db,porto_id="IMBITUBA",mensagens=rows,
                         as_of=CUTOFF,**kwargs)


def _replay(db,*,fim="2026-10-25T12:00:00Z",as_of=CUTOFF):
    return ler_replay_ais_sqlite(banco=str(db),porto_id="IMBITUBA",
        inicio="2026-10-25T09:00:00Z",fim=fim,as_of=as_of)


class LedgerAISBatchTests(unittest.TestCase):
    def test_multiplos_eventos_distinguem_sequencia_de_salto(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.sqlite"
            rows=[_item(0),_item(15,lat=-27.002),_item(30,lat=-10.0)]
            result=_insert(db,rows)
            self.assertEqual(result["novos"],3)
            self.assertEqual(result["qualidade"].get("CONFIRMED_SEQUENCE"),1)
            self.assertEqual(result["qualidade"].get("QUARANTINE"),1)
            self.assertFalse(result["geocerca_validada"])
            self.assertIsNone(result["navios_operados"])
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute(
                    "SELECT count(*) FROM maritime_ais").fetchone()[0],3)
                self.assertEqual(conn.execute(
                    "SELECT count(*) FROM maritime_ais WHERE quality_status='CONFIRMED_SEQUENCE'").fetchone()[0],1)
            report=_replay(db)
            self.assertEqual(report["eventos_lidos"],3)
            self.assertEqual(report["mmsi_distintos_confirmados"],1)
            self.assertIsNone(report["tonelagem_realizada"])
            self.assertFalse(report["apto_para_indice_fila"])

    def test_repeticoes_de_raw_nao_geram_novos_eventos(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.sqlite"
            a=_item(0)
            r1=_insert(db,[a,a])
            self.assertEqual(r1["novos"],1)
            b=dict(a,received_at="2026-10-25T10:02:00Z")
            r2=_insert(db,[b])
            self.assertEqual(r2["novos"],0)
            self.assertEqual(r2["repetidos"],1)
            self.assertEqual(_replay(db)["eventos_lidos"],1)

    def test_pit_coleta_nao_antecipa_evento(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.sqlite"
            _insert(db,[_item(0),_item(15)])
            before=_replay(db,fim="2026-10-25T10:10:00Z",
                           as_of="2026-10-25T10:10:00Z")
            self.assertEqual(before["eventos_lidos"],1)
            self.assertEqual(before["mmsi_distintos_confirmados"],0)
            after=_replay(db)
            self.assertEqual(after["eventos_confirmados_sequencia"],1)

    def test_lote_invalido_nao_abre_ou_grava_arquivo(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.sqlite"
            invalid=[
                {"raw_json":"{invalid","received_at":"2026-10-25T10:02:00Z"},
                {"raw_json":"{}","received_at":"2026-10-25T10:02:00Z"},
            ]
            for bad in invalid:
                with self.subTest(row=bad),self.assertRaises(ErroAIS):
                    _insert(db,[_item(0),bad])
                self.assertFalse(db.exists())

    def test_timestamp_de_origem_e_fuso_obrigatorios(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.sqlite"
            no_clock=_item(0)
            p=json.loads(no_clock["raw_json"]);del p["MetaData"]["time_utc"]
            no_clock["raw_json"]=json.dumps(p)
            with self.assertRaises(ErroAIS):_insert(db,[no_clock])
            future=_item(0)
            future["received_at"]="2026-10-26T10:00:00Z"
            with self.assertRaises(ErroAIS):_insert(db,[future])
            without_tz=_item(0)
            without_tz["received_at"]="2026-10-25T10:01:00"
            with self.assertRaises(ErroAIS):_insert(db,[without_tz])
            self.assertFalse(db.exists())

    def test_nao_aceitar_mmsi_invalido_ou_coordenadas_sem_sentido(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.sqlite"
            for bad in (_item(0,mmsi="000000000"),
                        _item(0,lat=100),_item(0,lon=-190)):
                with self.subTest(bad=bad),self.assertRaises(ErroAIS):
                    _insert(db,[bad])

    def test_nao_confirmar_ponto_isolado_ou_intervalo_grande(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.sqlite"
            _insert(db,[_item(0),_item(270)])
            with sqlite3.connect(db) as con:
                rows=con.execute("SELECT quality_status FROM maritime_ais ORDER BY observed_at").fetchall()
            self.assertTrue(all(r[0]=="UNCONFIRMED_SINGLE" for r in rows))

    def test_proveniencia_raw_adulterada_reprovada_no_replay(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"ais.sqlite"
            _insert(db,[_item(0)])
            with sqlite3.connect(db) as con:
                con.execute("UPDATE maritime_ais SET source_payload_json='{}'")
            with self.assertRaises(ErroMotor):
                _replay(db)

    def test_replay_do_painel_em_comando_unico(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); db=root/"ais.sqlite"
            inputs=root/"lote.jsonl"
            inputs.write_text("\n".join(json.dumps(x) for x in [_item(0),_item(15)]),
                              encoding="utf-8")
            cmd=[sys.executable,str(Path(__file__).resolve().parents[1]/"scripts"/"rodar_lote_ais.py"),
                "--entrada",str(inputs),"--banco",str(db),"--porto-id","IMBITUBA",
                "--as-of",CUTOFF]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertEqual(json.loads(result.stdout)["novos"],2)
            result2=analisar_fontes({"replays_ais_sqlite":[{
                "banco":str(db),"porto_id":"IMBITUBA",
                "inicio":"2026-10-25T09:00:00Z",
                "fim":"2026-10-25T12:00:00Z"}]},as_of=CUTOFF)
            self.assertEqual(result2["replays_ais"][0]["eventos_confirmados_sequencia"],1)
            self.assertEqual(result2["maritimo"],[])
            self.assertFalse(result2["executou_bigquery"])


if __name__=="__main__":
    unittest.main()
