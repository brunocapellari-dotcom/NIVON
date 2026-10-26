"""AIS append-only: somente evidências, sem inferir operação portuária.

Entrada: registros normalizados por `parse_aisstream_message` e JSON RAW de
origem. Preserva SHA dos bytes recebidos e rejeita relógios sem origem.
"""
from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
from math import asin,cos,isfinite,radians,sin,sqrt
from pathlib import Path
import json,re,sqlite3

from .ais_stream import parse_aisstream_message

PORT=re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")
MMSI=re.compile(r"^[0-9]{9}$")
SOURCE="aisstream"

class ErroAIS(ValueError):
    pass

def _time(s):
    if not isinstance(s,str):
        raise ErroAIS("horario AIS nao informado")
    try: d=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError as e: raise ErroAIS("horario AIS invalido") from e
    if d.utcoffset() is None: raise ErroAIS("horario AIS sem timezone")
    return d.astimezone(timezone.utc)

def _sha(s):
    return sha256(s.encode("utf-8")).hexdigest()

def _distance(a,b):
    p1,p2=radians(a[0]),radians(b[0])
    dlat=p2-p1;dlon=radians(b[1]-a[1])
    h=sin(dlat/2)**2+cos(p1)*cos(p2)*sin(dlon/2)**2
    return 2*6371.0088*asin(min(1,sqrt(max(h,0))))/1.852

SCHEMA="""CREATE TABLE IF NOT EXISTS maritime_ais(
 event_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,port_id TEXT NOT NULL,
 mmsi TEXT NOT NULL,observed_at TEXT NOT NULL,collected_at TEXT NOT NULL,
 quality_status TEXT NOT NULL,payload_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,
 source_payload_sha256 TEXT NOT NULL,source_payload_json TEXT NOT NULL,
 latitude REAL NOT NULL,longitude REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ais_port_mmsi_time
 ON maritime_ais(port_id,mmsi,observed_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ais_raw_unique
 ON maritime_ais(source_id,port_id,source_payload_sha256);"""

def registrar_lote(*,banco,porto_id,mensagens,as_of):
    if not isinstance(porto_id,str) or not PORT.fullmatch(porto_id):
        raise ErroAIS("porto_id invalido")
    if not isinstance(mensagens,list) or not 1<=len(mensagens)<=2000:
        raise ErroAIS("maximo 2000 mensagens AIS por lote")
    cutoff=_time(as_of)
    path=Path(banco)
    if path.is_symlink() or path.parent.is_symlink() or not path.parent.is_dir():
        raise ErroAIS("arquivo AIS inseguro")
    valid=[]
    for row in mensagens:
        if not isinstance(row,dict) or set(row)!={"raw_json","received_at"}:
            raise ErroAIS("evidencia AIS requer RAW e horario de recepcao")
        raw=row["raw_json"];received=_time(row["received_at"])
        if not isinstance(raw,str) or len(raw.encode("utf-8"))>32000 or not raw:
            raise ErroAIS("RAW ausente ou excessivo")
        if received>cutoff: raise ErroAIS("coleta posterior ao as_of")
        try: doc=json.loads(raw)
        except ValueError as e: raise ErroAIS("RAW JSON invalido") from e
        if not isinstance(doc,dict) or doc.get("MessageType")!="PositionReport":
            raise ErroAIS("RAW nao e posicao AIS")
        n=parse_aisstream_message(doc,received_at=row["received_at"])
        if n is None or n["timestamp_basis"]!="SOURCE":
            raise ErroAIS("origem do timestamp nao comprovada")
        observed=_time(n["observed_at"])
        if observed>received or (received-observed).total_seconds()>7200:
            raise ErroAIS("relogios AIS incoerentes")
        mmsi=str(n.get("mmsi") or "")
        if not MMSI.fullmatch(mmsi) or mmsi=="000000000":
            raise ErroAIS("MMSI invalido")
        lat,lon=n.get("latitude"),n.get("longitude")
        if any(type(x) not in (int,float) or not isfinite(x) for x in (lat,lon)):
            raise ErroAIS("coordenada AIS invalida")
        if not -90<=lat<=90 or not -180<=lon<=180:
            raise ErroAIS("coordenada fora do globo")
        raw_sha=_sha(raw)
        data={"mmsi":mmsi,"observed_at":observed.isoformat(),
              "collected_at":received.isoformat(),"latitude":lat,"longitude":lon,
              "source_raw_sha256":raw_sha,"port_id":porto_id,
              "geofence_validated":False,"duv_confirmada":False,
              "operacao_concluida":False}
        payload=json.dumps(data,sort_keys=True,separators=(",",":"))
        digest=_sha(payload)
        valid.append((SOURCE,porto_id,mmsi,observed.isoformat(),received.isoformat(),
                      digest,payload,raw_sha,raw,lat,lon))
    valid.sort(key=lambda x:(x[3],x[2],x[5]))
    with sqlite3.connect(path,timeout=10) as conn:
        conn.executescript(SCHEMA)
        added=0;quality={}
        for r in valid:
            event_id=_sha(SOURCE+"|"+r[5])
            if conn.execute("""SELECT 1 FROM maritime_ais
                WHERE event_id=? OR (source_id=? AND port_id=? AND source_payload_sha256=?)""",
                (event_id,SOURCE,porto_id,r[7])).fetchone():
                continue
            prior=conn.execute("""SELECT observed_at,latitude,longitude FROM maritime_ais
                WHERE port_id=? AND mmsi=? AND observed_at<?
                ORDER BY observed_at DESC LIMIT 1""",(porto_id,r[2],r[3])).fetchone()
            status="UNCONFIRMED_SINGLE"
            if prior:
                hours=(_time(r[3])-_time(prior[0])).total_seconds()/3600
                if 0<hours<=4:
                    speed=_distance((prior[1],prior[2]),(r[9],r[10]))/hours
                    status=("QUARANTINE" if speed>60 else
                            "CONFIRMED_SEQUENCE" if hours>=5/60 else "UNCONFIRMED_SINGLE")
            conn.execute("""INSERT INTO maritime_ais
                (event_id,source_id,port_id,mmsi,observed_at,collected_at,
                 quality_status,payload_sha256,payload_json,source_payload_sha256,
                 source_payload_json,latitude,longitude)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id,r[0],r[1],r[2],r[3],r[4],status,
                 r[5],r[6],r[7],r[8],r[9],r[10]))
            quality[status]=quality.get(status,0)+1
            added+=1
    return {"estado":"EVIDENCIAS_AIS_LOCAIS","porto_id":porto_id,
            "novos":added,"repetidos":len(valid)-added,
            "qualidade":quality,"geocerca_validada":False,
            "navios_operados":None,"duv_confirmadas":None,
            "carga_realizada":None,"publicavel":False}
