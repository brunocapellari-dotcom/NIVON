"""Leitura de réplica secundária ANTAQ — junção IDCarga hidrovia x Carga.

Nunca lê rede, não escreve BigQuery e não classifica dados como fonte oficial.
As somas por hidrovia não são necessariamente aditivas no sistema logístico.
"""
from __future__ import annotations
import json
import math
import unicodedata
from pathlib import Path
from .antaq_replica_hidrovia import ErroReplicaANTAQ, nome_normalizado


def classificar_sh4(sh4: str | None) -> str:
    if sh4 is None:
        return "NCM_NAO_INFORMADO"
    c = str(sh4).strip()
    if c == "1201": return "SOJA"
    if c == "1005": return "MILHO"
    if c == "2304": return "FARELO_DE_SOJA"
    if c.startswith("31") and len(c) == 4 and c.isdecimal(): return "FERTILIZANTES_CAP31"
    if c == "2710": return "DERIVADOS_PETROLEO_SH2710_NAO_SO_DIESEL"
    return "OUTRAS_MERCADORIAS"


def normalizar_texto(txt: str | None) -> str:
    if txt is None: return "NAO_INFORMADO"
    if not isinstance(txt, str): raise ErroReplicaANTAQ("texto invalido")
    s = txt
    if "Ã" in s or "Â" in s:
        try: s = s.encode("latin1").decode("utf8")
        except UnicodeError: raise ErroReplicaANTAQ("codificacao nao reconhecida") from None
    return unicodedata.normalize("NFC", " ".join(s.split()))


def resumo_parquets(hidrovia: str | Path, carga: str | Path, *, ano: int = 2025) -> dict:
    if ano != 2025:
        raise ErroReplicaANTAQ("ano requer validacao de schema independente")
    try:
        import duckdb
    except ImportError:
        raise ErroReplicaANTAQ("duckdb nao instalado") from None
    for p in (hidrovia, carga):
        path = Path(p)
        if not path.is_file() or not 100 <= path.stat().st_size <= 65_000_000:
            raise ErroReplicaANTAQ("arquivo parquet ausente ou tamanho nao aprovado")
    with duckdb.connect(database=":memory:") as db:
        db.execute("PRAGMA memory_limit='2GB'")
        db.execute("PRAGMA threads=2")
        hr = str(hidrovia)
        cr = str(carga)
        meta_h = db.execute(
            "SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE IDCarga IS NULL OR ValorMovimentado IS NULL OR ValorMovimentado < 0) AS invalidos "
            "FROM read_parquet(?)", [hr]).fetchone()
        meta_c = db.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT IDCarga) ids, COUNT(*) FILTER (WHERE IDCarga IS NULL) nulls "
            "FROM read_parquet(?)", [cr]).fetchone()
        if not meta_h or not meta_c or meta_h[0] <= 0 or meta_c[0] <= 0:
            raise ErroReplicaANTAQ("parquets vazios")
        if meta_h[1] or meta_c[2] or meta_c[0] != meta_c[1]:
            raise ErroReplicaANTAQ("integridade de chaves/pesos incompleta")
        resultados = db.execute("""
            SELECT h."Hidrovia" AS hidrovia, c."Tipo Navegação" AS navegacao,
                   c."CDMercadoria" AS sh4, c."Sentido" AS sentido,
                   COUNT(*) AS linhas, SUM(h."ValorMovimentado") AS toneladas,
                   COUNT(DISTINCT h."IDCarga") AS ids
              FROM read_parquet(?) h
              LEFT JOIN read_parquet(?) c ON h."IDCarga"=c."IDCarga"
             GROUP BY 1,2,3,4
        """,[hr,cr]).fetchall()
    agrupados = {}
    linhas_ok = 0
    linhas_sem = 0
    toneladas_sem = 0.0
    for hidro, nav, sh4, sentido, linhas, total, ids in resultados:
        if not isinstance(linhas, int) or linhas <= 0 or total is None or not math.isfinite(float(total)) or total < 0:
            raise ErroReplicaANTAQ("agregacao inesperada")
        if nav is None:
            linhas_sem += linhas
            toneladas_sem += float(total)
            continue
        linhas_ok += linhas
        hidrovia_nome = nome_normalizado(hidro)
        nav_nome = normalizar_texto(nav)
        sentido_nome = normalizar_texto(sentido)
        produto = classificar_sh4(sh4)
        k = (hidrovia_nome, nav_nome, sentido_nome, produto)
        x = agrupados.setdefault(k, {"linhas": 0, "toneladas": 0.0})
        x["linhas"] += linhas
        x["toneladas"] += float(total)
    if linhas_ok + linhas_sem != meta_h[0]:
        raise ErroReplicaANTAQ("junção perdeu/duplicou linhas")
    if linhas_sem > meta_h[0] * 0.02:
        raise ErroReplicaANTAQ("mais de 2% das linhas hidroviarias sem IDCarga")
    linhas = []
    for (h,n,s,p),v in sorted(agrupados.items()):
        linhas.append({"hidrovia": h, "navegacao": n, "sentido": s,
                       "grupo_produto": p, "linhas": v["linhas"],
                       "toneladas": round(v["toneladas"],3)})
    return {
        "estado": "REPLICA_2025_TERCEIRO_NAO_HOMOLOGADA",
        "ano": ano, "linhas_hidrovia": meta_h[0], "linhas_carga": meta_c[0],
        "linhas_qualificadas": linhas_ok,
        "linhas_sem_vinculo": linhas_sem,
        "toneladas_sem_vinculo": round(toneladas_sem,3),
        "conferencia_soma_hidrovias": False,
        "recortes": linhas,
    }


def resumo_agro(doc: dict) -> dict:
    produtos = {"SOJA","MILHO","FARELO_DE_SOJA","FERTILIZANTES_CAP31"}
    recortes = [r for r in doc["recortes"] if r["grupo_produto"] in produtos]
    recortes = sorted(recortes, key=lambda x: -x["toneladas"])
    return {
        "estado": doc["estado"], "ano": doc["ano"],
        "linhas_hidrovia": doc["linhas_hidrovia"],
        "linhas_sem_vinculo": doc["linhas_sem_vinculo"],
        "recortes_agro": recortes,
        "observacao": "Volumes por hidrovia e tipo navegacao; NAO SOMAR como carga unica ou tipo interior sem verificacao",
    }
