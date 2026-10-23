"""Armazenamento incremental REAL pré-homologação do diesel ANP/LPC.

Real baixado NÃO equivale a REAL_AUTORIZADO do histórico homologado.
Este store isolado admite fonte pública por autorização não comercial do
operador, preserva revisões e captura, sem postos individuais ou publicação.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import sqlite3
from typing import Mapping

from .anp_indice_lpc import descobrir_semanas_lpc
from .anp_resumo_lpc import ler_resumo_semanal_lpc
from .anp_semanal_store import _tempo


class ErroStagingANP(ValueError):
    pass


def iniciar_staging(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS anp_lpc_staging_edicoes (
      sha256 TEXT PRIMARY KEY, url TEXT NOT NULL, indice_sha256 TEXT NOT NULL,
      semana_inicio TEXT NOT NULL, semana_fim TEXT NOT NULL,
      capturado_indice_em TEXT NOT NULL, primeira_coleta_em TEXT NOT NULL,
      qtd_observacoes INTEGER NOT NULL,
      classificacao TEXT NOT NULL CHECK(classificacao='REAL_PRELIMINAR_NAO_HOMOLOGADO'),
      direitos_uso TEXT NOT NULL CHECK(direitos_uso='USO_INTERNO_NAO_COMERCIAL_ANP_ATRIBUICAO'),
      raw_arquivado INTEGER NOT NULL DEFAULT 0 CHECK(raw_arquivado IN (0,1))
    );
    CREATE TABLE IF NOT EXISTS anp_lpc_staging_capturas (
      sha256 TEXT NOT NULL REFERENCES anp_lpc_staging_edicoes(sha256),
      capturado_em TEXT NOT NULL, PRIMARY KEY(sha256,capturado_em)
    );
    CREATE TABLE IF NOT EXISTS anp_lpc_staging_observacoes (
      sha256 TEXT NOT NULL REFERENCES anp_lpc_staging_edicoes(sha256),
      uf TEXT NOT NULL CHECK(uf='MT'), municipio TEXT NOT NULL,
      produto TEXT NOT NULL CHECK(produto IN ('DIESEL','DIESEL S10')),
      preco_medio_rs_l TEXT NOT NULL, postos_pesquisados INTEGER NOT NULL,
      PRIMARY KEY(sha256,uf,municipio,produto)
    );
    CREATE INDEX IF NOT EXISTS idx_anp_lpc_staging_semana
      ON anp_lpc_staging_edicoes(semana_fim,primeira_coleta_em);
    CREATE INDEX IF NOT EXISTS idx_anp_lpc_staging_municipio
      ON anp_lpc_staging_observacoes(municipio,produto);
    """)


def integrar_real_preliminar(
    db: sqlite3.Connection, *, indice: bytes, arquivo: bytes,
    arquivo_url: str, ano: int, indice_capturado_em: str,
    arquivo_capturado_em: str, raw_arquivado: bool,
) -> dict:
    """HTML oficial e XLSX já obtidos: validação + persistência transacional.

    Não infere data de publicação: só data da primeira coleta verificável.
    """
    if type(raw_arquivado) is not bool:
        raise ErroStagingANP("prova de arquivamento deve ser booleana")
    index_time = _tempo(indice_capturado_em, "indice_capturado_em")
    file_time = _tempo(arquivo_capturado_em, "arquivo_capturado_em")
    if index_time > file_time:
        raise ErroStagingANP("índice capturado depois do arquivo")
    index_info = descobrir_semanas_lpc(indice, ano=ano)
    found = [x for x in index_info["semanas"] if x["url_pagina"] == arquivo_url]
    if len(found) != 1:
        raise ErroStagingANP("XLSX não anunciado inequivocamente no índice oficial")
    week = found[0]
    if week["semana_fim"] > file_time.date().isoformat():
        raise ErroStagingANP("período oficial posterior à captura")
    resumo = ler_resumo_semanal_lpc(
        arquivo, coletado_em=file_time.isoformat(), origem_url=arquivo_url
    )
    obs = resumo["observacoes"]
    if (resumo["semanas_distintas"] != 1
            or any(x["semana_inicio_oficial"] != week["semana_inicio"]
                   or x["semana_fim_oficial"] != week["semana_fim"] for x in obs)):
        raise ErroStagingANP("período oficial não coincide entre índice e XLSX")
    index_sha = sha256(indice).hexdigest()
    file_sha = sha256(arquivo).hexdigest()
    if resumo["sha256"] != file_sha:
        raise ErroStagingANP("SHA verificado diferentemente do XLSX")
    dados = sorted([
        (file_sha, x["uf"], x["municipio"], x["produto"],
         str(Decimal(str(x["preco_medio_revenda_rs_l"]))),
         int(x["postos_pesquisados"])) for x in obs
    ])
    iniciar_staging(db)
    db.row_factory = sqlite3.Row
    with db:
        existing = db.execute(
            "SELECT * FROM anp_lpc_staging_edicoes WHERE sha256=?", (file_sha,)
        ).fetchone()
        if existing is None:
            db.execute("""INSERT INTO anp_lpc_staging_edicoes
              (sha256,url,indice_sha256,semana_inicio,semana_fim,
               capturado_indice_em,primeira_coleta_em,qtd_observacoes,
               classificacao,direitos_uso,raw_arquivado)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
               (file_sha, arquivo_url, index_sha, week["semana_inicio"],
                week["semana_fim"], index_time.isoformat(), file_time.isoformat(),
                len(dados), "REAL_PRELIMINAR_NAO_HOMOLOGADO",
                "USO_INTERNO_NAO_COMERCIAL_ANP_ATRIBUICAO", int(raw_arquivado)))
            db.executemany("""INSERT INTO anp_lpc_staging_observacoes
              (sha256,uf,municipio,produto,preco_medio_rs_l,postos_pesquisados)
              VALUES (?,?,?,?,?,?)""", dados)
        else:
            if (existing["url"] != arquivo_url
                or existing["semana_inicio"] != week["semana_inicio"]
                or existing["semana_fim"] != week["semana_fim"]
                or existing["qtd_observacoes"] != len(dados)):
                raise ErroStagingANP("mesmos bytes vinculados a edição conflitante")
            stored = db.execute("""SELECT sha256,uf,municipio,produto,
              preco_medio_rs_l,postos_pesquisados
              FROM anp_lpc_staging_observacoes WHERE sha256=? ORDER BY
              sha256,uf,municipio,produto""", (file_sha,)).fetchall()
            if [tuple(x) for x in stored] != dados:
                raise ErroStagingANP("mesmos bytes com observações conflitantes")
            if raw_arquivado and not existing["raw_arquivado"]:
                db.execute("""UPDATE anp_lpc_staging_edicoes
                  SET raw_arquivado=1 WHERE sha256=?""", (file_sha,))
        nova = db.execute("""INSERT OR IGNORE INTO anp_lpc_staging_capturas
           (sha256,capturado_em) VALUES (?,?)""",
           (file_sha,file_time.isoformat())).rowcount == 1
    return {
        "status": "REAL_PRELIMINAR_STAGING",
        "sha256": file_sha, "indice_sha256": index_sha,
        "semana_inicio": week["semana_inicio"], "semana_fim": week["semana_fim"],
        "observacoes": len(dados), "municipios": len({d[2] for d in dados}),
        "captura_nova": nova, "edicao_nova": existing is None,
        "raw_arquivado": raw_arquivado, "publicavel": False,
        "homologado": False, "fonte": "ANP_LEVANTAMENTO_PRECOS_COMBUSTIVEIS",
    }



def auditar_arquivos_origem_lpc(
    db: sqlite3.Connection, *, raiz_raw: str, as_of: str,
) -> dict:
    """Confere bytes privados já arquivados versus os hashes persistidos.

    Só metadados de integridade. Não lê XLSX como fonte de preço,
    não devolve bytes nem nomes de postos e não homologa licenças.
    """
    from pathlib import Path
    raiz = Path(raiz_raw)
    if not raiz.is_dir() or raiz.is_symlink():
        raise ErroStagingANP("raiz privada de RAW ausente ou insegura")
    raiz = raiz.resolve()
    corte = _tempo(as_of, "as_of")
    db.row_factory = sqlite3.Row
    linhas = db.execute("""
        SELECT sha256, indice_sha256, raw_arquivado
        FROM anp_lpc_staging_edicoes e
        WHERE EXISTS (
            SELECT 1 FROM anp_lpc_staging_capturas c
            WHERE c.sha256=e.sha256 AND c.capturado_em<=?
        ) ORDER BY e.sha256""", (corte.isoformat(),)).fetchall()
    cache = {}
    falhas = []
    verificacoes = 0

    def validar(subpasta: str, expected: str, tipo: str) -> None:
        nonlocal verificacoes
        chave = (subpasta, expected)
        if chave in cache:
            resultado = cache[chave]
        else:
            p = raiz / subpasta / (expected + (".html" if subpasta=="indices" else ".xlsx"))
            if (p.is_symlink() or p.parent.is_symlink()
                    or not p.resolve().is_relative_to(raiz)):
                resultado = "CAMINHO_INSEGURO"
            elif not p.is_file():
                resultado = "ARQUIVO_AUSENTE"
            elif (p.stat().st_size < 100 or
                    p.stat().st_size > (4_000_000 if subpasta=="indices" else 14_000_000)):
                resultado = "TAMANHO_INVALIDO"
            else:
                digest = sha256()
                with p.open("rb") as fluxo:
                    for parte in iter(lambda: fluxo.read(1024*1024), b""):
                        digest.update(parte)
                resultado = "INTEGRO" if digest.hexdigest() == expected else "HASH_DIVERGENTE"
            cache[chave] = resultado
            verificacoes += 1
        if resultado != "INTEGRO":
            falhas.append({"tipo":tipo, "sha256_esperado":expected, "falha":resultado})

    for e in linhas:
        if not e["raw_arquivado"]:
            falhas.append({"tipo":"EDICAO", "sha256_esperado":e["sha256"],
                           "falha":"ARQUIVAMENTO_NAO_COMPROVADO"})
            continue
        validar("planilhas",e["sha256"],"XLSX")
        validar("indices",e["indice_sha256"],"INDICE_HTML")
    return {
        "status":"RAW_VERIFICADO_LOCALMENTE" if not falhas else "RAW_NAO_CONFIAVEL",
        "as_of":corte.isoformat(), "edicoes_consultadas":len(linhas),
        "arquivos_distintos_verificados":verificacoes,
        "quantidade_falhas":len(falhas), "falhas":falhas,
        "precos_expostos":False, "publicavel":False,
        "autenticidade_externa_comprovada":False,
    }


def painel_qualidade_lpc(db: sqlite3.Connection, *, as_of: str) -> dict:
    """Auditoria rápida do histórico preliminar, sem divulgar preços.

    Toda revisão é preservada, e cobertura municipal varia entre semanas.
    """
    corte = _tempo(as_of, "as_of")
    db.row_factory = sqlite3.Row
    edicoes = db.execute("""
        SELECT e.sha256,e.semana_inicio,e.semana_fim,e.qtd_observacoes,
          e.raw_arquivado
        FROM anp_lpc_staging_edicoes e
        WHERE EXISTS (SELECT 1 FROM anp_lpc_staging_capturas c
                      WHERE c.sha256=e.sha256 AND c.capturado_em<=?)
        ORDER BY e.semana_fim DESC, e.sha256""", (corte.isoformat(),)).fetchall()
    por_semana = {}
    for ed in edicoes:
        por_semana.setdefault(ed["semana_fim"], []).append(ed)
    from datetime import date
    dias = sorted(por_semana)
    faltantes = []
    for anterior, proxima in zip(dias, dias[1:]):
        diff = (date.fromisoformat(proxima) -
                date.fromisoformat(anterior)).days
        if diff > 7 and diff % 7 == 0:
            faltantes.extend(
                (date.fromisoformat(anterior) +
                 timedelta(days=k)).isoformat()
                for k in range(7, diff, 7)
            )
    return {
        "status": "STAGING_REAL_PRELIMINAR_SEM_HOMOLOGACAO",
        "corte_as_of": corte.isoformat(),
        "semanas_unicas": len(dias), "edicoes_distintas": len(edicoes),
        "observacoes_por_edicao_somadas": sum(x["qtd_observacoes"] for x in edicoes),
        "semanas_com_revisoes": sorted(
            [week for week,values in por_semana.items() if len(values)>1]
        ),
        "semanas_faltantes_entre_extremos": faltantes,
        "semana_mais_recente": dias[-1] if dias else None,
        "edicoes_sem_raw_arquivado": sum(not x["raw_arquivado"] for x in edicoes),
        "edicoes_homologadas": 0,
        "publicavel": False, "preco_atual_homologado": False,
    }


def tendencia_diesel_preliminar(
    db: sqlite3.Connection, *, municipio: str, produto: str, as_of: str,
    idade_maxima_dias: int = 28,
) -> dict:
    """Comparação apenas entre mesmas praça/produto, semanas contíguas.

    Não mede repasse a frete nem combina S10 com diesel comum. Apenas
    prévia interna, jamais saída pública/operacional.
    """
    tempo = _tempo(as_of, "as_of")
    if type(idade_maxima_dias) is not int or not 1 <= idade_maxima_dias <= 90:
        raise ErroStagingANP("limite de atualização inválido")
    if (not isinstance(municipio, str) or municipio != municipio.strip().upper()
            or not 1 <= len(municipio) <= 120
            or produto not in ("DIESEL", "DIESEL S10")):
        raise ErroStagingANP("chave de indicador inválida")
    db.row_factory = sqlite3.Row
    rows = db.execute("""SELECT ed.semana_inicio,ed.semana_fim,ed.sha256,
             ob.preco_medio_rs_l,ob.postos_pesquisados
             FROM anp_lpc_staging_observacoes ob
             JOIN anp_lpc_staging_edicoes ed ON ob.sha256=ed.sha256
             JOIN anp_lpc_staging_capturas c ON c.sha256=ed.sha256
             WHERE ob.municipio=? AND ob.produto=? AND ed.semana_fim<=?
             AND c.capturado_em<=?
             GROUP BY ed.sha256 ORDER BY ed.semana_fim DESC LIMIT 20""",
             (municipio,produto,tempo.date().isoformat(),tempo.isoformat())).fetchall()
    base = {
        "municipio": municipio, "uf": "MT", "produto": produto,
        "classificacao": "REAL_PRELIMINAR_NAO_HOMOLOGADO",
        "publicavel": False, "uso": "PREVIA_INTERNA_NAO_COMERCIAL",
        "fonte": "ANP_LPC_MEDIA_AMOSTRAL_REVENDA_DIESEL_B_NAO_FRETE",
    }
    if not rows:
        return {**base, "status": "SEM_DADOS_OBSERVADOS"}
    from datetime import date
    atraso = (tempo.date()-date.fromisoformat(rows[0]["semana_fim"])).days
    if atraso > idade_maxima_dias:
        return {
            **base, "status": "HISTORICO_VENCIDO",
            "ultima_semana_observada": rows[0]["semana_fim"],
            "defasagem_dias": atraso,
            "limite_defasagem_dias": idade_maxima_dias,
        }
    semanas = {}
    for row in rows:
        semanas.setdefault(row["semana_fim"], []).append(row)
    weeks = sorted(semanas, reverse=True)
    if len(weeks) < 2:
        return {**base, "status": "HISTORICO_INSUFICIENTE"}
    recent, before = semanas[weeks[0]], semanas[weeks[1]]
    if len(recent) != 1 or len(before) != 1:
        return {**base, "status": "REVISOES_DIVERGENTES_NAO_SELECIONADAS"}
    from datetime import date
    if (date.fromisoformat(weeks[0])-date.fromisoformat(weeks[1])).days != 7:
        return {**base, "status": "SEMANAS_NAO_CONSECUTIVAS"}
    p1,p0 = Decimal(recent[0]["preco_medio_rs_l"]),Decimal(before[0]["preco_medio_rs_l"])
    delta = p1 - p0
    pct = delta / p0 * 100
    return {
        **base, "status": "COMPARACAO_PRELIMINAR",
        "semana_atual": weeks[0], "semana_anterior": weeks[1],
        "preco_revenda_atual_rs_l": str(p1),
        "preco_revenda_anterior_rs_l": str(p0),
        "variacao_absoluta_rs_l": str(delta),
        "variacao_percentual": str(pct.quantize(Decimal("0.01"))),
        "direcao_observada": "ALTA" if delta>0 else "BAIXA" if delta<0 else "ESTAVEL",
        "sha256_atual": recent[0]["sha256"],
        "sha256_anterior": before[0]["sha256"],
        "inferir_frete": False,
    }
