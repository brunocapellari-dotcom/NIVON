"""Leitor do snapshot operacional REAL no bucket privado do NIVON.

Contrato: BigQuery -> coletor já existente -> GCS privado verificado -> terminal.
O terminal não cria tabelas, executa SQL, busca dados externos nem calcula valores.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import threading
import time

from .portal_interno import ErroPortal, MAX_INPUT, _json_unico, _tempo, validar_snapshot
from .transporte_multimodal import ErroTransporte

PROJECT = "nivon-data"
BUCKET = "nivon-data-raw-2026"
OBJECT = "interno/nivon/portal/v1/painel.json"
REGION = "southamerica-east1"
TTL = 300
MAX_AGE = timedelta(hours=24)
MAX_FUTURE = timedelta(minutes=5)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LeituraSnapshotBloqueada(ErroTransporte):
    """Nao retornar dados supostamente atuais sem prova da origem privada."""


def ler_gcs(*, storage_client=None, relogio=None) -> dict:
    """Somente metadados + GET privado, limitado, com integridade e proveniência."""
    instante = (relogio or (lambda: datetime.now(timezone.utc)))()
    if not isinstance(instante, datetime) or instante.utcoffset() is None:
        raise LeituraSnapshotBloqueada("relogio sem fuso")

    if storage_client is None:
        from google.cloud import storage
        storage_client = storage.Client(project=PROJECT)
    bucket = storage_client.get_bucket(BUCKET)
    pap = getattr(getattr(bucket, "iam_configuration", None),
                  "public_access_prevention", None)
    if (str(bucket.location).lower() != REGION or pap != "enforced"):
        raise LeituraSnapshotBloqueada("bucket privado/regiao nao comprovado")
    blob = bucket.blob(OBJECT)
    blob.reload()
    size = blob.size
    meta = blob.metadata or {}
    fingerprint = meta.get("sha256")
    if (type(size) is not int or not 0 < size <= MAX_INPUT
            or not isinstance(fingerprint, str) or not HEX64.fullmatch(fingerprint)
            or meta.get("nivon_modo") != "INTERNO_SHADOW"
            or not isinstance(blob.generation, int) or blob.generation < 1):
        raise LeituraSnapshotBloqueada("snapshot sem metadados seguros")
    # A geração elimina leitura de outra revisão entre HEAD e GET.
    raw = blob.download_as_bytes(if_generation_match=blob.generation)
    if len(raw) != size or sha256(raw).hexdigest() != fingerprint:
        raise LeituraSnapshotBloqueada("integridade GCS divergente")
    try:
        doc = json.loads(raw.decode("utf-8"),
                         object_pairs_hook=_json_unico,
                         parse_constant=lambda _: (_ for _ in ()).throw(
                             LeituraSnapshotBloqueada("constante JSON invalida")))
        validado = validar_snapshot(doc)
        coleta = _tempo(validado["gerado_em"])
    except (UnicodeError, ValueError, KeyError, TypeError, ErroPortal) as exc:
        raise LeituraSnapshotBloqueada("contrato do snapshot invalido") from exc
    atraso = instante.astimezone(timezone.utc) - coleta
    if atraso < -MAX_FUTURE or atraso > MAX_AGE:
        raise LeituraSnapshotBloqueada("snapshot ausente de janela recente")
    if not validado["indicadores"]:
        raise LeituraSnapshotBloqueada("snapshot sem indicadores reais")
    return {**validado, "frescor_snapshot": "ATUAL",
            "origem_terminal": "GCS_PRIVADO_COM_SHA256",
            "snapshot_sha256": fingerprint}


class EstadoSnapshot:
    """Cache somente de snapshot integro e recente; falha nao vira ultimo dado."""

    def __init__(self, *, reader=ler_gcs, relogio=time.monotonic):
        self.reader = reader
        self.relogio = relogio
        self._lock = threading.Lock()
        self._data = None
        self._expires = 0.0

    def obter(self):
        with self._lock:
            now = self.relogio()
            if self._data is None or now >= self._expires:
                # Não servir conteúdo expirado se a leitura falhar.
                self._data = None
                self._expires = 0.0
                result = self.reader()
                if (result.get("frescor_snapshot") != "ATUAL"
                        or result.get("go_live_publico") is not False):
                    raise LeituraSnapshotBloqueada("snapshot nao homologado")
                self._data = result
                self._expires = now + TTL
            return self._data
