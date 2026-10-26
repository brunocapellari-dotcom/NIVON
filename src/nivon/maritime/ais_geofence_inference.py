"""Candidatos de permanencia AIS por geocerca declarada, nunca escala real.

Consome o ledger RAW historizado, verifica proveniencia com replay RO e
exige repeticao temporal, sem ponte automatica para VQI/ETA/DUV.
"""
from __future__ import annotations
from datetime import datetime
from hashlib import sha256
from math import asin,cos,isfinite,radians,sin,sqrt
from pathlib import Path
import json,sqlite3

from .ais_ledger import ErroAIS
from ..adaptadores_operacionais import ler_replay_ais_sqlite
from ..painel_operacional import _tempo


def _nm(a,b):
    phi1,phi2=radians(a[0]),radians(b[0])
    dphi=phi2-phi1;dlam=radians(b[1]-a[1])
    h=sin(dphi/2)**2+cos(phi1)*cos(phi2)*sin(dlam/2)**2
    return 2*6371.0088*asin(min(1,sqrt(max(0,h))))/1.852


def _inside(lat,lon,poly):
    inside=False;j=len(poly)-1
    for i in range(len(poly)):
        yi,xi=poly[i];yj,xj=poly[j]
        if (xi>lon)!=(xj>lon):
            intersection=(yj-yi)*(lon-xi)/(xj-xi)+yi
            if lat<intersection:inside=not inside
        j=i
    return inside


def _polygon(polygon):
    if not isinstance(polygon,list) or not 3<=len(polygon)<=32:
        raise ErroAIS("geocerca precisa de 3 a 32 vertices")
    points=[]
    for row in polygon:
        if not isinstance(row,(list,tuple)) or len(row)!=2:
            raise ErroAIS("vertex exige latitude e longitude")
        a,b=row
        if any(type(x) not in (float,int) or not isfinite(x) for x in (a,b)):
            raise ErroAIS("coordenadas de geocerca invalidas")
        if not (-90<=a<=90 and -180<=b<=180):
            raise ErroAIS("vertices fora do globo")
        points.append((float(a),float(b)))
    if len(set(points))<3:
        raise ErroAIS("geocerca degenerada")
    if max(x[0] for x in points)-min(x[0] for x in points)>2:
        raise ErroAIS("geocerca excede alcance local")
    if max(x[1] for x in points)-min(x[1] for x in points)>2:
        raise ErroAIS("geocerca cruza area geograficamente invalida")
    shoelace=sum(points[i][1]*points[(i+1)%len(points)][0]-
                  points[(i+1)%len(points)][1]*points[i][0]
                  for i in range(len(points)))
    if abs(shoelace)<1e-8:
        raise ErroAIS("area da geocerca insuficiente")
    return points


def inferir_permanencias(*,banco,porto_id,inicio,fim,as_of,areas,
                         min_pontos=3,min_minutos=60,max_gap_minutos=90,
                         max_deslocamento_kn=2.0,limite=2000):
    """Retorna somente HIPOTESES de permanencia em area.

    As geocercas sao declaradas no pedido, sem homologacao independente.
    Mesmo candidatos consistentes NAO comprovam fundeio oficial ou berco.
    """
    if not isinstance(areas,dict) or not areas or set(areas)-{"FUNDEIO","BERCO"}:
        raise ErroAIS("areas aceitas: FUNDEIO ou BERCO")
    if type(min_pontos) is not int or not 3<=min_pontos<=10:
        raise ErroAIS("minimo de pontos invalido")
    if type(min_minutos) is not int or not 30<=min_minutos<=720:
        raise ErroAIS("permanencia minima invalida")
    if type(max_gap_minutos) is not int or not 15<=max_gap_minutos<=180:
        raise ErroAIS("gap AIS invalido")
    if type(max_deslocamento_kn) not in (int,float) or not (
        0.1<=max_deslocamento_kn<=5 and isfinite(max_deslocamento_kn)
    ):
        raise ErroAIS("velocidade de movimento maxima invalida")
    polys={k:_polygon(v) for k,v in areas.items()}
    # Confere hashes e cronologia sem escrever, reutilizando o verificador
    # do painel; qualquer corrupção/interrupcao bloqueia TODOS os candidatos.
    audit=ler_replay_ais_sqlite(banco=str(banco),porto_id=porto_id,
                               inicio=inicio,fim=fim,as_of=as_of,limite=limite)
    p=Path(banco)
    if p.is_symlink() or not p.is_file():
        raise ErroAIS("ledger nao existe")
    uri="file:"+str(p.resolve())+"?mode=ro"
    with sqlite3.connect(uri,uri=True,timeout=5) as conn:
        conn.execute("PRAGMA query_only=ON")
        cols={r[1] for r in conn.execute("PRAGMA table_info(maritime_ais)")}
        if not {"latitude","longitude","source_payload_sha256","source_payload_json"}.issubset(cols):
            raise ErroAIS("ledger AIS legado sem coordenadas e RAW original")
        from_date=_tempo(inicio).isoformat()
        end_date=_tempo(fim).isoformat()
        cutoff=_tempo(as_of).isoformat()
        rows=conn.execute("""SELECT mmsi,observed_at,latitude,longitude,quality_status
                             FROM maritime_ais WHERE port_id=? AND observed_at>=?
                             AND observed_at<=? AND collected_at<=?
                             ORDER BY mmsi,observed_at LIMIT ?""",
                          (porto_id,from_date,end_date,cutoff,limite+1)).fetchall()
    if len(rows)!=audit["eventos_lidos"]:
        raise ErroAIS("contagem de eventos muda entre replay e geocerca")
    grouped={}
    for mmsi,ts,lat,lon,quality in rows:
        if quality=="QUARANTINE":
            continue
        matching=[name for name,poly in polys.items() if _inside(lat,lon,poly)]
        if len(matching)>1:
            raise ErroAIS("geocercas sobrepostas para mesma posicao AIS")
        grouped.setdefault(mmsi,[]).append(
            (ts,lat,lon,quality,matching[0] if matching else None))
    candidates=[]
    def _inspect(mmsi,segment):
        if not segment or segment[0][4] is None:return
        distinct={r[0] for r in segment}
        delta=(_tempo(segment[-1][0])-_tempo(segment[0][0])).total_seconds()/60
        validated=sum(r[3]=="CONFIRMED_SEQUENCE" for r in segment)
        if (len(distinct)<min_pontos or delta<min_minutos
            or validated<min_pontos-1):
            return
        candidates.append({
            "mmsi":mmsi,"tipo":"PRESENCA_EM_"+segment[0][4]+"_INFERIDA",
            "primeira_posicao":_tempo(segment[0][0]).isoformat(),
            "ultima_posicao":_tempo(segment[-1][0]).isoformat(),
            "pontos_distintos":len(distinct),
            "permanencia_minutos_minima_inferida":round(delta,1),
            "duv":None,"atracacao_confirmada":False,
            "espera_oficial_confirmada":False,"operacao_confirmada":False,
            "natureza":"INFERIDO_AIS_SHADOW"
        })
    for mmsi,series in grouped.items():
        window=[]
        for pos in series:
            if window:
                h=(_tempo(pos[0])-_tempo(window[-1][0])).total_seconds()/3600
                speed=(_nm((window[-1][1],window[-1][2]),(pos[1],pos[2]))/h
                       if h>0 else float("inf"))
                if (pos[4]!=window[-1][4] or h*60>max_gap_minutos
                    or speed>max_deslocamento_kn):
                    _inspect(mmsi,window)
                    window=[]
            window.append(pos)
        _inspect(mmsi,window)
    return {
        "estado":"CANDIDATOS_PRESENCA_AIS_SHADOW",
        "porto_id":porto_id,"as_of":_tempo(as_of).isoformat(),
        "eventos_auditados":audit["eventos_lidos"],
        "mensagens_em_quarentena":audit["qualidade_eventos"].get("QUARANTINE",0),
        "geocercas_sha256":{key:sha256(json.dumps(poly).encode()).hexdigest()
                           for key,poly in sorted(polys.items())},
        "geocercas_homologadas":False,
        "candidatos":sorted(candidates,key=lambda x:(x["mmsi"],x["primeira_posicao"])),
        "navios_aguardando_observados":None,
        "navios_atracados_observados":None,
        "tonelagem_realizada":None,"publicavel":False,
        "vqi_alimentado":False,"duv_confirmada":False,
    }
