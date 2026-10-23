"""Continuidade da PAM/IVO: prioridades incrementais e revisão entre capturas.

Consulta SOMENTE o staging SQLite já existente. Produz tarefas para eventual
coletor AUTORIZADO, não executa rede, não autoriza direitos nem promove dados.
A data do corte é sempre de captura, nunca data oficial de publicação.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from .ivo_pam_qualidade import auditar_operacao_pam
from .ivo_pam_semantica import conferir_semantica_pam_1612
from .sidra_pam import planejar_pam_1612


class ErroContinuidadePAM(ValueError):
    pass


_MUDANCAS = frozenset({
    "VALOR_ALTERADO", "ESTADO_ALTERADO", "NOVOS_BYTES_MESMO_VALOR",
})


def _utc(x):
    if isinstance(x, str):
        try:
            x = datetime.fromisoformat(x.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErroContinuidadePAM("instante invalido") from exc
    if not isinstance(x, datetime) or x.tzinfo is None or x.utcoffset() is None:
        raise ErroContinuidadePAM("instante com fuso obrigatorio")
    return x.astimezone(timezone.utc)


def _json(raw):
    try:
        blob = json.dumps(raw, ensure_ascii=False, sort_keys=True,
                          allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ErroContinuidadePAM("relatorio nao serializavel") from exc
    if len(blob) > 200_000:
        raise ErroContinuidadePAM("relatorio excessivo")
    return blob


def _sha(raw):
    return hashlib.sha256(_json(raw)).hexdigest()


def _tarefas_validas(tarefas):
    if not isinstance(tarefas, list) or not 1 <= len(tarefas) <= 30:
        raise ErroContinuidadePAM("entre 1 e 30 tarefas PAM explicitas")
    vistos = set()
    saida = []
    for t in tarefas:
        if not isinstance(t, dict):
            raise ErroContinuidadePAM("tarefa nao e objeto")
        try:
            p = planejar_pam_1612(
                municipio_ibge=t.get("municipio_ibge"), ano=t.get("ano"),
                codigo_produto_c81=t.get("categoria_c81"),
                codigo_variavel=t.get("variavel"),
            )
            conferir_semantica_pam_1612(
                variavel=p["variavel"], categoria_c81=p["categoria_c81"],
                unidade="Toneladas" if p["variavel"] == "214" else "Hectares",
            )
        except ValueError as exc:
            raise ErroContinuidadePAM("recorte/indicador fora do contrato SIDRA") from exc
        ident = (p["municipio_ibge"], p["ano"], p["variavel"], p["categoria_c81"])
        if ident in vistos:
            raise ErroContinuidadePAM("recorte duplicado na selecao")
        vistos.add(ident)
        saida.append(p)
    return saida


def _falhas_comprovadas(resultado, total):
    if resultado is None:
        return set()
    if not isinstance(resultado, dict) or resultado.get("estado") != "LOTE_PAM_CONCLUIDO":
        raise ErroContinuidadePAM("resultado anterior fora do contrato operacional")
    linhas = resultado.get("resultados")
    if (not isinstance(linhas, list) or type(resultado.get("total")) is not int
            or resultado["total"] != len(linhas) or len(linhas) > total):
        raise ErroContinuidadePAM("quantitativos do lote anterior invalidos")
    if (type(resultado.get("aprovados")) is not int
            or type(resultado.get("falhas")) is not int
            or resultado["aprovados"] + resultado["falhas"] != len(linhas)):
        raise ErroContinuidadePAM("contagens de falhas incoerentes")
    failures = set()
    for seq, item in enumerate(linhas):
        if (not isinstance(item, dict) or type(item.get("ordem")) is not int
                or item["ordem"] != seq or item["ordem"] >= total
                or item.get("status") not in ("OK", "ERRO")):
            raise ErroContinuidadePAM("ordem de tarefas divergente")
        if item["status"] == "ERRO":
            failures.add(seq)
    if len(failures) != resultado["falhas"]:
        raise ErroContinuidadePAM("resultado anterior diverge das falhas")
    return failures


def planejar_continuidade_pam(
    *, db: sqlite3.Connection, tarefas: list[dict], corte: datetime,
    raiz: str | Path,
    idade_maxima_dias: int = 7, resultado_anterior: dict | None = None,
) -> dict:
    """Retorna recortes vencidos, falhos, novos e alertas de revisão observada.

    Uma captura pode ser real, porém a revisão só pode ser atribuída ao
    intervalo entre capturas, e nunca ao ano civil originalmente informado.
    """
    if not isinstance(db, sqlite3.Connection):
        raise ErroContinuidadePAM("SQLite operacional obrigatorio")
    if type(idade_maxima_dias) is not int or not 1 <= idade_maxima_dias <= 365:
        raise ErroContinuidadePAM("idade maxima fora de limites")
    data = _utc(corte)
    plans = _tarefas_validas(tarefas)
    retry = _falhas_comprovadas(resultado_anterior, len(plans))
    if not isinstance(raiz, (str, Path)):
        raise ErroContinuidadePAM("raiz de quarentena necessaria")
    db.row_factory = sqlite3.Row
    # Auditoria integral ANTES de calcular alertas. Sem a cadeia SQL,
    # recibos e bytes verificados, o plano operacional nao e confiavel.
    try:
        check = auditar_operacao_pam(db=db, raiz=raiz, max_vintages=3000)
    except (ValueError, TypeError, OSError, sqlite3.Error, KeyError) as exc:
        raise ErroContinuidadePAM("integridade operacional indisponivel") from exc
    if check.get("integridade_local_aprovada") is not True:
        raise ErroContinuidadePAM("staging e quarentena divergentes")
    itens = []
    alertas = []
    for index, p in enumerate(plans):
        try:
            rows = db.execute("""SELECT v.sha256, v.estado_valor, v.valor,
                   c.coletado_em, c.mudanca
               FROM pam_capturas c JOIN pam_vintages v
                 ON (c.municipio,c.ano,c.variavel,c.produto,c.sha256)
                  = (v.municipio,v.ano,v.variavel,v.produto,v.sha256)
               WHERE c.municipio=? AND c.ano=? AND c.variavel=?
                 AND c.produto=? AND c.coletado_em<=?
               ORDER BY c.coletado_em, c.sha256 LIMIT 1001""",
               (p["municipio_ibge"], p["ano"], p["variavel"],
                p["categoria_c81"], data.isoformat())).fetchall()
        except sqlite3.Error as exc:
            raise ErroContinuidadePAM("schema operacional inacessivel") from exc
        if len(rows) > 1000:
            raise ErroContinuidadePAM("historico excede cota de consulta")
        ultimo = rows[-1] if rows else None
        dt = _utc(ultimo["coletado_em"]) if ultimo else None
        if dt is not None and dt > data:
            raise ErroContinuidadePAM("captura futura inconsistente")
        idade = (data - dt).total_seconds() / 86400 if dt else None
        if index in retry:
            estado = "RETOMAR_FALHA_ANTERIOR"
        elif dt is None:
            estado = "PRIMEIRA_CAPTURA_PENDENTE"
        elif idade >= idade_maxima_dias:
            estado = "CAPTURA_DESATUALIZADA"
        else:
            estado = "CAPTURA_RECENTE"
        ident = {
            "municipio_ibge": p["municipio_ibge"],
            "ano": p["ano"], "variavel": p["variavel"],
            "categoria_c81": p["categoria_c81"],
        }
        novidades = []
        for r in rows:
            if r["mudanca"] in _MUDANCAS:
                novidades.append({
                    "coletado_em": _utc(r["coletado_em"]).isoformat(),
                    "tipo": r["mudanca"], "arquivo_sha256": r["sha256"],
                })
        linha = {
            **ident, "estado": estado,
            "pode_ser_programado": estado != "CAPTURA_RECENTE",
            "url_planejada": p["url"],
            "capturas_no_corte": len(rows),
            "ultima_coleta": dt.isoformat() if dt else None,
            "ultimo_sha256": ultimo["sha256"] if ultimo else None,
            "ultima_condicao_valor": ultimo["estado_valor"] if ultimo else None,
            "mudancas_entre_capturas": len(novidades),
            "coleta_autorizada_neste_relat": False,
        }
        itens.append(linha)
        for evento in novidades:
            alertas.append({
                **ident, **evento, "classe": "REVISAO_OBSERVADA_ENTRE_CAPTURAS",
                "publicacao_oficial_na_data_comprovada": False,
                "valor_numerico_publicavel": False,
            })
    tarefas_pendentes = [
        {k: item[k] for k in ("municipio_ibge", "ano", "variavel", "categoria_c81")}
        for item in itens if item["pode_ser_programado"]
    ]
    corpo = {
        "schema": "nivon_ivo_pam_continuidade_v1",
        "corte_coleta": data.isoformat(),
        "idade_maxima_dias": idade_maxima_dias,
        "estado": "PLANEJAMENTO_OPERACIONAL_SEM_COLETA",
        "selecionados": len(itens),
        "pendentes": len(tarefas_pendentes),
        "tarefas_pendentes": tarefas_pendentes,
        "situacoes": itens,
        "alertas_de_revisao": alertas,
        "alertas": len(alertas),
        "requisicoes_externas_executadas": 0,
        "escrita_no_sqlite": False,
        "integridade_local_verificada": True,
        "homologacao_de_fonte": False,
        "autoriza_coleta": False,
        "autoriza_treinamento": False,
        "autoriza_publicacao": False,
        "nota": "Alertas descrevem comparacoes entre capturas, nao publicacao oficial.",
    }
    return {**corpo, "manifesto_sha256": _sha(corpo)}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Plano PAM incremental sem rede, com falhas e revisoes"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--acervo", type=Path, required=True)
    parser.add_argument("--tarefas", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--corte", required=True)
    parser.add_argument("--idade-dias", type=int, default=7)
    parser.add_argument("--resultado-anterior", type=Path)
    args = parser.parse_args(argv)
    try:
        if (args.db.is_symlink() or not args.db.is_file()
                or args.tarefas.is_symlink() or not args.tarefas.is_file()
                or args.saida.is_symlink() or not args.saida.parent.is_dir()):
            raise ErroContinuidadePAM("entrada/saida sem caminho regular")
        tasks = json.loads(args.tarefas.read_text(encoding="utf-8"))
        previous = None
        if args.resultado_anterior is not None:
            if (args.resultado_anterior.is_symlink()
                    or not args.resultado_anterior.is_file()):
                raise ErroContinuidadePAM("resultado anterior indisponivel")
            previous = json.loads(args.resultado_anterior.read_text(encoding="utf-8"))
        dburi = "file:" + quote(str(args.db.resolve(strict=True)), safe="/") + "?mode=ro"
        with sqlite3.connect(dburi, uri=True, timeout=10) as db:
            db.execute("PRAGMA query_only=ON")
            result = planejar_continuidade_pam(
                db=db, tarefas=tasks, corte=_utc(args.corte),
                raiz=args.acervo,
                idade_maxima_dias=args.idade_dias, resultado_anterior=previous,
            )
        raw = (json.dumps(result, ensure_ascii=False, sort_keys=True,
                          indent=2) + "\n").encode("utf-8")
        try:
            with args.saida.open("xb") as file:
                file.write(raw)
        except FileExistsError:
            if args.saida.is_symlink() or args.saida.read_bytes() != raw:
                raise ErroContinuidadePAM("relatorio existente divergente")
        print(json.dumps({
            "estado": result["estado"], "pendentes": result["pendentes"],
            "alertas": result["alertas"], "manifesto_sha256": result["manifesto_sha256"],
            "coletas_realizadas": 0,
        }, sort_keys=True))
        return 0
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        print(json.dumps({"estado": "ERRO_PLANEJAMENTO",
                          "classe": type(exc).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
