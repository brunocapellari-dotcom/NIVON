"""Normalizador OFFLINE dos CSVs de exportação NCM do MDIC/Comex Stat.

Não é o conjunto "por municípios"; este último possui somente SH4 e
domicílio fiscal. Sem busca de sites, sem segredos e sem cópia bruta no Git.
"""
from __future__ import annotations
import csv
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
import hashlib
import re

HEADER = ("CO_ANO","CO_MES","CO_NCM","CO_UNID","CO_PAIS","SG_UF_NCM",
          "CO_VIA","CO_URF","QT_ESTAT","KG_LIQUIDO","VL_FOB")
UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


class ErroMDIC(ValueError): pass


def _inteiro(valor:str, campo:str)->int:
    if not isinstance(valor,str) or not re.fullmatch(r"\d+",valor.strip()):
        raise ErroMDIC(f"{campo}: inteiro não negativo obrigatório")
    return int(valor)


def resumir_exportacao_csv(caminho:str|Path,*,ncms:frozenset[str],
                         arquivo_limitado_bytes=75_000_000,linhas_max=2_000_000)->dict:
    """Agrupa por competência, NCM, UF, país, via, URF. NÃO por município.

    Cabeçalho oficial MDIC de EXPORTAÇÃO; outros layouts precisam de outro adaptador.
    `ncms` provém de dicionário NCM com competência/vigência separado.
    """
    if not ncms or any(not isinstance(n,str) or not re.fullmatch(r"\d{8}",n) for n in ncms):
        raise ErroMDIC("lista de NCMs explícita, oito dígitos, obrigatória")
    p=Path(caminho)
    if p.is_symlink() or not p.is_file() or p.suffix.lower()!=".csv":
        raise ErroMDIC("arquivo de exportação deve ser CSV regular")
    if p.stat().st_size>arquivo_limitado_bytes:
        raise ErroMDIC("arquivo excede limite configurado")
    h=hashlib.sha256()
    # Primeira passagem em bytes preserva hash da edição sem carregar CSV inteiro.
    with p.open("rb") as stream:
        for bloco in iter(lambda:stream.read(1024*256),b""):
            h.update(bloco)
    agg=defaultdict(lambda:{"kg":0,"usd_fob":0,"linhas":0})
    linhas=0
    filtradas=0
    try:
        with p.open("r",encoding="utf-8-sig",errors="strict",newline="") as stream:
            leitor=csv.DictReader(stream,delimiter=";")
            if tuple(leitor.fieldnames or ()) != HEADER:
                raise ErroMDIC("esquema de exportação MDIC alterado")
            for linha in leitor:
                linhas+=1
                if linhas>linhas_max:raise ErroMDIC("máximo de linhas excedido")
                if None in linha or any(linha.get(c) is None for c in HEADER):
                    raise ErroMDIC("CSV desalinhado")
                ncm=linha["CO_NCM"].strip()
                if not re.fullmatch(r"\d{8}",ncm):
                    raise ErroMDIC("NCM inválido")
                if ncm not in ncms:continue
                ano=_inteiro(linha["CO_ANO"],"ano")
                mes=_inteiro(linha["CO_MES"],"mes")
                if not (1997<=ano<=2100 and 1<=mes<=12):
                    raise ErroMDIC("competência inválida")
                uf=linha["SG_UF_NCM"].strip().upper()
                # Pode haver registros "ND"/"EX", tratar sem inferir UF.
                if not re.fullmatch(r"[A-Z]{2}",uf):
                    raise ErroMDIC("UF/código MDIC inválido")
                pais=_inteiro(linha["CO_PAIS"],"pais")
                via=_inteiro(linha["CO_VIA"],"via")
                urf=_inteiro(linha["CO_URF"],"urf")
                kg=_inteiro(linha["KG_LIQUIDO"],"kg")
                usd=_inteiro(linha["VL_FOB"],"fob")
                _inteiro(linha["QT_ESTAT"],"quantidade estatística")
                _inteiro(linha["CO_UNID"],"unidade estatística")
                key=(f"{ano:04d}-{mes:02d}",ncm,uf,pais,via,urf)
                agg[key]["kg"]+=kg
                agg[key]["usd_fob"]+=usd
                agg[key]["linhas"]+=1
                filtradas+=1
    except UnicodeError as exc:
        raise ErroMDIC("CSV não está em UTF-8") from exc
    if not filtradas:
        raise ErroMDIC("nenhum NCM solicitado encontrado: não atribuir zero")
    saida=[]
    for k,val in sorted(agg.items()):
        mes,ncm,uf,pais,via,urf=k
        saida.append({
            "competencia":mes,"ncm":ncm,"uf_ncm":uf,"codigo_pais":pais,
            "codigo_via":via,"codigo_urf":urf,
            "peso_liquido_kg":val["kg"],"toneladas":val["kg"]/1000,
            "valor_fob_usd":val["usd_fob"],"linhas_agregadas":val["linhas"],
            "valor_medio_usd_t": (val["usd_fob"]*1000/val["kg"] if val["kg"] else None),
            "natureza":"OBSERVADO_ESTATISTICA_SECOMEX",
            "nao_municipio":True,
        })
    return {
        "fonte_id":"MDIC_COMEX_NCM","direcao":"EXPORTACAO",
        "arquivo_sha256":h.hexdigest(),"coletado_em":datetime.now(timezone.utc).isoformat(),
        "registros_original":linhas,"registros_ncm_filtrados":filtradas,
        "recortes":saida,"classificacao":"ESTATISTICA_PUBLICA_NCM_UF_NAO_MUNICIPIO",
        "limitacao":"NCM e UF do produto; não identifica embarcador, fazenda, município do produtor ou empresa",
    }
