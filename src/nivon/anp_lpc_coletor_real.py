"""Coletor real ANP/LPC: índice oficial -> últimas XLSX -> staging SQLite.

Ativado APENAS por chamada explícita, sem cron/deploy/cloud/segredos.
Não faz crawling, não tenta contornar WAF, só segue URLs descobertas
dentro de índice oficial. Limite de 1 índice + até 3 XLSX por execução.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
import json
import os
import time

from .anp_indice_lpc import URL_INDICE, descobrir_semanas_lpc, _PREFIX, _PATTERN
from .anp_lpc_staging_real import integrar_real_preliminar, iniciar_staging


class ErroColetaANP(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _permitir_url(url: str, *, tipo: str) -> None:
    if not isinstance(url, str):
        raise ErroColetaANP("URL de origem inválida")
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != "www.gov.br"
            or p.username or p.password or p.query or p.fragment
            or p.port not in (None, 443)):
        raise ErroColetaANP("URL não está na origem ANP/HTTPS permitida")
    if tipo == "HTML" and url != URL_INDICE:
        raise ErroColetaANP("URL do índice não autorizada")
    if tipo == "XLSX":
        # O índice oficial disponibiliza o XLSX diretamente. Usar
        # exatamente a URL anunciada, sem acrescentar endpoints presumidos.
        partes = p.path.removeprefix(_PREFIX).split("/")
        if (not p.path.startswith(_PREFIX) or len(partes) != 2
                or not partes[0].isdigit() or len(partes[0]) != 4
                or not _PATTERN.fullmatch(partes[1])):
            raise ErroColetaANP("URL XLSX não corresponde a resumo oficial reconhecido")


def obter_documento(
    url: str, *, tipo: str, abridor=None, timeout: int = 25,
) -> bytes:
    """Acesso com URL estrita, sem redirecionamento e memória limitada."""
    if tipo not in ("HTML", "XLSX"):
        raise ErroColetaANP("tipo de fonte inválido")
    _permitir_url(url, tipo=tipo)
    tamanho = 4_000_000 if tipo == "HTML" else 14_000_000
    client = abridor if abridor is not None else build_opener(_SemRedirect())
    request = Request(url, headers={
        "User-Agent": "NIVON/0.1 (uso interno nao comercial; dados publicos ANP)",
        "Accept": "text/html" if tipo == "HTML" else
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream",
    })
    with client.open(request, timeout=timeout) as response:
        final = response.geturl()
        if response.status != 200 or final != url:
            raise ErroColetaANP("resposta, redirect ou URL final incompatível")
        mime = response.headers.get("Content-Type", "").lower().split(";",1)[0].strip()
        allowed = ({"text/html", "application/xhtml+xml"} if tipo=="HTML"
                   else {"application/octet-stream", "application/zip",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
        if mime not in allowed:
            raise ErroColetaANP("MIME inesperado; não interpretar página como XLSX")
        payload = response.read(tamanho + 1)
    if not 100 <= len(payload) <= tamanho:
        raise ErroColetaANP("arquivo vazio, truncado ou grande demais")
    if tipo == "HTML" and b"<html" not in payload[:5000].lower():
        raise ErroColetaANP("HTML ANP inválido ou bloqueado")
    if tipo == "XLSX" and not payload.startswith(b"PK\x03\x04"):
        raise ErroColetaANP("não é XLSX/ZIP real")
    return payload


def _raw_privado(raiz: Path, *, subpasta: str, nome: str, payload: bytes) -> None:
    """Arquiva bytes oficiais por hash, jamais sobrescreve revisão anterior."""
    if raiz.is_symlink() or not raiz.is_dir():
        raise ErroColetaANP("raiz RAW deve existir e não pode ser symlink")
    root = raiz.resolve()
    destino_dir = root/subpasta
    if destino_dir.is_symlink():
        raise ErroColetaANP("subdiretório RAW inseguro")
    destino_dir.mkdir(mode=0o700, exist_ok=True)
    caminho = destino_dir/nome
    if not caminho.resolve().is_relative_to(root):
        raise ErroColetaANP("arquivo RAW fora da raiz")
    if caminho.is_symlink():
        raise ErroColetaANP("symlink de arquivo RAW não permitido")
    if caminho.exists():
        if sha256(caminho.read_bytes()).hexdigest() != sha256(payload).hexdigest():
            raise ErroColetaANP("arquivo RAW imutável divergente")
        return
    temp = caminho.with_suffix(caminho.suffix + ".tmp")
    if temp.exists() or temp.is_symlink():
        raise ErroColetaANP("arquivo temporário RAW existente ou inseguro")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, caminho)
    finally:
        temp.unlink(missing_ok=True)


def coletar_lpc(
    db, *, ano: int, limite_semanas: int = 3,
    raw_dir: str | Path | None = None, abridor=None,
    indice_bytes: bytes | None = None, arquivos_locais: dict[str, bytes] | None = None,
    esperar_segundos: float = 1.0,
    semana_desde: str | None = None,
    semana_ate: str | None = None,
) -> dict:
    """Execução de lote: modo HTTP ou offline reprocessável.

    No modo offline fornece ambos índice e dict URL oficial -> bytes.
    Captura indica instante DESTA execução, não publicação pela ANP.
    """
    if (type(ano) is not int or ano < 2020 or ano > 2100
            or type(limite_semanas) is not int or not 1 <= limite_semanas <= 12):
        raise ErroColetaANP("ano/limite fora da política de coleta moderada")
    def validar_corte(corte, campo):
        if corte is None:
            return None
        if (not isinstance(corte, str) or len(corte) != 10
                or not __import__("re").fullmatch(r"\\d{4}-\\d{2}-\\d{2}", corte)):
            raise ErroColetaANP(f"{campo}: data ISO YYYY-MM-DD obrigatória")
        try:
            return date.fromisoformat(corte)
        except ValueError as exc:
            raise ErroColetaANP(f"{campo}: data de período inválida") from exc
    desde = validar_corte(semana_desde, "semana_desde")
    ate = validar_corte(semana_ate, "semana_ate")
    if desde and ate and desde > ate:
        raise ErroColetaANP("intervalo de backfill invertido")
    offline = indice_bytes is not None or arquivos_locais is not None
    if offline and (not isinstance(indice_bytes, bytes)
                    or not isinstance(arquivos_locais, dict)):
        raise ErroColetaANP("modo offline exige índice e arquivos pareados")
    if type(esperar_segundos) not in (float,int) or not 0 <= esperar_segundos <= 10:
        raise ErroColetaANP("cadência HTTP inválida")
    arquivo_raw = Path(raw_dir) if raw_dir is not None else None
    if not offline and arquivo_raw is None:
        raise ErroColetaANP("modo real exige destino privado para RAW")
    iniciar_staging(db)
    if offline:
        html = indice_bytes
    else:
        html = obter_documento(URL_INDICE, tipo="HTML", abridor=abridor)
    index_time = datetime.now(timezone.utc).isoformat()
    info = descobrir_semanas_lpc(html, ano=ano)
    semanas_catalogadas = len(info["semanas"])
    weeks = sorted(info["semanas"], key=lambda x:x["semana_inicio"], reverse=True)
    if desde is not None:
        weeks = [w for w in weeks if date.fromisoformat(w["semana_inicio"]) >= desde]
    if ate is not None:
        weeks = [w for w in weeks if date.fromisoformat(w["semana_fim"]) <= ate]
    elegiveis = len(weeks)
    weeks = weeks[:limite_semanas]
    if not weeks:
        raise ErroColetaANP("nenhuma planilha LPC encontrada para o recorte oficial")
    if arquivo_raw is not None:
        _raw_privado(arquivo_raw, subpasta="indices",
                     nome=sha256(html).hexdigest()+".html", payload=html)
    resultados, erros = [], []
    for entry in weeks:
        url = entry["url_pagina"]
        try:
            if offline:
                if url not in arquivos_locais:
                    raise ErroColetaANP("XLSX anunciado não fornecido")
                blob = arquivos_locais[url]
                if not isinstance(blob, bytes):
                    raise ErroColetaANP("arquivo local não contém bytes")
            else:
                # Somente como recurso de download da URL listada. Não
                # tenta adivinhar novos arquivos nem contornar bloqueios.
                if esperar_segundos:
                    time.sleep(esperar_segundos)
                # Link direto publicado no índice: alternativa mais segura
                # que compor uma rota de download não anunciada.
                blob = obter_documento(url,tipo="XLSX",abridor=abridor)
            capture_time = datetime.now(timezone.utc).isoformat()
            # Parser e período verificados antes de arquivar.
            from .anp_resumo_lpc import ler_resumo_semanal_lpc
            parsed = ler_resumo_semanal_lpc(
                blob, coletado_em=capture_time, origem_url=url)
            if (parsed["semanas_distintas"] != 1
                or any(x["semana_inicio_oficial"] != entry["semana_inicio"]
                       or x["semana_fim_oficial"] != entry["semana_fim"]
                       for x in parsed["observacoes"])):
                raise ErroColetaANP("XLSX não corresponde à semana indexada")
            if arquivo_raw is not None:
                _raw_privado(arquivo_raw,subpasta="planilhas",
                             nome=sha256(blob).hexdigest()+".xlsx",payload=blob)
            receipt = integrar_real_preliminar(
                db, indice=html, arquivo=blob, arquivo_url=url, ano=ano,
                indice_capturado_em=index_time,
                arquivo_capturado_em=capture_time,
                raw_arquivado=arquivo_raw is not None,
            )
            resultados.append(receipt)
        except (OSError, ValueError, PermissionError) as exc:
            # Nunca fingir sucesso parcial como coleta completa.
            erros.append({
                "semana_inicio": entry["semana_inicio"],
                "semana_fim": entry["semana_fim"],
                "erro_tipo":type(exc).__name__,
                "motivo":str(exc)[:200],
            })
    return {
        "status": "LOTE_COMPLETO" if not erros else
                  "LOTE_PARCIAL" if resultados else "LOTE_FALHOU",
        "tipo":"ANP_LPC_DIESEL_MT_REAL_PRELIMINAR",
        "semanas_catalogadas": semanas_catalogadas,
        "semanas_elegiveis_periodo": elegiveis,
        "semanas_encontradas": len(weeks),
        "ainda_pendentes_recorte": elegiveis-len(weeks),
        "semana_desde": semana_desde, "semana_ate": semana_ate,
        "edicoes_integradas":len(resultados),
        "edicoes_novas":sum(x["edicao_nova"] for x in resultados),
        "capturas_novas":sum(x["captura_nova"] for x in resultados),
        "observacoes_integradas":sum(x["observacoes"] for x in resultados),
        "edicoes":resultados,"erros":erros,
        "indice_sha256":sha256(html).hexdigest(),
        "indice_capturado_em":index_time,
        "arquivos_reais_baixados":not offline and bool(resultados),
        "publicavel":False, "homologado":False, "sem_custo_ativado":True,
    }
