"""Coletor PTAX executável para quarentena, com gates reais e lote atômico.

Um GET HTTPS por plano, sem redirecionamentos nem retries automáticos.
Rede NEGADA por padrão. Requer ativação no catálogo central + direitos
COLETA/ARMAZENAMENTO; nunca se baseia em valor booleano recebido pelo
usuário para declarar fonte homologada. Respostas sem boletins são
preservadas, não viram taxas zero e nunca alimentam o briefing.

Fluxo: plano oficial -> bytes HTTP/TLS -> metadados -> validação OData
-> persistência em quarentena. Captura e validação de todas as janelas
precedem a transação: falha na segunda janela não grava a primeira.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import sqlite3
from typing import Callable, Mapping

from .captura_ptax_http import (
    _autorizado, _cabecalhos, _momento_relogio, _requisitar_https,
)
from .ptax_odata_bruta_mercados import MAX_BYTES, _consulta
from .ptax_plano import planejar_consultas_ptax
from .ptax_quarentena_coleta import (
    validar_amostra_ptax, receber_amostra_ptax,
)
from .transacoes_sqlite import savepoint_atomico


class ErroColetaQuarentenaPTAX(ValueError):
    """Contrato de captura, direitos, resposta ou lote incorreto."""


MAX_PLANOS = 8
MAX_TOTAL_RAW = 8_000_000


def executar_coleta_ptax_quarentena(
    db: sqlite3.Connection, *, planos: list[dict], catalogo: Mapping,
    permitir_rede: bool = False,
    autorizacoes: frozenset[str] = frozenset(),
    evidencia_direitos: str | None = None,
    transporte: Callable[[str], tuple[int, Mapping, bytes]] | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> dict:
    """Processa até oito janelas; transporte injetado é SINTÉTICO.

    Capturar por HTTPS em máquina com rede exige o catálogo já aprovado,
    mas a própria coleta, ainda que real, fica em QUARENTENA; autenticação
    externa, licença derivada e horário de publicação não são provados.
    """
    if not isinstance(db, sqlite3.Connection) or (
        not isinstance(catalogo, Mapping) or
        type(planos) is not list or not 1 <= len(planos) <= MAX_PLANOS
    ):
        raise ErroColetaQuarentenaPTAX("banco/catálogo/lote inválido")
    if type(permitir_rede) is not bool or (
        transporte is not None and (not callable(transporte) or permitir_rede)
    ):
        raise ErroColetaQuarentenaPTAX("transporte real e sintético incompatíveis")
    if transporte is None:
        if not permitir_rede:
            raise PermissionError("rede desativada por padrão")
        _autorizado(catalogo, autorizacoes, evidencia_direitos)
        obter = _requisitar_https
        metodo = "HTTPS_BCB_QUARENTENA_NAO_HOMOLOGADA"
    else:
        if autorizacoes or evidencia_direitos is not None:
            raise ErroColetaQuarentenaPTAX("mock não pode alegar direitos reais")
        obter = transporte
        metodo = "TRANSPORTE_INJETADO_SINTETICO"
    identidades = set()
    for plano in planos:
        if not isinstance(plano, dict):
            raise ErroColetaQuarentenaPTAX("plano inválido")
        try:
            ini, fim = _consulta(plano["url"], plano["moeda"])
            esperado = planejar_consultas_ptax(
                moeda=plano["moeda"], inicio=ini.isoformat(),
                fim=fim.isoformat(), dias_janela=(fim-ini).days+1,
            )
        except (TypeError, KeyError, ValueError) as exc:
            raise ErroColetaQuarentenaPTAX("URL/plano inválido") from exc
        if len(esperado) != 1 or esperado[0] != plano:
            raise ErroColetaQuarentenaPTAX("plano divergente do canônico")
        if plano["url"] in identidades:
            raise ErroColetaQuarentenaPTAX("janela PTAX repetida")
        identidades.add(plano["url"])

    # Aquisição completa antes de abrir savepoint: nunca travar o banco
    # aguardando I/O externo, nem gravar metade do lote por erro de rede.
    verificadas = []
    total_bytes = 0
    for plano in planos:
        status, headers, raw = obter(plano["url"])
        if type(status) is not int or status != 200:
            raise ErroColetaQuarentenaPTAX("HTTP 200 obrigatório")
        canon_headers = _cabecalhos(headers)
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
            raise ErroColetaQuarentenaPTAX("raw ausente/excessivo")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_RAW:
            raise ErroColetaQuarentenaPTAX("lote acima do limite total")
        coleta = _momento_relogio(relogio or
                                  (lambda: datetime.now(timezone.utc)))
        manifest = {
            "fonte_declarada": "BCB_PTAX",
            "moeda": plano["moeda"],
            "consulta_url": plano["url"],
            "coletado_em": coleta,
            "status_http": status,
            "cabecalhos_http": canon_headers,
            "raw_sha256": sha256(raw).hexdigest(),
        }
        comprovacao = validar_amostra_ptax(raw, manifest)
        verificadas.append((raw, manifest, comprovacao))
    linhas = []
    with savepoint_atomico(db):
        for raw, manifest, validado in verificadas:
            salvo = receber_amostra_ptax(db, raw=raw, manifesto=manifest)
            if salvo["evento_sha256"] != validado["evento_sha256"]:
                raise ErroColetaQuarentenaPTAX(
                    "evento mudou entre verificação e persistência"
                )
            linhas.append({
                "moeda": manifest["moeda"],
                "inicio": _consulta(
                    manifest["consulta_url"], manifest["moeda"]
                )[0].isoformat(),
                "fim": _consulta(
                    manifest["consulta_url"], manifest["moeda"]
                )[1].isoformat(),
                "raw_sha256": salvo["raw_sha256"],
                "evento_sha256": salvo["evento_sha256"],
                "boletins": salvo["boletins"],
                "resposta_vazia": salvo["vazio"],
                "nova_captura": salvo["nova_versao"],
                "coletado_em": validado["manifesto_canonico"]["coletado_em"],
            })
    return {
        "status": "CAPTURAS_PTAX_QUARENTENA_SEM_PROMOCAO",
        "metodo": metodo,
        "tipo": "SINTETICO" if transporte is not None else
                "CAPTURA_HTTPS_NAO_HOMOLOGADA",
        "consultas": len(linhas), "bytes_recebidos": total_bytes,
        "boletins": sum(x["boletins"] for x in linhas),
        "respostas_vazias": sum(x["resposta_vazia"] for x in linhas),
        "linhas": linhas,
        "fonte_http_certificada_independentemente": False,
        "licenca_redistribuicao_homologada": False,
        "horario_publicacao_independente": False,
        "aprovado_para_ledger_operacional": False,
        "publicavel": False,
    }
