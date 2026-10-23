"""Conector BCB SGS11: fonte oficial -> RAW GCS -> estágio recuperável -> BQ.

Reutiliza EXCLUSIVAMENTE o núcleo canônico presente na branch main:
ingestao_fontes_reais, arquivo_raw_gcs, lote_cloud_recuperavel,
carga_bigquery_fontes e verificacao_cloud_fontes.

Não converte taxa diária em Selic-meta, não inventa data de publicação,
não cria recurso Cloud nem usa o histórico legado como dado atual.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .ingestao_fontes_reais import gravar_lote, exportar_jsonl
from .arquivo_raw_gcs import arquivar_gcs
from .lote_cloud_recuperavel import arquivar_stage
from .carga_bigquery_fontes import executar_carga
from .verificacao_cloud_fontes import verificar_publicacao
from .preflight_gcp_fontes import verificar_nuvem

URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json"
DATASET = "BCB_SGS_TAXA_SELIC_DIARIA"
OPERACOES = frozenset({"COLETA", "ARMAZENAMENTO", "PROCESSAMENTO"})
MAX_RAW = 250_000


class ErroSGSCloud(ValueError):
    pass


class _SemRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def coletar_http(*, abridor=None) -> bytes:
    """Aceita somente endpoint SGS11 fixo, HTTPS, sem redirect ou HTML/WAF."""
    client = abridor if abridor is not None else build_opener(_SemRedirecionar())
    req = Request(URL, headers={"Accept": "application/json",
                                "User-Agent": "NIVON/0.1 (serie-oficial-SGS11)"})
    with client.open(req, timeout=30) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ErroSGSCloud("HTTP status/redirect SGS11 inesperado")
        mime = str(response.headers.get("Content-Type", "")).split(";", 1)[0].lower().strip()
        if mime not in {"application/json", "text/json"}:
            raise ErroSGSCloud("BCB não retornou JSON oficial")
        raw = response.read(MAX_RAW + 1)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RAW:
        raise ErroSGSCloud("BCB retornou payload vazio ou excessivo")
    if raw.lstrip()[:16].lower().startswith((b"<html", b"<!doctype")):
        raise ErroSGSCloud("BCB respondeu HTML/WAF, não dados")
    return raw


def _sem_chaves_duplicadas(pares):
    d = {}
    for chave, valor in pares:
        if chave in d:
            raise ErroSGSCloud("JSON BCB com chave duplicada")
        d[chave] = valor
    return d


def normalizar(raw: bytes, *, coletado_em: datetime) -> list[dict]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RAW:
        raise ErroSGSCloud("JSON SGS11 vazio ou acima do limite")
    if not isinstance(coletado_em, datetime) or coletado_em.utcoffset() is None:
        raise ErroSGSCloud("data_coleta requer instante com fuso")
    agora = coletado_em.astimezone(timezone.utc)
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_sem_chaves_duplicadas)
    except (UnicodeError, ValueError) as exc:
        raise ErroSGSCloud("resposta oficial SGS11 inválida") from exc
    if not isinstance(payload, list) or not 1 <= len(payload) <= 31:
        raise ErroSGSCloud("BCB SGS11 sem linhas ou com volume inesperado")
    seen = set()
    obs = []
    for row in payload:
        if not isinstance(row, dict) or set(row) != {"data", "valor"}:
            raise ErroSGSCloud("linha SGS11 fora do contrato")
        s = row["data"]
        v = row["valor"]
        if not isinstance(s, str) or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
            raise ErroSGSCloud("data SGS11 inválida")
        try:
            d = datetime.strptime(s, "%d/%m/%Y").date()
        except ValueError as exc:
            raise ErroSGSCloud("data SGS11 impossível") from exc
        if d > agora.date() or d.isoformat() in seen:
            raise ErroSGSCloud("referência futura ou duplicada")
        seen.add(d.isoformat())
        if not isinstance(v, str) or not re.fullmatch(r"\d{1,3}(?:[,.]\d{1,12})?", v):
            raise ErroSGSCloud("taxa SGS11 sem formato decimal")
        try:
            number = Decimal(v.replace(",", "."))
        except InvalidOperation as exc:
            raise ErroSGSCloud("decimal SGS11 inválido") from exc
        if not number.is_finite() or not 0 <= number <= 10:
            raise ErroSGSCloud("taxa SGS11 fora dos limites")
        valor = format(number, "f")
        ref = d.isoformat()
        obs.append({
            "identidade": "BCB_SGS11|" + ref,
            "referencia": ref, "competencia": ref[:7],
            "publicacao": None,
            "natureza": "INFORMADO",
            "unidade": "PERCENTUAL_AO_DIA",
            "valor": valor,
            "campos": {
                "fonte": "BCB_SGS", "codigo_serie": 11,
                "data_referencia": ref, "valor_pct_ao_dia": valor,
                "data_publicacao_verificada": False,
                "nao_equivale_a_meta_selic_anual": True,
                "aprovado_para_publicacao_externa": False,
            },
        })
    return sorted(obs, key=lambda x: x["referencia"])


def executar_lote(*, base: str | Path, projeto: str, dataset: str, bucket: str,
                  executar: bool = False,
                  autorizacoes: frozenset[str] = frozenset(), evidencia: str = "",
                  agora: datetime | None = None, abridor=None, preflight=None,
                  raw_upload=None, stage_upload=None, bq_load=None, verificacao=None) -> dict:
    """E2E único e verificável. Apenas sucesso com retorno do verificador pós-carga."""
    if executar is not True or not OPERACOES <= set(autorizacoes):
        raise PermissionError("BCB SGS11: execução e operações não aprovadas")
    if not isinstance(evidencia, str) or len(evidencia.strip()) < 10:
        raise PermissionError("BCB SGS11: referência de direitos/uso ausente")
    base = Path(base)
    if base.is_symlink():
        raise ErroSGSCloud("diretório de trabalho não pode ser symlink")
    # Sempre validar a infraestrutura real ANTES de baixar a fonte.
    checker = preflight or verificar_nuvem
    pre = checker(projeto=projeto, dataset=dataset, bucket=bucket)
    if pre.get("tabela_validada") is not True or pre.get("bucket_existe") is not True:
        raise ErroSGSCloud("destino GCP sem tabela particionada e bucket verificados")
    tempo = agora or datetime.now(timezone.utc)
    if not isinstance(tempo, datetime) or tempo.utcoffset() is None:
        raise ErroSGSCloud("timestamp de execução deve ter fuso")
    tempo = tempo.astimezone(timezone.utc)
    raw = coletar_http(abridor=abridor)
    records = normalizar(raw, coletado_em=tempo)
    ledger = base / "fontes_reais.sqlite"
    raw_dir = base / "raw"
    registro = gravar_lote(
        banco=ledger, diretorio_bruto=raw_dir,
        dataset_id=DATASET, origem=URL, raw=raw, tipo="application/json",
        coletado_em=tempo.isoformat(), registros=records, estado="NORMALIZED",
    )
    archive = (raw_upload or arquivar_gcs)(
        banco=ledger, raw_dir=raw_dir, bucket=bucket, executar=True,
        fonte_dataset=DATASET, snapshot_ids=[registro["snapshot_id"]])
    if archive.get("executado") is not True:
        raise ErroSGSCloud("armazenamento RAW GCS não confirmado")
    arquivo = base / "sgs11_stage.jsonl"
    export = exportar_jsonl(
        banco=ledger, destino=arquivo,
        dataset_id=DATASET, snapshot_ids=[registro["snapshot_id"]])
    if export["observacoes"] < 1:
        raise ErroSGSCloud("sem observações exportadas, não gerar sucesso artificial")
    stage = (stage_upload or arquivar_stage)(
        banco=ledger, arquivo_jsonl=arquivo, bucket=bucket,
        projeto=projeto, dataset=dataset, executar=True)
    if stage.get("executado") is not True:
        raise ErroSGSCloud("stage/manifesto GCS não comprovado")
    carga = (bq_load or executar_carga)(
        arquivo=arquivo, project_id=projeto, dataset_id=dataset, executar=True)
    if carga.get("executado") is not True:
        raise ErroSGSCloud("MERGE BigQuery não confirmado")
    conferido = (verificacao or verificar_publicacao)(
        banco=ledger, raw_dir=raw_dir, bucket=bucket,
        arquivo_jsonl=arquivo, project_id=projeto, dataset_id=dataset,
        executar=True)
    if conferido.get("executado") is not True or (
            conferido.get("amostras_bigquery_confirmadas", 0) < 1):
        raise ErroSGSCloud("pós-carga não provou RAW e dados no BigQuery")
    return {
        "status": "GCS_BIGQUERY_CONFERIDOS",
        "dataset_id": DATASET,
        "observacoes": export["observacoes"],
        "novas_observacoes_locais": registro["novas_observacoes"],
        "snapshot_id": registro["snapshot_id"],
        "sha256_original": registro["sha256"],
        "manifesto_sha256": stage["manifesto_sha256"],
        "bigquery_executado": True,
        "bigquery_amostras_conferidas": conferido["amostras_bigquery_confirmadas"],
        "publicacao_externa": False,
        "taxa_equivale_meta_selic_anual": False,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="NIVON: SGS11 oficial -> RAW GCS -> BigQuery e verificação")
    p.add_argument("--base", default="data/nivon/sgs11")
    p.add_argument("--executar", action="store_true")
    a = p.parse_args(argv)
    if not a.executar:
        print(json.dumps({
            "status": "PLANO_SEM_REDE", "dataset_id": DATASET,
            "passos": ["WIF+BQ_PREFLIGHT", "BCB_SGS11", "SQLITE_RAW",
                       "GCS_RAW", "GCS_MANIFESTO", "BIGQUERY_MERGE", "BQ_GCS_READBACK"],
            "cloud_executado": False,
        }, ensure_ascii=False))
        return 0
    env = os.environ
    if any(env.get(key) != "true" for key in (
        "NIVON_SGS11_GCP_WRITE_APPROVED",
        "NIVON_ZERO_COST_BQ_APPROVED", "NIVON_RAW_ARCHIVE_APPROVED",
    )):
        raise PermissionError("BCB SGS11: gates de escrita/custos/RAW fechados")
    projeto, dataset, bucket = (
        env.get("NIVON_BQ_PROJECT"), env.get("NIVON_BQ_DATASET"),
        env.get("NIVON_GCS_BUCKET"),
    )
    resultado = executar_lote(
        base=a.base, projeto=projeto, dataset=dataset, bucket=bucket,
        executar=True, autorizacoes=OPERACOES,
        evidencia=env.get("NIVON_SGS11_EVIDENCIA_USO", ""))
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
