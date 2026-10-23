"""Diagnóstico OFFLINE de metadados oficiais potenciais do Agregados v3.

Um corpo JSON com URL declarada e ID válido NÃO comprova origem do IBGE.
Apenas cruza a estrutura interna dos bytes de metadados e valores; nenhum ID
e promovido para uso operacional automaticamente.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import re
import unicodedata

from .cadeias_adicionais import TABELAS_SIDRA
from .motores import DadoInvalido


def _texto(valor):
    if not isinstance(valor, str):
        return ""
    decom = unicodedata.normalize("NFKD", valor)
    return " ".join("".join(ch for ch in decom if not unicodedata.combining(ch)).casefold().split())


def _codigo(value):
    if type(value) is int and value >= 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return value
    return None


def analisar_contrato_metadados_sidra(*, bruto_metadados, especie, tabela_sidra,
                                     bruto_valores=None):
    """Devolve contratos candidatos e impedimentos, jamais homologação."""
    if TABELAS_SIDRA.get(especie) != tabela_sidra:
        raise DadoInvalido("especie/tabela de metadados divergentes")
    if not isinstance(bruto_metadados, bytes) or not 1 < len(bruto_metadados) <= 1_000_000:
        raise DadoInvalido("metadata nao binaria ou excessiva")
    try:
        obj = json.loads(bruto_metadados.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise DadoInvalido("metadata JSON invalida") from exc
    if not isinstance(obj, dict) or _codigo(obj.get("id")) != tabela_sidra:
        raise DadoInvalido("ID de metadados difere da tabela")
    variaveis = obj.get("variaveis")
    if variaveis is None:
        variaveis = []
    if not isinstance(variaveis, list) or len(variaveis) > 60:
        raise DadoInvalido("campo variaveis invalido")
    reconhecidas, ids_vistos = {}, set()
    for var in variaveis:
        if not isinstance(var, Mapping):
            raise DadoInvalido("variavel sem formato canonico")
        id_ = _codigo(var.get("id"))
        if id_ is None or id_ in ids_vistos:
            raise DadoInvalido("ID de variavel ausente/duplicado")
        ids_vistos.add(id_)
        nome, unid = _texto(var.get("nome")), _texto(var.get("unidade"))
        if "percentual" in nome or "%" in unid or "percentual" in unid:
            continue
        indicador = None
        if ("animais abatidos" in nome or "quantidade de animais abatidos" in nome) and (
                unid in ("cabecas", "cabeca")):
            indicador = "ABATE_CABECAS"
        elif "peso total das carcacas" in nome and unid in ("quilogramas", "quilograma", "kg"):
            indicador = "PESO_CARCACAS_KG"
        if indicador:
            if indicador in reconhecidas:
                raise DadoInvalido("mais de uma variavel candidata ao mesmo indicador")
            reconhecidas[indicador] = id_

    # Classificacoes sao diagnósticas; uma categoria 'Total' não significa
    # que se possa somar subcategorias, nem homologa a dimensao DnC.
    classificacoes = obj.get("classificacoes", [])
    if not isinstance(classificacoes, list) or len(classificacoes) > 50:
        raise DadoInvalido("classificacoes ausentes ou invalidas")
    tipos = {}
    for classe in classificacoes:
        if not isinstance(classe, Mapping):
            raise DadoInvalido("classificacao sem objeto")
        cid = _codigo(classe.get("id"))
        cats = classe.get("categorias", [])
        if cid is None or not isinstance(cats, list) or len(cats) > 300:
            raise DadoInvalido("classificacao/categorias invalidas")
        totais = []
        ids_cats = set()
        for cat in cats:
            if not isinstance(cat, Mapping):
                raise DadoInvalido("categoria invalida")
            categoria_id = _codigo(cat.get("id"))
            if categoria_id is None or categoria_id in ids_cats:
                raise DadoInvalido("categoria sem ID ou duplicada")
            ids_cats.add(categoria_id)
            if _texto(cat.get("nome")) in ("total", "total geral"):
                totais.append(categoria_id)
        if len(totais) > 1:
            raise DadoInvalido("multiplos totais na mesma classificacao")
        tipos[cid] = {"nome": classe.get("nome"),
                      "total_candidato": totais[0] if totais else None,
                      "categorias": len(cats)}
    cabecalho = {}
    if bruto_valores is not None:
        if not isinstance(bruto_valores, bytes) or not 0 < len(bruto_valores) <= 4_000_000:
            raise DadoInvalido("valores nao binarios ou excessivos")
        try:
            data = json.loads(bruto_valores.decode("utf-8-sig"))
        except (UnicodeError, ValueError) as exc:
            raise DadoInvalido("valores JSON invalidos") from exc
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise DadoInvalido("cabecalho SIDRA ausente")
        cabecalho = {k: v for k, v in data[0].items()
                     if isinstance(k, str) and re.fullmatch(r"D[1-9][0-9]*C", k)}
        if not all(isinstance(v, str) for v in cabecalho.values()):
            raise DadoInvalido("rotulos de dimensao nao textuais")
    candidatos = {id_: indic for indic, id_ in reconhecidas.items()}
    completos = set(reconhecidas) == {"ABATE_CABECAS", "PESO_CARCACAS_KG"}
    impedimentos = ["ORIGEM_HTTP_NAO_COMPROVADA",
                    "DIREITOS_DE_USO_NAO_VERIFICADOS",
                    "DIMENSOES_DNC_E_CATEGORIAS_NAO_HOMOLOGADAS",
                    "PUBLICACAO_HISTORICA_NAO_AUTENTICADA"]
    if not completos:
        impedimentos.append("VARIAVEIS_NAO_IDENTIFICADAS_NOS_METADADOS")
    return {
        "especie": especie, "tabela_sidra": tabela_sidra,
        "sha256_metadados": sha256(bruto_metadados).hexdigest(),
        "variaveis_candidatas": candidatos,
        "variaveis_completas": completos,
        "classificacoes_candidatas": tipos,
        "cabecalho_dimensoes": cabecalho,
        "impedimentos": impedimentos,
        "metadados_homologados": False,
        "publicacao_permitida": False,
    }


def confrontar_mapa_variaveis(*, diagnostico, mapa):
    """Rejeita mapa divergente SOMENTE se há duas variáveis identificadas."""
    if not isinstance(diagnostico, Mapping) or not isinstance(mapa, Mapping):
        raise DadoInvalido("contrato de comparacao invalido")
    if diagnostico.get("variaveis_completas"):
        if dict(mapa) != diagnostico["variaveis_candidatas"]:
            raise DadoInvalido("variaveis declaradas diferem dos metadados candidatos")
        return "CONSISTENTE_COM_METADADOS_NAO_HOMOLOGADOS"
    return "NAO_VERIFICAVEL_SEM_VARIAVEIS_COMPLETAS"
