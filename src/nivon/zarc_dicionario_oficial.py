"""Vocabulários ZARC conforme dicionário oficial MAPA/CGDA.

https://dados.agricultura.gov.br/dataset/6d3d141c-885e-41a4-ab7f-dc8ff323b96f/resource/bebb0ebb-bc75-460c-b900-a7a1ebd87bee/download/dicionario-de-dados---tabua-de-risco-2.pdf

É dicionário de METADADOS, não legenda de risco dos decêndios.
Cod_Munic é código do SICOR, nunca sinônimo de geocodigo IBGE.
"""
from __future__ import annotations

import re

CICLOS = {
    "13": "Perene", "19": "Semiperene", "20": "Grupo I",
    "21": "Grupo II", "22": "Grupo III", "24": "Grupo IV",
    "25": "Grupo V", "26": "Grupo VI",
}
SOLOS = {
    "1": "Arenoso", "2": "Textura Média", "3": "Argiloso",
    "11": "AD1", "12": "AD2", "13": "AD3", "14": "AD4",
    "15": "AD5", "16": "AD6",
}
MANEJOS = {
    "1": "Sequeiro", "2": "Irrigado",
    "3": "Irrigado com controle de geada",
}
CLIMAS = {
    "0": "Não se aplica",
    "1": "Alta disponibilidade de frio",
    "2": "Média disponibilidade de frio",
    "3": "Baixa disponibilidade de frio",
    "4": "Semiárido", "5": "Clima Ameno",
    "6": "Clima Quente", "7": "Clima Tropical",
    "8": "Clima Subtropical Ameno", "9": "Clima Subtropical Frio",
    "11": "Clima Subtropical",
}
NIVEIS_MANEJO = {"1": "NM1", "2": "NM2", "3": "NM3", "4": "NM4"}
DICIONARIO_ORIGEM = "MAPA_CGDA_TABUA_RISCO_DICIONARIO"
DICIONARIO_URL = (
    "https://dados.agricultura.gov.br/dataset/6d3d141c-885e-41a4-ab7f-dc8ff323b96f/"
    "resource/bebb0ebb-bc75-460c-b900-a7a1ebd87bee/download/"
    "dicionario-de-dados---tabua-de-risco-2.pdf"
)

class ErroDicionarioZarc(ValueError):
    pass

def interpretar_metadados_linha(row):
    """Mapeia somente classificações OFICIAIS, dec1..dec36 permanecem literais."""
    if not isinstance(row, dict):
        raise ErroDicionarioZarc("REGISTRO_NAO_OBJETO")
    for campo in ("geocodigo","Cod_Munic","Cod_Ciclo","Cod_Solo",
                  "Cod_Outros_Manejos","Cod_Clima","Cod_NM","UF"):
        if not isinstance(row.get(campo),str):
            raise ErroDicionarioZarc("CAMPO_OBRIGATORIO_NAO_TEXTO")
    ibge=row["geocodigo"].strip()
    sicor=row["Cod_Munic"].strip()
    if not re.fullmatch(r"\d{7}",ibge):
        raise ErroDicionarioZarc("GEOCODIGO_IBGE_NAO_VALIDO")
    if sicor and not re.fullmatch(r"\d{1,12}",sicor):
        raise ErroDicionarioZarc("CODIGO_SICOR_NAO_VALIDO")
    if row["UF"].strip()!="MT":
        raise ErroDicionarioZarc("ESCOPO_EXCLUSIVO_MT")
    labels = {}
    for campo, d in (
        ("Cod_Ciclo",CICLOS),("Cod_Solo",SOLOS),
        ("Cod_Outros_Manejos",MANEJOS),
        ("Cod_Clima",CLIMAS),("Cod_NM",NIVEIS_MANEJO),
    ):
        raw=row[campo].strip()
        labels[campo]={"codigo_original":raw,"descricao_oficial":d.get(raw),
                       "mapeamento":"DICIONARIO_MAPA" if raw in d else "NAO_MAPEADO"}
    decendios={}
    for i in range(1,37):
        k=f"dec{i}"
        val=row.get(k)
        if not isinstance(val,str) or len(val)>100:
            raise ErroDicionarioZarc("VALOR_DECENDIAL_INVALIDO")
        decendios[k]=val
    return {
        "municipio_ibge":ibge,
        "municipio_sicor":sicor or None,
        "codigos_originais_e_rotulos":labels,
        "decendios_valores_brutos":decendios,
        "decendios_interpretados_como_risco":False,
        "codigos_sicor_igualmente_ibge":False,
        "origem_dicionario":DICIONARIO_ORIGEM,
        "documento_referencia":DICIONARIO_URL,
        "pode_recomendar_plantio":False,
    }
