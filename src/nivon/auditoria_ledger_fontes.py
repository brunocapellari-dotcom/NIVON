"""NIVON: cobertura de coletas por evidência do ledger, somente leitura.

Catálogo/rotas são plano, não dados; tipo REAL_AUTORIZADO registrado no
SQLite não substitui homologação independente da fonte, bytes e direitos.
Na ausência de um banco, quantidades permanecem None, jamais zero.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .catalogo_fontes import carregar_catalogo, validar_catalogo

_TIPOS = frozenset({"SINTETICO", "REAL_AUTORIZADO"})
_COLUNAS_SNAPSHOT = frozenset({
    "id", "dataset_id", "fonte_id", "tipo", "sha256", "competencia",
    "referencia", "publicacao",
})
_COLUNAS_COLETA = frozenset({"snapshot_id", "coletado_utc"})
_HASH = re.compile(r"[a-f0-9]{64}\Z")


class ErroAuditoriaLedger(ValueError):
    pass


def _utc(valor: str) -> datetime:
    if not isinstance(valor, str):
        raise ErroAuditoriaLedger("data de coleta não é ISO")
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroAuditoriaLedger("timestamp ISO inválido") from exc
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroAuditoriaLedger("fuso obrigatório nos instantes de coleta")
    return instante.astimezone(timezone.utc)


def _tabelas_registro(db: sqlite3.Connection) -> None:
    esperadas = {
        "nivon_snapshots": _COLUNAS_SNAPSHOT,
        "nivon_coletas": _COLUNAS_COLETA,
    }
    for tabela, campos in esperadas.items():
        disponiveis = {row[1] for row in db.execute(f"PRAGMA table_info({tabela})")}
        if not campos <= disponiveis:
            raise ErroAuditoriaLedger(f"schema do ledger inválido/ausente: {tabela}")


def auditar_cobertura_ledger(catalogo: dict, db: sqlite3.Connection | None = None,
                            *, prioridade: str | None = None,
                            gerado_em: str | None = None) -> dict:
    """Retorna evidência local e NULL quando não há banco fornecido.

    Não interpreta linhas do ledger como observações agrícolas/portuárias.
    Não considera seu conteúdo prova de fonte oficial nem de publicação.
    """
    validar_catalogo(catalogo)
    if prioridade not in (None, "P0", "P1", "P2"):
        raise ErroAuditoriaLedger("prioridade de filtro inválida")
    agora = _utc(gerado_em) if gerado_em is not None else datetime.now(timezone.utc)
    todos = {d["id"]: d for d in catalogo["datasets"]}
    datasets = [d for d in catalogo["datasets"]
                if prioridade is None or d["priority"] == prioridade]
    data = {
        d["id"]: {
            "dataset_id": d["id"], "fonte_id": d["source_id"],
            "prioridade": d["priority"], "grupo": d["group"], "catalogo_stage": d["stage"],
            "snapshots_sinteticos": None if db is None else 0,
            "snapshots_marcados_real": None if db is None else 0,
            "capturas": None if db is None else 0,
            "snapshot_sem_coleta": None if db is None else 0,
            "data_ultima_coleta_utc": None,
            "competencia_ausente": None if db is None else 0,
            "referencia_ausente": None if db is None else 0,
            "publicacao_ausente": None if db is None else 0,
            "linhas_normalizadas": None,
            "raw_verificado_externamente": False,
            "pronto_para_publicar": False,
            "estado": "SEM_BANCO_NAO_AFERIDO" if db is None else "SEM_SNAPSHOT_NESTE_LEDGER",
        } for d in datasets
    }
    problemas = []
    if db is not None:
        _tabelas_registro(db)
        query = """SELECT s.id,s.dataset_id,s.fonte_id,s.tipo,s.sha256,
                          s.competencia,s.referencia,s.publicacao,
                          COUNT(c.coletado_utc),MAX(c.coletado_utc)
                   FROM nivon_snapshots s
                   LEFT JOIN nivon_coletas c ON c.snapshot_id=s.id
                   GROUP BY s.id
                   ORDER BY s.id LIMIT 250001"""
        registros = db.execute(query).fetchall()
        if len(registros) > 250000:
            raise ErroAuditoriaLedger("ledger muito extenso para auditoria sem paginação")
        for (sid,dataset_id,fonte_id,tipo,sha,comp,ref,pub,n_coletas,ultima) in registros:
            if dataset_id not in todos or todos[dataset_id]["source_id"] != fonte_id:
                raise ErroAuditoriaLedger("snapshot de fonte/dataset inconsistente com catálogo")
            if tipo not in _TIPOS or not isinstance(sha,str) or not _HASH.fullmatch(sha):
                raise ErroAuditoriaLedger("classe/hash de snapshot fora do contrato")
            if type(n_coletas) is not int or n_coletas < 0:
                raise ErroAuditoriaLedger("quantidade de coletas inválida")
            if ultima is not None and _utc(ultima) > agora:
                problemas.append({"dataset_id":dataset_id,"tipo":"COLETA_FUTURA","snapshot_id":sid})
            if ultima is None and n_coletas > 0:
                raise ErroAuditoriaLedger("contagem de coleta sem timestamp")
            if dataset_id not in data:
                continue  # Filtro de exibição não oculta inconsistências globais.
            row = data[dataset_id]
            row["snapshots_sinteticos" if tipo == "SINTETICO" else "snapshots_marcados_real"] += 1
            row["capturas"] += n_coletas
            row["snapshot_sem_coleta"] += int(n_coletas == 0)
            row["competencia_ausente"] += int(comp is None)
            row["referencia_ausente"] += int(ref is None)
            row["publicacao_ausente"] += int(pub is None)
            if ultima is not None:
                row["data_ultima_coleta_utc"] = max(
                    row["data_ultima_coleta_utc"] or ultima, ultima
                )
        for row in data.values():
            if row["snapshots_marcados_real"]:
                row["estado"] = "REAL_DECLARADO_NO_LEDGER_SEM_PROVA_EXTERNA"
            elif row["snapshots_sinteticos"]:
                row["estado"] = "SOMENTE_SINTETICO_NO_LEDGER"
            if row["snapshot_sem_coleta"]:
                row["estado"] = "ANOMALIA_SNAPSHOT_SEM_COLETA"
        for problem in problemas:
            if problem["dataset_id"] in data:
                data[problem["dataset_id"]]["estado"] = "ANOMALIA_COLETA_FUTURA"
    fontes = {}
    for item in data.values():
        f = fontes.setdefault(item["fonte_id"], {
            "fonte_id": item["fonte_id"], "datasets": 0,
            "snapshots_sinteticos": None if db is None else 0,
            "snapshots_marcados_real": None if db is None else 0,
            "capturas": None if db is None else 0,
        })
        f["datasets"] += 1
        if db is not None:
            for k in ("snapshots_sinteticos","snapshots_marcados_real","capturas"):
                f[k] += item[k]
    return {
        "fonte_de_verdade_catalogo": "config/fontes_nivon_master.v1.json",
        "origem_evidencia": "nivon_snapshots+nivon_coletas" if db is not None else None,
        "situacao": ("BANCO_NAO_FORNECIDO_SEM_EVIDENCIA_DE_COLETA" if db is None
                      else "LEDGER_LOCAL_AUDITADO_SEM_COMPROVAR_PROVENIENCIA_EXTERNA"),
        "datasets_auditados": len(data),
        "fontes_auditadas": len(fontes),
        "snapshots_sinteticos": sum(x["snapshots_sinteticos"] for x in data.values()) if db is not None else None,
        "snapshots_marcados_real": sum(x["snapshots_marcados_real"] for x in data.values()) if db is not None else None,
        "capturas_registradas": sum(x["capturas"] for x in data.values()) if db is not None else None,
        "problemas": problemas,
        "fontes": [fontes[k] for k in sorted(fontes)],
        "datasets": [data[k] for k in sorted(data)],
        "coleta_automatica_ativada": False,
        "volume_observacoes_reais_comprovado": None,
        "licenca_publicacao_comprovada": False,
    }


def _abrir_leitura(caminho: str) -> sqlite3.Connection:
    path = Path(caminho)
    if path.is_symlink() or not path.is_file():
        raise ErroAuditoriaLedger("banco deve existir e ser arquivo regular, sem symlink")
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True, timeout=5)
        db.execute("PRAGMA query_only=ON")
    except sqlite3.Error as exc:
        raise ErroAuditoriaLedger("não foi possível abrir ledger somente leitura") from exc
    return db


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON: status dos snapshots sem rede")
    parser.add_argument("--db", help="Banco local SQLite existente (somente leitura)")
    parser.add_argument("--prioridade", choices=("P0","P1","P2"))
    parser.add_argument("--gerado-em", help="Instante ISO com fuso (controle temporal)")
    parser.add_argument("--resumo", action="store_true")
    args = parser.parse_args(argv)
    db = None
    try:
        db = _abrir_leitura(args.db) if args.db else None
        out = auditar_cobertura_ledger(carregar_catalogo(),db,
                                      prioridade=args.prioridade,gerado_em=args.gerado_em)
        if args.resumo:
            out.pop("datasets")
            out.pop("fontes")
        print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True))
    except (OSError,sqlite3.Error,ValueError) as exc:
        parser.error(str(exc))
    finally:
        if db is not None:
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
