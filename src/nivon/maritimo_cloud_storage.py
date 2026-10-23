"""Snapshots historicos do NIVON no Cloud Storage com identidade de conteudo.

GCS e camada de evidencias; BigQuery contem registros estruturados.
Autenticacao por ADC da service account do Cloud Run, sem chave JSON.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
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

    def gravar_manifesto(self, *, run_id, snapshots, execucoes, portwatch_estado=None):
        """Indice imutavel ANTES de gravar no BigQuery, para replay auditavel."""
        try:
            run_id=str(uuid.UUID(str(run_id)))
        except (ValueError,AttributeError) as exc:
            raise ValueError("run_id invalido") from exc
        if len(snapshots)>24 or len(execucoes)>20:
            raise ValueError("manifesto excede o limite")
        for item in snapshots:
            if not {"fonte","uri","sha256","coletado_em"} <= item.keys():
                raise ValueError("snapshot incompleto")
            self._validar_evidencia(item)
        for e in execucoes:
            if e.get("estado") not in ("OK","QUARENTENA","FALHA"):
                raise ValueError("estado de execucao desconhecido")
            try:
                uuid.UUID(str(e["run_id"]))
            except (KeyError,ValueError,TypeError) as exc:
                raise ValueError("execucao sem UUID valido") from exc
            if e.get("fonte")=="FMI_PORTWATCH":
                continue
            if e.get("run_id")!=run_id:
                raise ValueError("execucao nao pertence ao lote")
        if portwatch_estado not in (None,"OK","QUARENTENA","FALHA"):
            raise ValueError("estado PortWatch invalido")
        manifest={"schema_version":1,"run_id":run_id,
                  "snapshots":snapshots,"execucoes":execucoes,
                  "portwatch_estado":portwatch_estado}
        raw=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
        if len(raw)>80000:
            raise ValueError("manifesto grande")
        path=f"{self.prefixo}/_manifestos/{run_id}.json"
        blob=self.bucket.blob(path)
        digest=hashlib.sha256(raw).hexdigest()
        blob.metadata={"sha256":digest,"tipo":"manifesto_nivon_v1"}
        blob.upload_from_string(raw,content_type="application/json",if_generation_match=0)
        return f"gs://{self.nome_bucket}/{path}"

    def _validar_evidencia(self, item):
        fonte=item["fonte"]
        sha=item["sha256"]
        fmt="json" if fonte=="fmi_portwatch" else "html"
        if not isinstance(fonte,str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,65}",fonte):
            raise ValueError("fonte invalida")
        if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{64}",sha):
            raise ValueError("hash invalido")
        if item["uri"]!=f"gs://{self.nome_bucket}/{self.prefixo}/{fonte}/{sha}.{fmt}":
            raise ValueError("objeto fora do namespace autorizado")
        timestamp=datetime.fromisoformat(item["coletado_em"].replace("Z","+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("data_coleta sem fuso")
        return f"{self.prefixo}/{fonte}/{sha}.{fmt}"

    def ler_evidencia(self,item):
        path=self._validar_evidencia(item)
        raw=self.bucket.blob(path).download_as_bytes()
        if not raw or len(raw)>2_000_000:
            raise ValueError("snapshot GCS excede limite")
        if hashlib.sha256(raw).hexdigest()!=item["sha256"]:
            raise ValueError("snapshot GCS corrompido; hash diferente")
        return raw

    def ler_manifesto(self, uri):
        prefix=f"gs://{self.nome_bucket}/{self.prefixo}/_manifestos/"
        if not isinstance(uri,str) or not uri.startswith(prefix):
            raise ValueError("manifesto fora do bucket/prefixo")
        name=uri[len(prefix):]
        if not re.fullmatch(r"[0-9a-f-]{36}\.json",name):
            raise ValueError("nome de manifesto invalido")
        blob=self.bucket.blob(f"{self.prefixo}/_manifestos/{name}")
        raw=blob.download_as_bytes()
        if len(raw)>80000:
            raise ValueError("manifesto muito grande")
        blob.reload()
        actual=hashlib.sha256(raw).hexdigest()
        if (blob.metadata or {}).get("sha256")!=actual:
            raise ValueError("manifesto GCS adulterado; hash nao confere")
        manifest=json.loads(raw)
        if manifest.get("schema_version")!=1 or manifest.get("run_id")!=name[:-5]:
            raise ValueError("manifesto desconhecido ou id incorreto")
        if len(manifest.get("snapshots",()))>24 or len(manifest.get("execucoes",()))>20:
            raise ValueError("manifesto excede limites")
        for item in manifest["snapshots"]:
            self._validar_evidencia(item)
        return manifest
