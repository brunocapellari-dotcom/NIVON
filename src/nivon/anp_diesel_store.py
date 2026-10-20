"""Persistência e indicador de preços ANP municipal, sem identificadores de postos.

Entrada: resumo_diesel_municipal de CSV ANP adquirido por via autorizada.
Sem rede, sem números inventados; snapshots brutos devem ficar em evidência
externa autorizada. Semanas domingo-sábado são derivadas do calendário,
NÃO períodos oficiais divulgados pela ANP. Sem média ponderada por volume.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from pathlib import Path

from .indicadores_historicos import _direitos, _instante


class ErroHistoricoDiesel(ValueError):
    pass


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MESES = re.compile(r"20[0-9]{2}-(0[1-9]|1[0-2])\Z")
_UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
_PRODUTOS = frozenset(("DIESEL","DIESEL S10"))
_CAMPOS = frozenset({
    "uf","municipio","produto","semana_inicio_inferida",
    "semana_fim_inferida","postos_observacoes","preco_medio_revenda_rs_l",
    "preco_mediano_revenda_rs_l","preco_minimo_revenda_rs_l",
    "preco_maximo_revenda_rs_l",
})


def abrir_historico_diesel(path: str | Path = ":memory:") -> sqlite3.Connection:
    if str(path) != ":memory:":
        p=Path(path)
        if p.is_symlink() or not p.parent.is_dir():
            raise ErroHistoricoDiesel("caminho do SQLite inseguro")
    db=sqlite3.connect(str(path),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS diesel_edicoes (
        id INTEGER PRIMARY KEY,
        sha256_original TEXT NOT NULL UNIQUE,
        competencia_mes TEXT NOT NULL,
        fonte_url TEXT NOT NULL,
        evidencia_direitos TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ('SINTETICO','REAL_AUTORIZADO')),
        sha256_series TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS diesel_capturas (
        edicao_id INTEGER NOT NULL REFERENCES diesel_edicoes(id),
        coletado_utc TEXT NOT NULL,
        PRIMARY KEY(edicao_id,coletado_utc)
      );
      CREATE TABLE IF NOT EXISTS diesel_municipios (
        edicao_id INTEGER NOT NULL REFERENCES diesel_edicoes(id),
        uf TEXT NOT NULL, municipio TEXT NOT NULL, produto TEXT NOT NULL,
        semana_inicio TEXT NOT NULL, semana_fim TEXT NOT NULL,
        observacao_json TEXT NOT NULL,
        PRIMARY KEY(edicao_id,uf,municipio,produto,semana_inicio)
      );
      CREATE INDEX IF NOT EXISTS idx_diesel_municipio_chave ON
        diesel_municipios(uf,municipio,produto,semana_inicio);
    """)
    return db


def _validar_linha(linha: dict) -> dict:
    if not isinstance(linha,dict) or set(linha)!=_CAMPOS:
        raise ErroHistoricoDiesel("schema resumido da ANP divergente")
    uf=linha["uf"]
    mun=linha["municipio"]
    p=linha["produto"]
    if (uf not in _UFS or p not in _PRODUTOS
        or not isinstance(mun,str) or not 1<=len(mun)<=120
        or mun!=mun.strip().upper()):
        raise ErroHistoricoDiesel("localidade/produto não canônicos")
    try:
        start=date.fromisoformat(linha["semana_inicio_inferida"])
        end=date.fromisoformat(linha["semana_fim_inferida"])
    except (ValueError,TypeError) as exc:
        raise ErroHistoricoDiesel("semana inválida") from exc
    if (start.weekday()!=6 or (end-start).days!=6):
        raise ErroHistoricoDiesel("semana derivada fora do calendário domingo-sábado")
    n=linha["postos_observacoes"]
    if type(n) is not int or not 1<=n<=150_000:
        raise ErroHistoricoDiesel("quantidade de amostras inválida")
    values=[linha[k] for k in ("preco_medio_revenda_rs_l",
        "preco_mediano_revenda_rs_l","preco_minimo_revenda_rs_l",
        "preco_maximo_revenda_rs_l")]
    if any(type(v) not in (int,float) or not isfinite(v) or not 0<v<50
           for v in values):
        raise ErroHistoricoDiesel("preços inválidos/ausentes")
    mean,med,minv,maxv=values
    if not minv<=mean<=maxv or not minv<=med<=maxv:
        raise ErroHistoricoDiesel("agregados ANP incoerentes")
    return dict(linha)


def gravar_resumo_diesel(db: sqlite3.Connection, resumo: dict, *,
                        fonte_url: str, coletado_em: str,
                        tipo: str = "SINTETICO",
                        evidencia_direitos: str | None = None,
                        direitos_confirmados: bool = False) -> dict:
    """Grava só agregados anônimos; exige evidência específica para fonte real."""
    from urllib.parse import urlsplit
    host=urlsplit(fonte_url) if isinstance(fonte_url,str) else None
    if (host is None or host.scheme!="https"
        or host.hostname not in {"www.gov.br","dados.gov.br","www.anp.gov.br"}
        or host.username or host.password or host.fragment):
        raise ErroHistoricoDiesel("proveniência não é URL HTTPS ANP governamental")
    coleta=_instante(coletado_em).isoformat()
    if tipo not in ("SINTETICO","REAL_AUTORIZADO"):
        raise ErroHistoricoDiesel("tipo não contratado")
    if tipo=="REAL_AUTORIZADO":
        if (direitos_confirmados is not True or not isinstance(evidencia_direitos,str)
            or len(evidencia_direitos.strip())<8):
            raise PermissionError("arquivo ANP real sem direitos/evidência de armazenamento")
    elif direitos_confirmados or evidencia_direitos:
        raise ErroHistoricoDiesel("fixture sintética não recebe direitos reais")
    if not isinstance(resumo,dict) or resumo.get("fonte")!="ANP_SERIE_ABERTA_PRECOS_DIESEL":
        raise ErroHistoricoDiesel("resumo não gerado pelo parser ANP")
    if (resumo.get("natureza")!="OBSERVADO_POR_AMOSTRA_PESQUISA_PRECO_REVENDA"
        or resumo.get("semana_origem")!="INFERIDA_CALENDARIO_NAO_SEMANA_OFICIAL_ANP"
        or resumo.get("privacidade")!="SEM_IDENTIFICADORES_DE_POSTO_NO_RESULTADO"):
        raise ErroHistoricoDiesel("metadados de semântica/privacidade divergentes")
    mes=resumo.get("competencia_mes")
    sha=resumo.get("arquivo_sha256")
    rows=resumo.get("series")
    if (not isinstance(mes,str) or not _MESES.fullmatch(mes)
        or not isinstance(sha,str) or not _SHA.fullmatch(sha)
        or not isinstance(rows,list) or not 1<=len(rows)<=50_000):
        raise ErroHistoricoDiesel("competência, hash ou agregados inválidos")
    seen=set()
    normal=[]
    for row in rows:
        data=_validar_linha(row)
        periodo=(data["uf"],data["municipio"],data["produto"],
                 data["semana_inicio_inferida"])
        if periodo in seen:
            raise ErroHistoricoDiesel("agrupamento municipal duplicado")
        seen.add(periodo)
        # A semana pode atravessar dois meses; o mês da coleta define o arquivo.
        start=date.fromisoformat(data["semana_inicio_inferida"])
        end=date.fromisoformat(data["semana_fim_inferida"])
        if mes not in (start.strftime("%Y-%m"),end.strftime("%Y-%m")):
            raise ErroHistoricoDiesel("semana fora do arquivo mensal")
        normal.append(data)
    canonical=json.dumps(sorted(normal,key=lambda x:(
            x["uf"],x["municipio"],x["produto"],x["semana_inicio_inferida"])),
        sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    digest=hashlib.sha256(canonical.encode()).hexdigest()
    with db:
        old=db.execute("SELECT * FROM diesel_edicoes WHERE sha256_original=?",(sha,)).fetchone()
        if old is None:
            ident=db.execute("""INSERT INTO diesel_edicoes
               (sha256_original,competencia_mes,fonte_url,evidencia_direitos,tipo,sha256_series)
               VALUES (?,?,?,?,?,?)""",(sha,mes,fonte_url,
                 evidencia_direitos or "SINTETICO_SEM_AUTORIZACAO",tipo,digest)).lastrowid
            db.executemany("""INSERT INTO diesel_municipios VALUES (?,?,?,?,?,?,?)""",[
                (ident,x["uf"],x["municipio"],x["produto"],x["semana_inicio_inferida"],
                 x["semana_fim_inferida"],json.dumps(x,ensure_ascii=False,sort_keys=True,
                                           separators=(",",":"),allow_nan=False)) for x in normal
            ])
        else:
            if (old["sha256_series"]!=digest or old["competencia_mes"]!=mes
                or old["tipo"]!=tipo or old["fonte_url"]!=fonte_url):
                raise ErroHistoricoDiesel("mesmos bytes não podem mudar agregados, classe ou fonte")
            ident=old["id"]
        ret=db.execute("INSERT OR IGNORE INTO diesel_capturas VALUES (?,?)",(ident,coleta))
    return {"status":"AGREGADOS_ANONIMOS_ARMAZENADOS","sha256_original":sha,
            "grupos":len(normal),"nova_captura":ret.rowcount==1,
            "classe":tipo,"publicacao_oficial":None,
            "apto_backtest_publicacao":False}


def indicador_diesel_municipal(db: sqlite3.Connection, *, uf: str,
                              municipio: str, produto: str,
                              gerado_em: str, fontes: dict,
                              limite_dias_semana: int = 21) -> dict:
    """Última semana amostral disponível as-of por coleta, não data publicação."""
    corte=_instante(gerado_em)
    if (uf not in _UFS or produto not in _PRODUTOS or not isinstance(municipio,str)
        or municipio!=municipio.strip().upper() or not 1<=len(municipio)<=120):
        raise ErroHistoricoDiesel("localidade ou produto inválido")
    if type(limite_dias_semana) is not int or not 1<=limite_dias_semana<=60:
        raise ErroHistoricoDiesel("janela de frescor inválida")
    if not _direitos(fontes,"ANP_DIESEL"):
        return {"status":"BLOQUEADO_DIREITOS",
                "motivo":"publicação derivada do resumo ANP não autorizada"}
    try:
        res=db.execute("""
          SELECT x.observacao_json, e.sha256_original, e.fonte_url,
                 MAX(c.coletado_utc) AS coleta
          FROM diesel_municipios x
          JOIN diesel_edicoes e ON e.id=x.edicao_id
          JOIN diesel_capturas c ON c.edicao_id=e.id
          WHERE e.tipo='REAL_AUTORIZADO' AND x.uf=?
            AND x.municipio=? AND x.produto=?
            AND c.coletado_utc<=?
          GROUP BY e.id,x.uf,x.municipio,x.produto,x.semana_inicio
          ORDER BY x.semana_inicio DESC, coleta DESC
          LIMIT 1001""",(uf,municipio,produto,corte.isoformat())).fetchall()
    except sqlite3.Error:
        return {"status":"BANCO_INDISPONIVEL","motivo":"banco diesel não disponível"}
    if len(res)>1000:
        return {"status":"HISTORICO_EXCESSIVO","motivo":"consultar janela menor"}
    if not res:
        return {"status":"SEM_OBSERVACAO_REAL","motivo":"município/produto sem levantamento disponível"}
    candidatos=[]
    for row in res:
        obs=json.loads(row[0])
        item=_validar_linha(obs)
        inicio=date.fromisoformat(item["semana_inicio_inferida"])
        if inicio>corte.date():
            continue
        candidatos.append((inicio,_instante(row[3]),row[1],row[2],item))
    if not candidatos:
        return {"status":"SEM_OBSERVACAO_ASOF","motivo":"sem semana observada até o corte"}
    latest_start=max(x[0] for x in candidatos)
    same=[x for x in candidatos if x[0]==latest_start]
    # Proibir correções conflitantes para a mesma semana sem reconciliação.
    medidas={(x[4]["postos_observacoes"],x[4]["preco_medio_revenda_rs_l"])
             for x in same}
    if len(medidas)>1:
        return {"status":"VINTAGES_CONFLITANTES",
                "motivo":"mesma semana amostral com agregados discordantes"}
    selected=max(same,key=lambda x:(x[1],x[2]))
    start,captura,sha,url,obs=selected
    end=date.fromisoformat(obs["semana_fim_inferida"])
    ref=end if end<=corte.date() else corte.date()
    if (corte.date()-ref).days>limite_dias_semana:
        return {"status":"DADO_VENCIDO","motivo":"levantamento municipal antigo"}
    n=obs["postos_observacoes"]
    preco=obs["preco_medio_revenda_rs_l"]
    return {
        "status":"INDICADOR_VERIFICADO_TEMPO",
        "indicador":{
            "fonte_id":"ANP_DIESEL","secao":"DIESEL",
            "titulo":f"{produto} revenda — {municipio}/{uf}",
            "valor":(f"R$ {preco:.3f}/L; {n} observações; "
                f"semana calendário inferida {start.isoformat()} a {end.isoformat()}"),
            "referencia":captura.isoformat(),
            "fonte":"ANP pesquisa amostral; média simples, não preço de atacado",
        },
        "evidencia":{
            "dataset_id":"ANP_PRECO_REVENDA_DIESEL",
            "arquivo_sha256":sha,"fonte_url":url,
            "coleta":captura.isoformat(),"publicacao":None,
            "semana_calendario_inferida":[start.isoformat(),end.isoformat()],
            "preco_medio_rs_l":preco,"postos_observacoes":n,
            "amostra_parcial_possivel":end>corte.date(),
            "apto_backtest_por_publicacao":False,
            "classificacao":"PRECO_REVENDA_AMOSTRAL_NAO_PPI",
        },
    }
