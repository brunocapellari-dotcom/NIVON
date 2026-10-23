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
            "SELECT COUNT(*) n, COUNT(DISTINCT IDCarga) ids, COUNT(*) FILTER (WHERE IDCarga IS NULL) ids_nulos "
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


def soma_carga_unica_2025(hidrovia: str | Path, carga: str | Path) -> dict:
    """Confronta navegação interior deduplicada por IDCarga com o total oficial.

    As linhas de Carga_Hidrovia são segmentos que podem repetir IDCarga.
    Somar apenas Carga, que deve ter IDCarga única no ano (falha fechada).
    """
    try:
        import duckdb
    except ImportError:
        raise ErroReplicaANTAQ("duckdb nao instalado") from None
    for caminho in (hidrovia,carga):
        p = Path(caminho)
        if not p.is_file() or not 100 <= p.stat().st_size <= 65_000_000:
            raise ErroReplicaANTAQ("arquivo ausente/tamanho inesperado")
    with duckdb.connect(database=":memory:") as db:
        db.execute("PRAGMA memory_limit='2GB'")
        db.execute("PRAGMA threads=2")
        c, h = str(carga), str(hidrovia)
        meta = db.execute(
            'SELECT COUNT(*), COUNT(DISTINCT "IDCarga"),'
            ' COUNT(*) FILTER (WHERE "IDCarga" IS NULL OR "VLPesoCargaBruta" IS NULL OR "VLPesoCargaBruta" < 0)'
            ' FROM read_parquet(?)',[c]).fetchone()
        if meta[0] != meta[1] or meta[2]:
            raise ErroReplicaANTAQ("Carga com chaves ou pesos nao confiaveis")
        grouped = db.execute("""
          WITH trechos AS (
              SELECT DISTINCT "IDCarga" FROM read_parquet(?)
          )
          SELECT c."Tipo Navegação" AS navegacao,
                 c."CDMercadoria" AS sh4,
                 COUNT(*) AS n,
                 SUM(c."VLPesoCargaBruta") AS peso_total,
                 COUNT(*) FILTER (WHERE t."IDCarga" IS NOT NULL) AS n_trecho,
                 SUM(c."VLPesoCargaBruta") FILTER (WHERE t."IDCarga" IS NOT NULL) AS peso_trecho
            FROM read_parquet(?) c
            LEFT JOIN trechos t ON c."IDCarga" = t."IDCarga"
           GROUP BY 1,2
        """,[h,c]).fetchall()
    totais = {}
    por_produto = {}
    for nav, sh4, n, peso, n_trecho, peso_trecho in grouped:
        nave = normalizar_texto(nav)
        if peso is None or not math.isfinite(float(peso)) or float(peso) < 0:
            raise ErroReplicaANTAQ("peso agregado invalido")
        t = totais.setdefault(nave, {"cargas_unicas":0,"toneladas":0.0,
                                      "cargas_com_hidrovia":0,"toneladas_com_hidrovia":0.0})
        t["cargas_unicas"] += int(n)
        t["toneladas"] += float(peso)
        t["cargas_com_hidrovia"] += int(n_trecho)
        t["toneladas_com_hidrovia"] += float(peso_trecho or 0)
        if nave == "Interior":
            prod = classificar_sh4(sh4)
            por_produto[prod] = por_produto.get(prod,0.0) + float(peso)
    interior = totais.get("Interior")
    if interior is None:
        raise ErroReplicaANTAQ("navegacao interior ausente na fonte")
    return {
        "estado": "DERIVADO_TERCEIRO_2025_NAO_HOMOLOGADO",
        "ano": 2025, "universo": "CARGA_NAVEGACAO_INTERIOR_IDCARGA_UNICA",
        "total_ton": round(interior["toneladas"],3),
        "cargas_unicas": interior["cargas_unicas"],
        "ton_com_classificacao_hidrovia": round(interior["toneladas_com_hidrovia"],3),
        "cargas_com_classificacao_hidrovia": interior["cargas_com_hidrovia"],
        "por_grupo_produto": {k: round(v,3) for k,v in sorted(por_produto.items())},
        "todos_tipos_navegacao": {k: {"cargas_unicas":v["cargas_unicas"],
                                     "toneladas":round(v["toneladas"],3)}
                                  for k,v in sorted(totais.items())},
        "nao_somar_hidrovias": True,
    }
