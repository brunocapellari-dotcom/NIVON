"""Migração reversa PTAX RAW -> visão legada em cópia SQLite isolada.

Nunca escreve no banco-fonte. Não altera schema snapshots. Recusa valores
que a representação legada float a quatro casas não possa transportar
sem perda verificável. Não autoriza troca do briefing, fonte ou direitos.
"""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import sqlite3

from .continuidade_ptax import (
    ErroContinuidadePTAX, criar_pacote_backup_ptax,
    restaurar_pacote_backup_ptax, auditar_integridade_ptax,
)
from .pipeline_api_dados import _normalizar_bytes, preparar_tabelas
from .ptax_odata_bruta_mercados import (
    _consulta, verificar_ptax_odata_bruta,
)
from .ptax_plano import planejar_consultas_ptax
from .transacoes_sqlite import savepoint_atomico


class ErroMigracaoReversaPTAX(ValueError):
    """Migração RAW->visão legada recusada por integridade ou precisão."""


_QUATRO = Decimal("0.0001")


def materializar_visao_legada_em_copia(
    db_origem: sqlite3.Connection, *, raw_sha256: str,
) -> dict:
    """Restaura cópia, materializa linhas compatíveis e retorna conexão.

    O chamador deve fechar resultado['copia']; o original permanece
    intacto mesmo quando a operação falha. SEM publicação automática.
    """
    if not isinstance(db_origem, sqlite3.Connection):
        raise ErroMigracaoReversaPTAX("banco original inválido")
    if (not isinstance(raw_sha256, str) or len(raw_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in raw_sha256)):
        raise ErroMigracaoReversaPTAX("SHA original inválido")
    pacote = criar_pacote_backup_ptax(db_origem)
    db = restaurar_pacote_backup_ptax(pacote)
    try:
        registro = db.execute(
            "SELECT id,schema_versao,tipo FROM nivon_snapshots "
            "WHERE dataset_id='BCB_PTAX' AND sha256=?",
            (raw_sha256,),
        ).fetchone()
        if registro is None or registro["schema_versao"] != "PTAX_ODATA_RAW_V1":
            raise ErroMigracaoReversaPTAX(
                "SHA não pertence a snapshot exclusivamente RAW"
            )
        sid = registro["id"]
        raw = db.execute(
            "SELECT dados FROM nivon_ptax_raw_blobs WHERE sha256=?",
            (raw_sha256,),
        ).fetchone()
        if raw is None or sha256(raw[0]).hexdigest() != raw_sha256:
            raise ErroMigracaoReversaPTAX("blobs originais ausentes/adulterados")
        capturas = db.execute(
            "SELECT coletado_em,consulta_url,moeda "
            "FROM nivon_ptax_raw_capturas WHERE snapshot_id=? "
            "ORDER BY coletado_em",
            (sid,),
        ).fetchall()
        if not capturas or len(capturas) > 10000:
            raise ErroMigracaoReversaPTAX("conjunto de capturas indisponível")
        moeda = capturas[0]["moeda"]
        urls = {r["consulta_url"] for r in capturas}
        if len(urls) != 1 or any(c["moeda"] != moeda for c in capturas):
            raise ErroMigracaoReversaPTAX("múltiplas identidades para o mesmo SHA")
        url = capturas[0]["consulta_url"]
        inicio, fim = _consulta(url, moeda)
        plano = planejar_consultas_ptax(
            moeda=moeda, inicio=inicio.isoformat(), fim=fim.isoformat(),
            dias_janela=(fim-inicio).days+1,
        )[0]
        conferir = verificar_ptax_odata_bruta(
            raw[0], consulta_url=url, moeda=moeda,
            coletado_em=capturas[0]["coletado_em"],
            as_of=capturas[0]["coletado_em"],
            raw_sha256_esperado=raw_sha256,
        )
        for obs in conferir["boletins"]:
            for campo in ("cotacao_compra_decimal", "cotacao_venda_decimal"):
                valor = Decimal(obs[campo])
                # Exatidão para todos os boletins: nada de arredondamento
                # que o legado não consiga representar com 4 casas.
                if valor != valor.quantize(_QUATRO):
                    raise ErroMigracaoReversaPTAX(
                        "perda de casas decimais no adaptador legado"
                    )
                if format(float(valor), ".4f") != format(valor, ".4f"):
                    raise ErroMigracaoReversaPTAX(
                        "float legado diverge da representação decimal"
                    )
        for r in capturas[1:]:
            verificar_ptax_odata_bruta(
                raw[0], consulta_url=url, moeda=moeda,
                coletado_em=r["coletado_em"],as_of=r["coletado_em"],
                raw_sha256_esperado=raw_sha256,
            )
        normalizadas = _normalizar_bytes(
            raw[0], "BCB_PTAX", plano, capturas[0]["coletado_em"],
        )
        preparar_tabelas(db)
        with savepoint_atomico(db):
            existentes = db.execute(
                "SELECT COUNT(*) FROM nivon_observacoes_api WHERE snapshot_id=?",
                (sid,),
            ).fetchone()[0]
            if existentes:
                raise ErroMigracaoReversaPTAX(
                    "observações legadas já presentes; não sobrescrever"
                )
            db.executemany(
                "INSERT INTO nivon_observacoes_api "
                "(snapshot_id,chave,observacao_json) VALUES(?,?,?)",
                [(sid,key,valor) for key,valor in normalizadas],
            )
        verificacao = auditar_integridade_ptax(db)
        if verificacao["total_snapshots"] != pacote["manifesto"]["inventario"]["total_snapshots"]:
            raise ErroMigracaoReversaPTAX("cópia alterou snapshots")
        return {
            "status": "VISAO_LEGADA_MATERIALIZADA_SOMENTE_EM_COPIA",
            "copia": db,
            "sha256_backup": pacote["manifesto"]["sha256"],
            "raw_sha256": raw_sha256,
            "schema_snapshot_preservado": "PTAX_ODATA_RAW_V1",
            "linhas_compatibilizadas": len(normalizadas),
            "tipo": registro["tipo"],
            "banco_original_modificado": False,
            "promocao_editorial_autorizada": False,
            "publicavel": False,
        }
    except (ValueError, sqlite3.Error, TypeError, IndexError, KeyError):
        db.close()
        raise
