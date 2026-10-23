"""Auditoria temporal do progresso agrícola derivado do histórico no Drive.

Distingue ausência de publicação, lacunas, quedas na fração e resets
potenciais. Sem regra de qual ano-safra pertence a cada observação, quedas
não são interpretadas como piora do plantio/colheita, correção ou erro.
Não presume que o histórico até julho/2026 esteja atualizado.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys


class ErroAuditoriaProgresso(ValueError):
    pass


_SHA=re.compile(r"[a-f0-9]{64}\Z")
_UFS=frozenset("BA GO MA MG MT MS PR PI RS SC SP TO".split())
_OP=frozenset(("SEMEADURA","COLHEITA"))
_PROD=frozenset(("SOJA","MILHO_1","MILHO_2","ALGODAO"))


def auditar_progresso_conab_drive(*, normalizado: dict, limite_alertas: int=40) -> dict:
    """Resumo de QUALIDADE sem transformar mudanças em previsões."""
    if not isinstance(normalizado,dict) or normalizado.get("status")!="HISTORICO_DRIVE_NORMALIZADO_SEM_ASOF":
        raise ErroAuditoriaProgresso("arquivo não é série do importador Drive")
    for gate in ("habilita_backtest","habilita_treino","habilita_publicacao"):
        if normalizado.get(gate) is not False:
            raise ErroAuditoriaProgresso("série tenta habilitar uso indevido")
    if type(limite_alertas) is not int or not 1<=limite_alertas<=100:
        raise ErroAuditoriaProgresso("limite_alertas deve ser entre 1 e 100")
    digest=normalizado.get("raw_sha256")
    if not isinstance(digest,str) or not _SHA.fullmatch(digest):
        raise ErroAuditoriaProgresso("hash CSV de importação ausente")
    records=normalizado.get("registros")
    if not isinstance(records,list) or not 1<=len(records)<=30000 or normalizado.get("total")!=len(records):
        raise ErroAuditoriaProgresso("tamanho de série inconsistente")
    groups=defaultdict(list)
    uf_counts,op_counts,prod_counts=Counter(),Counter(),Counter()
    unique_dates=set()
    seen=set()
    first,last="9999-99-99","0000-00-00"
    for r in records:
        if not isinstance(r,dict) or r.get("fonte_raw_sha256")!=digest:
            raise ErroAuditoriaProgresso("registro sem vínculo SHA do CSV")
        if (r.get("vintage_asof_comprovada") is not False or
                r.get("publicado_em") is not None or
                r.get("disponivel_em") is not None or
                r.get("unidade")!="FRACAO_0_1"):
            raise ErroAuditoriaProgresso("registro tenta afirmar vintage/unidade")
        uf,op,prod,ref=r.get("uf"),r.get("operacao"),r.get("cultura_segmento"),r.get("referencia")
        if uf not in _UFS or op not in _OP or prod not in _PROD or not isinstance(ref,str):
            raise ErroAuditoriaProgresso("dimensão agrícola inválida")
        try:
            d=date.fromisoformat(ref)
            if ref!=d.isoformat(): raise ValueError()
            val=Decimal(r.get("progresso_fracao"))
            if not val.is_finite() or not 0<=val<=1: raise InvalidOperation()
        except (ValueError,TypeError,InvalidOperation) as exc:
            raise ErroAuditoriaProgresso("referência ou fração inválida") from exc
        key=(uf,op,prod,ref)
        if key in seen:
            raise ErroAuditoriaProgresso("referência repetida no mesmo recorte")
        seen.add(key)
        groups[(uf,op,prod)].append((d,val))
        uf_counts[uf]+=1
        op_counts[op]+=1
        prod_counts[prod]+=1
        unique_dates.add(ref)
        first=min(first,ref)
        last=max(last,ref)
    if normalizado.get("data_min")!=first or normalizado.get("data_max")!=last:
        raise ErroAuditoriaProgresso("extremos temporais incompatíveis com dados")
    alerts=[]
    descidas=grandes=hiatos=eventos=0
    semanas_por_grupo={}
    for key, values in sorted(groups.items()):
        values.sort(key=lambda d:d[0])
        semanas_por_grupo["/".join(key)]=len(values)
        for (older,oldval),(newer,newval) in zip(values,values[1:]):
            gap=(newer-older).days
            if gap<=0:
                raise ErroAuditoriaProgresso("datas não crescentes")
            change=newval-oldval
            reasons=[]
            if gap>60:
                hiatos+=1
                reasons.append("LACUNA_SUPERIOR_60_DIAS")
            if change<0:
                descidas+=1
                reasons.append("PERCENTUAL_MENOR_SEM_SAFRA_IDENTIFICADA")
                if change<Decimal("-0.25"):
                    grandes+=1
            if reasons:
                eventos+=1
            if reasons and len(alerts)<limite_alertas:
                alerts.append({
                    "uf":key[0],"operacao":key[1],"cultura_segmento":key[2],
                    "referencia_anterior":older.isoformat(),
                    "referencia_posterior":newer.isoformat(),
                    "dias_entre_observacoes":gap,
                    "progresso_anterior":str(oldval),
                    "progresso_posterior":str(newval),
                    "delta_fracao":str(change),
                    "eventos":reasons,
                    "erro_confirmado":False,
                    "troca_safra_confirmada":False,
                })
    return {
        "estado":"AUDITORIA_SERIES_PROGRESSO_DRIVE_SEM_SAFRAS_SEGMENTADAS",
        "fonte_id":"CONAB_DERIVADO_ARQUIVO_DRIVE",
        "sha256_csv_importado":digest,
        "total_registros":len(records),"datas_distintas":len(unique_dates),
        "data_min":first,"data_max":last,
        "grupos_uf_operacao_produto":len(groups),
        "por_uf":dict(sorted(uf_counts.items())),
        "por_operacao":dict(sorted(op_counts.items())),
        "por_produto":dict(sorted(prod_counts.items())),
        "intervalos_superiores_60_dias":hiatos,
        "reducoes_de_fracao_sem_ciclo_validado":descidas,
        "reducoes_de_25pp_ou_mais_sem_ciclo_validado":grandes,
        "eventos_amostrados":alerts,
        "alertas_limitados":eventos>len(alerts),
        "disponibilidade_historica_comprovada":False,
        "safras_ano_ciclo_identificadas":False,
        "habilita_backtest":False,"habilita_treino":False,
        "habilita_publicacao":False,
        "nota":"Quedas podem representar novo ciclo, mudança de cobertura ou correção; jamais classificar como tendência sem contexto.",
    }


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="Audita temporalmente progresso CONAB do Drive sem safras/vintage")
    p.add_argument("--input",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args(argv)
    try:
        src,dest=Path(args.input),Path(args.out)
        if (src.is_symlink() or not src.is_file() or src.stat().st_size>25_000_000
                or dest.exists() or dest.is_symlink()):
            raise ErroAuditoriaProgresso("caminho de entrada/saída inseguro")
        result=auditar_progresso_conab_drive(
            normalizado=json.loads(src.read_text(encoding="utf-8"))
        )
        with dest.open("x",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
            f.write("\n")
        print("AUDITADOS="+str(result["total_registros"])+" ASOF=NAO")
        return 0
    except (ErroAuditoriaProgresso,UnicodeError,OSError,ValueError) as exc:
        print("AUDITORIA CONAB BLOQUEADA: "+str(exc),file=sys.stderr)
        return 3


if __name__=="__main__":
    raise SystemExit(main())
