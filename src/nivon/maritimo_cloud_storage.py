"""Snapshots historicos do NIVON no Cloud Storage com identidade de conteudo.

GCS e camada de evidencias; BigQuery contem registros estruturados.
Autenticacao por ADC da service account do Cloud Run, sem chave JSON.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

class ArquivoMaritimoGCS:
    def __init__(self, bucket, *, prefixo="nivon/maritimo/raw", storage_client=None):
        if not isinstance(bucket,str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,61}[a-z0-9]",bucket):
            raise ValueError("bucket invalido")
        if not isinstance(prefixo,str) or not re.fullmatch(r"[a-zA-Z0-9_/-]{1,100}",prefixo):
            raise ValueError("prefixo de evidencias invalido")
        if storage_client is None:
            from google.cloud import storage
            storage_client=storage.Client()
        self.bucket=storage_client.bucket(bucket)
        self.nome_bucket=bucket
        self.prefixo=prefixo.strip("/")

    def arquivar(self, fonte, dados, *, coletado_em):
        if not isinstance(fonte,str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,65}",fonte):
            raise ValueError("fonte fora da allowlist de nomes")
        if not isinstance(dados,(str,bytes)):
            raise TypeError("snapshot deve ser str ou bytes")
        raw=dados.encode("utf-8") if isinstance(dados,str) else dados
        if not raw or len(raw)>2_000_000:
            raise ValueError("snapshot vazio ou excede limite")
        parsed=datetime.fromisoformat(coletado_em.replace("Z","+00:00"))
        if parsed.tzinfo is None:raise ValueError("coleta sem fuso")
        digest=hashlib.sha256(raw).hexdigest()
        kind="html" if isinstance(dados,str) else "json"
        path=f"{self.prefixo}/{fonte}/{digest}.{kind}"
        blob=self.bucket.blob(path)
        blob.metadata={"sha256":digest,"fonte":fonte,
                       "data_coleta":parsed.astimezone(timezone.utc).isoformat(),
                       "formato":"html_decodificado_utf8" if kind=="html" else "bytes_origem"}
        try:
            blob.upload_from_string(raw,content_type=("text/html; charset=utf-8" if kind=="html"
                                  else "application/json"),if_generation_match=0)
        except Exception as exc:
            # Objeto imutavel existente: somente aceitar replay quando
            # o hash cadastrado do objeto corresponde aos bytes enviados.
            from google.api_core.exceptions import PreconditionFailed
            if not isinstance(exc,PreconditionFailed):
                raise
            blob.reload()
            if (blob.metadata or {}).get("sha256")!=digest:
                raise RuntimeError("snapshot existente diverge do hash") from exc
        return {"uri":f"gs://{self.nome_bucket}/{path}","sha256":digest}
