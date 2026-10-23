"""Auditoria de edicoes da quarentena SIDRA por escopo inteiro (BR vs UFs).

Snapshot de UFs e substituicao INTEGRAL do seu recorte territorial. Uma UF
omitida na revisao seguinte NAO carrega o valor da revisao antiga. A omissao
gera status AUSENTE_NO_EXTRATO e nunca 0/censura artificial.
"""
from __future__ import annotations

from collections.abc import Mapping

from .cadeias_adicionais import TABELAS_SIDRA, _instante
from .motores import DadoInvalido


def _estado(snapshot):
    if not isinstance(snapshot, Mapping) or snapshot.get(
            "classificacao") != "NORMALIZACAO_OFFLINE_NAO_HOMOLOGADA":
        raise DadoInvalido("snapshot nao normalizado")
    estado = {}
    for obs in snapshot.get("observacoes", []):
        chave = (obs.uf, obs.competencia, obs.indicador)
        if chave in estado:
            raise DadoInvalido("duplicacao em snapshot numerico")
        estado[chave] = ("VALOR", obs.valor)
    for censura in snapshot.get("linhas_indisponiveis", []):
        chave = (censura["uf"], censura["competencia"], censura["indicador"])
        if chave in estado:
            raise DadoInvalido("duplicacao censura/valor em snapshot")
        estado[chave] = ("CENSURADO", None)
    if not estado:
        raise DadoInvalido("edicao vazia")
    return estado


def auditar_edicoes_quarentena(*, capturas, especie, tabela_sidra):
    """Recebe as edicoes conhecidas no corte; retorna edicoes vigentes e diffs.

    Capturas: lista de mapas com id, periodo, territorio, primeira_coleta_em,
    sha256_bruto e snapshot. A comparacao esta restrita ao mesmo recorte e
    indicador: NAO subtrai Brasil da soma das UFs.
    """
    if TABELAS_SIDRA.get(especie) != tabela_sidra:
        raise DadoInvalido("especie/tabela incompativeis")
    if not isinstance(capturas, list) or len(capturas) > 300:
        raise DadoInvalido("quantidade de capturas invalida")
    anteriores = {}
    vigentes = {}
    diferencas = []
    for cap in sorted(capturas, key=lambda c: (
            _instante(c["primeira_coleta_em"], "primeira_coleta_em"),
            c["id"])):
        if (cap.get("territorio") not in ("BR", "UFS")
            or cap.get("snapshot", {}).get("especie") != especie
            or cap["snapshot"].get("tabela_sidra") != tabela_sidra):
            raise DadoInvalido("edicao sem identidade territorial/especie")
        chave_escopo = (cap["periodo"], cap["territorio"])
        atual = _estado(cap["snapshot"])
        for uf, periodo, indicador in atual:
            if periodo.replace("-T", "0") != cap["periodo"]:
                raise DadoInvalido("competencia da edicao contradiz escopo")
            if ((cap["territorio"] == "BR") != (uf == "BR")):
                raise DadoInvalido("escopo BR/UF misturado no arquivo")
        anterior = anteriores.get(chave_escopo)
        if anterior is not None:
            state_antigo, origem_antiga = anterior
            if origem_antiga["primeira_coleta_em"] == cap["primeira_coleta_em"] and (
                    state_antigo != atual):
                raise DadoInvalido("edicoes diferentes com mesma primeira coleta")
            for chave in sorted(set(state_antigo) | set(atual)):
                velho = state_antigo.get(chave, ("AUSENTE_NO_EXTRATO", None))
                novo = atual.get(chave, ("AUSENTE_NO_EXTRATO", None))
                if velho == novo:
                    continue
                # Relatar todo movimento, inclusive a linha que sumiu de
                # um extrato, em vez de perpetuar valor antigo como vigente.
                diferencas.append({
                    "uf": chave[0], "competencia": chave[1], "indicador": chave[2],
                    "de_status": velho[0], "para_status": novo[0],
                    "valor_anterior": velho[1], "valor_atual": novo[1],
                    "id_anterior": origem_antiga["id"], "id_novo": cap["id"],
                    "sha256_anterior": origem_antiga["sha256_bruto"],
                    "sha256_novo": cap["sha256_bruto"],
                    "primeira_coleta_anterior": origem_antiga["primeira_coleta_em"],
                    "primeira_coleta_nova": cap["primeira_coleta_em"],
                    "data_publicacao_ibge_verificada": False,
                })
        anteriores[chave_escopo] = (atual, cap)
        vigentes[chave_escopo] = cap
    return {
        "edicoes_vigentes": [vigentes[k] for k in sorted(vigentes)],
        "alteracoes_observadas": diferencas,
        "total_alteracoes": len(diferencas),
        "estados_possiveis": ["VALOR", "CENSURADO", "AUSENTE_NO_EXTRATO"],
        "status": "DIFERENCAS_POR_CAPTURA_NAO_HOMOLOGADAS",
        "publicacao_ibge_verificada": False,
        "soma_territorial_autorizada": False,
    }
