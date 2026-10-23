"""Consulta gerencial PAM para IVO, diretamente do banco operacional versionado.

Exibe estatísticas anuais com vintages e origem, não produção mensal,
nem previsão homologada, nem revisão anterior à própria coleta. Todas
as variações são entre anos civis de mesmo município/produto/variável.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime,timezone
from pathlib import Path

from .ivo_pam_operacao import abrir_operacao_pam, consultar_pam_operacional
from .ivo_pam_semantica import conferir_semantica_pam_1612


class ErroConsultaPAM(ValueError):
    pass


def _utc(value):
    if value is None:
        return None
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ErroConsultaPAM("corte exige datetime com fuso")
    return value.astimezone(timezone.utc)


def painel_pam_ivo(db,*,municipio_ibge,produto,variavel,
                  ano_inicio,ano_fim,corte_coleta=None):
    """Paineis por município e culturas sem consolidar edições como medições."""
    if (type(ano_inicio) is not int or type(ano_fim) is not int
        or not 1974<=ano_inicio<=ano_fim<=2100 or ano_fim-ano_inicio>30):
        raise ErroConsultaPAM("janela anual entre 1 e 31 anos")
    corte=_utc(corte_coleta)
    sem=conferir_semantica_pam_1612(
        variavel=variavel,categoria_c81=produto,
        unidade="Toneladas" if variavel=="214" else "Hectares")
    series=[]
    anterior=None
    for ano in range(ano_inicio,ano_fim+1):
        r=consultar_pam_operacional(db,municipio_ibge=municipio_ibge,
            ano=ano,variavel=variavel,produto=produto,corte_coleta=corte)
        ultimo=r["ultima"]
        row={"ano_civil":ano,"capturas":r["capturas"],
             "estado":"SEM_CAPTURA" if not ultimo else ultimo["estado_valor"],
             "valor":None,"sha256":ultimo["sha256"] if ultimo else None,
             "capturado_em":ultimo["coletado_em"] if ultimo else None,
             "delta_anual":None,"variacao_pct_anual":None,
             "anos_consecutivos":False,
             "revisoes_de_valor":sum(x["mudanca"]=="VALOR_ALTERADO" for x in r["historico"])}
        if ultimo and ultimo["estado_valor"]=="OBSERVADO_NUMERICO":
            row["valor"]=ultimo["valor"]
            if anterior is not None and anterior["ano_civil"]==ano-1:
                row["anos_consecutivos"]=True
                row["delta_anual"]=row["valor"]-anterior["valor"]
                if anterior["valor"]!=0:
                    row["variacao_pct_anual"]=100*row["delta_anual"]/anterior["valor"]
            anterior=row
        else:
            anterior=None
        series.append(row)
    validos=[x for x in series if x["valor"] is not None]
    return {
        "estado":"PAINEL_PAM_ANUAL_OPERACIONAL_NAO_HOMOLOGADO",
        "fonte":"IBGE_PAM","municipio_ibge":municipio_ibge,
        "produto":sem["produto"],"categoria_c81":produto,
        "indicador":sem["indicador"],"variavel":variavel,
        "unidade":sem["unidade"],"periodo":[ano_inicio,ano_fim],
        "corte_coleta":corte.isoformat() if corte else None,
        "anos_com_captura_numerica":len(validos),
        "anos_sem_captura_numerica":len(series)-len(validos),
        "serie_anual":series,
        "ultima_competencia":validos[-1]["ano_civil"] if validos else None,
        "ultima_estatistica_candidata":validos[-1]["valor"] if validos else None,
        "revisao_verdade_oficial_certificada":False,
        "horario_publicacao_conhecido":False,
        "previsao_homologada":False,
        "aviso":"Valores PAM anuais coletados; revisões e captura não comprovam publicação na época nem produção medida.",
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="Consulta anual do IVO/PAM com versões")
    parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--municipio",required=True)
    parser.add_argument("--produto",required=True)
    parser.add_argument("--variavel",choices=("109","214"),required=True)
    parser.add_argument("--inicio",type=int,required=True)
    parser.add_argument("--fim",type=int,required=True)
    parser.add_argument("--corte",help="ISO 8601 com fuso")
    a=parser.parse_args(argv)
    try:
        db=abrir_operacao_pam(a.db)
        try:
            corte=datetime.fromisoformat(a.corte.replace("Z","+00:00")) if a.corte else None
            r=painel_pam_ivo(db,municipio_ibge=a.municipio,
                produto=a.produto,variavel=a.variavel,
                ano_inicio=a.inicio,ano_fim=a.fim,corte_coleta=corte)
        finally: db.close()
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError) as exc:
        print(json.dumps({"estado":"ERRO","motivo":str(exc)[:240]},ensure_ascii=False))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
