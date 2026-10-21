"""Ponte de registros de FRETES ANUNCIADOS para vintages quantitativos.

Aceita o schema 'registros' consolidado da PR #18 com SHA opcional do bruto
(se ausente, bloqueia criação de série). Não faz media/mediana por municipio,
não infere frete realizado, contratação ou movimento de carga.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
import json
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo
from .quant_core import ErroQuantitativo, _identidade, _instante, _hash, _dia

CHAVE=("municipio_ibge","pickup_entity_id","transportadora_id",
       "destino_ibge","descarga_entity_id","produto","equipamento","regime")
NATUREZA="FRETE_ANUNCIADO_NAO_CONTRATADO"
FUSO_COMERCIAL=ZoneInfo("America/Cuiaba")


def _valor_decimal(valor: object, campo: str, *, nao_negativo: bool=False) -> Decimal:
    if isinstance(valor,bool) or not isinstance(valor,(str,int,Decimal)):
        raise ErroQuantitativo(f"{campo}: decimal sem ambiguidade obrigatorio")
    try: n=Decimal(str(valor))
    except InvalidOperation as exc: raise ErroQuantitativo(f"{campo}: valor invalido") from exc
    if not n.is_finite() or len(n.as_tuple().digits)>18 or (n < 0 if nao_negativo else n <= 0):
        raise ErroQuantitativo(f"{campo}: fora do dominio")
    try:
        aproximado=float(n)
    except OverflowError as exc:
        raise ErroQuantitativo(f"{campo}: overflow ao representar BRL/T") from exc
    if not isfinite(aproximado) or (n != 0 and aproximado == 0):
        raise ErroQuantitativo(f"{campo}: numero irrepresentavel")
    # O contrato do motor armazena float: proibir perda silenciosa de
    # centavos/digitos ao converter valores Decimais comercialmente exatos.
    if Decimal(str(aproximado)) != n:
        raise ErroQuantitativo(f"{campo}: precisao decimal perdida na conversao")
    return n


def _chave(chave: Mapping) -> dict:
    if not isinstance(chave,Mapping) or set(chave)!=set(CHAVE):
        raise ErroQuantitativo("identidade economica incompleta")
    out={k:_identidade(chave[k],k) for k in CHAVE}
    for k in ("municipio_ibge","destino_ibge"):
        if len(out[k])!=7 or not out[k].isascii() or not out[k].isdecimal():
            raise ErroQuantitativo("codigo IBGE deve ter 7 digitos")
    if out["regime"] not in {"PF","PJ","NAO_INFORMADO"}:
        raise ErroQuantitativo("regime comercial invalido")
    return out


def preparar_serie_frete_anunciado(
    registros: Sequence[Mapping], *, chave: Mapping, fonte_id: str,
    tipo_valor: str, as_of: str
) -> dict:
    """Filtra? NÃO: rejeita lote misturado para impedir escolha enviesada.

    Entrada deve conter registros da MESMA identidade economica. Alteracoes
    de valor no mesmo dia sao vintages distintas se tiveram coleta distinta.
    Ausência de edicao_sha256 (como no contrato atual PR #18) bloqueia serie
    as-of: SHA não é inferido de preco e data. Sem preenchimento de lacunas.
    """
    identidade=_chave(chave)
    fonte=_identidade(fonte_id,"fonte_id")
    corte=_instante(as_of,"as_of")
    if tipo_valor not in {"BASE","CHEIO"}:
        raise ErroQuantitativo("tipo_valor precisa ser BASE ou CHEIO")
    if not isinstance(registros,(list,tuple)) or not 1<=len(registros)<=100000:
        raise ErroQuantitativo("lote de fretes invalido")
    registros_normalizados=[]
    hashes_ausentes=0
    vistos={}
    registro_ids={}
    pedagio_presente=set()
    for row in registros:
        if not isinstance(row,Mapping):
            raise ErroQuantitativo("registro de frete invalido")
        if any(row.get(k)!=v for k,v in identidade.items()):
            raise ErroQuantitativo("estabelecimento, transportadora ou condicoes heterogeneas")
        if row.get("natureza")!=NATUREZA:
            raise ErroQuantitativo("natureza deve ser FRETE_ANUNCIADO_NAO_CONTRATADO")
        if row.get("fonte_id")!=fonte:
            raise ErroQuantitativo("fonte_id heterogenea")
        registro_id=_identidade(row.get("registro_id"),"registro_id")
        oferta_id=_identidade(row.get("oferta_id"),"oferta_id")
        periodo=_dia(row.get("data_referencia"),"data_referencia")
        pub=_instante(row.get("data_publicacao"),"data_publicacao")
        coleta=_instante(row.get("data_coleta"),"data_coleta")
        if not pub<=coleta<=corte:
            raise ErroQuantitativo("cronologia invalida ou preco apos as_of")
        # Um anuncio divulgado em 2026 com referencia comercial de 2024
        # NAO e uma serie de preco atual. Datas em UTC tambem podem mudar
        # de dia na fronteira: a unidade comercial e o dia local de Mato Grosso.
        if periodo != pub.astimezone(FUSO_COMERCIAL).date():
            raise ErroQuantitativo(
                "data de referencia difere do dia local de publicacao; "
                "republicacao antiga ou fuso comercial nao validado"
            )
        base=_valor_decimal(row.get("frete_base_brl_t"),"frete_base_brl_t")
        pedagio=row.get("pedagio_brl_t")
        cheio=row.get("frete_cheio_brl_t")
        toll=None if pedagio is None else _valor_decimal(pedagio,"pedagio_brl_t",nao_negativo=True)
        full=None if cheio is None else _valor_decimal(cheio,"frete_cheio_brl_t")
        if full is not None and toll is not None and full!=base+toll:
            raise ErroQuantitativo("frete cheio != frete base + pedagio")
        pedagio_presente.add(toll is not None)
        if tipo_valor=="CHEIO":
            if full is None or toll is None or full!=base+toll:
                raise ErroQuantitativo("frete CHEIO exige base, pedagio e total reconciliados")
            valor=full
        else:
            valor=base
        digest=row.get("edicao_sha256")
        if digest is None:
            hashes_ausentes+=1
        else:
            _hash(digest)
        key=(periodo.isoformat(),coleta.isoformat())
        same=(str(base),str(valor),str(toll),str(full),digest,
              pub.isoformat(),registro_id,oferta_id)
        if registro_id in registro_ids and registro_ids[registro_id]!=same:
            raise ErroQuantitativo("registro_id reutilizado para edicoes comerciais diferentes")
        registro_ids[registro_id]=same
        if key in vistos:
            if vistos[key]!=same:
                raise ErroQuantitativo("vintages de frete conflitantes na mesma coleta")
            continue
        vistos[key]=same
        registros_normalizados.append({
            "periodo":periodo.isoformat(),"publicado_em":pub.isoformat(),
            "coletado_em":coleta.isoformat(),"valor":float(valor),
            "edicao_sha256":digest,
        })
    if len(pedagio_presente)!=1:
        raise ErroQuantitativo("presenca de pedagio varia no periodo; contrato incomparavel")
    # serie_id de identidade ECONOMICA exata; não tem município como unidade de
    # preco agregada: município é apenas um componente da chave.
    keydata={"chave":identidade,"tipo_valor":tipo_valor,"fonte_id":fonte,
             "pedagio_discriminado":pedagio_presente.pop()}
    codigo=sha256(json.dumps(keydata,sort_keys=True,ensure_ascii=True,
                             separators=(",",":")).encode("utf8")).hexdigest()
    sid="FRETE_OFERTA:"+codigo[:24]
    if hashes_ausentes:
        return {
            "status":"BLOQUEADO_SHA_EDICAO_AUSENTE","serie_id":sid,
            "natureza":NATUREZA,"registros":len(registros_normalizados),
            "edicoes_sem_sha":hashes_ausentes,"asof_pronto":False,
            "preparacao_offline_possivel":False,
            "edicao_raw_externamente_verificada":False,
            "uso_preditivo_real_autorizado":False,
            "observacoes_asof":[],"publicavel":False,
            "motivo":"edicao_sha256 original nao consta do contrato consolidado; nao sintetizar vintage",
        }
    for r in registros_normalizados:
        r.update(serie_id=sid,unidade="BRL/T",fonte_id=fonte)
    registros_normalizados.sort(key=lambda r:(r["periodo"],r["coletado_em"]))
    return {
        "status":"SERIE_ECONOMICA_INDIVIDUAL_PARA_TESTES_OFFLINE",
        "serie_id":sid,"natureza":NATUREZA,"tipo_valor":tipo_valor,
        "chave_economica":identidade,"registros":len(registros_normalizados),
        "observacoes_asof":registros_normalizados,
        "asof_pronto":False,
        "preparacao_offline_possivel":True,
        "edicao_raw_externamente_verificada":False,
        "uso_preditivo_real_autorizado":False,
        "publicavel":False,
        "limite":"SHA informado ainda exige verificacao do bruto; sem dados reais autorizados e backtest."
    }
