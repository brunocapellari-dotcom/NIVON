"""Ledger transacional SQLite de previsões de frete PREVIAMENTE emitidas.

Append-only lógico com cadeia SHA256 e HMAC do emissor. Integração local,
sem rede, scheduler, deploy ou segredos embarcados. NÃO é WORM nem oferece
timestamp independente: DBA ou dono da chave pode reescrever a cadeia.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import sqlite3
from typing import Mapping, Sequence

from .fretes_atestacoes import serializacao_canonica
from .fretes_previsoes_arquivadas import (
    CAMPOS, DOMINIO, ErroAvaliacaoFrete, _delta, _dia, _digest, _hora, _id,
    avaliar_previsoes_arquivadas_frete,
)

GENESIS = "0" * 64
CADEIA = b"NIVON_FRETE_LEDGER_V1\x00"
ESCOPO = ("origem_ibge", "destino_ibge", "descarga_entity_id", "produto",
          "equipamento", "regime", "pedagio", "fonte_id")


class ErroLedgerFrete(ErroAvaliacaoFrete):
    """Falha fechada de integridade, tempo, escopo ou transação."""


def _conexao(con: sqlite3.Connection) -> None:
    if not isinstance(con, sqlite3.Connection):
        raise ErroLedgerFrete("conexão SQLite local obrigatória")


def _canonico(obj: Mapping) -> str:
    return serializacao_canonica(obj).decode("utf-8")


def _hash_registro(anterior: str, previsao: Mapping, recebimento: str) -> str:
    return sha256(CADEIA + anterior.encode("ascii") + serializacao_canonica(
        {"previsao": previsao, "recebido_em": recebimento}
    )).hexdigest()


def _escopo_hash(previsao: Mapping) -> str:
    return sha256(serializacao_canonica({k: previsao[k] for k in ESCOPO})).hexdigest()


def _validar_previsao(previsao: Mapping, chave: bytes, emissor: str) -> None:
    if not isinstance(previsao, Mapping) or set(previsao) != CAMPOS:
        raise ErroLedgerFrete("esquema de previsão assinada incompatível")
    if not isinstance(chave, bytes) or len(chave) < 32:
        raise ErroLedgerFrete("chave externa de verificação ausente")
    if previsao.get("emissor_id") != emissor:
        raise ErroLedgerFrete("emissor não confiável")
    for k in ("previsao_id", "modelo_versao", "emissor_id", "fonte_id", *ESCOPO):
        _id(previsao[k], k)
    if type(previsao["horizonte_dias_corridos"]) is not int or not (
            1 <= previsao["horizonte_dias_corridos"] <= 365):
        raise ErroLedgerFrete("horizonte de dias corridos inválido")
    origem = _dia(previsao["data_origem"], "data_origem")
    alvo = _dia(previsao["data_alvo"], "data_alvo")
    if alvo != origem + timedelta(days=previsao["horizonte_dias_corridos"]):
        raise ErroLedgerFrete("origem e data-alvo incompatíveis")
    _delta(previsao["delta_previsto_brl_t"])
    _digest(previsao["base_snapshot_sha256"], "base_snapshot_sha256")
    assinatura = _digest(previsao["assinatura_hmac_sha256"], "assinatura_hmac_sha256")
    corpo = {k: v for k, v in previsao.items() if k != "assinatura_hmac_sha256"}
    calc = hmac.new(chave, DOMINIO + serializacao_canonica(corpo), sha256).hexdigest()
    if not hmac.compare_digest(calc, assinatura):
        raise ErroLedgerFrete("HMAC inválido; conteúdo não assinado pelo emissor")
    emissao = _hora(previsao["emitido_em"], "emitido_em")
    registro = _hora(previsao["registrado_em"], "registrado_em")
    treino = _hora(previsao["treinado_ate"], "treinado_ate")
    from .fretes_previsoes_arquivadas import MT
    if (emissao.astimezone(MT).date() != origem or not treino <= emissao <= registro
            or registro.astimezone(MT).date() > origem):
        raise ErroLedgerFrete("cronologia de previsão retroativa ou fora da origem")


def inicializar_ledger_frete(con: sqlite3.Connection) -> None:
    """Cria tabelas e triggers. Não cria nem armazena chaves secretas."""
    _conexao(con)
    if con.in_transaction:
        raise ErroLedgerFrete("inicialização em transação pendente")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS nivon_frete_previsoes_v1 (
            sequencia INTEGER PRIMARY KEY AUTOINCREMENT,
            previsao_id TEXT NOT NULL UNIQUE,
            modelo_versao TEXT NOT NULL,
            escopo_sha256 TEXT NOT NULL,
            data_origem TEXT NOT NULL,
            horizonte_dias INTEGER NOT NULL,
            recebido_em TEXT NOT NULL,
            anterior_sha256 TEXT NOT NULL,
            registro_sha256 TEXT NOT NULL UNIQUE,
            previsao_json TEXT NOT NULL,
            UNIQUE(modelo_versao, escopo_sha256, data_origem, horizonte_dias)
        );
        CREATE TRIGGER IF NOT EXISTS nivon_frete_previsoes_sem_update
        BEFORE UPDATE ON nivon_frete_previsoes_v1
        BEGIN SELECT RAISE(ABORT, 'append_only_frete'); END;
        CREATE TRIGGER IF NOT EXISTS nivon_frete_previsoes_sem_delete
        BEFORE DELETE ON nivon_frete_previsoes_v1
        BEGIN SELECT RAISE(ABORT, 'append_only_frete'); END;
    """)


def verificar_ledger_frete(
    con: sqlite3.Connection, *, cabeca_esperada_sha256: str,
    chave_verificacao: bytes, emissor_esperado: str,
) -> dict:
    """Só compara com uma âncora *fornecida*, que deve existir fora do SQLite."""
    _conexao(con)
    _digest(cabeca_esperada_sha256, "cabeca_esperada_sha256")
    linhas = con.execute(
        "SELECT sequencia, previsao_id, modelo_versao, escopo_sha256, "
        "data_origem, horizonte_dias, recebido_em, anterior_sha256, "
        "registro_sha256, previsao_json FROM nivon_frete_previsoes_v1 "
        "ORDER BY sequencia ASC"
    ).fetchall()
    atual, previsoes, anterior_recebimento = GENESIS, [], None
    for ordinal, (seq, pid, modelo, escopo, origem, horizonte, recebido,
                  anterior, digest, body) in enumerate(linhas, 1):
        if seq != ordinal or anterior != atual:
            raise ErroLedgerFrete("cadeia do ledger truncada ou sequência rompida")
        try:
            p = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise ErroLedgerFrete("payload do ledger inválido") from exc
        if not isinstance(p, dict) or _canonico(p) != body:
            raise ErroLedgerFrete("payload não canônico ou alterado")
        _validar_previsao(p, chave_verificacao, emissor_esperado)
        if (p["previsao_id"] != pid or p["modelo_versao"] != modelo
                or _escopo_hash(p) != escopo or p["data_origem"] != origem
                or p["horizonte_dias_corridos"] != horizonte):
            raise ErroLedgerFrete("índice econômico diferente do payload assinado")
        instante = _hora(recebido, "recebido_em")
        registro = _hora(p["registrado_em"], "registrado_em")
        if (not registro <= instante <= registro + timedelta(minutes=5)
                or instante.astimezone(
                    __import__("zoneinfo").ZoneInfo("America/Cuiaba")
                ).date() != _dia(origem, "data_origem")
                or anterior_recebimento is not None and instante < anterior_recebimento):
            raise ErroLedgerFrete("recebimento temporal fora da janela, desordenado ou retroativo")
        if not hmac.compare_digest(_hash_registro(atual, p, recebido), digest):
            raise ErroLedgerFrete("SHA da cadeia adulterado")
        atual, anterior_recebimento = digest, instante
        previsoes.append(p)
    if atual != cabeca_esperada_sha256:
        raise ErroLedgerFrete("cabeça diverge da âncora externa fornecida")
    return {
        "status": "LEDGER_LOCAL_HASH_HMAC_VERIFICADO",
        "quantidade": len(previsoes),
        "cabeca_sha256": atual,
        "previsoes": previsoes,
        "publicavel": False,
        "ancora_temporal_externa_autenticada": False,
        "worm_fisico": False,
    }


def anexar_previsao_frete(
    con: sqlite3.Connection, previsao: Mapping, *,
    recebido_em: datetime, cabeca_anterior_sha256: str,
    chave_verificacao: bytes, emissor_esperado: str,
) -> dict:
    """Adiciona UMA previsão em BEGIN IMMEDIATE, exigindo cabeça anterior.

    O timestamp `recebido_em` é fornecido pelo runtime e não constitui,
    sem um serviço externo confiável, prova independente do tempo real.
    """
    _conexao(con)
    _validar_previsao(previsao, chave_verificacao, emissor_esperado)
    _digest(cabeca_anterior_sha256, "cabeca_anterior_sha256")
    if (not isinstance(recebido_em, datetime)
            or recebido_em.tzinfo is None or recebido_em.utcoffset() is None):
        raise ErroLedgerFrete("recebido_em deve vir de relógio timezone-aware")
    instante = recebido_em.astimezone(timezone.utc)
    registro = _hora(previsao["registrado_em"], "registrado_em")
    from .fretes_previsoes_arquivadas import MT
    if (not registro <= instante <= registro + timedelta(minutes=5)
            or instante.astimezone(MT).date() != _dia(previsao["data_origem"], "data_origem")):
        raise ErroLedgerFrete("previsão recebida tardiamente ou após dia de origem")
    if con.in_transaction:
        raise ErroLedgerFrete("transação externa pendente impede gravação segura")
    try:
        con.execute("BEGIN IMMEDIATE")
        estado = verificar_ledger_frete(
            con, cabeca_esperada_sha256=cabeca_anterior_sha256,
            chave_verificacao=chave_verificacao, emissor_esperado=emissor_esperado,
        )
        if estado["previsoes"]:
            last = con.execute(
                "SELECT recebido_em FROM nivon_frete_previsoes_v1 ORDER BY sequencia DESC LIMIT 1"
            ).fetchone()[0]
            if instante < _hora(last, "ultimo_recebimento"):
                raise ErroLedgerFrete("ingestão fora de ordem; possível backfill")
        recebido = instante.isoformat()
        p = dict(previsao)
        novo = _hash_registro(cabeca_anterior_sha256, p, recebido)
        con.execute(
            "INSERT INTO nivon_frete_previsoes_v1 "
            "(previsao_id, modelo_versao, escopo_sha256, data_origem, horizonte_dias,"
            " recebido_em, anterior_sha256, registro_sha256, previsao_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["previsao_id"], p["modelo_versao"], _escopo_hash(p),
             p["data_origem"], p["horizonte_dias_corridos"], recebido,
             cabeca_anterior_sha256, novo, _canonico(p)),
        )
        con.commit()
        return {
            "status": "GRAVADO_SQLITE_LOCAL_AGUARDA_ANCORA_EXTERNA",
            "previsao_id": p["previsao_id"],
            "cabeca_sha256": novo,
            "registros": estado["quantidade"] + 1,
            "publicavel": False,
            "ancora_externa_comprovada": False,
        }
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        con.rollback()
        if isinstance(exc, ErroLedgerFrete):
            raise
        raise ErroLedgerFrete("append de previsão abortado sem gravação") from exc


def avaliar_ledger_frete(
    con: sqlite3.Connection, ofertas: Sequence, *, cabeca_esperada_sha256: str,
    chave_verificacao: bytes, emissor_esperado: str, as_of: datetime,
    origem_ibge: str, destino_ibge: str, descarga_entity_id: str,
    produto: str, equipamento: str, regime: str, pedagio: str,
    fonte_id: str, modelo_versao: str, horizonte_dias_corridos: int,
    minimo_previsoes: int = 5,
) -> dict:
    """Encadeia verificação do SQLite, seleção homogênea e avaliação existente."""
    verificado = verificar_ledger_frete(
        con, cabeca_esperada_sha256=cabeca_esperada_sha256,
        chave_verificacao=chave_verificacao, emissor_esperado=emissor_esperado,
    )
    scope = {k:v for k,v in locals().items() if k in ESCOPO}
    filtros = [p for p in verificado["previsoes"] if (
        all(p[k] == v for k,v in scope.items())
        and p["modelo_versao"] == modelo_versao
        and p["horizonte_dias_corridos"] == horizonte_dias_corridos
    )]
    resultado = avaliar_previsoes_arquivadas_frete(
        ofertas, filtros,
        origem_ibge=origem_ibge, destino_ibge=destino_ibge,
        descarga_entity_id=descarga_entity_id, produto=produto,
        equipamento=equipamento, regime=regime, pedagio=pedagio,
        fonte_id=fonte_id, modelo_versao=modelo_versao,
        horizonte_dias_corridos=horizonte_dias_corridos, as_of=as_of,
        chave_verificacao=chave_verificacao, emissor_esperado=emissor_esperado,
        minimo_previsoes=minimo_previsoes,
    )
    return {
        **resultado,
        "ledger_sha256": verificado["cabeca_sha256"],
        "ledger_total_registros": verificado["quantidade"],
        "ledger_hmac_sha256_validado": True,
        "ancora_temporal_independente_comprovada": False,
        "publicavel": False,
    }


def anexar_lote_previsoes_frete(
    con: sqlite3.Connection, previsoes: Sequence[Mapping], *,
    recebimentos: Sequence[datetime], cabeca_anterior_sha256: str,
    chave_verificacao: bytes, emissor_esperado: str,
) -> dict:
    """Grava todos os forecasts numa única transação ou não grava nenhum."""
    _conexao(con)
    if (not isinstance(previsoes, (list, tuple))
            or not isinstance(recebimentos, (list, tuple))
            or not 1 <= len(previsoes) <= 500 or len(previsoes) != len(recebimentos)):
        raise ErroLedgerFrete("lote e recebimentos inconsistentes")
    _digest(cabeca_anterior_sha256, "cabeca_anterior_sha256")
    if con.in_transaction:
        raise ErroLedgerFrete("transação já pendente")
    try:
        con.execute("BEGIN IMMEDIATE")
        estado = verificar_ledger_frete(
            con, cabeca_esperada_sha256=cabeca_anterior_sha256,
            chave_verificacao=chave_verificacao, emissor_esperado=emissor_esperado,
        )
        ids = {p["previsao_id"] for p in estado["previsoes"]}
        series = {(p["modelo_versao"], _escopo_hash(p), p["data_origem"],
                   p["horizonte_dias_corridos"]) for p in estado["previsoes"]}
        anterior_instante = None
        if estado["quantidade"]:
            anterior_instante = _hora(con.execute(
                "SELECT recebido_em FROM nivon_frete_previsoes_v1 "
                "ORDER BY sequencia DESC LIMIT 1"
            ).fetchone()[0], "recebido_em_anterior")
        from .fretes_previsoes_arquivadas import MT
        anterior = cabeca_anterior_sha256
        comprovantes = []
        for p, recebido in zip(previsoes, recebimentos):
            _validar_previsao(p, chave_verificacao, emissor_esperado)
            if (not isinstance(recebido, datetime) or recebido.tzinfo is None
                    or recebido.utcoffset() is None):
                raise ErroLedgerFrete("recebimento exige instante timezone-aware")
            instante = recebido.astimezone(timezone.utc)
            registro = _hora(p["registrado_em"], "registrado_em")
            if (not registro <= instante <= registro + timedelta(minutes=5)
                    or instante.astimezone(MT).date() != _dia(p["data_origem"], "data_origem")
                    or anterior_instante is not None and instante < anterior_instante):
                raise ErroLedgerFrete("recebimento retroativo, futuro ou tardio")
            escopo = _escopo_hash(p)
            chave = (p["modelo_versao"], escopo, p["data_origem"],
                     p["horizonte_dias_corridos"])
            if p["previsao_id"] in ids or chave in series:
                raise ErroLedgerFrete("previsão ou combinação modelo/origem/horizonte repetida")
            proximo = _hash_registro(anterior, p, instante.isoformat())
            con.execute(
                "INSERT INTO nivon_frete_previsoes_v1 "
                "(previsao_id, modelo_versao, escopo_sha256, data_origem, "
                "horizonte_dias, recebido_em, anterior_sha256, "
                "registro_sha256, previsao_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p["previsao_id"], p["modelo_versao"], escopo, p["data_origem"],
                 p["horizonte_dias_corridos"], instante.isoformat(),
                 anterior, proximo, _canonico(dict(p))),
            )
            comprovantes.append({
                "previsao_id": p["previsao_id"], "registro_sha256": proximo,
            })
            anterior, anterior_instante = proximo, instante
            ids.add(p["previsao_id"])
            series.add(chave)
        con.commit()
        return {
            "status": "LOTE_SQLITE_ATOMICO_AGUARDA_ANCORA_INDEPENDENTE",
            "adicionados": len(previsoes),
            "total": estado["quantidade"] + len(previsoes),
            "cabeca_sha256": anterior, "comprovantes": comprovantes,
            "ancora_temporal_externa_autenticada": False, "publicavel": False,
        }
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        con.rollback()
        if isinstance(exc, ErroLedgerFrete):
            raise
        raise ErroLedgerFrete("erro transacional; lote inteiro revertido") from exc
