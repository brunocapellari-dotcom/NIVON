"""Exportação ANP/LPC para bucket privado do Google Cloud Storage.

Permite usar o staging SQLite local como camada de preparação, exportando
RAW original + versões normalizadas para objetos imutáveis por SHA-256.
Não cria projeto, bucket, credenciais, serviços, custo nem agendamento.

A função exige bucket GCS já configurado, privado e com prevenção pública
ENFORCED; identidade e concessão de acesso são responsabilidade da nuvem.
Dados permanecem PRELIMINARES; não promove a publicação de preços.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .anp_lpc_staging_real import auditar_arquivos_origem_lpc
from .anp_semanal_store import _tempo


class ErroGCSANP(PermissionError):
    pass


def _json_deterministico(objeto: Any) -> bytes:
    return (json.dumps(objeto, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def _validar_destino(bucket, prefixo: str) -> str:
    if (not isinstance(prefixo, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9/_-]{1,120}", prefixo)
            or "//" in prefixo or prefixo.endswith("/")
            or any(p in {"", ".", ".."} for p in prefixo.split("/"))):
        raise ErroGCSANP("prefixo de armazenamento inválido")
    nome = getattr(bucket, "name", None)
    configuracao = getattr(bucket, "iam_configuration", None)
    prevencao = getattr(configuracao, "public_access_prevention", None)
    if not isinstance(nome, str) or not nome.strip() or prevencao != "enforced":
        raise ErroGCSANP("bucket precisa existir e ter bloqueio de acesso público ENFORCED")
    return prefixo


def _gravar_objeto(bucket, *, chave: str, sha: str, tipo: str,
                   conteudo: bytes | None = None,
                   caminho: Path | None = None) -> bool:
    if (conteudo is None) == (caminho is None):
        raise ErroGCSANP("objeto deve vir de bytes OU caminho verificado")
    blob=bucket.blob(chave)
    if blob.exists():
        blob.reload()
        metadata=blob.metadata or {}
        if metadata.get("sha256") != sha:
            raise ErroGCSANP(f"colisão de objeto ou conteúdo sem hash de proveniência: {chave}")
        return False
    blob.metadata={
        "sha256":sha,
        "classificacao":"REAL_PRELIMINAR_NAO_HOMOLOGADO",
        "fonte":"ANP_LPC",
        "publicavel":"false",
    }
    if conteudo is not None:
        if sha256(conteudo).hexdigest() != sha:
            raise ErroGCSANP("conteúdo de exportação divergente do SHA")
        blob.upload_from_string(
            conteudo, content_type=tipo, if_generation_match=0,
        )
    else:
        if (caminho is None or caminho.is_symlink()
                or not caminho.is_file()
                or sha256(caminho.read_bytes()).hexdigest() != sha):
            raise ErroGCSANP("RAW local ausente, simbólico ou divergente")
        blob.upload_from_filename(
            str(caminho), content_type=tipo, if_generation_match=0,
        )
    return True


def exportar_lpc_staging_gcs(
    db: sqlite3.Connection, *, raiz_raw: str,
    bucket, as_of: str, prefixo: str = "nivon/anp/lpc/v1",
) -> dict:
    """Backup privado idempotente de vintages e evidências originais.

    Primeiro valida todos os hashes locais; depois cria objetos imutáveis
    sem sobrescrever versões anteriores. A operação NÃO é uma transação
    distribuída: em caso de interrupção, reexecutar para completar itens
    restantes, com if_generation_match=0.
    """
    _validar_destino(bucket,prefixo)
    corte=_tempo(as_of,"as_of")
    estado=auditar_arquivos_origem_lpc(
        db, raiz_raw=raiz_raw, as_of=corte.isoformat(),
    )
    if estado["status"] != "RAW_VERIFICADO_LOCALMENTE":
        raise ErroGCSANP("RAW não íntegro; sincronização bloqueada")
    if estado["edicoes_consultadas"] == 0:
        raise ErroGCSANP("base sem edição real para exportar")
    raiz=Path(raiz_raw).resolve()
    db.row_factory=sqlite3.Row
    edicoes=db.execute("""
      SELECT * FROM anp_lpc_staging_edicoes e
      WHERE EXISTS(SELECT 1 FROM anp_lpc_staging_capturas c
                   WHERE c.sha256=e.sha256 AND c.capturado_em<=?)
      ORDER BY e.semana_fim, e.sha256
    """,(corte.isoformat(),)).fetchall()
    snapshots=db.execute("""
      SELECT DISTINCT indice_sha256 FROM anp_lpc_staging_indices
      WHERE capturado_indice_em<=? ORDER BY indice_sha256
    """,(corte.isoformat(),)).fetchall()
    novos=0; ja_existentes=0; objetos=0
    def enviar(chave,sha,tipo,**kwargs):
        nonlocal novos,ja_existentes,objetos
        if _gravar_objeto(bucket,chave=chave,sha=sha,tipo=tipo,**kwargs):
            novos+=1
        else:
            ja_existentes+=1
        objetos+=1

    for item in snapshots:
        sha=item["indice_sha256"]
        enviar(f"{prefixo}/indices/{sha}.html",sha,"text/html",
               caminho=raiz/"indices"/f"{sha}.html")
    for ed in edicoes:
        sha=ed["sha256"]
        enviar(f"{prefixo}/planilhas/{sha}.xlsx",sha,
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               caminho=raiz/"planilhas"/f"{sha}.xlsx")
        obs=db.execute("""
            SELECT uf,municipio,produto,preco_medio_rs_l,postos_pesquisados
            FROM anp_lpc_staging_observacoes WHERE sha256=?
            ORDER BY uf,municipio,produto""",(sha,)).fetchall()
        capturas=db.execute("""
            SELECT capturado_em FROM anp_lpc_staging_capturas
            WHERE sha256=? AND capturado_em<=? ORDER BY capturado_em""",
            (sha,corte.isoformat())).fetchall()
        indices=db.execute("""
            SELECT indice_sha256,capturado_indice_em
            FROM anp_lpc_staging_indices
            WHERE sha256=? AND capturado_indice_em<=?
            ORDER BY indice_sha256,capturado_indice_em""",
            (sha,corte.isoformat())).fetchall()
        payload=_json_deterministico({
            "dataset":"ANP_LPC_DIESEL_MT",
            "classificacao":"REAL_PRELIMINAR_NAO_HOMOLOGADO",
            "publicavel":False,
            "direitos":"USO_INTERNO_NAO_COMERCIAL_ANP_ATRIBUICAO",
            "sha256_original":sha,"origem_url":ed["url"],
            "semana_inicio":ed["semana_inicio"],
            "semana_fim":ed["semana_fim"],
            "capturas":[v["capturado_em"] for v in capturas],
            "indices":[dict(v) for v in indices],
            "observacoes":[dict(v) for v in obs],
        })
        digest=sha256(payload).hexdigest()
        # O caminho do objeto normalizado contém digest do conteúdo para
        # preservar também atualizações de captures/índices sem sobrescrever.
        enviar(f"{prefixo}/edicoes/{sha}/{digest}.json",
               digest,"application/json",conteudo=payload)
    return {
        "status":"EXPORTACAO_GCS_PRIVADA_CONCLUIDA",
        "bucket":bucket.name,"prefixo":prefixo,
        "edicoes":len(edicoes),"snapshots_indice":len(snapshots),
        "objetos_total":objetos,"objetos_novos":novos,
        "objetos_preexistentes":ja_existentes,
        "publicavel":False,
        "dados_homologados":False,
        "acesso_gcs_real_executado":True,
    }
