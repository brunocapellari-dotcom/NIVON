"""Regressão em lote: ledger comercial + SQLite AIS lidos por CLI real."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from nivon.adaptadores_operacionais import adaptar_fretes_consolidados, ler_replay_ais_sqlite
from nivon.painel_operacional import ErroMotor
from nivon.ponte_painel_fontes import analisar_fontes


AS_OF = "2026-10-23T12:00:00Z"


def pacote_fretes():
    registros = []
    for i, dia in enumerate((10, 11, 12, 17, 18, 20)):
        data=f"2026-10-{dia:02d}"
        registros.append({
            "registro_id": f"reg-{i}", "oferta_id":f"of-{i}", "publicacao_id": f"pub-{i}",
            "municipio_ibge": "5107602", "destino_ibge":"3548500",
            "pickup_entity_id":"SILO_001", "transportadora_id":"CARREGADOR_A",
            "descarga_entity_id":"TERMINAL_A", "produto":"SOJA",
            "equipamento":"RODOTREM", "regime":"PJ",
            "frete_base_brl_t":str((100,100,100,105,110,110)[i]),
            "pedagio_brl_t":"10", "frete_cheio_brl_t":"110",
            "data_referencia":data,
            "data_publicacao":data+"T09:00:00Z", "data_coleta":data+"T10:00:00Z",
            "fonte_id":"WHATSAPP_AUTORIZADO", "provedor_id":"CANAL_A",
            "publicacoes_origem":[f"pub-{i}"],
        })
    return {
        "natureza":"FRETE_ANUNCIADO_NAO_CONTRATADO",
        "total_registros_individuais_deduplicados":len(registros),
        "total_registros_divulgados":len(registros),
        "total_publicacoes_recebidas":len(registros),
        "registros":registros,
    }


def abrir_ais(banco):
    conn=sqlite3.connect(banco)
    conn.execute("""
      CREATE TABLE maritime_ais (
        event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
        port_id TEXT, mmsi TEXT, observed_at TEXT NOT NULL,
        collected_at TEXT NOT NULL, quality_status TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL)
    """)
    for n, (mmsi, qualidade) in enumerate((
        ("123456789","CONFIRMED_SEQUENCE"),
        ("123456789","CONFIRMED_SEQUENCE"),
        ("987654321","UNCONFIRMED_SINGLE"),
        ("234567890","CONFIRMED_SEQUENCE"),
    )):
        obs=f"2026-10-23T10:{n*10:02d}:00+00:00"
        row={"observed_at":obs,"mmsi":mmsi,"message_type":"PositionReport"}
        raw=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        digest=sha256(raw.encode()).hexdigest()
        event_id=sha256(("AISSTREAM_PILOTO|"+digest).encode()).hexdigest()
        conn.execute("""INSERT INTO maritime_ais VALUES(?,?,?,?,?,?,?,?,?)""",
                     (event_id,"AISSTREAM_PILOTO","SANTOS",mmsi,obs,
                      "2026-10-23T11:00:00+00:00",qualidade,digest,raw))
    conn.commit()
    conn.close()


class AdaptadoresTests(unittest.TestCase):
    def test_consolidado_sem_mesclar_transportadoras_ou_pontos(self):
        base=pacote_fretes()
        mais=dict(base["registros"][-1], registro_id="reg-novo",
                  pickup_entity_id="OUTRO_SILO",frete_base_brl_t="210")
        base["registros"].append(mais)
        base["total_registros_individuais_deduplicados"]+=1
        saida=adaptar_fretes_consolidados(base,as_of=AS_OF)
        self.assertEqual(saida["series_distintas"],2)
        self.assertEqual(saida["registros_elegiveis"],7)
        self.assertFalse(saida["negociacoes_confirmadas"])
        originais=[s for s in saida["series"]
                   if s["observacoes"][0]["campos"]["ponto_embarque"]=="SILO_001"]
        self.assertEqual(len(originais),1)
        self.assertEqual(len(originais[0]["observacoes"]),6)

    def test_tendencia_avaliada_com_dinamica_nao_certificada(self):
        painel=analisar_fontes({"fretes_consolidados":pacote_fretes()},as_of=AS_OF)
        self.assertEqual(len(painel["quantitativo"]),1)
        r=painel["quantitativo"][0]
        self.assertEqual(r["tendencia"],"ALTA")
        self.assertFalse(r["publicavel"])
        self.assertEqual(r["dinamica_historica"]["motivo"],"banda_comercial_ausente")
        self.assertEqual(painel["fretes_consolidados"]["registros_elegiveis"],6)

    def test_preco_futuro_omitido_sem_alterar_amostra(self):
        dados=pacote_fretes()
        novo=dict(dados["registros"][0],registro_id="reg-futuro",oferta_id="of-futuro",
                  data_referencia="2026-10-24",data_publicacao="2026-10-24T09:00:00Z",
                  data_coleta="2026-10-24T10:00:00Z",frete_base_brl_t="999")
        dados["registros"].append(novo)
        dados["total_registros_individuais_deduplicados"]+=1
        result=adaptar_fretes_consolidados(dados,as_of=AS_OF)
        self.assertEqual(result["registros_futuros_excluidos"],1)
        self.assertEqual(result["registros_elegiveis"],6)

    def test_erros_de_contagem_ou_divulgacao_negociada(self):
        a=pacote_fretes()
        a["total_registros_individuais_deduplicados"]=100
        with self.assertRaises(ErroMotor):
            adaptar_fretes_consolidados(a,as_of=AS_OF)
        b=pacote_fretes()
        b["natureza"]="FRETE_NEGOCIADO"
        with self.assertRaises(ErroMotor):
            adaptar_fretes_consolidados(b,as_of=AS_OF)

    def test_replay_sqlite_verdadeiro_readonly_sem_inferir_fila(self):
        with tempfile.TemporaryDirectory() as d:
            arq=str(Path(d)/"ais.sqlite")
            abrir_ais(arq)
            antes=Path(arq).read_bytes()
            saida=ler_replay_ais_sqlite(
                banco=arq,porto_id="SANTOS",inicio="2026-10-23T09:30:00Z",
                fim="2026-10-23T11:00:00Z",as_of=AS_OF)
            self.assertEqual(saida["eventos_lidos"],4)
            self.assertEqual(saida["eventos_confirmados_sequencia"],3)
            self.assertEqual(saida["mmsi_distintos_confirmados"],2)
            self.assertIsNone(saida["navios_aguardando"])
            self.assertIsNone(saida["tonelagem_realizada"])
            self.assertFalse(saida["apto_para_indice_fila"])
            self.assertEqual(Path(arq).read_bytes(),antes)

    def test_replay_truncado_e_corrompido_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            arq=str(Path(d)/"ais.sqlite")
            abrir_ais(arq)
            with self.assertRaises(ErroMotor):
                ler_replay_ais_sqlite(banco=arq,porto_id="SANTOS",
                    inicio="2026-10-23T09:00:00Z",fim="2026-10-23T11:00:00Z",
                    as_of=AS_OF,limite=3)
            with sqlite3.connect(arq) as conn:
                conn.execute("UPDATE maritime_ais SET payload_sha256=? LIMIT 1",("f"*64,))
            with self.assertRaises(ErroMotor):
                ler_replay_ais_sqlite(banco=arq,porto_id="SANTOS",
                    inicio="2026-10-23T09:00:00Z",fim="2026-10-23T11:00:00Z",
                    as_of=AS_OF)
            with self.assertRaises(ErroMotor):
                ler_replay_ais_sqlite(banco=arq,porto_id="SANTOS;DROP",
                    inicio="2026-10-23T09:00:00Z",fim="2026-10-23T11:00:00Z",
                    as_of=AS_OF)

    def test_integracao_duas_fontes_em_um_unico_comando(self):
        with tempfile.TemporaryDirectory() as d:
            pasta=Path(d)
            db=str(pasta/"mar.sqlite")
            abrir_ais(db)
            pacote={"fretes_consolidados":pacote_fretes(),
                "replays_ais_sqlite":[{
                    "banco":db,"porto_id":"SANTOS",
                    "inicio":"2026-10-23T09:30:00Z",
                    "fim":"2026-10-23T11:00:00Z"
                }]}
            entrada=pasta/"painel.json"
            entrada.write_text(json.dumps(pacote,ensure_ascii=False),encoding="utf-8")
            proc=subprocess.run([sys.executable,
                str(Path(__file__).resolve().parents[1]/"scripts"/"rodar_painel_operacional.py"),
                "--entrada",str(entrada),"--as-of",AS_OF],text=True,capture_output=True,
                timeout=30,cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(proc.returncode,0,proc.stderr+" "+proc.stdout)
            result=json.loads(proc.stdout)
            self.assertEqual(result["replays_ais"][0]["eventos_lidos"],4)
            self.assertEqual(result["quantitativo"][0]["tendencia"],"ALTA")
            self.assertEqual(result["quantitativo"][0]["dinamica_historica"]
                             ["motivo"],"banda_comercial_ausente")
            self.assertFalse(result["quantitativo"][0]["publicavel"])


if __name__=="__main__":
    unittest.main()
