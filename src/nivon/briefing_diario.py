"""Briefing diário: curadoria temporal, proveniência e texto WhatsApp.

Módulo offline. Não coleta de sites, não gera cotações e não envia mensagens.
As entradas devem vir de conectores licenciados e revisados.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

JANELA_NOTICIAS = timedelta(hours=24)
FUSO_EDICAO = ZoneInfo("America/Sao_Paulo")
CATEGORIAS = (
    "MERCADO E COMMODITIES", "SAFRA E PRODUÇÃO", "PECUÁRIA",
    "CLIMA", "LOGÍSTICA E PORTOS", "COMBUSTÍVEIS E ENERGIA",
    "EXPORTAÇÕES", "POLÍTICA E ECONOMIA", "GEOPOLÍTICA",
)
OPERACOES_EXIGIDAS = frozenset({"LEITURA", "RESUMO", "PUBLICACAO_DERIVADA"})
PARAMETROS_RASTREIO = frozenset({
    "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src",
})


class ErroBriefing(ValueError):
    """Contrato de entrada inválido; não publicar o registro."""


def _instante(valor: str | datetime, campo: str) -> datetime:
    if isinstance(valor, str):
        if "T" not in valor and " " not in valor:
            raise ErroBriefing(f"{campo}: data sem hora não comprova janela de 24h")
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErroBriefing(f"{campo}: timestamp ISO inválido") from exc
    if not isinstance(valor, datetime) or valor.tzinfo is None or valor.utcoffset() is None:
        raise ErroBriefing(f"{campo}: timezone/offset obrigatório")
    return valor.astimezone(timezone.utc)


def _texto(valor: object, campo: str, *, maximo: int = 1000) -> str:
    if not isinstance(valor, str) or not valor.strip() or len(valor) > maximo:
        raise ErroBriefing(f"{campo}: texto vazio ou extenso demais")
    return re.sub(r"\s+", " ", valor).strip()


def _url(url: object) -> str:
    valor = _texto(url, "url", maximo=2048)
    partes = urlsplit(valor)
    if (partes.scheme != "https" or not partes.hostname or partes.username
            or partes.password or partes.port not in (None, 443)
            or partes.hostname in ("localhost", "localhost.localdomain")
            or "." not in partes.hostname):
        raise ErroBriefing("url: HTTPS público obrigatório")
    return valor


def _chave_url(url: str) -> str:
    partes = urlsplit(url)
    consulta = urlencode(sorted(
        (k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in PARAMETROS_RASTREIO
    ))
    return urlunsplit(("https", partes.hostname.lower(), partes.path.rstrip("/") or "/",
                       consulta, ""))


def _chave_titulo(titulo: str) -> str:
    base = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", base.lower()).strip()


def _fonte_autorizada(item: dict, fontes: dict) -> None:
    fonte_id = _texto(item.get("fonte_id"), "fonte_id", maximo=120)
    contrato = fontes.get(fonte_id)
    if not isinstance(contrato, dict):
        raise ErroBriefing("fonte não cadastrada")
    if contrato.get("status_direitos") != "APROVADA":
        raise ErroBriefing("direitos pendentes da fonte")
    operacoes = contrato.get("operacoes", [])
    if not isinstance(operacoes, list) or not OPERACOES_EXIGIDAS.issubset(set(operacoes)):
        raise ErroBriefing("operações da fonte não autorizadas")


def selecionar_noticias(
    noticias: list[dict], fontes: dict, *, gerado_em: str | datetime,
) -> tuple[list[dict], list[dict]]:
    """Seleciona originais com publicação comprovada em [agora-24h, agora].

    Deduplica ANTES de aplicar o recorte temporal: republicação idêntica não
    ressuscita notícia antiga. Alteração em updated_at/coletado_em não muda idade.
    Não aceita data sem hora/fuso. Fontes negadas são descartadas com motivo.
    """
    agora = _instante(gerado_em, "gerado_em")
    limite = agora - JANELA_NOTICIAS
    validos: list[dict] = []
    rejeitados: list[dict] = []
    for pos, entrada in enumerate(noticias):
        titulo = str(entrada.get("titulo", ""))[:120] if isinstance(entrada, dict) else ""
        try:
            if not isinstance(entrada, dict):
                raise ErroBriefing("registro não é objeto")
            _fonte_autorizada(entrada, fontes)
            t = _texto(entrada.get("titulo"), "titulo", maximo=240)
            resumo = _texto(entrada.get("resumo"), "resumo", maximo=900)
            fonte = _texto(entrada.get("fonte"), "fonte", maximo=120)
            url = _url(entrada.get("url"))
            categoria = _texto(entrada.get("categoria"), "categoria", maximo=80).upper()
            if categoria not in CATEGORIAS:
                raise ErroBriefing("categoria fora do catálogo")
            pub = _instante(entrada.get("publicado_em"), "publicado_em")
            if pub > agora:
                raise ErroBriefing("publicação futura")
            observacao = {
                "titulo": t, "resumo": resumo, "fonte": fonte, "url": url,
                "categoria": categoria, "publicado_em": pub,
            }
            for campo in ("impacto_brasil", "impacto_produtor"):
                valor = entrada.get(campo)
                if valor is not None:
                    observacao[campo] = _texto(valor, campo, maximo=450)
            validos.append(observacao)
        except (ErroBriefing, TypeError, ValueError) as exc:
            rejeitados.append({"indice": pos, "titulo": titulo, "motivo": str(exc)})

    # Primeiro por publicação MAIS ANTIGA. Uma notícia republicada não ganha vida nova.
    validos.sort(key=lambda n: n["publicado_em"])
    urls: set[str] = set()
    titulos: set[str] = set()
    escolhidos: list[dict] = []
    for item in validos:
        chave_url = _chave_url(item["url"])
        chave_titulo = _chave_titulo(item["titulo"])
        if chave_url in urls or chave_titulo in titulos:
            rejeitados.append({"titulo": item["titulo"], "motivo": "duplicada/republicada"})
            continue
        urls.add(chave_url)
        titulos.add(chave_titulo)
        if item["publicado_em"] < limite:
            rejeitados.append({"titulo": item["titulo"], "motivo": "publicada há mais de 24h"})
        else:
            escolhidos.append(item)
    escolhidos.sort(key=lambda n: (CATEGORIAS.index(n["categoria"]), -n["publicado_em"].timestamp()))
    return escolhidos, rejeitados


def gerar_texto(
    noticias: list[dict], fontes: dict, *, gerado_em: str | datetime,
    cotacoes: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Monta texto editorial sem inventar cotações nem promover hipótese a fato."""
    agora = _instante(gerado_em, "gerado_em")
    itens, rejeitados = selecionar_noticias(noticias, fontes, gerado_em=agora)
    data_local = agora.astimezone(FUSO_EDICAO)
    inicio = (agora - JANELA_NOTICIAS).astimezone(FUSO_EDICAO)
    linhas = [
        "📋 *BRIEFING ESTRATÉGICO DO AGRONEGÓCIO — NIVON*",
        "📅 " + data_local.strftime("%d/%m/%Y %H:%M") + " (Brasília)",
        "🔎 Notícias de " + inicio.strftime("%d/%m %H:%M") +
        " até " + data_local.strftime("%d/%m %H:%M") + " (24 horas)",
    ]
    if cotacoes:
        linhas.extend(["", "━━━━━━━━━━━━━━━━━━", "📊 *COTAÇÕES E INDICADORES*"])
        for cotacao in cotacoes:
            # Um último fechamento pode ser mais antigo que 24h, mas deve ter data própria.
            if not isinstance(cotacao, dict):
                raise ErroBriefing("cotação inválida")
            titulo = _texto(cotacao.get("titulo"), "cotação.titulo", maximo=100)
            valor = _texto(cotacao.get("valor"), "cotação.valor", maximo=80)
            fonte = _texto(cotacao.get("fonte"), "cotação.fonte", maximo=120)
            referencia = _texto(cotacao.get("referencia"), "cotação.referencia", maximo=40)
            linhas.append(f"• {titulo}: {valor} (ref. {referencia}; {fonte})")

    linhas.extend(["", "━━━━━━━━━━━━━━━━━━", "📰 *NOTÍCIAS — ÚLTIMAS 24H*"])
    if not itens:
        linhas.append("Nenhuma notícia elegível, com data comprovada e uso autorizado, nesta janela.")
    for categoria in CATEGORIAS:
        grupo = [n for n in itens if n["categoria"] == categoria]
        if not grupo:
            continue
        linhas.extend(["", "*" + categoria + "*"])
        for n in grupo:
            hora = n["publicado_em"].astimezone(FUSO_EDICAO).strftime("%d/%m %H:%M")
            linhas.extend([
                "", "🔹 *" + n["titulo"] + "*",
                n["resumo"], f"Fonte: {n['fonte']} — publicado {hora} (Brasília)",
            ])
            for campo, rotulo in (("impacto_brasil", "Brasil"), ("impacto_produtor", "Produtor")):
                if n.get(campo):
                    linhas.append(f"▶️ Possível impacto {rotulo} (análise NIVON): {n[campo]}")
            linhas.append(n["url"])
    linhas.extend(["", f"Notícias elegíveis: {len(itens)}. Dados com proveniência; sem inferir fatos ausentes."])
    return "\n".join(linhas), rejeitados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Briefing offline com filtro estrito de 24h")
    parser.add_argument("--entrada", required=True, help="JSON local autorizado")
    parser.add_argument("--saida", required=True, help="TXT, não envia mensagens")
    parser.add_argument("--gerado-em", required=True, help="ISO 8601 com fuso")
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.entrada).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ErroBriefing("arquivo raiz precisa ser objeto")
    texto, recusas = gerar_texto(
        payload["noticias"], payload["fontes"], gerado_em=args.gerado_em,
        cotacoes=payload.get("cotacoes"),
    )
    Path(args.saida).write_text(texto + "\n", encoding="utf-8")
    print(json.dumps({"arquivo": args.saida, "rejeicoes": Counter(
        r["motivo"] for r in recusas
    )}, ensure_ascii=False, default=dict), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
