"""Ponte R11 -> RAW canônico do NIVON (GCS somente após opt-in separado).

Somente edições verificadas em bancos LAB/quarentena e bytes SHA-validos são
estagiados. O estágio mantém QUARANTINED, zero observações analíticas e dados
de terceiro explicitamente rotulados. NÃO executa HTTP/GCS/BigQuery.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import stat

from .arquivo_raw_gcs import preparar_manifesto
from .ingestao_fontes_reais import gravar_lote
from .sincronizacao_incremental_argentina_local import (
    _manifesto as manifesto_argentina, _auditar as auditar_argentina,
)
from .sincronizacao_incremental_conab_lab import _auditar_historico_local
from .auditoria_vintages_conab import validar_catalogo_vintages
from .lote_conab_integracao import _url_fixada

_MAX_OBJECTS = 60
_MAX_BYTES = 25_000_000
_DATASETS = {
    "ARG_SAGYP": "ARG_SAGYP_QUARENTENA",
    "CONAB_LAB": "CONAB_AGROBR_TERCEIRO",
}


class ErroPonteRaw(ValueError):
    pass


def _diretorio_privado(p: str | Path):
    path = Path(p)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ErroPonteRaw("diretório privado absoluto existente obrigatório")
    st = path.stat()
    if os.name == "posix" and (
        stat.S_IMODE(st.st_mode) & 0o077 or
        (hasattr(os, "getuid") and st.st_uid != os.getuid())
    ):
        raise ErroPonteRaw("diretório privado 0700 de propriedade do operador obrigatório")
    return path


def _arquivo_privado(p: Path):
    if p.is_symlink() or not p.is_file():
        raise ErroPonteRaw("RAW regular ausente ou symlink")
    st = p.stat()
    if os.name == "posix" and (
        stat.S_IMODE(st.st_mode) & 0o077 or
        (hasattr(os, "getuid") and st.st_uid != os.getuid())
    ):
        raise ErroPonteRaw("RAW requer modo 0600 e propriedade do operador")
    if not 0 < st.st_size <= _MAX_BYTES:
        raise ErroPonteRaw("RAW ausente ou acima do limite do arquivo canônico")
    return p


def _db_ro(path):
    db = _arquivo_privado(Path(path))
    # Só abrir leitura: nunca criar banco de origem por engano.
    return sqlite3.connect("file:" + db.as_posix() + "?mode=ro", uri=True)


def _sha_bytes(path: Path, expected):
    raw = _arquivo_privado(path).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ErroPonteRaw("RAW diferente do SHA auditado na origem")
    return raw


def _planejar_conab(info):
    if not isinstance(info, dict) or set(info) != {"catalogo", "banco", "raw_dir"}:
        raise ErroPonteRaw("configuração CONAB incompleta")
    edicoes = validar_catalogo_vintages(info["catalogo"])["edicoes"]
    pasta = _diretorio_privado(info["raw_dir"])
    planos = []
    with _db_ro(info["banco"]) as db:
        _auditar_historico_local(db)
        for item in edicoes:
            row = db.execute(
                "SELECT sha,competencia,origem,qtde FROM lab_referencia_conab "
                "WHERE referencia_id=?", (item["id"],),
            ).fetchone()
            if row is None or (
                row[0] != item["sha256"] or
                row[1] != item["competencia"] or
                row[2] != item["origem_repositorio"] or row[3] <= 0
            ):
                raise ErroPonteRaw("edição CONAB não confirmada no LAB")
            raw = _sha_bytes(pasta / item["arquivo"], item["sha256"])
            planos.append({
                "dataset": _DATASETS["CONAB_LAB"],
                "id": item["id"], "raw": raw, "sha": item["sha256"],
                # O byte vem de repositório terceiro fixado, não da CONAB oficial.
                "origem": _url_fixada(item),
                "coleta": datetime.now(timezone.utc).isoformat(),
                "mime": "application/octet-stream",
            })
    return planos


def _planejar_argentina(info):
    if not isinstance(info, dict) or set(info) != {"catalogo", "banco", "raw_dir"}:
        raise ErroPonteRaw("configuração Argentina incompleta")
    edicoes = manifesto_argentina(info["catalogo"])
    pasta = _diretorio_privado(info["raw_dir"])
    planos = []
    with _db_ro(info["banco"]) as db:
        auditar_argentina(db)
        for eid, recurso, digest, url, instante in edicoes:
            row = db.execute(
                "SELECT recurso,sha256,origen_url,recogido_utc,"
                "publicado_utc,disponibilidad_verificada FROM ar_ediciones "
                "WHERE edicion_id=?", (eid,),
            ).fetchone()
            if row is None or row[:4] != (recurso, digest, url, instante):
                raise ErroPonteRaw("edição Argentina não confirmada na quarentena")
            if row[4] is not None or row[5] != 0:
                raise ErroPonteRaw("edição Argentina mudou de estado e exige reauditoria")
            raw = _sha_bytes(pasta / (digest + ".csv"), digest)
            planos.append({
                "dataset": _DATASETS["ARG_SAGYP"],
                "id": eid, "raw": raw, "sha": digest,
                "origem": url, "coleta": instante,
                "mime": "text/csv",
            })
    return planos


def estagiar_raw_incremental(
    *, banco_stage: str | Path, pasta_stage: str | Path,
    conab: dict | None = None, argentina: dict | None = None,
    executar: bool = False, direitos_arquivamento_verificados: bool = False,
    bucket: str | None = None,
):
    """Consolida RAW auditado no formato já existente da GCS sem publicar.

    Cada fonte é independente; preflight de todas as versões antecede qualquer
    escrita. Após falha de disco, reexecução idempotente reconcilia por SHA.
    """
    fontes = [x for x, val in (("CONAB_LAB", conab), ("ARG_SAGYP", argentina))
              if val is not None]
    if not fontes:
        raise ErroPonteRaw("nenhuma fonte solicitada")
    if executar is not True:
        return {"estado": "PONTE_RAW_DESABILITADA",
                "fontes": fontes, "executado": False,
                "upload_gcs": False, "bigquery_executado": False}
    if direitos_arquivamento_verificados is not True:
        raise PermissionError("direitos de arquivamento de cada RAW não comprovados")
    planos = []
    if conab is not None:
        planos.extend(_planejar_conab(conab))
    if argentina is not None:
        planos.extend(_planejar_argentina(argentina))
    if not planos or len(planos) > _MAX_OBJECTS:
        raise ErroPonteRaw("quantidade de edições inválida para o estágio")
    target = Path(banco_stage)
    root = _diretorio_privado(pasta_stage)
    if not target.is_absolute() or target.is_symlink() or target.parent != root:
        raise ErroPonteRaw("banco de estágio deve ficar dentro da pasta privada")
    for fonte in fontes:
        pasta = root / _DATASETS[fonte]
        if pasta.is_symlink():
            raise ErroPonteRaw("pasta de dataset em symlink")
        pasta.mkdir(mode=0o700, exist_ok=True)
        _diretorio_privado(pasta)
    if not target.exists():
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
    _arquivo_privado(target) if target.stat().st_size else None
    resultados = []
    for e in planos:
        # Não exportar observações: ausência de data comprovada de publicação
        # bloqueia estágio analítico; somente RAW + metadados de provenance.
        out = gravar_lote(
            banco=target, diretorio_bruto=root,
            dataset_id=e["dataset"], origem=e["origem"], raw=e["raw"],
            tipo=e["mime"], coletado_em=e["coleta"],
            registros=(), estado="QUARANTINED",
        )
        with _db_ro(target) as db:
            row = db.execute(
                "SELECT estado,url_publica,sha256 FROM snapshots "
                "WHERE snapshot_id=?", (out["snapshot_id"],),
            ).fetchone()
            if row != ("QUARANTINED", e["origem"], e["sha"]):
                raise ErroPonteRaw("snapshot antigo divergente, promovido ou sem origem")
        resultados.append({
            "dataset":e["dataset"], "edicao":e["id"], "sha256":e["sha"],
            "snapshot_id":out["snapshot_id"],"estado":"QUARANTINED",
        })
    resultado = {"estado":"RAW_QUARENTENA_STAGE_LOCAL",
                 "executado":True,"quantidade":len(resultados),
                 "edicoes":resultados,
                 "observacoes_analiticas_criadas":0,
                 "bigquery_executado":False,"upload_gcs":False,
                 "publicacao_permitida":False,
                 "origem_conab_direta":False}
    if bucket is not None:
        manifest = preparar_manifesto(
            banco=target,raw_dir=root,bucket=bucket,
        )
        resultado["manifesto_gcs"] = {
            "bucket":manifest["bucket"],
            "objetos":manifest["quantidade"],
            "bytes":manifest["bytes_total"],"executado":False,
        }
    return resultado
