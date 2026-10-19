"""Gate local de consistência para agregados de capacidade SICARM/CONAB.

Não consulta fonte, não homologa direitos, não publica nem apresenta estoques.
Rejeita perda de linhas, soma inconsistente e eventual vazamento de registros.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from math import isfinite


class ErroQualidadeArmazens(ValueError):
    pass


_TOP = frozenset({
    "dataset_id", "fonte_id", "sha256_original", "bytes", "linhas_validas",
    "municipios", "agregados", "capacidade_total_t", "coleta",
    "referencia", "publicacao", "status", "alerta",
})
_AGREGADO = frozenset({
    "uf", "municipio_normalizado", "codigo_ibge", "armazens_distintos",
    "capacidade_estatica_t", "unidade", "natureza",
})
_UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


def _decimal(valor, campo: str, *, zero=False) -> Decimal:
    if type(valor) not in (float, int, Decimal):
        raise ErroQualidadeArmazens(f"{campo}: número obrigatório")
    if isinstance(valor, float) and not isfinite(valor):
        raise ErroQualidadeArmazens(f"{campo}: valor não-finito")
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as exc:
        raise ErroQualidadeArmazens(f"{campo}: decimal inválido") from exc
    if not numero.is_finite() or (numero < 0 if zero else numero <= 0):
        raise ErroQualidadeArmazens(f"{campo}: valor inválido")
    return numero


def verificar_consistencia_armazens(
    resultado: dict, *, exigir_ibge: bool = False,
    total_referencia_informado_t: int | float | Decimal | None = None,
    tolerancia_t: int | float | Decimal = 0.001,
) -> dict:
    """Audita o agregado; nunca concede autorização de coleta ou publicação.

    O total de referência, quando informado, é fornecido pelo operador e NÃO
    se converte automaticamente em conciliação com a publicação oficial.
    """
    if not isinstance(resultado, dict) or set(resultado) != _TOP:
        raise ErroQualidadeArmazens("contrato do resumo incompleto ou com campos extras")
    if resultado["dataset_id"] != "CONAB_ARMAZENS_CAPACIDADE" or resultado["fonte_id"] != "CONAB":
        raise ErroQualidadeArmazens("dataset/fonte não é SICARM")
    if resultado["status"] != "AGREGACAO_LOCAL_SEM_HOMOLOGACAO_DE_LAYOUT_DIREITOS_OU_PUBLICACAO":
        raise ErroQualidadeArmazens("estado de evidência indevido")
    if not isinstance(resultado["sha256_original"], str) or not re.fullmatch(r"[0-9a-f]{64}",resultado["sha256_original"]):
        raise ErroQualidadeArmazens("SHA-256 original inválido")
    if type(resultado["bytes"]) is not int or not 0 < resultado["bytes"] <= 120_000_000:
        raise ErroQualidadeArmazens("bytes fora do limite SICARM")
    if not isinstance(resultado["coleta"], str) or "T" not in resultado["coleta"]:
        raise ErroQualidadeArmazens("coleta ausente")
    if not isinstance(exigir_ibge, bool):
        raise ErroQualidadeArmazens("exigir_ibge deve ser bool")
    tol = _decimal(tolerancia_t, "tolerancia_t", zero=True)
    if tol > 1:
        raise ErroQualidadeArmazens("tolerância agregada máxima é 1 tonelada")
    agg = resultado["agregados"]
    if not isinstance(agg, list) or not agg or len(agg) > 6000:
        raise ErroQualidadeArmazens("municípios agregados ausentes ou excedidos")
    linhas = resultado["linhas_validas"]
    if type(linhas) is not int or not 1 <= linhas <= 400_000:
        raise ErroQualidadeArmazens("quantidade de registros inválida")
    if type(resultado["municipios"]) is not int or resultado["municipios"] != len(agg):
        raise ErroQualidadeArmazens("contagem de municípios divergente")
    visto_nome = set()
    visto_codigo = set()
    soma = Decimal(0)
    quant_armazens = 0
    sem_ibge = 0
    for item in agg:
        if not isinstance(item, dict) or set(item) != _AGREGADO:
            raise ErroQualidadeArmazens("linha do agregado contém campo ausente ou não permitido")
        uf, cidade, codigo = item["uf"],item["municipio_normalizado"],item["codigo_ibge"]
        if uf not in _UFS or not isinstance(cidade, str) or not cidade.strip() or len(cidade)>130:
            raise ErroQualidadeArmazens("UF/município inválidos")
        if cidade != " ".join(cidade.upper().split()):
            raise ErroQualidadeArmazens("município não normalizado")
        if (uf, cidade) in visto_nome:
            raise ErroQualidadeArmazens("município duplicado na mesma UF")
        visto_nome.add((uf,cidade))
        if codigo is None:
            sem_ibge += 1
            if exigir_ibge:
                raise ErroQualidadeArmazens("código IBGE não conciliado")
        else:
            if not isinstance(codigo,str) or not re.fullmatch(r"\d{7}",codigo) or codigo in visto_codigo:
                raise ErroQualidadeArmazens("código IBGE inválido/duplicado")
            visto_codigo.add(codigo)
        if type(item["armazens_distintos"]) is not int or item["armazens_distintos"] < 1:
            raise ErroQualidadeArmazens("quantidade de armazéns inválida")
        if item["unidade"] != "t" or item["natureza"] != "CAPACIDADE_CADASTRADA_NAO_ESTOQUE":
            raise ErroQualidadeArmazens("unidade/natureza incorreta")
        soma += _decimal(item["capacidade_estatica_t"],"capacidade_estatica_t")
        quant_armazens += item["armazens_distintos"]
    if quant_armazens != linhas:
        raise ErroQualidadeArmazens("contagem de armazéns diverge da quantidade de linhas")
    reportado = _decimal(resultado["capacidade_total_t"],"capacidade_total_t")
    if abs(soma - reportado) > tol:
        raise ErroQualidadeArmazens("soma municipal diverge do total agregado")
    referencia_conferida = False
    if total_referencia_informado_t is not None:
        ref = _decimal(total_referencia_informado_t,"total_referencia_informado_t")
        if abs(ref-reportado) > tol:
            raise ErroQualidadeArmazens("total de referência informado diverge do agregado")
        referencia_conferida = True
    return {
        "dataset_id": "CONAB_ARMAZENS_CAPACIDADE",
        "estado": "CONSISTENCIA_INTERNA_OK_SEM_HOMOLOGACAO",
        "municipios":len(agg),"armazens":quant_armazens,
        "codigo_ibge_sem_resolucao":sem_ibge,
        "total_t":float(reportado),
        "total_de_referencia_informado_confere":referencia_conferida,
        "referencia_oficial_homologada":False,
        "liberado_para_publicacao":False,
        "pendencias":["DIREITOS_POR_OPERACAO","CONFERENCIA_ARQUIVO_COMPLETO",
                     "RECONCILIACAO_COM_FONTE_OFICIAL","PUBLICACAO_E_VIGENCIA",
                     "BACKUP_DURAVEL_E_RESTORE"],
    }
