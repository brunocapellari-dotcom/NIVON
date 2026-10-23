"""NIVON IMEA — validação estrutural de cotações.
O uso de dados reais depende da permissão aplicável. Este módulo não consulta a rede.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib

CHAINS = {"soja","milho","algodao","bovinocultura"}

def normalize(row):
    if not isinstance(row,dict):
        raise ValueError("Registro inválido")
    chain=str(row.get("cadeia","")).lower()
    if chain not in CHAINS:
        raise ValueError("Cadeia desconhecida")
    indicator_id=str(row.get("indicador_id") or "").strip()
    if not indicator_id.isdecimal():
        raise ValueError("Indicador inválido")
    title=str(row.get("indicador") or "").strip()
    location=str(row.get("localidade") or "").strip()
    unit=str(row.get("unidade") or "").strip()
    if not title or not location or not unit:
        raise ValueError("Dados de identificação ausentes")
    if chain=="soja" and "semente" in title.casefold():
        raise ValueError("Semente não é grão")
    if not any(word in title.casefold() for word in ("preço","preco","frete")):
        raise ValueError("Indicador não é preço/frete")
    try:
        price=Decimal(str(row.get("valor")))
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise ValueError("Número inválido") from exc
    if not price.is_finite() or price<=0:
        raise ValueError("Cotação zero, ausente ou negativa")
    published=row.get("data_publicacao")
    if published is None:
        raise ValueError("Publicação sem data")
    if isinstance(published,datetime):
        timestamp=published.isoformat()
    else:
        timestamp=str(published)
        datetime.fromisoformat(timestamp.replace("Z","+00:00"))
    crop_year=str(row["safra"]) if row.get("safra") is not None else None
    key="|".join([indicator_id,location,timestamp,crop_year or "",unit])
    return {"source":"IMEA","chain":chain,"indicator_id":indicator_id,
            "indicator":title,"location":location,"unit":unit,
            "value":str(price),"crop_year":crop_year,
            "published_at":timestamp,"reference_date":None,
            "source_key":hashlib.sha256(key.encode()).hexdigest(),
            "version_hash":hashlib.sha256(str(price).encode()).hexdigest(),
            "status":"PUBLICACAO_NAO_EQUIVALE_REFERENCIA"}
