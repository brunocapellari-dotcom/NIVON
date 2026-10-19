"""Importação MDIC NCM: CSV local, sem rede, sem direitos presumidos."""
from __future__ import annotations
import csv
import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

COLUNAS = ("CO_ANO","CO_MES","CO_NCM","CO_UNID","CO_PAIS","SG_UF_NCM",
           "CO_VIA","CO_URF","QT_ESTAT","KG_LIQUIDO","VL_FOB","VL_FRETE","VL_SEGURO")
UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())

class ErroImportacao(ValueError):
    pass

def _inteiro(x, nome):
    if not isinstance(x,str) or not re.fullmatch(r"\d+",x.strip()):
        raise ErroImportacao(nome + ": inteiro não negativo obrigatório")
    return int(x.strip())

def resumir_importacao_csv(caminho, *, ncms: frozenset[str], limite_bytes=75000000,
                           limite_linhas=2000000):
    """FOB + frete + seguro = CIF aritmético; NÃO equivale a custo nacional."""
    if not isinstance(ncms,frozenset) or not ncms or any(
        not isinstance(x,str) or not re.fullmatch(r"\d{8}",x) for x in ncms
    ):
        raise ErroImportacao("NCM deve ter oito dígitos e ser explícito")
    if type(limite_bytes) is not int or not 0 < limite_bytes <= 100000000:
        raise ErroImportacao("limite_bytes inválido")
    if type(limite_linhas) is not int or not 0 < limite_linhas <= 5000000:
        raise ErroImportacao("limite_linhas inválido")
    p=Path(caminho)
    if p.is_symlink() or not p.is_file() or p.suffix.lower()!=".csv":
        raise ErroImportacao("CSV local regular obrigatório")
    if not 0 < p.stat().st_size <= limite_bytes:
        raise ErroImportacao("arquivo vazio ou grande demais")
    sha=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(262144), b""):
            sha.update(chunk)
    agg=defaultdict(lambda:[0,0,0,0,0])
    total=filtradas=0
    try:
        with p.open("r",encoding="utf-8-sig",errors="strict",newline="") as f:
            leitor=csv.DictReader(f,delimiter=";")
            if tuple(leitor.fieldnames or ()) != COLUNAS:
                raise ErroImportacao("layout de importação MDIC alterado")
            for row in leitor:
                total+=1
                if total>limite_linhas:
                    raise ErroImportacao("limite de linhas excedido")
                if None in row or any(row.get(c) is None for c in COLUNAS):
                    raise ErroImportacao("linha desalinhada")
                ncm=row["CO_NCM"].strip()
                if not re.fullmatch(r"\d{8}",ncm):
                    raise ErroImportacao("NCM inválido")
                if ncm not in ncms:
                    continue
                ano,mes=_inteiro(row["CO_ANO"],"ano"),_inteiro(row["CO_MES"],"mês")
                if not 1997<=ano<=2100 or not 1<=mes<=12:
                    raise ErroImportacao("competência inválida")
                uf=row["SG_UF_NCM"].strip().upper()
                if not re.fullmatch(r"[A-Z]{2}",uf):
                    raise ErroImportacao("UF/código inválido")
                pais=_inteiro(row["CO_PAIS"],"país")
                via=_inteiro(row["CO_VIA"],"via")
                urf=_inteiro(row["CO_URF"],"URF")
                _inteiro(row["CO_UNID"],"unidade")
                _inteiro(row["QT_ESTAT"],"quantidade")
                valores=[_inteiro(row[x],x) for x in
                         ("KG_LIQUIDO","VL_FOB","VL_FRETE","VL_SEGURO")]
                key=(f"{ano:04d}-{mes:02d}",ncm,uf,pais,via,urf)
                entry=agg[key]
                for i,v in enumerate(valores):
                    entry[i]+=v
                entry[4]+=1
                filtradas+=1
    except UnicodeError as exc:
        raise ErroImportacao("CSV não codificado em UTF-8") from exc
    if not filtradas:
        raise ErroImportacao("NCM não encontrado; ausência não equivale a zero")
    recortes=[]
    for (competencia,ncm,uf,pais,via,urf),(kg,fob,frete,seguro,n) in sorted(agg.items()):
        cif=fob+frete+seguro
        recortes.append({
            "competencia":competencia,"ncm":ncm,"uf_ncm":uf,
            "uf_brasileira":uf in UFS,"codigo_pais":pais,
            "codigo_via":via,"codigo_urf":urf,"peso_liquido_kg":kg,
            "toneladas":kg/1000,"valor_fob_usd":fob,
            "frete_internacional_usd":frete,"seguro_internacional_usd":seguro,
            "valor_cif_calculado_usd":cif,
            "cif_usd_t":cif*1000/kg if kg else None,
            "linhas_agregadas":n,"nao_municipio":True,
        })
    return {"fonte_id":"MDIC_COMEX_NCM","direcao":"IMPORTACAO",
            "arquivo_sha256":sha.hexdigest(),
            "coletado_em":datetime.now(timezone.utc).isoformat(),
            "publicacao":None,"registros_original":total,
            "registros_ncm_filtrados":filtradas,"recortes":recortes,
            "status":"PARSER_OFFLINE_SEM_COLETA_HOMOLOGADA",
            "limite_semantico":"CIF calculado não mede custo final, tributos, paridade nacional ou município"}
