"""Lotes incrementais IMEA: validação de origem e quarentena, sem escrita.

Transformação em lotes pequenos, sem publicar valores nos logs da CI.
Nenhuma data de publicação vira data de referência automaticamente.
"""
from collections import Counter
from urllib.parse import urlsplit

from nivon.imea_publico import normalize

CHAIN_IDS={"soja":"4","milho":"3","algodao":"1","bovinocultura":"2"}

def verify_meta(meta,chain):
    if chain not in CHAIN_IDS:
        raise ValueError("CADEIA_INVALIDA")
    if str(getattr(meta,"source","")).lower()!="imea":
        raise ValueError("FONTE_DIFERENTE_DO_IMEA")
    u=str(getattr(meta,"source_url","") or "")
    url=urlsplit(u)
    expected=f"/api/v2/mobile/cadeias/{CHAIN_IDS[chain]}/cotacoes"
    if url.scheme!="https" or url.hostname!="api1.imea.com.br" or url.path!=expected or url.username or url.password:
        raise ValueError("ENDPOINT_DIFERENTE_DO_IMEA")
    return u

def prepare(rows,meta,chain,batch_size=80):
    source=verify_meta(meta,chain)
    if not isinstance(rows,list) or not rows:
        raise ValueError("ORIGEM_SEM_LINHAS")
    if not isinstance(batch_size,int) or isinstance(batch_size,bool) or not 1<=batch_size<=100:
        raise ValueError("TAMANHO_LOTE_INVALIDO")
    clean=[]
    reasons=Counter()
    seen=set()
    for original in rows:
        try:
            normalized=normalize(original)
            if normalized["chain"]!=chain:
                raise ValueError("CADEIA_NAO_CORRESPONDE_A_ORIGEM")
            key=(normalized["source_key"],normalized["version_hash"])
            if key in seen:
                raise ValueError("DUPLICATA_EXATA_NA_COLETA")
            seen.add(key)
            normalized["source_url"]=source
            clean.append(normalized)
        except (ValueError,TypeError,KeyError) as exc:
            reasons[str(exc).split(":")[0][:80]]+=1
    if not clean:
        raise ValueError("SEM_CANDIDATOS_HOMOLOGADOS")
    clean.sort(key=lambda r:(r["published_at"],r["indicator_id"],r["source_key"]))
    lots=[clean[i:i+batch_size] for i in range(0,len(clean),batch_size)]
    return {"batches":lots,
            "received":len(rows),"validated":len(clean),
            "discarded":sum(reasons.values()),
            "discard_reasons":dict(sorted(reasons.items())),
            "last_publication":max(r["published_at"][:10] for r in clean),
            "reference_dates_verified":0,
            "state":"STAGING_ONLY","source_url":source}
