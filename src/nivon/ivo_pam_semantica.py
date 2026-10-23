"""IVO: contrato explícito da Tabela SIDRA/PAM 1612 para grandezas e unidades.

Os códigos aqui são whitelist de mapeamentos verificados por documentação
da PAM e exemplos SIDRA. Não significa confirmação de publicação, direito
de usar dados ou equivalência com safras CONAB. Para adicionar variáveis,
revisar metadados oficiais e criar testes antes de alterar este dicionário.
"""
from __future__ import annotations

from dataclasses import dataclass


class ErroSemanticaPAM(ValueError):
    pass


@dataclass(frozen=True)
class GrandezaPAM:
    codigo: str
    nome: str
    unidade: str
    familia: str


# Quantidade produzida ≠ área plantada. Não reutilizar pesos/erro/unidades.
GRANDEZAS_1612 = {
    "109": GrandezaPAM("109", "AREA_PLANTADA", "Hectares", "AREA"),
    "214": GrandezaPAM("214", "QUANTIDADE_PRODUZIDA", "Toneladas", "MASSA"),
}
# Apenas identificadores comprovados, SEM apelidar produtos desconhecidos.
PRODUTOS_VERIFICADOS = {
    "2692": "ARROZ_EM_CASCA",
    "2711": "MILHO_EM_GRAO",
    "2713": "SOJA_EM_GRAO",
    "2714": "SORGO_EM_GRAO",
}


def conferir_semantica_pam_1612(
    *, variavel: str, categoria_c81: str, unidade: str,
    indicador_esperado: str | None = None,
) -> dict:
    if not isinstance(variavel,str) or variavel not in GRANDEZAS_1612:
        raise ErroSemanticaPAM("variável PAM não homologada para grandeza/unidade")
    if not isinstance(categoria_c81,str) or categoria_c81 not in PRODUTOS_VERIFICADOS:
        raise ErroSemanticaPAM("produto PAM sem mapeamento C81 verificado nesta versão")
    item=GRANDEZAS_1612[variavel]
    if unidade != item.unidade:
        raise ErroSemanticaPAM(
            f"unidade da variável {variavel} incompatível: esperada {item.unidade}")
    if indicador_esperado is not None and indicador_esperado != item.nome:
        raise ErroSemanticaPAM("indicador declarado divergente do SIDRA")
    return {
        "tabela":"1612", "variavel":item.codigo,
        "indicador":item.nome, "familia":item.familia,
        "unidade":item.unidade, "categoria_c81":categoria_c81,
        "produto":PRODUTOS_VERIFICADOS[categoria_c81],
        "mapa_unidades_aprovado_localmente":True,
        "rotulo_real_certificado":False,
        "tabela_safra_conab":False,
        "direitos_verificados":False,
    }
