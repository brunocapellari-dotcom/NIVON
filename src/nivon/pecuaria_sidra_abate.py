"""Parser estrito e OFFLINE de instantaneos SIDRA 1092/1093/1094.

Nao descobre IDs de variaveis/categorias: exige mapa conferido contra os
metadados oficiais da extracao. Nao coleta, grava, agenda nem redistribui.
Os valores "..." e "-" sao NA, nunca zero. O trimestre nao pode ser somado
a seus meses; as categorias de inspecao/rebanho nao podem ser somadas aos totais.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re

from .cadeias_adicionais import (
    ObservacaoCadeia, TABELAS_SIDRA, _instante,
)
from .motores import DadoInvalido, validar_fonte

DIMENSOES_COMUNS = frozenset({
    "territorio", "periodo", "variavel", "referencia_temporal", "inspecao",
})
UF_IBGE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
    "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS",
    "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}
INDICADORES = frozenset({"ABATE_CABECAS", "PESO_CARCACAS_KG"})
UNIDADE_FONTE = {"ABATE_CABECAS": "cabeças", "PESO_CARCACAS_KG": "quilogramas"}
UNIDADE_CANONICA = {"ABATE_CABECAS": "CABECAS", "PESO_CARCACAS_KG": "KG"}
DADO_NAO_DISPONIVEL = frozenset({"...", "..", "-", "X", "x", "", "NA", "N/A"})


def _exigir_mapa(*, especie, tabela, dimensoes, totais, variaveis):
    if TABELAS_SIDRA.get(especie) != tabela:
        raise DadoInvalido("especie e tabela SIDRA incompativeis")
    chaves = DIMENSOES_COMUNS | ({"rebanho"} if especie == "BOVINO" else set())
    if not isinstance(dimensoes, Mapping) or set(dimensoes) != chaves:
        raise DadoInvalido("dimensoes SIDRA incompletas ou adicionais")
    if len(set(dimensoes.values())) != len(chaves) or any(
        not isinstance(campo, str) or not re.fullmatch(r"D[1-9][0-9]*C", campo)
        for campo in dimensoes.values()
    ):
        raise DadoInvalido("colunas dimensionais devem ser DnC distintas")
    totais_esperados = chaves - {"territorio", "periodo", "variavel"}
    if not isinstance(totais, Mapping) or set(totais) != totais_esperados or any(
        not isinstance(v, str) or not re.fullmatch(r"[0-9]+", v)
        for v in totais.values()
    ):
        raise DadoInvalido("codigos totais nao conferidos por classificacao")
    if (not isinstance(variaveis, Mapping) or len(variaveis) != 2
        or set(variaveis.values()) != INDICADORES
        or any(not isinstance(k, str) or not re.fullmatch(r"[0-9]+", k)
               for k in variaveis)):
        raise DadoInvalido("duas variaveis oficiais explicitas exigidas")
    return chaves


def _competencia(codigo):
    if not isinstance(codigo, str) or not re.fullmatch(r"20[0-9]{2}0[1-4]", codigo):
        raise DadoInvalido("periodo trimestral deve ser AAAA0T (ex: 202602)")
    ano, tri = int(codigo[:4]), int(codigo[-1])
    mes_fim, dia_fim = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[tri]
    return f"{ano}-T{tri}", f"{ano}-{mes_fim:02d}-{dia_fim:02d}"


def _uf(linha, campo):
    nivel, geo = str(linha.get("NC", "")), str(linha.get(campo, ""))
    if nivel == "1" and geo == "1":
        return "BR"
    if nivel == "3" and geo in UF_IBGE:
        return UF_IBGE[geo]
    raise DadoInvalido("geografia nao e BR ou UF oficial do IBGE")


def _numero(valor, indicador):
    if not isinstance(valor, str):
        raise DadoInvalido("valor SIDRA nao textual; conversao implicita proibida")
    if valor.strip() in DADO_NAO_DISPONIVEL:
        return None
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", valor):
        raise DadoInvalido("valor SIDRA nao numerico ou notacao inesperada")
    try:
        numero = Decimal(valor)
    except InvalidOperation as exc:
        raise DadoInvalido("decimal SIDRA invalido") from exc
    if not numero.is_finite() or numero < 0 or numero > 9007199254740991:
        raise DadoInvalido("valor SIDRA fora de faixa segura")
    if indicador == "ABATE_CABECAS" and numero != numero.to_integral_value():
        raise DadoInvalido("cabecas fracionarias")
    return float(numero)


def normalizar_snapshot_sidra_abate(
    bruto: bytes, *, especie: str, tabela_sidra: str, dimensoes: Mapping[str, str],
    totais: Mapping[str, str], variaveis: Mapping[str, str],
    publicacao: str, coleta: str, status_fonte: str,
    operacoes_autorizadas: set[str], max_bytes: int = 4_000_000,
    max_linhas: int = 15000,
) -> dict:
    """Ler resposta JSON salva localmente, com mapa de dimensoes verificado.

    Metadados temporais devem ter evidencia independente da propria resposta
    (SIDRA values nao garante timestamp de divulgacao retroativo).
    """
    _exigir_mapa(especie=especie, tabela=tabela_sidra,
                 dimensoes=dimensoes, totais=totais, variaveis=variaveis)
    validar_fonte(status=status_fonte, operacao="LEITURA",
                  operacoes_autorizadas=operacoes_autorizadas)
    if "ARMAZENAMENTO" not in operacoes_autorizadas:
        raise PermissionError("ARMAZENAMENTO nao autorizado")
    if (type(max_bytes) is not int or not 1 <= max_bytes <= 4_000_000
        or type(max_linhas) is not int or not 1 <= max_linhas <= 15000):
        raise DadoInvalido("limites de seguranca invalidos")
    if not isinstance(bruto, bytes) or not 0 < len(bruto) <= max_bytes:
        raise DadoInvalido("bruto JSON vazio, nao binario ou excessivo")
    pub, col = _instante(publicacao, "publicacao"), _instante(coleta, "coleta")
    if pub > col:
        raise DadoInvalido("publicacao posterior a coleta")
    try:
        payload = json.loads(bruto.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise DadoInvalido("JSON SIDRA invalido") from exc
    if not isinstance(payload, list) or not 2 <= len(payload) <= max_linhas + 1:
        raise DadoInvalido("resposta deve conter cabecalho e linhas dentro do limite")
    cabecalho = payload[0]
    if not isinstance(cabecalho, dict) or any(
        coluna not in cabecalho for coluna in
        {"NC", "MN", "V"} | set(dimensoes.values())
    ):
        raise DadoInvalido("cabecalho SIDRA incompleto")
    colunas_dimensoes = {
        k for k in cabecalho if isinstance(k, str) and re.fullmatch(r"D[1-9][0-9]*C", k)
    }
    if colunas_dimensoes != set(dimensoes.values()):
        raise DadoInvalido("classificacao nao declarada: risco de dupla contagem")
    if not all(isinstance(cabecalho[k], str) for k in colunas_dimensoes):
        raise DadoInvalido("rotulos do cabecalho nao textuais")
    registros, censurados, vistos = [], [], set()
    por_chave = defaultdict(set)
    origem_hash = sha256(bruto).hexdigest()
    for linha in payload[1:]:
        if not isinstance(linha, dict) or any(
            campo not in linha for campo in {"NC", "MN", "V"} | set(dimensoes.values())
        ):
            raise DadoInvalido("linha SIDRA incompleta")
        for classe, total in totais.items():
            if str(linha[dimensoes[classe]]) != total:
                raise DadoInvalido("categoria nao total, soma proibida")
        codigo_variavel = str(linha[dimensoes["variavel"]])
        if codigo_variavel not in variaveis:
            raise DadoInvalido("variavel SIDRA nao homologada ou percentual")
        indicador = variaveis[codigo_variavel]
        mn = linha["MN"]
        if not isinstance(mn, str) or mn.strip().casefold() != UNIDADE_FONTE[indicador]:
            raise DadoInvalido("unidade SIDRA diferente de cabecas/quilogramas")
        uf = _uf(linha, dimensoes["territorio"])
        competencia, referencia = _competencia(str(linha[dimensoes["periodo"]]))
        if pub < datetime.fromisoformat(referencia).replace(tzinfo=timezone.utc):
            raise DadoInvalido("publicacao anterior ao fim da competencia")
        identidade = (uf, competencia, indicador)
        if identidade in vistos:
            raise DadoInvalido("linha duplicada: total por inspecao ou por rebanho")
        vistos.add(identidade)
        valor = _numero(linha["V"], indicador)
        por_chave[(uf, competencia)].add(indicador if valor is not None else "CENSURADO_"+indicador)
        if valor is None:
            censurados.append({"uf": uf, "competencia": competencia, "indicador": indicador,
                               "situacao": "INDISPONIVEL_OU_SIGILOSO"})
            continue
        registros.append(ObservacaoCadeia(
            produto=especie, uf=uf, calendario="TRIMESTRE", competencia=competencia,
            indicador=indicador, valor=valor, unidade=UNIDADE_CANONICA[indicador],
            classificacao="INFORMADO", fonte_id="IBGE", referencia=referencia,
            publicacao=publicacao, coleta=coleta, origem_sha256=origem_hash,
        ))
    if not registros and not censurados:
        raise DadoInvalido("nenhuma linha de dados")
    incompletos = [
        {"uf": uf, "competencia": periodo, "situacao": "PARES_ABATE_CARCACA_INCOMPLETOS"}
        for (uf, periodo), indicadores in sorted(por_chave.items())
        if indicadores != INDICADORES
    ]
    return {"especie": especie, "tabela_sidra": tabela_sidra,
            "observacoes": sorted(registros, key=lambda o: (o.uf, o.competencia, o.indicador)),
            "linhas_indisponiveis": censurados, "pares_incompletos": incompletos,
            "origem_sha256": origem_hash, "publicacao": publicacao, "coleta": coleta,
            "classificacao": "NORMALIZACAO_OFFLINE_NAO_HOMOLOGADA",
            "coleta_real_executada": False, "previsao_homologada": False,
            "limitacao": "IDs/codigos de categorias exigem verificacao da fonte; sem prova de vintages anteriores."}



def auditar_agregados_sidra_abate(*, resultado: Mapping[str, object]) -> list[dict]:
    """Comparar BR e 27 UFs apenas quando ambos cobrem a mesma medida/periodo.

    Sem imputar UFs suprimidas, sem assumir que uma divergencia prove erro.
    Resultado nao promove serie, cotacao ou previsao.
    """
    if not isinstance(resultado, Mapping) or resultado.get("classificacao") != "NORMALIZACAO_OFFLINE_NAO_HOMOLOGADA":
        raise DadoInvalido("auditoria exige snapshot normalizado sem homologacao")
    obs = resultado.get("observacoes")
    if not isinstance(obs, list) or any(not isinstance(o, ObservacaoCadeia) for o in obs):
        raise DadoInvalido("observacoes invalidas na auditoria")
    if any(o.produto != resultado.get("especie") or o.fonte_id != "IBGE" for o in obs):
        raise DadoInvalido("fontes ou especies misturadas")
    periodos = defaultdict(dict)
    for o in obs:
        chave = (o.competencia, o.indicador)
        if o.uf in periodos[chave]:
            raise DadoInvalido("observacao duplicada na auditoria")
        periodos[chave][o.uf] = o.valor
    relatorio = []
    for (competencia, indicador), valores in sorted(periodos.items()):
        ufs = [u for u in valores if u != "BR"]
        esperado = len(UF_IBGE)
        item = {"especie": resultado["especie"], "competencia": competencia,
                "indicador": indicador, "unidade": UNIDADE_CANONICA[indicador],
                "ufs_presentes": len(ufs), "ufs_esperadas": esperado,
                "valor_brasil": valores.get("BR"), "soma_ufs": None,
                "residuo_brasil_menos_ufs": None,
                "status": "INCOMPLETO_SEM_IMPUTACAO"}
        if "BR" in valores and len(ufs) == esperado:
            soma = sum(valores[u] for u in UF_IBGE.values())
            item["soma_ufs"] = soma
            item["residuo_brasil_menos_ufs"] = valores["BR"] - soma
            item["status"] = ("CONSISTENTE" if valores["BR"] == soma
                              else "DIVERGENCIA_A_INVESTIGAR")
        relatorio.append(item)
    return relatorio
