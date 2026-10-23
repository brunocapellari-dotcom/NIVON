"""NOAA CPC RONI / ERSSTv6: leitor histórico oficial sem download.

Fonte: https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt
RONI é referência oficial CPC desde fev/2026. Tabelas históricas podem ser
revisadas e NÃO provam conhecimento point-in-time de períodos passados.
Seasons DJF..NDJ são médias móveis sobre 3 meses, não dados mensais
independentes. Cinco temporadas consecutivas são regra para episódio ENSO.
"""
from __future__ import annotations

from datetime import date,datetime,timezone
from hashlib import sha256
from math import isfinite
import re


class ErroRONI(ValueError):
    pass


ENDPOINT_OFICIAL = "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"
SEASONS = ("DJF","JFM","FMA","MAM","AMJ","MJJ","JJA","JAS","ASO","SON","OND","NDJ")
MAX_RAW_BYTES = 120_000


def importar_roni_ascii(*,raw:bytes,coletado_em:str,
                        versao_ersst:str="6") -> dict:
    """Carrega fonte primária exata, não recupera vintages por inferência."""
    if versao_ersst!="6":
        raise ErroRONI("somente NOAA CPC RONI ERSSTv6 no contrato atual")
    if not isinstance(raw,bytes) or not 10<len(raw)<=MAX_RAW_BYTES:
        raise ErroRONI("arquivo NOAA RONI vazio ou excessivo")
    try:
        content=raw.decode("ascii")
        collected=datetime.fromisoformat(coletado_em.replace("Z","+00:00"))
    except (UnicodeError,TypeError,AttributeError,ValueError) as exc:
        raise ErroRONI("ASCII NOAA e coleta ISO com fuso obrigatórios") from exc
    if collected.tzinfo is None or collected.utcoffset() is None:
        raise ErroRONI("fuso UTC de coleta obrigatório")
    collected=collected.astimezone(timezone.utc)
    if collected>datetime.now(timezone.utc):
        raise ErroRONI("coleta futura")
    lines=[x.strip() for x in content.splitlines() if x.strip()]
    if not lines or re.sub(r"\s+"," ",lines[0].upper())!="SEAS YR ANOM":
        raise ErroRONI("cabeçalho da fonte não reconhecido")
    records=[];seen=set();last=None
    for s in lines[1:]:
        fields=s.split()
        if len(fields)!=3 or fields[0] not in SEASONS:
            raise ErroRONI("temporada NOAA com estrutura inesperada")
        code,yy,raw_value=fields
        if not re.fullmatch(r"[0-9]{4}",yy):
            raise ErroRONI("ano RONI inválido")
        year=int(yy);month=SEASONS.index(code)+1
        if not 1950<=year<=collected.year or (year==collected.year and month>collected.month):
            raise ErroRONI("mês central futuro ou anterior a 1950")
        # Não supor que DJF foi publicado no mês central de janeiro.
        try:val=float(raw_value)
        except ValueError as exc:raise ErroRONI("anomalia não numérica") from exc
        if not isfinite(val) or abs(val)>8.0:
            raise ErroRONI("anomalia fora do domínio de validação")
        key=(year,month)
        if key in seen or (last is not None and (year*12+month)!=(last[0]*12+last[1]+1)):
            raise ErroRONI("duplicata ou lacuna na sequência de temporadas")
        seen.add(key);last=key
        records.append({
            "centro_ano":year,"centro_mes":month,
            "competencia_centro":f"{year:04d}-{month:02d}",
            "temporada":code,"anomalia_roni_c":val,
            "modelo_sst":"ERSSTv6","indice":"RONI",
            "revisao_temporal_possivel":True,
            "publicado_em":None,"disponivel_asof":False,
        })
    if len(records)<24:
        raise ErroRONI("histórico insuficiente para importação")
    last_year,last_month=last
    for row in records:
        months=(last_year*12+last_month)-(row["centro_ano"]*12+row["centro_mes"])
        row["recente_ainda_revisavel"]=months<2
    return {"dataset_id":"NOAA_ENSO_RONI","source":"NOAA_CPC",
            "endpoint":ENDPOINT_OFICIAL,"sha256":sha256(raw).hexdigest(),
            "coletado_em_utc":collected.isoformat(),
            "quantidade":len(records),"centro_primeiro":records[0]["competencia_centro"],
            "centro_ultimo":records[-1]["competencia_centro"],
            "registros":records,"status":"HISTORICO_RETROSPECTIVO_SEM_VINTAGE_ASOF",
            "vintages_de_publicacao_homologadas":False,
            "pode_treinar_modelo_point_in_time":False}


def classificar_episodios_roni(pacote:dict) -> dict:
    """Cinco temporadas sobrepostas consecutivas com limiar +/-0,5 °C.

    Não confundir uma temporada acima/abaixo do limiar com episódio
    formal; resultado retrospectivo pode mudar após revisões oficiais.
    """
    if not isinstance(pacote,dict) or pacote.get("status")!="HISTORICO_RETROSPECTIVO_SEM_VINTAGE_ASOF":
        raise ErroRONI("arquivo RONI oficial normalizado obrigatório")
    rows=pacote.get("registros")
    if not isinstance(rows,list) or len(rows)<24:
        raise ErroRONI("série RONI insuficiente")
    regimes={"EL_NINO":1,"LA_NINA":-1}
    events=[]
    for regime,sign in regimes.items():
        run=[]
        for row in rows:
            v=row["anomalia_roni_c"]
            matched=v>=0.5 if sign==1 else v<=-0.5
            if matched:run.append(row)
            else:
                if len(run)>=5:events.append((regime,run[:]))
                run=[]
        if len(run)>=5:events.append((regime,run[:]))
    events.sort(key=lambda item:(item[1][0]["centro_ano"],item[1][0]["centro_mes"]))
    return {"indice":"RONI","metodo":"NOAA_5_TEMPORADAS_CONSECUTIVAS",
            "eventos":[{"tipo":kind,"inicio_centro":parts[0]["competencia_centro"],
                        "fim_centro":parts[-1]["competencia_centro"],
                        "temporadas":len(parts),
                        "inclui_valor_provisorio":any(x["recente_ainda_revisavel"] for x in parts)}
                       for kind,parts in events],
            "status":"EPISODIOS_HISTORICOS_REVISAO_POSSIVEL",
            "modelo_de_previsao_validado":False}
