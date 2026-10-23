"""Mudanças relevantes da PAM para IVO, derivadas de capturas verificáveis.

Somente a mesma célula município+ano civil+variável+C81 é comparada.
Revisão de quantidade ou de estado é alerta; primeira captura, recoleta
idêntica e bytes alterados sem mudar o número não geram falso alerta.
Corte temporal corresponde à COLETA, nunca à publicação oficial.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .ivo_pam_semantica import conferir_semantica_pam_1612


class ErroAlertasPAM(ValueError):
    pass


def _corte(value, nome):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ErroAlertasPAM(f"{nome} exige datetime com fuso")
    return value.astimezone(timezone.utc).isoformat()


def alertas_revisoes_pam(
    db: sqlite3.Connection, *, desde_exclusivo: datetime,
    ate_inclusivo: datetime | None = None, limite_capturas: int = 5000,
) -> dict:
    """Reconstrói mudanças no intervalo sem confiar em 'mudanca' do staging.

    SQL window LAG inclui todas as capturas anteriores ao início:
    a primeira coleta do período é comparada com a última edição histórica
    da mesma célula, e nunca com outro município ou outra cultura.
    """
    if not isinstance(db, sqlite3.Connection):
        raise ErroAlertasPAM("SQLite operacional necessário")
    inicio = _corte(desde_exclusivo, "desde_exclusivo")
    fim = _corte(ate_inclusivo, "ate_inclusivo") if ate_inclusivo else None
    if fim is not None and fim < inicio:
        raise ErroAlertasPAM("intervalo temporal invertido")
    if type(limite_capturas) is not int or not 1 <= limite_capturas <= 10000:
        raise ErroAlertasPAM("limite de capturas inválido")

    rows = db.execute("""
      WITH sequencia AS (
        SELECT c.municipio,c.ano,c.variavel,c.produto,c.sha256,
               c.coletado_em,c.origem,v.unidade,v.estado_valor,v.valor,
               LAG(c.sha256) OVER part AS sha_anterior,
               LAG(v.estado_valor) OVER part AS estado_anterior,
               LAG(v.valor) OVER part AS valor_anterior
        FROM pam_capturas c JOIN pam_vintages v ON
          (c.municipio,c.ano,c.variavel,c.produto,c.sha256)=
          (v.municipio,v.ano,v.variavel,v.produto,v.sha256)
        WINDOW part AS (
          PARTITION BY c.municipio,c.ano,c.variavel,c.produto
          ORDER BY c.coletado_em,c.sha256)
      )
      SELECT * FROM sequencia
      WHERE coletado_em > ? AND (? IS NULL OR coletado_em <= ?)
      ORDER BY coletado_em,municipio,ano,variavel,produto,sha256 LIMIT ?
      """, (inicio, fim, fim, limite_capturas+1)).fetchall()
    if len(rows) > limite_capturas:
        raise ErroAlertasPAM("excesso de capturas: dividir intervalo para não ocultar alertas")
    contagens = dict.fromkeys((
        "PRIMEIRA_CAPTURA","SEM_ALTERACAO","NOVOS_BYTES_MESMO_VALOR",
        "VALOR_ALTERADO","ESTADO_ALTERADO"), 0)
    eventos = []
    for r in rows:
        d = dict(r)
        sem = conferir_semantica_pam_1612(
            variavel=d["variavel"], categoria_c81=d["produto"],
            unidade=d["unidade"])
        if d["sha_anterior"] is None:
            tipo = "PRIMEIRA_CAPTURA"
        elif d["sha_anterior"] == d["sha256"]:
            tipo = "SEM_ALTERACAO"
        elif d["estado_anterior"] != d["estado_valor"]:
            tipo = "ESTADO_ALTERADO"
        elif d["estado_valor"] == "OBSERVADO_NUMERICO" and d["valor_anterior"] != d["valor"]:
            tipo = "VALOR_ALTERADO"
        else:
            tipo = "NOVOS_BYTES_MESMO_VALOR"
        contagens[tipo] += 1
        if tipo not in ("VALOR_ALTERADO","ESTADO_ALTERADO"):
            continue
        antigo = d["valor_anterior"] if d["estado_anterior"] == "OBSERVADO_NUMERICO" else None
        novo = d["valor"] if d["estado_valor"] == "OBSERVADO_NUMERICO" else None
        delta = novo-antigo if novo is not None and antigo is not None else None
        pct = 100*delta/antigo if delta is not None and antigo != 0 else None
        eventos.append({
            "id_evento": ":".join((d["municipio"],str(d["ano"]),d["variavel"],
                                  d["produto"],d["coletado_em"],d["sha256"])),
            "tipo":tipo, "municipio_ibge":d["municipio"],
            "ano_civil":d["ano"], "categoria_c81":d["produto"],
            "produto":sem["produto"], "variavel":d["variavel"],
            "indicador":sem["indicador"], "unidade":sem["unidade"],
            "valor_anterior":antigo,"valor_atual":novo,
            "estado_anterior":d["estado_anterior"],"estado_atual":d["estado_valor"],
            "variacao_absoluta":delta,"variacao_pct":pct,
            "sha_anterior":d["sha_anterior"],"sha_atual":d["sha256"],
            "coletado_em":d["coletado_em"],"origem":d["origem"],
            "classificacao":"ALTERACAO_ENTRE_CAPTURAS_NAO_DATA_DE_PUBLICACAO",
        })
    return {
        "estado":"RADAR_PAM_CALCULADO_SOBRE_CAPTURAS",
        "fonte":"IBGE_PAM","inicio_exclusivo":inicio,"fim_inclusivo":fim,
        "capturas_analisadas":len(rows),"contagens":contagens,
        "alteracoes_relevantes":len(eventos),"eventos":eventos,
        "captura_equivale_a_publicacao":False,
        "previsao_homologada":False,
        "aviso":"Alterações detectadas entre versões capturadas; não representam operação realizada nem data oficial da errata.",
    }
