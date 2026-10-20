"""Índice histórico offline do progresso semanal CONAB (não extrai percentuais).

Recebe HTML oficial previamente capturado com autorização. Descobre páginas
sem construir URLs de boletins, preserva SHA do índice e reporta lacunas.
'Última modificação' do portal não é publication timestamp nem vintage as-of.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

BASE = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra"
ROTULO = re.compile(r"^Acompanhamento das Lavouras\s*-\s*(\d{2}/\d{2})\s+a\s+(\d{2}/\d{2}/\d{2})$", re.I)
MODIFICACAO = re.compile(r"última modificação\s+(\d{2}/\d{2}/\d{4})\s+(\d{2})h(\d{2})", re.I)


class ErroIndiceConab(ValueError):
    pass


def _tempo(instante: str) -> str:
    try:
        v = datetime.fromisoformat(instante.replace("Z", "+00:00"))
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("sem fuso")
    except (AttributeError, ValueError) as exc:
        raise ErroIndiceConab("captura exige timestamp ISO com fuso") from exc
    return v.astimezone(timezone.utc).isoformat(timespec="seconds")


def _url_pagina(url: str) -> str:
    if not isinstance(url, str):
        raise ErroIndiceConab("URL do índice inválida")
    p = urlsplit(url)
    b = urlsplit(BASE)
    if (p.scheme != "https" or p.netloc != b.netloc or p.path.rstrip("/") != b.path
            or p.fragment or p.username or p.password or p.port not in (None, 443)):
        raise ErroIndiceConab("índice fora da página oficial CONAB")
    if p.query:
        pares = parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)
        if len(pares) != 1 or pares[0][0] != "b_start:int":
            raise ErroIndiceConab("consulta não reconhecida no índice")
        offset = pares[0][1]
        if not offset.isascii() or not offset.isdecimal() or int(offset) > 5000 or int(offset) % 20:
            raise ErroIndiceConab("paginação fora do contrato")
    return url


def _url_boletim(href: str) -> str:
    if not isinstance(href, str) or not href.strip():
        raise ErroIndiceConab("link de boletim vazio")
    u = urlsplit(urljoin(BASE + "/", href))
    p = urlsplit(BASE)
    if (u.scheme != "https" or u.netloc != p.netloc or
            not u.path.startswith(p.path + "/") or u.query or u.fragment or
            u.username or u.password or u.port not in (None, 443)):
        raise ErroIndiceConab("link de boletim fora do domínio/caminho autorizado")
    return u.geturl()


class _Ancora(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.atual = None
        self.rotulo = []
        self.indice_trailer = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            # Nunca atribuir metadados após um link não relacionado ao boletim.
            self.indice_trailer = None
            self.atual = dict(attrs).get("href")
            self.rotulo = []

    def handle_data(self, data):
        if self.atual is not None:
            self.rotulo.append(data)
        elif self.indice_trailer is not None:
            self.links[self.indice_trailer]["trailer"] += " " + data[:200]

    def handle_endtag(self, tag):
        if tag == "a" and self.atual is not None:
            rotulo = " ".join(" ".join(self.rotulo).split())
            if ROTULO.fullmatch(rotulo):
                self.links.append({"href": self.atual, "label": rotulo, "trailer": ""})
                self.indice_trailer = len(self.links) - 1
            self.atual = None
            self.rotulo = []


def descobrir_indice(html: str, *, url_indice: str = BASE, coletado_em: str) -> dict:
    """Uma página HTML -> manifesto de URLs, NÃO observações agrícolas."""
    _url_pagina(url_indice)
    coleta = _tempo(coletado_em)
    if not isinstance(html, str) or not html.strip() or len(html.encode("utf-8")) > 5_000_000:
        raise ErroIndiceConab("HTML vazio ou excessivo")
    p = _Ancora()
    p.feed(html)
    p.close()
    itens = []
    seen = {}
    for link in p.links:
        match = ROTULO.fullmatch(link["label"])
        if match is None:
            continue
        fim = datetime.strptime(match.group(2), "%d/%m/%y").date()
        dia, mes = map(int, match.group(1).split("/"))
        try:
            inicio = date(fim.year, mes, dia)
            if inicio > fim:
                inicio = date(fim.year - 1, mes, dia)
        except ValueError as exc:
            raise ErroIndiceConab("intervalo semanal inválido") from exc
        if fim - inicio != timedelta(days=6) or inicio.weekday() != 0:
            raise ErroIndiceConab("intervalo CONAB não corresponde a semana segunda-domingo")
        url = _url_boletim(link["href"])
        mod = MODIFICACAO.search(link["trailer"][:300])
        texto_modificacao = None
        if mod:
            try:
                datetime.strptime(mod.group(1) + " " + mod.group(2) + ":" + mod.group(3),
                                  "%d/%m/%Y %H:%M")
            except ValueError as exc:
                raise ErroIndiceConab("metadado de última modificação inválido") from exc
            texto_modificacao = mod.group(0)
        chave = fim.isoformat()
        if chave in seen:
            if seen[chave]["url_boletim"] != url:
                raise ErroIndiceConab("mesma semana com URLs oficiais divergentes")
            if seen[chave]["ultima_modificacao_texto"] != texto_modificacao:
                raise ErroIndiceConab("mesma semana com modificações conflitantes")
            continue
        entry = {
            "dataset_id": "CONAB_PROGRESSO_SEMANAL",
            "inicio_semana": inicio.isoformat(),
            "fim_semana": chave,
            "url_boletim": url,
            "ultima_modificacao_texto": texto_modificacao,
            "publicacao_utc": None,
            "dados_agricolas_disponiveis": False,
            "natureza": "LINK_PUBLICADO_NO_INDICE_NAO_VALIDADO_COMO_ARQUIVO",
        }
        seen[chave] = entry
        itens.append(entry)
    if not itens:
        raise ErroIndiceConab("nenhum boletim semanal encontrado: falha fechada")
    return {
        "dataset_id": "CONAB_PROGRESSO_SEMANAL",
        "indice_url": url_indice,
        "indice_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "capturado_em_utc": coleta,
        "registros": sorted(itens, key=lambda x: x["fim_semana"]),
        "estado": "DESCOBERTA_OFFLINE_SEM_COLETA_DOS_BOLETINS",
    }


def consolidar_paginas(paginas: list[dict]) -> dict:
    """Consolida páginas oficiais; reporta semanas ausentes sem interpolar."""
    if not isinstance(paginas, list) or not 1 <= len(paginas) <= 250:
        raise ErroIndiceConab("de 1 a 250 páginas históricas exigidas")
    entradas = {}
    capturas = []
    urls = set()
    for item in paginas:
        if not isinstance(item, dict) or set(item) != {"html", "url_indice", "coletado_em"}:
            raise ErroIndiceConab("entrada de página incompleta")
        m = descobrir_indice(**item)
        if m["indice_url"] in urls:
            raise ErroIndiceConab("página de índice duplicada")
        urls.add(m["indice_url"])
        capturas.append({k: m[k] for k in ("indice_url", "indice_sha256", "capturado_em_utc")})
        for r in m["registros"]:
            key = r["fim_semana"]
            if key in entradas and entradas[key] != r:
                raise ErroIndiceConab("boletim divergente entre páginas do mesmo histórico")
            entradas[key] = r
    semanas = sorted(entradas)
    if len(semanas) > 5000:
        raise ErroIndiceConab("manifesto excessivo")
    lacunas = []
    cursor = date.fromisoformat(semanas[0])
    ultima = date.fromisoformat(semanas[-1])
    while cursor < ultima:
        cursor += timedelta(days=7)
        if cursor.isoformat() not in entradas:
            lacunas.append(cursor.isoformat())
    return {
        "dataset_id": "CONAB_PROGRESSO_SEMANAL",
        "paginas_capturadas": capturas,
        "boletins_identificados": len(semanas),
        "lacunas_na_sequencia": lacunas,
        "interpretacao_lacunas": "AUSENCIA_NO_INDICE_CAPTURADO_NAO_PROVA_AUSENCIA_NA_FONTE",
        "registros": [entradas[s] for s in semanas],
        "coleta_real_dos_boletins": False,
        "publicacao_historica_comprovada": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CONAB: índice HTML salvo localmente, sem HTTP")
    parser.add_argument("--html", required=True)
    parser.add_argument("--url", default=BASE)
    parser.add_argument("--coletado-em", required=True)
    args = parser.parse_args(argv)
    path = Path(args.html)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
        parser.error("arquivo HTML regular e até 5 MB obrigatório")
    try:
        result = descobrir_indice(path.read_text(encoding="utf-8"),
                                 url_indice=args.url, coletado_em=args.coletado_em)
    except (UnicodeError, ErroIndiceConab) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
