"""IVO: ponte entre séries diárias ANA/INMET e indicadores mensais candidatos.

Exige todos os dias da competência com observações disponíveis as-of, mesma
estação, métrica, unidade e natureza observada. Não estima períodos faltantes,
não infere cobertura espacial e não autoriza treinamento ou redistribuição.
"""
from __future__ import annotations

import calendar
import re
import sqlite3
from datetime import date, datetime, timezone
from hashlib import sha256
from math import fsum, isfinite

from .series_ambientais import METRICAS, consultar_asof

class ErroPonteAmbiental(ValueError):
    pass

AGREGACOES={
    "CHUVA_DIA_MM":"SOMA_DIARIA",
    "COTA_CM":"MEDIA_DIARIA",
    "VAZAO_M3_S":"MEDIA_DIARIA",
    "TMIN_C":"MEDIA_MINIMAS_DIARIAS",
    "TMAX_C":"MEDIA_MAXIMAS_DIARIAS",
    "UMIDADE_REL_PCT":"MEDIA_DIARIA",
    "VENTO_MS":"MEDIA_DIARIA",
}
SHA=re.compile(r"[0-9a-f]{64}\Z")


def _utc(v):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None:
        raise ErroPonteAmbiental("corte exige datetime com fuso")
    return v.astimezone(timezone.utc)


def resumo_mensal_estacao_asof(db:sqlite3.Connection,*,dataset_id:str,
        estacao_id:str,metrica:str,mes:str,
        corte_publicacao:datetime,corte_coleta:datetime)->dict:
    if not isinstance(db,sqlite3.Connection):
        raise ErroPonteAmbiental("conexão SQLite canônica necessária")
    if dataset_id not in METRICAS or metrica not in METRICAS[dataset_id]:
        raise ErroPonteAmbiental("métrica não permitida no dataset")
    if not isinstance(mes,str) or re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])",mes) is None:
        raise ErroPonteAmbiental("mês deve ser AAAA-MM")
    y,m=map(int,mes.split("-"))
    dias=calendar.monthrange(y,m)[1]
    inicio=date(y,m,1)
    fim=date(y,m,dias)
    pub,coleta=_utc(corte_publicacao),_utc(corte_coleta)
    if coleta<pub:
        raise ErroPonteAmbiental("coleta de corte anterior a publicação de corte")
    if coleta.date()<=fim or pub.date()<=fim:
        raise ErroPonteAmbiental("mês ainda não encerrado no corte")
    rows=consultar_asof(db,dataset_id=dataset_id,estacao_id=estacao_id,
        metrica=metrica,inicio=inicio.isoformat(),fim=fim.isoformat(),
        corte_publicacao=pub.isoformat(),corte_coleta=coleta.isoformat())
    # Se falta um dia, o agregado não pode ser reconstruído por interpolação.
    calendario={ (inicio.toordinal()+i) for i in range(dias) }
    dias_serie=[]
    seen=set()
    classes=set()
    provenance=[]
    for r in rows:
        if (r.get("dataset_id"),r.get("estacao_id"),r.get("metrica"))!=(
                dataset_id,estacao_id,metrica):
            raise ErroPonteAmbiental("estação ou série fora de escopo")
        d=date.fromisoformat(r["data_local"])
        if d.toordinal() not in calendario or d in seen:
            raise ErroPonteAmbiental("dia inesperado/duplicado")
        seen.add(d)
        if r.get("unidade")!=METRICAS[dataset_id][metrica] or r.get("natureza")!="OBSERVADO":
            raise ErroPonteAmbiental("unidade/natureza não observada")
        v=r.get("valor")
        if type(v) not in (int,float) or not isfinite(v):
            raise ErroPonteAmbiental("dado diário inválido")
        original=r.get("sha256")
        if not isinstance(original,str) or SHA.fullmatch(original) is None:
            raise ErroPonteAmbiental("SHA diário inválido")
        # Metadado do registro original: a fonte sintética não pode se
        # converter em observação operacional por agregação mensal.
        meta=db.execute("""SELECT classe_registro,direitos_ref
            FROM ambiental_edicoes WHERE dataset_id=? AND sha256=?""",
            (dataset_id,original)).fetchone()
        if meta is None or meta["classe_registro"] not in ("SINTETICO","REAL_AUTORIZADO"):
            raise ErroPonteAmbiental("classe de edição desconhecida")
        tipo=meta["classe_registro"]
        if tipo=="REAL_AUTORIZADO" and not meta["direitos_ref"]:
            raise ErroPonteAmbiental("registro real sem referência aos direitos")
        classes.add(tipo)
        if len(classes)>1:
            raise ErroPonteAmbiental("não misturar edições sintéticas e reais")
        pub_src=r.get("publicado_utc")
        col_src=r.get("visto_utc")
        try:
            p=datetime.fromisoformat(pub_src)
            c=datetime.fromisoformat(col_src)
        except (TypeError,ValueError) as exc:
            raise ErroPonteAmbiental("datas de edição inválidas") from exc
        if p.tzinfo is None or c.tzinfo is None or p>pub or c>coleta or p>c:
            raise ErroPonteAmbiental("observação publicada/coletada fora do corte")
        dias_serie.append((d,float(v),p,c))
        provenance.append((d.isoformat(),original,round(float(v),12),
                           p.isoformat(),c.isoformat()))
    faltam=dias-len(dias_serie)
    cabecalho={
        "dataset_id":dataset_id,"estacao_id":estacao_id,
        "metrica":metrica,"mes":mes,"unidade":METRICAS[dataset_id][metrica],
        "dias_esperados":dias,"dias_disponiveis":len(dias_serie),
        "dias_ausentes":faltam,"corte_publicacao":pub.isoformat(),
        "corte_coleta":coleta.isoformat(),
        "treino_autorizado":False,
        "cobertura_espacial_homologada":False,
        "interpretacao":"Medida derivada de UMA estação, não previsão para município/bacia.",
    }
    if faltam:
        return dict(cabecalho,estado="BLOQUEADO_COBERTURA_DIARIA_INCOMPLETA",
                    valor_mensal=None,hash_evidencia=None,classe_registro=None)
    modo=AGREGACOES[metrica]
    valores=[r[1] for r in dias_serie]
    valor=fsum(valores) if modo=="SOMA_DIARIA" else fsum(valores)/dias
    if not isfinite(valor):
        raise ErroPonteAmbiental("agregado não finito")
    digest=sha256(repr((dataset_id,estacao_id,metrica,mes,
                 sorted(provenance))).encode("utf-8")).hexdigest()
    return dict(cabecalho,
        estado="CANDIDATO_MENSAL_COMPLETO_NAO_HOMOLOGADO",
        valor_mensal=valor,regra_calculo=modo,
        classe_registro=next(iter(classes)),
        hash_evidencia=digest,
        ultima_publicacao=max(r[2] for r in dias_serie).isoformat(),
        ultima_coleta=max(r[3] for r in dias_serie).isoformat(),
        observado_na_estacao=True,
    )
