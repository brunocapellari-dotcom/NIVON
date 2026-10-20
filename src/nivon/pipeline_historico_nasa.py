"""Retrocarga NASA POWER: planejamento paginado + importação RAW offline auditável.

O módulo NÃO faz HTTP nem agenda execuções. Quem adquirir dados deve passar
pelos gates de licença/autorização, TLS, MIME, limite de tamanho e captura RAW.
Estimativas gridded não são chuva de pluviômetro, e séries API atuais NÃO
reconstituem automaticamente vintages disponíveis historicamente.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import sqlite3

from .nasa_power_nivon import (
    MAX_BYTES, PERMITIDOS, normalizar_resposta, url_diaria,
)
from .qualidade_cientifica import ErroCientifico, _instante, numero

DATASET = "NASA_POWER_AGRO_DAILY"
_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS raw_nasa (
 raw_sha256 TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL,
 request_url TEXT NOT NULL, coletado_em_utc TEXT NOT NULL,
 fonte_id TEXT NOT NULL, dataset_id TEXT NOT NULL, natureza TEXT NOT NULL,
 modo TEXT NOT NULL, direitos_ref TEXT,
 raw_bytes BLOB NOT NULL, linhas_total INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS obs_nasa (
 raw_sha256 TEXT NOT NULL REFERENCES raw_nasa(raw_sha256),
 dia TEXT NOT NULL, variavel TEXT NOT NULL, valor TEXT,
 unidade TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
 evidencia TEXT NOT NULL,
 PRIMARY KEY(raw_sha256, dia, variavel)
);
CREATE INDEX IF NOT EXISTS idx_nasa_obs ON obs_nasa(dia,variavel);
"""


def planejar_retrocarga(
    *, latitudes_longitudes: list[tuple[float, float]],
    inicio: date, fim: date, cursor: int = 0,
    limite_lotes: int = 4, parametros: tuple[str, ...] = PERMITIDOS,
) -> dict[str, Any]:
    """Paginação sem HTTP, por ano/posição; não gera carga acima dos limites.

    Coordenadas exatas deduplicadas a seis casas. O serviço tem resoluções
    distintas por variável; NÃO supor que toda coordenada próxima seja a
    mesma célula, nem disparar pedidos repetidos em loop.
    """
    if not isinstance(inicio,date) or type(inicio) is not date or type(fim) is not date:
        raise ErroCientifico("datas devem ser date, sem horário implícito")
    if inicio.year < 1981 or fim > date.today() or fim < inicio:
        raise ErroCientifico("período NASA POWER fora da disponibilidade declarada")
    if type(cursor) is not int or cursor < 0 or type(limite_lotes) is not int or not 1 <= limite_lotes <= 8:
        raise ErroCientifico("cursor/limite não autorizado")
    if not isinstance(latitudes_longitudes,list) or not 1 <= len(latitudes_longitudes) <= 3:
        raise ErroCientifico("máximo 3 pontos explícitos por plano")
    locais: list[tuple[float,float]] = []
    ids: set[tuple[float,float]] = set()
    for point in latitudes_longitudes:
        if not isinstance(point,(tuple,list)) or len(point)!=2:
            raise ErroCientifico("ponto deve ser latitude/longitude")
        lat = numero(point[0],"latitude",nao_negativo=False)
        lon = numero(point[1],"longitude",nao_negativo=False)
        if not (-90<=lat<=90 and -180<=lon<=180):
            raise ErroCientifico("coordenadas fora da Terra")
        rounded=(round(lat,6),round(lon,6))
        if rounded not in ids:
            ids.add(rounded);locais.append(rounded)
    lots: list[dict[str,Any]] = []
    for latitude,longitude in locais:
        year=inicio.year
        while year<=fim.year:
            start=max(inicio,date(year,1,1))
            end=min(fim,date(year,12,31))
            url=url_diaria(latitude=latitude,longitude=longitude,
                           inicio=start,fim=end,parametros=parametros)
            lots.append({
                "dataset_id":DATASET,
                "latitude":latitude,"longitude":longitude,
                "inicio":start.isoformat(),"fim":end.isoformat(),
                "parametros":list(parametros),"time_standard":"UTC",
                "url":url,"requisicao_sha256":sha256(url.encode("utf-8")).hexdigest(),
                "origem":"NASA_POWER_MODELATED_GRIDDED",
                "status":"PLANEJADO_SEM_AUTORIZACAO_DE_COLETA",
            })
            year+=1
    if cursor>len(lots):
        raise ErroCientifico("cursor além do número de lotes")
    selected=lots[cursor:cursor+limite_lotes]
    next_cursor=cursor+len(selected)
    return {
        "dataset_id":DATASET,"inicio":inicio.isoformat(),"fim":fim.isoformat(),
        "total_lotes":len(lots),"localizacoes_unicas":len(locais),
        "lotes":selected,
        "proximo_cursor":next_cursor if next_cursor<len(lots) else None,
        "calls_executadas":0,
        "gate":"PROIBIDO_AUTOMATIZAR_SEM_DIREITOS_E_POLITICA_DE_TAXA",
        "nota":"NASA alerta contra repetição de pedidos da mesma célula espacial; dedupe das células oficiais requer metadados e resolução por parâmetro",
    }


class HistoricoNASA:
    """Índice local RAW+normalizado; não faz tráfego de rede."""

    def __init__(self, destino: str = ":memory:", *, modo: str = "FIXTURE_OFFLINE"):
        if modo not in {"FIXTURE_OFFLINE","IMPORTACAO_AUTORIZADA"}:
            raise ErroCientifico("modo desconhecido")
        if modo=="FIXTURE_OFFLINE" and destino!=":memory:":
            raise ErroCientifico("fixtures somente em memória, nunca em arquivo do projeto")
        if modo=="IMPORTACAO_AUTORIZADA":
            p=Path(destino)
            if not p.is_absolute() or p.is_symlink() or destino==":memory:":
                raise ErroCientifico("modo real exige caminho absoluto regular controlado")
        self.modo=modo
        self.conn=sqlite3.connect(destino)
        self.conn.row_factory=sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def fechar(self) -> None:
        self.conn.close()

    def _validar_direitos(self, direitos: dict | None) -> str | None:
        if self.modo=="FIXTURE_OFFLINE":
            if direitos is not None:raise ErroCientifico("fixtures não recebem atestado de uso real")
            return None
        if (not isinstance(direitos,dict)
            or direitos.get("coleta_permitida") is not True
            or direitos.get("armazenamento_permitido") is not True
            or direitos.get("analise_permitida") is not True
            or not isinstance(direitos.get("aprovacao_externa_ref"),str)
            or not direitos["aprovacao_externa_ref"].strip()):
            raise PermissionError("autorizações externas de coleta, armazenamento e análise exigidas")
        return direitos["aprovacao_externa_ref"]

    def importar_raw(
        self, *, lote: dict, resposta_json: bytes, coletado_em: str,
        direitos: dict | None = None,
    ) -> dict:
        ref=self._validar_direitos(direitos)
        if not isinstance(lote,dict) or lote.get("dataset_id")!=DATASET:
            raise ErroCientifico("lote sem identidade canônica")
        if not isinstance(resposta_json,bytes) or not 0<len(resposta_json)<=MAX_BYTES:
            raise ErroCientifico("RAW inválido ou acima do limite máximo")
        data=_instante(coletado_em,"coletado_em")
        if data>datetime.now(timezone.utc)+timedelta(minutes=5):
            raise ErroCientifico("coleta futura não comprovável")
        try:
            start=date.fromisoformat(lote["inicio"])
            end=date.fromisoformat(lote["fim"])
            params=tuple(lote["parametros"])
            latitude=numero(lote["latitude"],"latitude",nao_negativo=False)
            longitude=numero(lote["longitude"],"longitude",nao_negativo=False)
        except (KeyError,TypeError,ValueError) as exc:
            raise ErroCientifico("metadados do lote inválidos") from exc
        url=url_diaria(latitude=latitude,longitude=longitude,
                       inicio=start,fim=end,parametros=params)
        if (url!=lote.get("url") or lote.get("time_standard")!="UTC"
            or lote.get("requisicao_sha256")!=sha256(url.encode()).hexdigest()):
            raise ErroCientifico("lote alterado ou fora do planejador")
        try:payload=json.loads(resposta_json.decode("utf-8"))
        except (ValueError,UnicodeError) as exc:
            raise ErroCientifico("JSON NASA corrompido/não UTF-8") from exc
        if not isinstance(payload,dict):
            raise ErroCientifico("NASA POWER: objeto JSON obrigatório")
        normalizados=normalizar_resposta(payload,parametros=params,inicio=start,fim=end,
                         coletado_em=coletado_em,fonte_url=url,
                         latitude_solicitada=latitude,longitude_solicitada=longitude)
        if not normalizados:
            raise ErroCientifico("NASA POWER: resposta sem observações")
        digest=sha256(resposta_json).hexdigest()
        ids=(digest,sha256(url.encode()).hexdigest())
        antigo=self.conn.execute(
            "SELECT request_sha256, linhas_total FROM raw_nasa WHERE raw_sha256=?",(digest,)
        ).fetchone()
        if antigo:
            if antigo["request_sha256"]!=ids[1] or antigo["linhas_total"]!=len(normalizados):
                raise ErroCientifico("hash RAW associado a identidade conflitante")
            return {"status":"RAW_IDEMPOTENTE","raw_sha256":digest,
                    "linhas":antigo["linhas_total"],"permite_backtest_vintage":False}
        with self.conn:
            self.conn.execute(
                """INSERT INTO raw_nasa (
                raw_sha256, request_sha256,request_url,coletado_em_utc,fonte_id,
                dataset_id,natureza,modo,direitos_ref,raw_bytes,linhas_total
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (digest,ids[1],url,data.astimezone(timezone.utc).isoformat(),
                 "NASA_POWER",DATASET,"ESTIMADO_EM_GRADE",self.modo,ref,
                 sqlite3.Binary(resposta_json),len(normalizados)))
            self.conn.executemany(
                """INSERT INTO obs_nasa (raw_sha256,dia,variavel,valor,unidade,
                latitude,longitude,evidencia) VALUES(?,?,?,?,?,?,?,?)""",
                [(digest,x["competencia"],x["variavel"],
                  None if x["valor"] is None else str(Decimal(str(x["valor"]))),
                  x["unidade"],x["latitude"],x["longitude"],"ESTIMADO_EM_GRADE")
                 for x in normalizados])
        return {
            "status":"RAW_E_LINHAS_PERSISTIDOS_OFFLINE",
            "raw_sha256":digest,"linhas":len(normalizados),
            "natureza":"ESTIMADO_EM_GRADE","permite_backtest_vintage":False,
            "motivo":"Ausência de vintage/publicação validada; RAW atual não prova conhecimento histórico",
        }

    def qualidade(self, *, raw_sha256: str, inicio: date, fim: date,
                  parametros: tuple[str,...]) -> dict:
        if not isinstance(raw_sha256,str) or len(raw_sha256)!=64:
            raise ErroCientifico("hash SHA256 obrigatório")
        raw=self.conn.execute(
            "SELECT request_url,modo FROM raw_nasa WHERE raw_sha256=?",(raw_sha256,)
        ).fetchone()
        if raw is None:raise ErroCientifico("RAW não encontrado")
        if type(inicio) is not date or type(fim) is not date or fim<inicio:
            raise ErroCientifico("período inválido")
        d=(fim-inicio).days+1
        scores={}
        for param in parametros:
            if param not in PERMITIDOS:raise ErroCientifico("parâmetro desconhecido")
            rows=self.conn.execute(
                "SELECT dia,valor FROM obs_nasa WHERE raw_sha256=? AND variavel=? AND dia>=? AND dia<=?",
                (raw_sha256,param,inicio.isoformat(),fim.isoformat())
            ).fetchall()
            disponiveis=sum(r["valor"] is not None for r in rows)
            scores[param]={
                "dias_esperados":d,"dias_encontrados":len(rows),
                "dias_validos":disponiveis,
                "dias_sem_registro":d-len(rows),
                "dias_com_faltante":len(rows)-disponiveis,
                "cobertura_valida":disponiveis/d,
            }
        return {
            "dataset_id":DATASET,"raw_sha256":raw_sha256,
            "por_variavel":scores,
            "status":"QUALIDADE_FISICA_PRELIMINAR_SEM_HOMOLOGACAO",
            "permite_backtest_vintage":False,
            "nota":"Cobertura não equivale a acurácia; comparar com estações oficiais INMET posteriormente",
        }

    def contagem(self) -> dict:
        return {"raw":self.conn.execute("SELECT COUNT(*) FROM raw_nasa").fetchone()[0],
                "observacoes":self.conn.execute("SELECT COUNT(*) FROM obs_nasa").fetchone()[0]}
