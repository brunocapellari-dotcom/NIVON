"""Cenarios economicos pecuarios por especie, SEM previsao homologada.

Entrada de dados declarados, sem rede. Nenhum parametro biologico e inferido.
Arroba bovina = 15 kg de carcaca; aves/suinos comercializados em kg vivo.
"""
from __future__ import annotations

from math import isfinite

from .motores import DadoInvalido


def _numero(valor, campo, *, zero=False):
    if type(valor) not in (int, float) or not isfinite(valor):
        raise DadoInvalido(f"{campo}: numero finito obrigatorio")
    if valor < 0 or (valor == 0 and not zero):
        raise DadoInvalido(f"{campo}: valor fora do dominio")
    return float(valor)


def _fracao(valor, campo, *, admite_um=True):
    n = _numero(valor, campo, zero=True)
    if n > 1 or (n == 1 and not admite_um):
        raise DadoInvalido(f"{campo}: fracao fora de [0,1]")
    return n


def _prova(valor):
    if not isinstance(valor, str) or not valor.strip():
        raise DadoInvalido("origem dos parametros obrigatoria")
    return valor


def custo_racao_kg(*, fracao_milho, fracao_farelo_soja, fracao_outros,
                   preco_milho_rs_t, preco_farelo_soja_rs_t,
                   preco_outros_rs_t, fonte_parametros):
    """Formula declarada: fracao de massa * preco R$/t; custo retorna R$/kg."""
    frac = [_fracao(fracao_milho, "fracao_milho"),
            _fracao(fracao_farelo_soja, "fracao_farelo_soja"),
            _fracao(fracao_outros, "fracao_outros")]
    if abs(sum(frac) - 1.0) > 1e-9:
        raise DadoInvalido("formulacao nao fecha 100%")
    precos = [_numero(preco_milho_rs_t, "preco_milho_rs_t", zero=True),
              _numero(preco_farelo_soja_rs_t, "preco_farelo_soja_rs_t", zero=True),
              _numero(preco_outros_rs_t, "preco_outros_rs_t", zero=True)]
    _prova(fonte_parametros)
    return sum(a * b for a, b in zip(frac, precos)) / 1000.0


def simular_ciclo_bovino(*, peso_vivo_saida_kg, rendimento_carcaca,
                         preco_boi_rs_arroba_carcaca, preco_reposicao_rs_cabeca,
                         dias_engorda, consumo_racao_kg_dia,
                         custo_racao_rs_kg, outros_custos_rs_cabeca,
                         fonte_parametros):
    """Recria/engorda: resultado por cabeca terminada, sem mortalidade inferida.

    Preco por arroba da CARCACA, nao por arroba do peso vivo. Custos de pasto,
    juros, impostos e perdas devem constar em outros_custos se aplicaveis.
    """
    kg = _numero(peso_vivo_saida_kg, "peso_vivo_saida_kg")
    rendimento = _fracao(rendimento_carcaca, "rendimento_carcaca")
    if rendimento == 0:
        raise DadoInvalido("rendimento nulo")
    preco = _numero(preco_boi_rs_arroba_carcaca, "preco_boi_rs_arroba_carcaca")
    reposicao = _numero(preco_reposicao_rs_cabeca, "preco_reposicao_rs_cabeca", zero=True)
    dias = _numero(dias_engorda, "dias_engorda")
    if not dias.is_integer():
        raise DadoInvalido("dias_engorda deve ser inteiro")
    consumo = _numero(consumo_racao_kg_dia, "consumo_racao_kg_dia", zero=True)
    custo_racao = _numero(custo_racao_rs_kg, "custo_racao_rs_kg", zero=True)
    outros = _numero(outros_custos_rs_cabeca, "outros_custos_rs_cabeca", zero=True)
    origem = _prova(fonte_parametros)
    arrobas = kg * rendimento / 15.0
    receita = arrobas * preco
    custo = reposicao + dias * consumo * custo_racao + outros
    return {"cadeia": "BOVINO", "arrobas_carcaca_cabeca": arrobas,
            "receita_bruta_rs_cabeca": receita, "custo_declarado_rs_cabeca": custo,
            "margem_declarada_rs_cabeca": receita - custo,
            "fonte_parametros": origem, "homologado": False,
            "classificacao": "SIMULACAO_ECONOMICA_BOVINA",
            "limitacao": "Nao representa lucro observado, ciclo completo ou precificacao de bezerro."}


def simular_lote_frango(*, aves_alojadas, mortalidade_fracao,
                       peso_vivo_saida_kg_ave, preco_frango_vivo_rs_kg,
                       racao_kg_por_ave_alojada, custo_racao_rs_kg,
                       custo_pintinho_rs_ave_alojada, outros_custos_rs_ave_alojada,
                       fonte_parametros):
    """Ciclo de frango de corte por alojamento; ração inclui aves que morreram."""
    if type(aves_alojadas) is not int or aves_alojadas <= 0:
        raise DadoInvalido("aves_alojadas: inteiro positivo")
    mortalidade = _fracao(mortalidade_fracao, "mortalidade_fracao", admite_um=False)
    sobreviventes = aves_alojadas * (1 - mortalidade)
    peso = _numero(peso_vivo_saida_kg_ave, "peso_vivo_saida_kg_ave")
    preco = _numero(preco_frango_vivo_rs_kg, "preco_frango_vivo_rs_kg")
    consumo = _numero(racao_kg_por_ave_alojada, "racao_kg_por_ave_alojada")
    racao = _numero(custo_racao_rs_kg, "custo_racao_rs_kg", zero=True)
    pintinho = _numero(custo_pintinho_rs_ave_alojada, "custo_pintinho_rs_ave_alojada", zero=True)
    outros = _numero(outros_custos_rs_ave_alojada, "outros_custos_rs_ave_alojada", zero=True)
    origem = _prova(fonte_parametros)
    receita = sobreviventes * peso * preco
    custo = aves_alojadas * (consumo * racao + pintinho + outros)
    return {"cadeia": "FRANGO", "sobreviventes_esperados_cabecas": sobreviventes,
            "receita_bruta_rs_lote": receita, "custo_declarado_rs_lote": custo,
            "margem_declarada_rs_lote": receita - custo,
            "fonte_parametros": origem, "homologado": False,
            "classificacao": "SIMULACAO_ECONOMICA_FRANGO",
            "limitacao": "Sobreviventes esperados podem ser fracionarios; sem producao frigorifica ou preco carcaca."}


def simular_lote_suino(*, suinos_entrada, mortalidade_fracao,
                      peso_vivo_saida_kg_suino, preco_suino_vivo_rs_kg,
                      racao_kg_por_suino_entrada, custo_racao_rs_kg,
                      aquisicao_rs_suino_entrada, outros_custos_rs_suino_entrada,
                      fonte_parametros):
    """Ciclo de terminacao suina; nao simula gestacao, lactacao ou creche."""
    if type(suinos_entrada) is not int or suinos_entrada <= 0:
        raise DadoInvalido("suinos_entrada: inteiro positivo")
    mortalidade = _fracao(mortalidade_fracao, "mortalidade_fracao", admite_um=False)
    sobreviventes = suinos_entrada * (1 - mortalidade)
    peso = _numero(peso_vivo_saida_kg_suino, "peso_vivo_saida_kg_suino")
    preco = _numero(preco_suino_vivo_rs_kg, "preco_suino_vivo_rs_kg")
    consumo = _numero(racao_kg_por_suino_entrada, "racao_kg_por_suino_entrada")
    racao = _numero(custo_racao_rs_kg, "custo_racao_rs_kg", zero=True)
    compra = _numero(aquisicao_rs_suino_entrada, "aquisicao_rs_suino_entrada", zero=True)
    outros = _numero(outros_custos_rs_suino_entrada, "outros_custos_rs_suino_entrada", zero=True)
    origem = _prova(fonte_parametros)
    receita = sobreviventes * peso * preco
    custo = suinos_entrada * (consumo * racao + compra + outros)
    return {"cadeia": "SUINO", "sobreviventes_esperados_cabecas": sobreviventes,
            "receita_bruta_rs_lote": receita, "custo_declarado_rs_lote": custo,
            "margem_declarada_rs_lote": receita - custo,
            "fonte_parametros": origem, "homologado": False,
            "classificacao": "SIMULACAO_ECONOMICA_SUINO_TERMINACAO",
            "limitacao": "Terminacao somente, sem multiplicacao, creche, frigorifico ou cotacao de carcaca."}
