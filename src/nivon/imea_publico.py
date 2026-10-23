"""NIVON IMEA — validação estrutural de cotações.
O uso de dados reais depende da permissão aplicável. Este módulo não consulta a rede.
"""
from datetime import datetime, date, timezone
import re
from decimal import Decimal, InvalidOperation
import hashlib

CHAINS = {"soja","milho","algodao","bovinocultura"}

def normalize(row):
    if not isinstance(row,dict):
        raise ValueError("Registro inválido")
    chain=str(row.get("cadeia","")).strip().lower()
    if chain not in CHAINS:
        raise ValueError("Cadeia desconhecida")
    indicator_id=str(row.get("indicador_id") or "").strip()
    if not re.fullmatch(r"[0-9]{1,30}",indicator_id):
        raise ValueError("Indicador inválido")
    title=str(row.get("indicador") or "").strip()
    location=str(row.get("localidade") or "").strip()
    unit=str(row.get("unidade") or "").strip()
    if not title or not location or not unit or len(title)>250 or len(location)>250 or len(unit)>50:
        raise ValueError("Dados de identificação ausentes")
    if chain=="soja" and "semente" in title.casefold():
        raise ValueError("Semente não é grão")
    if not any(word in title.casefold() for word in ("preço","preco","frete")):
        raise ValueError("Indicador não é preço/frete")
    try:
        price=Decimal(str(row.get("valor")))
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise ValueError("Número inválido") from exc
    if not price.is_finite() or price<=0 or price>1000000000:
        raise ValueError("Cotação zero, ausente ou negativa")
    published=row.get("data_publicacao")
    if published is None:
        raise ValueError("Publicação sem data")
    if isinstance(published,datetime):
        timestamp=published.isoformat()
    else:
        timestamp=str(published)
        datetime.fromisoformat(timestamp.replace("Z","+00:00"))
    parsed=datetime.fromisoformat(timestamp.replace("Z","+00:00"))
    if parsed.date()>datetime.now(timezone.utc).date():
        raise ValueError("Data de publicação futura")
    raw_crop=row.get("safra")
    crop_year=None if raw_crop is None or str(raw_crop) in ("", "nan", "<NA>", "NaT") else str(raw_crop).strip()
    if crop_year is not None and not re.fullmatch(r"(?:[0-9]{2}|20[0-9]{2})/[0-9]{2}",crop_year):
        raise ValueError("Safra inválida")
    kind="FRETE" if "frete" in title.casefold() else "PRECO"
    if kind=="FRETE" and unit.casefold() not in ("r$/t","r$/ton","r$/tonelada"):
        raise ValueError("Unidade de frete não homologada")
    key="|".join(["IMEA",chain,kind,indicator_id,location,timestamp,crop_year or "",unit])
    return {"source":"IMEA","chain":chain,"indicator_kind":kind,"indicator_id":indicator_id,
            "indicator":title,"location":location,"unit":unit,
            "value":str(price),"crop_year":crop_year,
            "published_at":timestamp,"reference_date":None,
            "source_key":hashlib.sha256(key.encode()).hexdigest(),
            "version_hash":hashlib.sha256(str(price).encode()).hexdigest(),
            "status":"PUBLICACAO_NAO_EQUIVALE_REFERENCIA"}
