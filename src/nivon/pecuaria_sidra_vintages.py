"""Vintages trimestrais SIDRA sem look-ahead e sem fabricar historico.

Recebe apenas respostas ja normalizadas OFFLINE de pecuaria_sidra_abate.
Backfill coletado hoje NUNCA fica disponivel em um corte no passado.
Sem escrita, rede, cron, promocao de modelo ou direitos presumidos.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re

from .cadeias_adicionais import ObservacaoCadeia, TABELAS_SIDRA, _instante
from .motores import DadoInvalido

_STATUS = "NORMALIZACAO_OFFLINE_NAO_HOMOLOGADA"
_CENSURA = "INDISPONIVEL_OU_SIGILOSO"
_INDICADORES = frozenset({"ABATE_CABECAS", "PESO_CARCACAS_KG"})
_UF = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO BR".split())


def _chave(uf, competencia, indicador):
    if not isinstance(uf, str) or uf not in _UF:
        raise DadoInvalido("UF invalida no registro de vintage")
    if not isinstance(competencia, str) or not re.fullmatch(r"(?:19|20)\d{2}-T[1-4]", competencia):
        raise DadoInvalido("competencia trimestral invalida")
    if indicador not in _INDICADORES:
        raise DadoInvalido("indicador de abate desconhecido")
    return uf, competencia, indicador


def _ler(snapshot, especie, tabela):
    if not isinstance(snapshot, Mapping) or snapshot.get("classificacao") != _STATUS:
        raise DadoInvalido("vintage nao normalizado ou artificialmente homologado")
    if snapshot.get("especie") != especie or snapshot.get("tabela_sidra") != tabela:
        raise DadoInvalido("serie mistura especies ou tabelas")
    if not isinstance(snapshot.get("origem_sha256"), str) or not re.fullmatch(
            r"[a-f0-9]{64}", snapshot["origem_sha256"]):
        raise DadoInvalido("snapshot sem hash de origem")
    publicacao, coleta = snapshot.get("publicacao"), snapshot.get("coleta")
    pub, col = _instante(publicacao, "publicacao"), _instante(coleta, "coleta")
    if pub > col:
        raise DadoInvalido("publicacao posterior a coleta")
    observacoes, censuras = snapshot.get("observacoes"), snapshot.get("linhas_indisponiveis")
    if not isinstance(observacoes, list) or not isinstance(censuras, list):
        raise DadoInvalido("listas de observacao e censura ausentes")
    if not observacoes and not censuras:
        raise DadoInvalido("snapshot vazio")
    if len(observacoes)+len(censuras) > 15000:
        raise DadoInvalido("limite de linhas do parser ultrapassado")
    entradas = {}
    for obs in observacoes:
        if not isinstance(obs, ObservacaoCadeia) or (
            obs.produto != especie or obs.fonte_id != "IBGE"
            or obs.calendario != "TRIMESTRE"
            or obs.origem_sha256 != snapshot["origem_sha256"]
            or obs.publicacao != publicacao or obs.coleta != coleta
            or obs.classificacao != "INFORMADO"
        ):
            raise DadoInvalido("observacao nao pertence ao snapshot")
        key = _chave(obs.uf, obs.competencia, obs.indicador)
        if key in entradas:
            raise DadoInvalido("registro duplicado no vintage")
        entradas[key] = ("VALOR", obs)
    for row in censuras:
        if not isinstance(row, Mapping) or set(row) != {
            "uf", "competencia", "indicador", "situacao"
        } or row.get("situacao") != _CENSURA:
            raise DadoInvalido("censura sem proveniencia de parser")
        key = _chave(row["uf"], row["competencia"], row["indicador"])
        if key in entradas:
            raise DadoInvalido("registro e censura simultaneos")
        entradas[key] = ("CENSURADO", None)
    return pub, col, entradas


def historico_sidra_asof(
    *, snapshots, especie: str, tabela_sidra: str, corte_asof: str,
    max_snapshots: int = 300, max_observacoes: int = 100_000,
) -> dict:
    """Selecao bitemporal de abates, revisoes e tombstones de censura.

    Datas publicacao/coleta sao declaradas pelo chamador e NAO autenticadas.
    Ordena edicoes por publicacao e depois coleta, nunca por competencia.
    Rejeita alteracao do mesmo registro com igual data de publicacao.
    """
    if TABELAS_SIDRA.get(especie) != tabela_sidra:
        raise DadoInvalido("especie/tabela SIDRA incoerentes")
    if (type(max_snapshots) is not int or not 1 <= max_snapshots <= 300
        or type(max_observacoes) is not int or not 1 <= max_observacoes <= 100_000):
        raise DadoInvalido("limites de snapshots invalidos")
    if not isinstance(snapshots, (tuple, list)) or len(snapshots) > max_snapshots:
        raise DadoInvalido("snapshots ausentes ou acima do limite")
    corte = _instante(corte_asof, "corte_asof")
    eventos, total = [], 0
    vistos_snapshots = set()
    for s in snapshots:
        pub, col, entradas = _ler(s, especie, tabela_sidra)
        total += len(entradas)
        if total > max_observacoes:
            raise DadoInvalido("volume total de observacoes excedido")
        # Bloqueia reenvio do mesmo bruto/publicacao/coleta duas vezes.
        snapshot_id = (pub, col, s["origem_sha256"])
        if snapshot_id in vistos_snapshots:
            raise DadoInvalido("snapshot duplicado")
        vistos_snapshots.add(snapshot_id)
        if pub <= corte and col <= corte:
            for chave, entry in entradas.items():
                eventos.append((chave, pub, col, s["origem_sha256"], entry))
    eventos.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    atuais, revisoes, anteriores = {}, [], {}
    for chave, pub, col, sha, entry in eventos:
        estado, obs = entry
        antigo = anteriores.get(chave)
        if antigo is not None and antigo[0] == pub:
            if antigo[2][0] != estado or (estado == "VALOR" and antigo[2][1].valor != obs.valor):
                raise DadoInvalido("mutacao de valor/censura sem nova publicacao")
            # Replicas de mesma publicacao, novo download: valor identico.
        elif antigo is not None:
            anterior_estado, anterior_obs = antigo[2]
            if estado != anterior_estado or (
                    estado == "VALOR" and obs.valor != anterior_obs.valor):
                revisoes.append({
                    "uf": chave[0], "competencia": chave[1], "indicador": chave[2],
                    "de_status": anterior_estado, "para_status": estado,
                    "valor_anterior": anterior_obs.valor if anterior_obs else None,
                    "valor_atual": obs.valor if obs else None,
                    "publicacao_anterior": antigo[0].isoformat(),
                    "publicacao_nova": pub.isoformat(),
                    "sha256_anterior": antigo[3], "sha256_novo": sha,
                })
        # Nao rebaixa snapshot novo para uma copia antiga coletada tardiamente.
        if antigo is None or (pub, col) >= (antigo[0], antigo[1]):
            anteriores[chave] = (pub, col, entry, sha)
            atuais[chave] = entry
    registros = [estado[1] for _, estado in sorted(atuais.items()) if estado[0] == "VALOR"]
    censurados = [
        {"uf": k[0], "competencia": k[1], "indicador": k[2], "situacao": _CENSURA}
        for k, estado in sorted(atuais.items()) if estado[0] == "CENSURADO"
    ]
    return {
        "especie": especie, "tabela_sidra": tabela_sidra,
        "corte_asof": corte.isoformat(),
        "observacoes": registros, "censuras_vigentes": censurados,
        "revisoes": revisoes, "snapshots_conhecidos_no_corte":
            len({(pub, col, sha) for _, pub, col, sha, _ in eventos}),
        "classificacao": "HISTORICO_OFFLINE_VINTAGES_NAO_HOMOLOGADO",
        "metadados_publicacao_verificados": False,
        "amostra_real_homologada": False,
        "previsao_homologada": False,
    }
