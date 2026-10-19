"""PAM IBGE SIDRA 1612: consultas pontuais e normalização offline.

Lavouras temporárias anuais. Código c81 e variável precisam de dicionário
oficial com vigência; não infere correspondência do nome comercial.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

BASE = "https://apisidra.ibge.gov.br/values"
_MARCADORES = {"-":"ZERO_ABSOLUTO","0":"ZERO_ARREDONDADO",
               "X":"SUPRIMIDO_SIGILO","..":"NAO_APLICAVEL",
               "...":"NAO_DISPONIVEL"}

class ErroSIDRAPAM(ValueError):
    pass

def _id(valor,nome,digitos_min=1,digitos_max=12):
    if not isinstance(valor,str) or not re.fullmatch(rf"\d{{{digitos_min},{digitos_max}}}",valor):
        raise ErroSIDRAPAM(f"{nome}: código numérico explícito obrigatório")
    return valor

def planejar_pam_1612(*,municipio_ibge:str,ano:int,
                      codigo_produto_c81:str,codigo_variavel:str)->dict:
    """Uma consulta/município/produto/variável/ano, para não atingir limites."""
    _id(municipio_ibge,"municipio_ibge",7,7)
    _id(codigo_produto_c81,"codigo_produto_c81")
    _id(codigo_variavel,"codigo_variavel")
    if type(ano) is not int or not 1974<=ano<=2100:
        raise ErroSIDRAPAM("ano civil fora da série técnica")
    url=(f"{BASE}/t/1612/n6/{municipio_ibge}/v/{codigo_variavel}/"
         f"p/{ano}/c81/{codigo_produto_c81}/h/y/f/a")
    return {"dataset_id":"IBGE_PAM","url":url,
            "municipio_ibge":municipio_ibge,"ano":ano,
            "categoria_c81":codigo_produto_c81,"variavel":codigo_variavel,
            "natureza":"PAM_ANUAL_NAO_PREVISAO_LSPA",
            "estado":"PLANO_OFFLINE_CODIGOS_EXIGEM_VERIFICACAO"}

def _tempo(valor):
    if not isinstance(valor,str):
        raise ErroSIDRAPAM("coleta sem data")
    try:
        d=datetime.fromisoformat(valor.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroSIDRAPAM("instante inválido") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ErroSIDRAPAM("data de coleta sem timezone")
    return d.astimezone(timezone.utc).isoformat()

def _pares_sem_repeticao(pares):
    obj={}
    for k,v in pares:
        if k in obj:
            raise ErroSIDRAPAM("chave JSON duplicada")
        obj[k]=v
    return obj

def normalizar_pam_1612(payload:bytes,*,plano:dict,coletado_em:str)->dict:
    """Lê JSON SIDRA em memória. Marcadores especiais não viram dados inventados."""
    if not isinstance(plano,dict):
        raise ErroSIDRAPAM("plano necessário")
    esperado=planejar_pam_1612(municipio_ibge=plano.get("municipio_ibge"),
        ano=plano.get("ano"),codigo_produto_c81=plano.get("categoria_c81"),
        codigo_variavel=plano.get("variavel"))
    if plano!=esperado:
        raise ErroSIDRAPAM("plano diverge do contrato oficial do adaptador")
    uri=urlsplit(plano["url"])
    if uri.scheme!="https" or uri.hostname!="apisidra.ibge.gov.br":
        raise ErroSIDRAPAM("endpoint não é SIDRA oficial")
    coleta=_tempo(coletado_em)
    if not isinstance(payload,bytes) or not 0<len(payload)<=2_000_000:
        raise ErroSIDRAPAM("JSON ausente ou excede 2 MB")
    try:
        dados=json.loads(payload.decode("utf-8-sig"),object_pairs_hook=_pares_sem_repeticao)
    except (UnicodeError,ValueError) as exc:
        raise ErroSIDRAPAM("JSON inválido") from exc
    if not isinstance(dados,list) or not 2<=len(dados)<=2001:
        raise ErroSIDRAPAM("lista com cabeçalho e registros obrigatória")
    campos=("D1C","D2C","D3C","D4C","V","MN")
    cabecalho=dados[0]
    if not isinstance(cabecalho,dict) or not set(campos).issubset(cabecalho):
        raise ErroSIDRAPAM("cabeçalho SIDRA incompatível")
    normalizados=[]
    vistos=set()
    for linha in dados[1:]:
        if not isinstance(linha,dict) or not set(campos).issubset(linha):
            raise ErroSIDRAPAM("registro SIDRA inválido")
        chave=(linha["D1C"],linha["D2C"],linha["D3C"],linha["D4C"])
        if chave != (plano["municipio_ibge"],str(plano["ano"]),plano["variavel"],
                     plano["categoria_c81"]):
            raise ErroSIDRAPAM("município, período ou classificação divergentes")
        if chave in vistos:
            raise ErroSIDRAPAM("observação duplicada")
        vistos.add(chave)
        raw=linha["V"]
        if not isinstance(raw,str) or not raw.strip():
            raise ErroSIDRAPAM("valor bruto inválido")
        if raw in _MARCADORES:
            estado=_MARCADORES[raw]
            valor=0.0 if raw in ("-","0") else None
        else:
            if not re.fullmatch(r"\d+(?:[.,]\d+)?",raw):
                raise ErroSIDRAPAM("valor numérico não homologado")
            try:
                valor=float(Decimal(raw.replace(",",".")))
            except (ValueError,InvalidOperation,OverflowError) as exc:
                raise ErroSIDRAPAM("valor numérico inválido") from exc
            if not 0<=valor<1e16:
                raise ErroSIDRAPAM("valor fora de limite técnico")
            estado="OBSERVADO_NUMERICO"
        unidade=linha["MN"]
        if not isinstance(unidade,str) or not unidade.strip() or len(unidade)>100:
            raise ErroSIDRAPAM("unidade ausente")
        normalizados.append({"municipio_ibge":chave[0],"ano_civil":int(chave[1]),
            "variavel_sidra":chave[2],"produto_categoria_c81":chave[3],
            "unidade_original":unidade,"valor":valor,"estado_valor":estado,
            "natureza":"PAM_ANUAL_ESTATISTICA_NAO_PREVISAO"})
    return {"dataset_id":"IBGE_PAM","sha256_original":hashlib.sha256(payload).hexdigest(),
            "coletado_em":coleta,"publicacao":None,"consulta":plano["url"],
            "observacoes":normalizados,"linhas":len(normalizados),
            "status":"OFFLINE_AMOSTRA_NAO_HOMOLOGADA",
            "limite":"PAM ano civil não é progresso semanal de plantio/colheita ou previsão LSPA"}
