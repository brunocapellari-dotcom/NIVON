"""Ciclo integral RONI offline: lote atômico, relatório comparativo e backup.

Orquestra componentes já existentes, sem coletor recorrente nem forecast ENSO.
O RAW contém edições retrospectivas; só a primeira observação no NIVON é
um fato local datado. Nunca reconstruir publicações históricas NOAA a partir
de valores atuais.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .noaa_roni import ErroRONI, importar_roni_ascii
from .roni_store import (
    _safe_dir, _guard_raw, _tempo, abrir_arquivo_roni, executar_lote_roni,
    auditar_acervo_roni, consultar_arquivo_roni,
)
from .transacoes_sqlite import savepoint_atomico


def processar_ciclo_roni(db, *, raw_dir, itens):
    """Aplica até 50 arquivos pré-validados como UMA transação SQLite.

    Se qualquer edição falhar, todas as linhas novas são revertidas. Arquivos
    RAW criados por este ciclo e sem referência na base são limpos. Requer
    diretório RAW dedicado a este banco e execução serializada pelo operador.
    """
    if not isinstance(db, sqlite3.Connection):
        raise ErroRONI("banco SQLite obrigatório")
    if not isinstance(itens, list) or not 1 <= len(itens) <= 50:
        raise ErroRONI("ciclo requer 1 a 50 arquivos pré-validados")
    for item in itens:
        if not isinstance(item, dict) or not all(k in item for k in
            ("raw", "coletado_em", "classe", "sha256", "filename")):
            raise ErroRONI("manifesto pré-validado incompleto")
        if not isinstance(item["raw"], bytes) or sha256(item["raw"]).hexdigest() != item["sha256"]:
            raise ErroRONI("bytes mudaram depois do preflight")
    root = _safe_dir(raw_dir)
    existing_raw = {p.name for p in root.glob("*.ascii")}
    prior = db.execute("SELECT COUNT(*) FROM roni_snapshots").fetchone()[0]
    results = []
    try:
        with savepoint_atomico(db):
            for item in itens:
                result = executar_lote_roni(
                    db, raw_dir=root, raw=item["raw"],
                    coletado_em=item["coletado_em"], classe=item["classe"])
                results.append({"arquivo": item["filename"], **result})
            # Verificação dentro da mesma transação: DB/RAW precisam concordar
            # antes do aceite; falhas revertem todas as edições do ciclo.
            audit = auditar_acervo_roni(db, raw_dir=root)
    except BaseException:
        # Preserva os RAWs preexistentes; remove apenas artefatos novos não
        # referenciados após o rollback. Não apagar arquivo de outra captura.
        referenced = {row[0] + ".ascii" for row in db.execute(
            "SELECT sha256 FROM roni_snapshots")}
        for p in root.glob("*.ascii"):
            if p.name not in existing_raw and p.name not in referenced:
                if not p.is_symlink() and p.is_file():
                    p.unlink()
        raise
    after = db.execute("SELECT COUNT(*) FROM roni_snapshots").fetchone()[0]
    return {
        "estado": "LOTES_PERSISTIDOS_OFFLINE_NAO_HOMOLOGADOS",
        "lote_atomico": True,
        "lotes_processados": len(results), "snapshots_novos": after-prior,
        "resultados": results, "auditoria": audit,
        "atualizacao_em_lote_confirmada": True,
        "http": 0, "agendamento": False, "publicacao": False,
        "homologado": False,
    }


def relatorio_revisoes_roni(db, *, raw_dir, classe="SINTETICO", corte_em=None):
    """Compara as duas últimas versões ATIVAS conhecidas no corte local.

    Não indica movimento meteorológico ou mudança atual do clima; compara
    apenas dados retroativos de duas edições observadas pelo NIVON.
    """
    if classe not in ("SINTETICO", "EXTERNO_NAO_HOMOLOGADO"):
        raise ErroRONI("classe de histórico desconhecida")
    cutoff = _tempo(corte_em, "corte") if corte_em is not None else datetime.now(timezone.utc)
    rows = db.execute(
        "SELECT c.sha256,c.visto_nivon_em_utc FROM roni_capturas c "
        "JOIN roni_snapshots s ON s.sha256=c.sha256 "
        "WHERE s.classe=? AND c.visto_nivon_em_utc<=? "
        "ORDER BY c.visto_nivon_em_utc DESC,c.sha256 DESC LIMIT 500",
        (classe, cutoff.isoformat())
    ).fetchall()
    unique = []
    for row in rows:
        if not unique or unique[-1]["sha256"] != row["sha256"]:
            unique.append(dict(row))
        if len(unique) == 2:
            break
    if not unique:
        return {"estado": "SEM_EDICAO_NO_CORTE", "classe": classe,
                "homologado": False, "previsao_validada": False}
    root = _safe_dir(raw_dir, criar=False)
    current = unique[0]
    _guard_raw(root, current["sha256"])
    last_values = {x["competencia"]: float(x["anomalia"]) for x in db.execute(
        "SELECT competencia,anomalia FROM roni_valores WHERE sha256=?",
        (current["sha256"],))}
    prev = unique[1] if len(unique) > 1 else None
    previous_values = {}
    if prev:
        _guard_raw(root, prev["sha256"])
        previous_values = {x["competencia"]: float(x["anomalia"]) for x in db.execute(
            "SELECT competencia,anomalia FROM roni_valores WHERE sha256=?",
            (prev["sha256"],))}
    changes = [
        {"competencia": period, "anterior_c": previous_values[period],
         "atual_c": last_values[period],
         "diferenca_c": round(last_values[period]-previous_values[period], 4)}
        for period in sorted(last_values)
        if period in previous_values and last_values[period] != previous_values[period]
    ]
    new = [k for k in sorted(last_values) if k not in previous_values]
    latest_period = max(last_values)
    return {
        "estado": "RELATORIO_DE_REVISOES_DESCRITIVO",
        "classe": classe, "corte_utc": cutoff.isoformat(),
        "snapshot_mais_recente_sha256": current["sha256"],
        "snapshot_anterior_sha256": prev["sha256"] if prev else None,
        "edicao_ativa_desde": current["visto_nivon_em_utc"],
        "ultima_competencia": latest_period,
        "ultimo_roni_c": last_values[latest_period],
        "temporadas_conhecidas": len(last_values),
        "competencias_novas": len(new) if prev else len(last_values),
        "competencias_revisadas": len(changes),
        "maior_revisao_absoluta_c": max(
            (abs(x["diferenca_c"]) for x in changes), default=0.0),
        "amostra_revisoes": changes[:12],
        "revisoes_adicionais_nao_exibidas": max(0, len(changes)-12),
        "edicao_comparavel_anterior": prev is not None,
        "fonte_retrospetiva": True,
        "vintage_historico_externo_comprovado": False,
        "resultado_enso_preditivo": False,
        "homologado": False,
    }


def gerar_backup_roni(db, *, raw_dir, destino):
    """Exporta DB e todos os RAWs para pasta nova, verificando a restauração.

    Não toca na base original. Backup consistente requer operação serializada;
    processo não compartilha pasta RAW com outro writer simultâneo.
    """
    if not isinstance(db, sqlite3.Connection):
        raise ErroRONI("banco SQLite obrigatório")
    target = Path(destino)
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        raise ErroRONI("destino de backup deve ser pasta NOVA, sob diretório existente")
    source = _safe_dir(raw_dir, criar=False)
    status = auditar_acervo_roni(db, raw_dir=source)
    if status["estado"] != "ACERVO_LOCAL_INTEGRO_NAO_HOMOLOGADO":
        raise ErroRONI("backup de histórico vazio bloqueado")
    staging = Path(tempfile.mkdtemp(prefix=".nivon-roni-backup-", dir=target.parent))
    try:
        (staging / "raw").mkdir(mode=0o700)
        dest_db = abrir_arquivo_roni(staging / "roni.sqlite")
        try:
            db.backup(dest_db)
        finally:
            dest_db.close()
        for row in db.execute("SELECT sha256 FROM roni_snapshots"):
            name = row[0] + ".ascii"
            shutil.copyfile(source / name, staging / "raw" / name)
        check = abrir_arquivo_roni(staging / "roni.sqlite")
        try:
            restored = auditar_acervo_roni(check, raw_dir=staging / "raw")
        finally:
            check.close()
        if (restored["snapshots_auditados"] != status["snapshots_auditados"]
                or restored["registros_validados"] != status["registros_validados"]):
            raise ErroRONI("backup não reproduziu o acervo de origem")
        manifest = {
            "tipo": "BACKUP_LOCAL_RONI", "schema": "1.0",
            "db_sha256": sha256((staging / "roni.sqlite").read_bytes()).hexdigest(),
            "raw_sha256": sorted(x[0] for x in db.execute(
                "SELECT sha256 FROM roni_snapshots")),
            "auditoria": restored,
            "homologado": False, "coleta_autorizada": False,
        }
        (staging / "manifesto_backup.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        staging.rename(target)
        return {"estado": "BACKUP_LOCAL_VERIFICADO_NAO_HOMOLOGADO",
                "local": str(target), "snapshots": status["snapshots_auditados"],
                "registros": status["registros_validados"],
                "db_sha256": manifest["db_sha256"],
                "homologado": False}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def validar_backup_roni(*, caminho):
    """Confere backup sem alterar seus bytes ou criar estrutura faltante."""
    root = Path(caminho)
    if root.is_symlink() or not root.is_dir():
        raise ErroRONI("backup ausente ou symlink")
    mf = root / "manifesto_backup.json"
    dbpath = root / "roni.sqlite"
    if mf.is_symlink() or dbpath.is_symlink() or not mf.is_file() or not dbpath.is_file():
        raise ErroRONI("backup não contém manifesto e banco seguros")
    try:
        m = json.loads(mf.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ErroRONI("manifesto do backup inválido") from exc
    if (m.get("tipo") != "BACKUP_LOCAL_RONI" or m.get("schema") != "1.0" or
            m.get("db_sha256") != sha256(dbpath.read_bytes()).hexdigest()):
        raise ErroRONI("backup SQLite divergente do manifesto")
    uri = dbpath.resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    try:
        audit = auditar_acervo_roni(db, raw_dir=root / "raw")
        current = sorted(row[0] for row in db.execute("SELECT sha256 FROM roni_snapshots"))
        if (current != m["raw_sha256"] or
                audit["snapshots_auditados"] != m["auditoria"]["snapshots_auditados"] or
                audit["registros_validados"] != m["auditoria"]["registros_validados"]):
            raise ErroRONI("backup com valores divergentes do manifesto")
    finally:
        db.close()
    return {"estado": "BACKUP_RESTAURAVEL_VALIDADO",
            "snapshots": audit["snapshots_auditados"],
            "registros": audit["registros_validados"],
            "homologado": False}
