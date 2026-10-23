"""Recuperação conservadora de emissão de frete após commit e antes de recibo.

Usa um checkpoint EXTERNO da cabeça/quantidade anterior, confirma exatamente
o trio de previsões shadow e recalcula o baseline somente com dados que já
existiam em sua emissão original. Não escreve/ressuscita previsões no SQLite.
Não é âncora de tempo independente, WORM ou comprovação de fonte real.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from typing import Mapping

from .fretes_baseline_shadow import preparar_intencoes_baseline_frete
from .fretes_ciclo_shadow import _ofertas_rota
from .fretes_ledger_persistente import verificar_ledger_frete, GENESIS
from .fretes_ofertas_store import verificar_store_ofertas_frete
from .fretes_previsoes_arquivadas import _hora
from .fretes_recibos_ancora import (
    criar_recibo_local_frete, verificar_recibo_local_frete,
    salvar_recibo_em_diretorio_local, ErroReciboFrete,
)


class ErroRecuperacaoFrete(ValueError):
    """Checkpoint, histórico PIT ou lote pós-commit não reconciliado."""


_ECON = frozenset({
    "origem_ibge", "destino_ibge", "descarga_entity_id", "produto",
    "equipamento", "regime", "pedagio",
})


def _validar_configuracao(*, condicoes, horizontes_dias, quantidade_anterior,
                          instante_recuperacao, chave_previsao, chave_recibo):
    if (not isinstance(condicoes, dict) or set(condicoes) != _ECON
            or any(not isinstance(v, str) or not v for v in condicoes.values())):
        raise ErroRecuperacaoFrete("identidade econômica inválida")
    if (not isinstance(horizontes_dias, tuple)
            or not 1 <= len(horizontes_dias) <= 8
            or any(type(n) is not int or not 1 <= n <= 365 for n in horizontes_dias)
            or list(horizontes_dias) != sorted(set(horizontes_dias))):
        raise ErroRecuperacaoFrete("horizontes inválidos")
    if type(quantidade_anterior) is not int or not 0 <= quantidade_anterior <= 1_000_000:
        raise ErroRecuperacaoFrete("contagem do checkpoint inválida")
    if (not isinstance(instante_recuperacao, datetime)
            or instante_recuperacao.tzinfo is None
            or instante_recuperacao.utcoffset() is None):
        raise ErroRecuperacaoFrete("recuperação exige tempo com timezone")
    if (not isinstance(chave_previsao, bytes) or len(chave_previsao) < 32
            or not isinstance(chave_recibo, bytes) or len(chave_recibo) < 32
            or chave_previsao == chave_recibo):
        raise ErroRecuperacaoFrete("chaves de previsão e recibo devem ser distintas")


def recuperar_recibo_poscommit_frete(
    con: sqlite3.Connection, *, cabeca_previsoes_anterior_sha256: str,
    quantidade_previsoes_anterior: int, cabeca_ofertas_sha256: str,
    condicoes: dict, fonte_id: str, emissor_previsao: str,
    chave_previsao: bytes, emissor_recibo: str, chave_recibo: bytes,
    instante_recuperacao: datetime, diretorio_recibos: str | Path,
    horizontes_dias: tuple[int, ...] = (7, 30, 90),
) -> dict:
    """Restaura SOMENTE recibo de lote já persistido, conferido de ponta a ponta.

    A cabeça anterior e o tamanho do prefixo têm de vir do checkpoint
    independente anterior ao commit. Sem checkpoint externo, negar
    certificação; é inseguro aceitar auto-descoberta da cabeça prefixo.
    """
    _validar_configuracao(
        condicoes=condicoes, horizontes_dias=horizontes_dias,
        quantidade_anterior=quantidade_previsoes_anterior,
        instante_recuperacao=instante_recuperacao,
        chave_previsao=chave_previsao, chave_recibo=chave_recibo,
    )
    if not isinstance(con, sqlite3.Connection) or con.in_transaction:
        raise ErroRecuperacaoFrete("SQLite disponível e sem transação pendente obrigatório")
    from .fretes_recibos_ancora import _hash
    _hash(cabeca_previsoes_anterior_sha256, "checkpoint anterior")
    _hash(cabeca_ofertas_sha256, "snapshot ofertas")
    momento = instante_recuperacao.astimezone(timezone.utc)
    origem = verificar_store_ofertas_frete(
        con, cabeca_esperada_sha256=cabeca_ofertas_sha256
    )
    # Head atual é candidato NÃO CONFIÁVEL. Validar integralmente HMAC, SHA
    # e a conexão com o checkpoint anterior ANTES de emitir qualquer recibo.
    n = con.execute(
        "SELECT COUNT(*) FROM nivon_frete_previsoes_v1"
    ).fetchone()[0]
    previsto_total = quantidade_previsoes_anterior + len(horizontes_dias)
    if n != previsto_total:
        raise ErroRecuperacaoFrete("quantidade pós-commit não corresponde ao lote esperado")
    if quantidade_previsoes_anterior == 0:
        prefixo = GENESIS
    else:
        prefixo_row = con.execute(
            "SELECT registro_sha256 FROM nivon_frete_previsoes_v1 "
            "WHERE sequencia = ?", (quantidade_previsoes_anterior,),
        ).fetchone()
        if prefixo_row is None:
            raise ErroRecuperacaoFrete("prefixo anterior truncado")
        prefixo = prefixo_row[0]
    if prefixo != cabeca_previsoes_anterior_sha256:
        raise ErroRecuperacaoFrete("prefixo não coincide com checkpoint externo anterior")
    tail_rows = con.execute(
        "SELECT registro_sha256, anterior_sha256 "
        "FROM nivon_frete_previsoes_v1 WHERE sequencia > ? ORDER BY sequencia",
        (quantidade_previsoes_anterior,),
    ).fetchall()
    if len(tail_rows) != len(horizontes_dias) or tail_rows[0][1] != prefixo:
        raise ErroRecuperacaoFrete("lote pós-commit ou continuidade inválidos")
    candidato = tail_rows[-1][0]
    try:
        confirmado = verificar_ledger_frete(
            con, cabeca_esperada_sha256=candidato,
            chave_verificacao=chave_previsao,
            emissor_esperado=emissor_previsao,
        )
    except (ValueError, TypeError, sqlite3.Error) as exc:
        raise ErroRecuperacaoFrete("cadeia/HMAC do ledger não homologáveis") from exc
    novas = confirmado["previsoes"][quantidade_previsoes_anterior:]
    if len(novas) != len(horizontes_dias):
        raise ErroRecuperacaoFrete("lote shadow recuperado incompleto")
    emissao = _hora(novas[0]["emitido_em"], "emitido_em")
    if emissao > momento or any(
        _hora(p["emitido_em"], "emitido_em") != emissao
        or _hora(p["registrado_em"], "registrado_em") != emissao
        or p["fonte_id"] != fonte_id or p["emissor_id"] != emissor_previsao
        or any(p.get(k) != v for k, v in condicoes.items())
        for p in novas
    ):
        raise ErroRecuperacaoFrete("lote shadow misturou emitente, instante ou condições")
    from .fretes_previsoes_arquivadas import MT
    if emissao.astimezone(MT).date() != momento.astimezone(MT).date():
        # Não se pode emitir recibo retroativo em dia posterior
        # e afirmá-lo como testemunha do dia anterior.
        raise ErroRecuperacaoFrete("recuperação tardia requer testemunha externa")
    ofertas = _ofertas_rota(
        origem["ofertas"], fonte_id=fonte_id, condicoes=condicoes
    )
    disponiveis = [
        r for r in ofertas
        if r.data_publicacao.astimezone(timezone.utc) <= emissao
        and r.data_coleta.astimezone(timezone.utc) <= emissao
    ]
    try:
        propostas = preparar_intencoes_baseline_frete(
            disponiveis, emitido_em=emissao, fonte_id=fonte_id,
            emissor_id=emissor_previsao, horizontes_dias=horizontes_dias,
            **condicoes,
        )
    except ValueError as exc:
        raise ErroRecuperacaoFrete("snapshot point-in-time anterior incompatível") from exc
    esperados = {
        p["horizonte_dias_corridos"]: p
        for p in propostas["previsoes_para_assinatura_externa"]
    }
    vistos = set()
    for p in novas:
        h = p["horizonte_dias_corridos"]
        if h in vistos or h not in esperados:
            raise ErroRecuperacaoFrete("horizontes duplicados ou inesperados")
        visto = {k: v for k, v in p.items()
                 if k not in ("registrado_em", "assinatura_hmac_sha256")}
        if visto != esperados[h]:
            raise ErroRecuperacaoFrete("previsão não coincide com a emissão PIT original")
        vistos.add(h)
    if vistos != set(horizontes_dias):
        raise ErroRecuperacaoFrete("previsões de horizonte incompletas")
    path = Path(diretorio_recibos)
    if (not path.is_absolute() or path.is_symlink() or not path.is_dir()
            or path.stat().st_mode & 0o077):
        raise ErroRecuperacaoFrete("diretório privado de recibos não disponível")
    # Não emitir um segundo recibo se já existe o comprovante válido dessa
    # cabeça. Se houver arquivo com nome compatível corrompido, bloqueia.
    for item in sorted(path.glob("frete_PREVISOES_*.json")):
        if item.is_symlink() or not item.is_file() or item.stat().st_size > 8192:
            raise ErroRecuperacaoFrete("recibo anterior local inseguro")
        try:
            existing = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise ErroRecuperacaoFrete("recibo local anterior ilegível") from exc
        if existing.get("cabeca_sha256") != candidato:
            continue
        try:
            v = verificar_recibo_local_frete(
                existing, chave_recibo=chave_recibo, as_of=momento,
                tipo_esperado="PREVISOES", emissor_esperado=emissor_recibo,
            )
        except ValueError as exc:
            raise ErroRecuperacaoFrete("recibo da mesma cabeça adulterado") from exc
        if v["sequencia"] != n:
            raise ErroRecuperacaoFrete("recibo da mesma cabeça com sequência divergente")
        return {
            "status": "RECIBO_JA_EXISTENTE_VALIDADO_LOCALMENTE",
            "cabeca_sha256": candidato, "total_previsoes": n,
            "recibo_local_caminho": str(item),
            "recibo_duplicado_criado": False,
            "recuperacao_do_ledger_reexecutada": False,
            "testemunha_independente": False,
            "publicavel": False,
        }
    # O recibo de recuperação usa o instante ATUAL, nunca o da emissão.
    recibo = criar_recibo_local_frete(
        tipo_ledger="PREVISOES", emissor_id=emissor_recibo,
        cabeca_sha256=candidato, sequencia=n,
        assinado_em=momento, chave_recibo=chave_recibo,
    )
    try:
        gravado = salvar_recibo_em_diretorio_local(
            recibo, diretorio_privado=path,
        )
    except (OSError, ValueError) as exc:
        raise ErroRecuperacaoFrete("recuperação do recibo falhou; ledger inalterado") from exc
    return {
        "status": "RECIBO_RECUPERADO_LOCALMENTE_SEM_PROVA_TEMPORAL_EXTERNA",
        "cabeca_sha256": candidato, "total_previsoes": n,
        "recibo_local_caminho": gravado["caminho_local"],
        "recibo_local_sha256": gravado["sha256"],
        "recibo_duplicado_criado": False,
        "recuperacao_do_ledger_reexecutada": False,
        "testemunha_independente": False,
        "armazenamento_worm_comprovado": False,
        "publicavel": False,
    }
