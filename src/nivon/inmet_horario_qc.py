"""NIVON: extração INMET automático horário, sem rede e sem escrita de dados.

INMET: observações horárias UTC brutas NÃO têm QC automaticamente aprovado.
Dados ausentes nunca viram zero. Agrupamento UTC não garante por si só
a janela física do acumulado horário; metadado externo é necessário.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, date
from math import isfinite


class ErroINMETHorario(ValueError):
    pass


MAX_BYTES = 8_000_000
MAX_REGISTROS = 30000


def _normal(chave: str) -> str:
    s=unicodedata.normalize("NFKD",chave).encode("ascii","ignore").decode("ascii")
    return "".join(c for c in s.upper() if c.isalnum())


_ALIASES = {
    "data": {"DATA", "DATAYYYYMMDD", "DATAMEDICAO", "DATAMEDICAOYYYYMMDD"},
    "hora": {"HORAUTC", "HORAMEDICAO", "HORAMEDICAOUTC"},
    "chuva": {"PRECIPITACAOTOTALHORARIOMM", "PRECIPITACAOTOTALHORARIAMM"},
    "temp": {"TEMPERATURADOARBULBOSECOHORARIAC", "TEMPERATURADOARBULBOSECOHORARIACELSIUS"},
}


def _colunas(headers):
    folded=[_normal(x) for x in headers]
    if len(folded)!=len(set(folded)):
        raise ErroINMETHorario("CSV com colunas duplicadas")
    chosen={}
    for kind,aliases in _ALIASES.items():
        matches=[i for i,h in enumerate(folded) if h in aliases]
        if len(matches)>1:
            raise ErroINMETHorario("colunas equivalentes duplicadas: "+kind)
        chosen[kind]=matches[0] if matches else None
    if chosen["data"] is None or chosen["hora"] is None:
        raise ErroINMETHorario("data/hora UTC ausentes no cabeçalho")
    if chosen["chuva"] is None and chosen["temp"] is None:
        raise ErroINMETHorario("sem chuva ou temperatura horária")
    return chosen


def _date(s):
    if not isinstance(s,str):
        raise ErroINMETHorario("data não textual")
    for fmt in ("%Y-%m-%d","%Y/%m/%d","%d/%m/%Y"):
        try:return datetime.strptime(s.strip(),fmt).date()
        except ValueError:continue
    raise ErroINMETHorario("data fora de formatos oficiais conhecidos")


def _hour(s):
    if not isinstance(s,str):
        raise ErroINMETHorario("hora UTC ausente")
    txt=re.sub(r"\s*UTC\s*$","",s.strip().upper())
    if re.fullmatch(r"\d{1,2}:\d{2}",txt):
        hh,mm=[int(x) for x in txt.split(":")]
    elif re.fullmatch(r"\d{4}",txt):
        hh,mm=int(txt[:2]),int(txt[2:])
    elif re.fullmatch(r"\d{1,2}",txt):
        hh,mm=int(txt),0
    else:
        raise ErroINMETHorario("formato de hora UTC não aceito")
    if not 0<=hh<=23 or mm!=0:
        raise ErroINMETHorario("hora fora do passo horário/UTC")
    return hh


def _number(raw,kind):
    if raw is None:return None
    text=str(raw).strip()
    if text.upper() in ("","NULL","NAN","NA","9999","9999,0","-9999","-9999,0"):
        return None
    if not re.fullmatch(r"-?\d+(?:[,.]\d+)?",text):
        raise ErroINMETHorario(kind+": número malformado")
    x=float(text.replace(",","."))
    if not isfinite(x):
        raise ErroINMETHorario(kind+": valor não finito")
    if kind=="chuva" and x<0 or kind=="temp" and not -90<=x<=70:
        raise ErroINMETHorario(kind+": limite físico violado")
    return x


def extrair_horarios_inmet(*,csv_bytes:bytes,estacao_esperada:str,
                          ano_esperado:int) -> dict:
    """CSV individual dentro de ZIP INMET/BDMEP previamente inspecionado.

    Estação deve estar no metadado CODIGO (WMO), não inferida de filename.
    Não cria fatos por interpolação, nem identifica automaticamente direitos.
    """
    if not isinstance(csv_bytes,bytes) or not 0<len(csv_bytes)<=MAX_BYTES:
        raise ErroINMETHorario("CSV ausente ou acima do limite")
    if not isinstance(estacao_esperada,str) or not re.fullmatch(r"[A-Z][0-9]{3,5}",estacao_esperada):
        raise ErroINMETHorario("código de estação não homologado")
    if type(ano_esperado) is not int or not 2000<=ano_esperado<=2100:
        raise ErroINMETHorario("ano esperado inválido")
    try:raw=csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:raw=csv_bytes.decode("latin1")
    reader=csv.reader(io.StringIO(raw),delimiter=";")
    metadata={};header=None;cols=None;records=[];seen=set()
    for no,row in enumerate(reader,1):
        if no>MAX_REGISTROS+50:
            raise ErroINMETHorario("CSV excede limite de registros")
        if not row or all(not x.strip() for x in row):
            continue
        if header is None:
            if _normal(row[0]).startswith("DATA") and any("HORA" in _normal(x) for x in row):
                header=row;cols=_colunas(row)
                continue
            if len(metadata)>25:
                raise ErroINMETHorario("cabeçalho não localizado")
            if len(row)>1:
                metadata[_normal(row[0])]=row[1].strip().upper()
            continue
        if len(row)!=len(header):
            raise ErroINMETHorario("linha CSV com largura inconsistente")
        day=_date(row[cols["data"]])
        hour=_hour(row[cols["hora"]])
        if day.year!=ano_esperado:
            raise ErroINMETHorario("data de outro ano no CSV anual")
        key=(day.isoformat(),hour)
        if key in seen:
            raise ErroINMETHorario("registro horário duplicado")
        seen.add(key)
        chuva=_number(row[cols["chuva"]],"chuva") if cols["chuva"] is not None else None
        temp=_number(row[cols["temp"]],"temp") if cols["temp"] is not None else None
        records.append({
            "data_utc":day.isoformat(),"hora_utc":hour,
            "chuva_hora_mm":chuva,"temp_ar_bulbo_seco_c":temp,
            "status":"BRUTO_INMET_SEM_QC","dataset_id":"INMET_ESTACOES",
        })
    if header is None or not records:
        raise ErroINMETHorario("CSV sem série reconhecível")
    codigo=next((v.strip() for k,v in metadata.items()
        if k.startswith("CODIGOWMO") or k=="CODIGODAESTACAO"),None)
    if codigo is None or codigo!=estacao_esperada:
        raise ErroINMETHorario("metadado WMO/estação não corresponde ao esperado")
    records.sort(key=lambda r:(r["data_utc"],r["hora_utc"]))
    return {"dataset_id":"INMET_ESTACOES","estacao":codigo,
        "ano":ano_esperado,"raw_sha256":hashlib.sha256(csv_bytes).hexdigest(),
        "linhas":len(records),"tem_chuva":cols["chuva"] is not None,
        "tem_temperatura":cols["temp"] is not None,
        "observacoes":records,"status":"BRUTO_HORARIO_SEM_QC",
        "fuso":"UTC_DECLARADO_NO_CABECALHO",
        "publicacao":None,"vintage_disponivel_comprovado":False,
        "direitos_verificados":False}


def agregar_dias_inmet(*,pacote:dict,
                       convencao_intervalo_chuva_confirmada:bool=False,
                       referencia_convencao:str|None=None) -> dict:
    """Chuva diária disponível APENAS com 24 horas não nulas e 24 horas presentes.

    Mesmo 24 horas não confirmam medição sem erros de sensor/intervalo; guarda
    estados distintos. Tmax/Tmin obtidas de bulbo seco são extremos AMOSTRADOS,
    não os extremos oficiais de termômetro dedicado.
    """
    if not isinstance(pacote,dict) or pacote.get("status")!="BRUTO_HORARIO_SEM_QC":
        raise ErroINMETHorario("pacote fora do contrato")
    if type(convencao_intervalo_chuva_confirmada) is not bool:
        raise ErroINMETHorario("comprovação deve ser bool")
    if convencao_intervalo_chuva_confirmada and (
        not isinstance(referencia_convencao,str) or len(referencia_convencao.strip())<12):
        raise ErroINMETHorario("evidência externa de intervalo horário obrigatória")
    byday=defaultdict(list)
    for row in pacote["observacoes"]:
        byday[row["data_utc"]].append(row)
    daily=[]
    for dia,rows in sorted(byday.items()):
        hs=[x["hora_utc"] for x in rows]
        if len(hs)!=len(set(hs)) or len(hs)>24:
            raise ErroINMETHorario("horários inconsistentes")
        rains=[x["chuva_hora_mm"] for x in rows]
        temps=[x["temp_ar_bulbo_seco_c"] for x in rows]
        rain24=len(rows)==24 and all(x is not None for x in rains) and pacote["tem_chuva"]
        temp24=len(rows)==24 and all(x is not None for x in temps) and pacote["tem_temperatura"]
        rain=round(sum(rains),6) if rain24 else None
        if rain is not None and rain>1000:
            raise ErroINMETHorario("chuva diária extrema exige QC manual, não inferir")
        daily.append({
            "data_utc":dia,"horas_encontradas":len(rows),
            "horas_chuva_validas":sum(x is not None for x in rains) if pacote["tem_chuva"] else 0,
            "horas_temp_validas":sum(x is not None for x in temps) if pacote["tem_temperatura"] else 0,
            "chuva_rotulo_utc_mm":rain,
            "tmin_bulbo_amostrada_c":min(temps) if temp24 else None,
            "tmax_bulbo_amostrada_c":max(temps) if temp24 else None,
            "convencao_intervalo_confirmada":convencao_intervalo_chuva_confirmada,
            "comparacao_grade_permitida":bool(rain24 and convencao_intervalo_chuva_confirmada),
            "qc_sensor":"NAO_HOMOLOGADO",
            "classificacao":"AGREGACAO_ESTACAO_SEM_QC",
        })
    return {"dataset_id":"INMET_ESTACOES","estacao":pacote["estacao"],
            "raw_sha256":pacote["raw_sha256"],"dias":daily,
            "status":"DIARIO_PRELIMINAR_NAO_HOMOLOGADO",
            "referencia_convencao":referencia_convencao,
            "publicacao":None,"liberacao_preditiva":False}
