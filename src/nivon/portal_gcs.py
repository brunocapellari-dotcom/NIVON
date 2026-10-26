"""Leitura GCS do snapshot privado do NIVON, com fail-closed e cache limitado.

Não libera acesso público; a autenticação de pessoas é responsabilidade do
Cloud Run com IAM. Este código só usa a identidade da service account (ADC).
Nunca armazena credenciais nem oferece URLs assinadas.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
import re
from threading import Lock
from time import monotonic

from .portal_interno import (ErroPortal, MAX_INPUT, _json_unico,
                             validar_snapshot, criar_app)

PROJECT="nivon-data"
BUCKET="nivon-data-raw-2026"
OBJECT="interno/nivon/portal/v1/painel.json"
SHA=re.compile(r"[a-f0-9]{64}\Z")


class LeitorSnapshotGCS:
    """Uma única leitura consistente por geração; erro interrompe a publicação.

    Reuso positivo de até 60s evita cobrança de leitura do bucket em cada
    polling do navegador. Nunca conserva snapshot vencido após uma falha.
    """

    def __init__(self, *, projeto: str, bucket: str,
                 cliente_factory=None, relogio=monotonic, cache_segundos=60):
        if projeto != PROJECT or bucket != BUCKET:
            raise ErroPortal("projeto/bucket nao autorizados")
        if type(cache_segundos) is not int or not 0 <= cache_segundos <= 60:
            raise ErroPortal("cache fora do limite")
        self.projeto=projeto
        self.bucket=bucket
        self._factory=cliente_factory
        self._relogio=relogio
        self._ttl=cache_segundos
        self._lock=Lock()
        self._ultimo=None
        self._doc=None

    def carregar(self) -> dict:
        agora=self._relogio()
        with self._lock:
            if self._doc is not None and self._ultimo is not None and (
                    0 <= agora-self._ultimo < self._ttl):
                return self._doc
            self._doc=None
            self._ultimo=None
            try:
                if self._factory is None:
                    from google.cloud import storage
                    factory=storage.Client
                else:
                    factory=self._factory
                cli=factory(project=self.projeto)
                bucket=cli.get_bucket(self.bucket)
                if str(getattr(bucket,"location","")).lower()!="southamerica-east1":
                    raise ErroPortal("bucket fora da regiao NIVON")
                blob=bucket.blob(OBJECT)
                blob.reload(timeout=15)
                meta=blob.metadata
                length=blob.size
                generation=blob.generation
                if (not isinstance(meta,dict)
                        or meta.get("nivon_modo")!="INTERNO_SHADOW"
                        or not isinstance(meta.get("sha256"),str)
                        or not SHA.fullmatch(meta["sha256"])
                        or type(length) is not int or not 0 < length <= MAX_INPUT
                        or not isinstance(generation,(int,str))
                        or not str(generation).isdigit()
                        or int(generation) <= 0
                        or getattr(blob,"content_type",None)!="application/json"):
                    raise ErroPortal("metadados privados inconsistentes")
                data=blob.download_as_bytes(if_generation_match=int(generation),
                                            timeout=15,checksum="crc32c")
                if not isinstance(data,bytes) or len(data)!=length:
                    raise ErroPortal("download incompleto")
                if sha256(data).hexdigest()!=meta["sha256"]:
                    raise ErroPortal("integridade do snapshot divergente")
                doc=json.loads(data.decode("utf-8"),
                               object_pairs_hook=_json_unico,
                               parse_constant=lambda _: (_ for _ in ()).throw(ErroPortal("NaN proibido")))
                validado=validar_snapshot(doc)
            except Exception as exc:
                # Nunca expor detalhes GCP/IAM/identidade ou bytes ao navegador.
                raise ErroPortal("snapshot privado indisponivel ou invalido") from exc
            self._doc=validado
            self._ultimo=agora
            return validado


def criar_app_cloud(*, env=None, cliente_factory=None, relogio=monotonic):
    vars=os.environ if env is None else env
    obrigatorias=(
        "NIVON_PORTAL_PRIVATE_INGRESS_APPROVED",
        "NIVON_PORTAL_GCS_READ_APPROVED",
        "NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED",
    )
    if (any(vars.get(k)!="true" for k in obrigatorias)
            or vars.get("GOOGLE_CLOUD_PROJECT")!=PROJECT
            or vars.get("NIVON_PORTAL_GCS_BUCKET")!=BUCKET
            or vars.get("K_SERVICE")!="nivon-portal-interno"):
        raise ErroPortal("runtime cloud nao autorizado ou fora do destino")
    leitor=LeitorSnapshotGCS(projeto=PROJECT,bucket=BUCKET,
                             cliente_factory=cliente_factory,relogio=relogio)
    return criar_app(None,leitor_snapshot=leitor.carregar)


# Gunicorn somente importa este módulo na revisão Cloud Run com gates.
application=criar_app_cloud() if os.environ.get("K_SERVICE")=="nivon-portal-interno" else None
