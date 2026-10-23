"""Execução contínua em lote do NIVON marítimo.

Uma falha de fonte não impede a ingestão das outras. O registro operacional
não contém HTML, credenciais nem conteúdo de terceiros e não libera CDP/AIS.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Callable

from nivon.maritimo_pipeline import (
    HTML_AUTORIZADO, HistoricoMaritimo, agora_utc, baixar_html, processar_html, _utc,
)

ESTADOS = frozenset(("OK", "QUARENTENA", "FALHA"))
MAX_FONTES = 8


def preparar_registro(db: HistoricoMaritimo):
    db.con.execute("""
    CREATE TABLE IF NOT EXISTS lote_execucoes(
      run_id TEXT NOT NULL, fonte TEXT NOT NULL,
      coletado_em TEXT NOT NULL, estado TEXT NOT NULL,
      quantidade INTEGER NOT NULL CHECK(quantidade>=0),
      revisoes INTEGER NOT NULL CHECK(revisoes>=0),
      captura_sha256 TEXT, motivo TEXT NOT NULL,
      duracao_ms INTEGER NOT NULL CHECK(duracao_ms>=0),
      PRIMARY KEY(run_id,fonte)
    )""")
    db.con.execute("CREATE INDEX IF NOT EXISTS idx_lote_fonte_data ON lote_execucoes(fonte,coletado_em DESC)")
    db.con.commit()


def _registrar(db, registro):
    with db.con:
        db.con.execute("""
        INSERT INTO lote_execucoes
        (run_id,fonte,coletado_em,estado,quantidade,revisoes,captura_sha256,motivo,duracao_ms)
        VALUES(?,?,?,?,?,?,?,?,?)
        """, (registro["run_id"], registro["fonte"], registro["coletado_em"],
              registro["estado"], registro["quantidade"], registro["revisoes"],
              registro["captura_sha256"], registro["motivo"], registro["duracao_ms"]))


def _motivo_excecao(exc):
    # Nao incluir texto da excecao: pode conter URL, arquivo e resposta externa.
    if isinstance(exc, (PermissionError, FileNotFoundError)):
        return "ACESSO_OU_ARQUIVO_INDISPONIVEL"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "TRANSPORTE_INDISPONIVEL"
    return "FONTE_INVALIDA_OU_PARSER_INCOMPATIVEL"


def executar_lote(fontes, db: HistoricoMaritimo, *, coletado_em=None,
                  fornecedor_html: Callable[[str], str] | None = None,
                  permitir_rede=False, on_result=None):
    """Um lote, historico atomico POR FONTE e resultado resumido por execucao.

    fornecedor_html e injetavel para replay autorizado; rede exige opt-in.
    A importacao agregada guarda apenas metadados e referencial da captura.
    """
    fontes = tuple(fontes)
    if (not 1 <= len(fontes) <= MAX_FONTES or len(fontes) != len(set(fontes))
            or any(f not in HTML_AUTORIZADO for f in fontes)):
        raise ValueError("lista de fontes invalida ou repetida")
    if fornecedor_html is None and not permitir_rede:
        raise PermissionError("sem fonte offline nem opt-in de rede")
    at = _utc(coletado_em or agora_utc())
    rid = str(uuid.uuid4())
    preparar_registro(db)
    saida = []
    for fonte in fontes:
        inicio = time.monotonic()
        record = {"run_id":rid, "fonte":fonte, "coletado_em":at, "estado":"FALHA",
                  "quantidade":0, "revisoes":0, "captura_sha256":None,
                  "motivo":"NAO_EXECUTADO", "duracao_ms":0}
        try:
            html = fornecedor_html(fonte) if fornecedor_html else baixar_html(
                fonte, habilitar_rede=permitir_rede)
            if not isinstance(html, str) or len(html.encode("utf-8")) > 2_000_000:
                raise ValueError("html invalido ou acima do limite")
            result = processar_html(fonte, html, db, coletado_em=at)
            flags = result["qualidade"].get("flags", ())
            record.update({
                "estado":"QUARENTENA" if result["qualidade"]["quarentena"] else "OK",
                "quantidade":result["registros"], "revisoes":result["revisoes_novas"],
                "captura_sha256":result["captura_sha256"],
                "motivo":",".join(sorted(flags)) if flags else "VALIDADO_PARSER",
            })
        except (OSError, ValueError, PermissionError, UnicodeError, TypeError) as exc:
            record["motivo"] = _motivo_excecao(exc)
        record["duracao_ms"] = max(0, round((time.monotonic() - inicio)*1000))
        _registrar(db, record)
        saida.append(record)
        if on_result is not None:
            on_result(record)
    counts = {k:sum(1 for r in saida if r["estado"]==k) for k in ESTADOS}
    return {"run_id":rid, "coletado_em":at, "estados":counts,
            "fontes":saida, "apto_operacao": counts["OK"] > 0 and counts["FALHA"] == 0}


def executar_portwatch(passagens, inicio, fim, *, banco_lineups, banco_portwatch,
                       coletado_em=None, fornecer_json=None, permitir_rede=False):
    """Ingere PortWatch em lote sem confundir passagens com escalas portuarias.

    Replay de uma pagina JSON; para serie real usa paginacao oficial limitada.
    """
    from nivon.portwatch_fluxos import (
        PASSAGENS, HistoricoPortWatch, normalizar, consultar_janela
    )
    names = tuple(passagens)
    if not names or len(names) != len(set(names)) or any(n not in PASSAGENS for n in names):
        raise ValueError("passagens invalidas")
    if fornecer_json is None and not permitir_rede:
        raise PermissionError("PortWatch precisa de arquivo autorizado ou opt-in")
    collected = _utc(coletado_em or agora_utc())
    preparar_registro(banco_lineups)
    rid = str(uuid.uuid4())
    start = time.monotonic()
    registro = {"run_id":rid, "fonte":"FMI_PORTWATCH", "coletado_em":collected,
                "estado":"FALHA", "quantidade":0, "revisoes":0,
                "captura_sha256":None, "motivo":"NAO_EXECUTADO", "duracao_ms":0}
    try:
        if fornecer_json is not None:
            rows, more = normalizar(fornecer_json, consultadas=names, coletado_em=collected)
            if more:
                raise ValueError("snapshot incompleto: paginacao requerida")
        else:
            rows = consultar_janela(names, inicio, fim, permitir_rede=True)
        if not rows:
            registro.update(estado="QUARENTENA", motivo="SEM_REGISTROS_VALIDOS")
        else:
            db_pw = HistoricoPortWatch(banco_portwatch)
            try:
                count = db_pw.inserir(rows)
            finally:
                db_pw.fechar()
            registro.update(estado="OK", quantidade=len(rows), revisoes=count,
                            motivo="DADOS_AGREGADOS_FMI_NAO_COMPROVAM_CARGA_REALIZADA")
    except (OSError, ValueError, PermissionError, TypeError, UnicodeError) as exc:
        registro["motivo"] = _motivo_excecao(exc)
    registro["duracao_ms"] = max(0, round((time.monotonic()-start)*1000))
    _registrar(banco_lineups,registro)
    return registro


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON ingestao maritima em lote")
    p.add_argument("--fontes",default="suape,imbituba,santarem_cdp,vila_conde_cdp")
    p.add_argument("--banco",type=Path,required=True)
    p.add_argument("--pasta-html",type=Path)
    p.add_argument("--permitir-rede",action="store_true")
    p.add_argument("--relatorio",type=Path)
    p.add_argument("--passagens",default="")
    p.add_argument("--inicio")
    p.add_argument("--fim")
    p.add_argument("--portwatch-json",type=Path)
    p.add_argument("--portwatch-banco",type=Path)
    args=p.parse_args(argv)
    if args.permitir_rede and args.pasta_html:
        p.error("modos rede e replay HTML sao mutuamente exclusivos")
    if not args.permitir_rede and not args.pasta_html:
        p.error("informe --pasta-html ou --permitir-rede")
    sources=tuple(v.strip() for v in args.fontes.split(","))
    def offline(fonte):
        if not args.pasta_html or fonte not in HTML_AUTORIZADO:
            raise ValueError("fonte invalida")
        return (args.pasta_html / (fonte + ".html")).read_text(encoding="utf-8")
    db=HistoricoMaritimo(args.banco)
    try:
        report=executar_lote(sources,db,fornecedor_html=None if args.permitir_rede else offline,
                            permitir_rede=args.permitir_rede)
        if args.passagens:
            if not args.portwatch_banco:
                p.error("--portwatch-banco obrigatorio")
            names=tuple(v.strip() for v in args.passagens.split(","))
            if args.portwatch_json:
                payload=args.portwatch_json.read_bytes()
            else:
                if not args.permitir_rede or not args.inicio or not args.fim:
                    p.error("PortWatch live requer rede e datas")
                payload=None
            portwatch=executar_portwatch(names,args.inicio,args.fim,banco_lineups=db,
                 banco_portwatch=args.portwatch_banco,
                 fornecer_json=payload, permitir_rede=args.permitir_rede)
            report["portwatch"]=portwatch
        if args.relatorio:
            if args.relatorio.exists():
                p.error("relatorio ja existe; nao sobrescrever")
            args.relatorio.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"run_id":report["run_id"], "estados":report["estados"],
                          "portwatch_estado":report.get("portwatch",{}).get("estado")},sort_keys=True))
        return 0 if (report["apto_operacao"] and report.get("portwatch",{}).get("estado","OK")=="OK") else 2
    finally:
        db.fechar()


if __name__=="__main__":
    raise SystemExit(main())
