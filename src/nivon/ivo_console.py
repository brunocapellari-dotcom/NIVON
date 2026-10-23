"""Console IVO: planejamento geral e consulta opcional à PAM já armazenada.

A pergunta NUNCA autoriza a escolher município, cultura ou período por
inferência. Fonte operacional é SQLite local já existente e somente leitura.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime

from .ivo_planejador import ErroPlanejamento, planejar_consulta
from .ivo_pam_leitura import abrir_pam_somente_leitura, ErroLeituraPAM
from .ivo_pam_consulta import painel_pam_ivo
from .ivo_pam_alertas import alertas_revisoes_pam


def _dt(value):
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp exige ISO 8601 com timezone") from exc


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(
        description="IVO: planejar perguntas e ler séries PAM já capturadas, sem coletar ou prever.")
    parser.add_argument("--pergunta",required=True)
    parser.add_argument("--max-frentes",type=int,default=6)
    parser.add_argument("--pam-db",help="SQLite operacional já existente; somente leitura")
    parser.add_argument("--municipio",help="código IBGE de 7 dígitos, explícito")
    parser.add_argument("--produto",help="categoria C81 SIDRA explícita")
    parser.add_argument("--variavel",choices=("109","214"))
    parser.add_argument("--inicio",type=int,help="primeiro ano civil")
    parser.add_argument("--fim",type=int,help="último ano civil")
    parser.add_argument("--corte",help="data/hora de coleta limite ISO com fuso")
    parser.add_argument("--alertas-desde",help="início exclusivo ISO com fuso")
    args=parser.parse_args(argv)
    try:
        resultado=planejar_consulta(args.pergunta,max_frentes=args.max_frentes)
        valores=(args.municipio,args.produto,args.variavel,args.inicio,args.fim)
        if args.pam_db is None:
            if any(v is not None for v in valores) or args.corte or args.alertas_desde:
                raise ValueError("parâmetros PAM exigem --pam-db existente")
        else:
            if any(v is None for v in valores):
                raise ValueError("consulta PAM exige município, produto, variável e anos explícitos")
            corte=_dt(args.corte)
            inicio_alertas=_dt(args.alertas_desde)
            with closing(abrir_pam_somente_leitura(args.pam_db)) as db:
                painel=painel_pam_ivo(
                    db,municipio_ibge=args.municipio,produto=args.produto,
                    variavel=args.variavel,ano_inicio=args.inicio,
                    ano_fim=args.fim,corte_coleta=corte)
                radar=(alertas_revisoes_pam(
                    db,desde_exclusivo=inicio_alertas,ate_inclusivo=corte,
                    municipio_ibge=args.municipio,categoria_c81=args.produto,
                    variavel=args.variavel,ano_inicio=args.inicio,
                    ano_fim=args.fim)
                    if inicio_alertas is not None else None)
            resultado={
                **resultado,
                "status":"IVO_COM_CONSULTA_PAM_OPERACIONAL",
                "serie_pam":painel,
                "alertas_pam":radar,
                "dados_recuperados_do_sqlite":True,
                "coleta_nova_executada":False,
                "modelo_preditivo_executado":False,
                "veracidade_data_de_publicacao_comprovada":False,
            }
    except (ErroPlanejamento,ErroLeituraPAM,OSError,ValueError,
            KeyError,sqlite3.Error) as exc:
        print(json.dumps({"status":"BLOQUEADO","erro":str(exc)[:280]},ensure_ascii=False))
        return 2
    print(json.dumps(resultado,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
