"""Preços ANP de diesel: observações semanais inferidas a partir de CSV mensal.

Entrada: dados abertos ANP de postos, sem reter ou exportar qualquer
CNPJ, razão social, endereço, telefone ou identificador de estabelecimento.
DIESEL e DIESEL S10 são produtos DISTINTOS; são preços de revenda,
não preços de refinaria, paridade internacional ou preço de atacado.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median

CAMPOS = (
    "Regiao - Sigla", "Estado - Sigla", "Municipio", "Revenda",
    "CNPJ da Revenda", "Nome da Rua", "Numero Rua", "Complemento",
    "Bairro", "Cep", "Produto", "Data da Coleta",
    "Valor de Venda", "Valor de Compra", "Unidade de Medida", "Bandeira",
)
UF = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
_PRECO = re.compile(r"^\d{1,2},\d{1,3}$")


class ErroANP(ValueError):
    pass


def _valor_preco(valor: str) -> Decimal:
    if not isinstance(valor, str) or not _PRECO.fullmatch(valor.strip()):
        raise ErroANP("preço de revenda inválido ou nulo")
    try:
        preco = Decimal(valor.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ErroANP("preço de revenda não decimal") from exc
    if preco <= 0 or preco >= 50:
        raise ErroANP("preço de revenda fora de limite técnico")
    return preco


def semana_calendario(coleta: date) -> tuple[date,date]:
    """Âncora domingo-sábado derivada, NÃO semana oficial publicada pela ANP."""
    if not isinstance(coleta, date):
        raise ErroANP("data de coleta obrigatória")
    inicio = coleta - timedelta(days=(coleta.weekday()+1)%7)
    return inicio, inicio+timedelta(days=6)


def resumo_diesel_municipal(dados: bytes, *, mes_esperado: str) -> dict:
    """CSV autorizado da ANP; agrega somente preços sem armazenar postos.

    Dados fora do mês são rejeitados, não filtrados silenciosamente.
    Fonte pode conter lacunas de cobertura: ausência de município NÃO vira zero.
    """
    if not isinstance(dados, bytes) or not dados or len(dados)>15_000_000:
        raise ErroANP("CSV vazio ou acima do limite")
    if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", mes_esperado):
        raise ErroANP("mês esperado deve ser AAAA-MM")
    texto = None
    codificacao = ""
    for encoding in ("utf-8-sig","cp1252"):
        try:
            texto = dados.decode(encoding, errors="strict")
            codificacao = encoding
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ErroANP("codificação CSV não reconhecida")
    leitor = csv.DictReader(io.StringIO(texto,newline=""),delimiter=";")
    if leitor.fieldnames is None or tuple(leitor.fieldnames) != CAMPOS:
        raise ErroANP("schema ANP diesel divergente do contrato")
    grupos:dict[tuple[str,...],list[Decimal]] = defaultdict(list)
    totais = {"linhas_arquivo":0,"linhas_diesel_validas":0,"linhas_outros_produtos":0}
    for indice,linha in enumerate(leitor, start=2):
        totais["linhas_arquivo"] += 1
        if indice > 150_002:
            raise ErroANP("limite de linhas excedido")
        if None in linha or any(linha.get(c) is None for c in CAMPOS):
            raise ErroANP(f"linha {indice}: CSV desalinhado")
        produto = linha["Produto"].strip().upper()
        if produto not in ("DIESEL", "DIESEL S10"):
            totais["linhas_outros_produtos"] += 1
            continue
        uf = linha["Estado - Sigla"].strip().upper()
        municipio = " ".join(linha["Municipio"].strip().upper().split())
        if uf not in UF or not municipio or len(municipio)>120:
            raise ErroANP(f"linha {indice}: município/UF inválido")
        if linha["Unidade de Medida"].strip() != "R$ / litro":
            raise ErroANP(f"linha {indice}: unidade de preço inválida")
        try:
            coleta = datetime.strptime(linha["Data da Coleta"].strip(),"%d/%m/%Y").date()
        except ValueError as exc:
            raise ErroANP(f"linha {indice}: data inválida") from exc
        if coleta.strftime("%Y-%m") != mes_esperado:
            raise ErroANP(f"linha {indice}: data fora da competência do CSV")
        inicio,fim=semana_calendario(coleta)
        preco=_valor_preco(linha["Valor de Venda"])
        grupos[(uf,municipio,produto,inicio.isoformat(),fim.isoformat())].append(preco)
        totais["linhas_diesel_validas"] += 1
    if not grupos:
        raise ErroANP("CSV sem observações de diesel")
    series=[]
    for (uf,municipio,produto,inicio,fim),precos in sorted(grupos.items()):
        quantidade = len(precos)
        media = sum(precos,Decimal("0")) / Decimal(quantidade)
        mediana = median(precos)
        series.append({
            "uf":uf,"municipio":municipio,"produto":produto,
            "semana_inicio_inferida":inicio,"semana_fim_inferida":fim,
            "postos_observacoes":quantidade,
            "preco_medio_revenda_rs_l":float(media.quantize(Decimal("0.0001"))),
            "preco_mediano_revenda_rs_l":float(mediana.quantize(Decimal("0.0001"))),
            "preco_minimo_revenda_rs_l":float(min(precos)),
            "preco_maximo_revenda_rs_l":float(max(precos)),
        })
    return {
        "fonte":"ANP_SERIE_ABERTA_PRECOS_DIESEL",
        "competencia_mes":mes_esperado,"arquivo_sha256":hashlib.sha256(dados).hexdigest(),
        "codificacao":codificacao,
        "natureza":"OBSERVADO_POR_AMOSTRA_PESQUISA_PRECO_REVENDA",
        "semana_origem":"INFERIDA_CALENDARIO_NAO_SEMANA_OFICIAL_ANP",
        "diesel_tipo":"DIESEL_B_REVENDA; NAO_INFERIR_DIESEL_A_OU_PARIDADE",
        "totais":totais,
        "grupos_municipio_semana":len(series),
        "series":series,
        "privacidade":"SEM_IDENTIFICADORES_DE_POSTO_NO_RESULTADO",
        "limitacoes":"PRECO_MEDIO_SIMPLES_NAO_PONDERADO_POR_VOLUME_VENDIDO",
    }
