"""Escolha determinística e limitada das publicações oficiais da CONAB.

Catalogado em agrobr.conab.levantamentos(); dados são metadados, não cotações.
Não supor data/levantamento apenas pelo relógio ou nomes do arquivo.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit


class CatalogoConabInvalido(ValueError):
    pass


def normalizar_publicacao(item: dict, hoje: date) -> dict | None:
    if not isinstance(item, dict):
        return None
    ano = item.get("safra")
    n = item.get("levantamento")
    quando = item.get("data_publicacao")
    url = item.get("url")
    if not isinstance(ano, str) or len(ano) != 7 or ano[4] != "/" or not (ano[:4]+ano[-2:]).isdigit():
        return None
    inicio = int(ano[:4])
    if int(ano[-2:]) != (inicio+1) % 100:
        return None
    if inicio < 2010 or inicio > hoje.year:
        return None
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > 12:
        return None
    if not isinstance(quando, str):
        return None
    try:
        data = date.fromisoformat(quando)
    except ValueError:
        return None
    if data > hoje or data.year < inicio or data.year > inicio+2:
        return None
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.gov.br" or not parsed.path.startswith("/conab/") or parsed.username or parsed.password or parsed.query:
        return None
    return {"safra": ano, "levantamento": n, "data_publicacao": data.isoformat(), "url": url}


def selecionar_publicacoes(catalogo: list[dict], *, hoje: date | None = None,
                         limite: int = 2, primeira_safra: int = 2024) -> list[dict]:
    """Seleciona até N edições mais recentes e publicadas; histórico só se solicitado.

    O agendador consulta apenas releases efetivamente publicados e preserva a
    revisão do ano-safra anterior; não antecipa edições do calendário.
    """
    hoje = hoje or date.today()
    if not isinstance(catalogo, list) or not catalogo:
        raise CatalogoConabInvalido("Catálogo de edições vazio")
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= 12:
        raise ValueError("Limite por execução deve ser 1..12")
    if isinstance(primeira_safra, bool) or not isinstance(primeira_safra,int) or not 2010 <= primeira_safra <= hoje.year:
        raise ValueError("Primeira safra inválida")
    unicos: dict[tuple[str, int], dict] = {}
    for item in catalogo:
        p=normalizar_publicacao(item, hoje)
        if not p or int(p["safra"][:4]) < primeira_safra:
            continue
        chave=(p["safra"],p["levantamento"])
        if chave in unicos and unicos[chave] != p:
            raise CatalogoConabInvalido("Edição duplicada com metadados conflitantes")
        unicos[chave]=p
    if not unicos:
        raise CatalogoConabInvalido("Nenhuma edição válida publicada no período")
    return sorted(unicos.values(),key=lambda r:(r["data_publicacao"],r["safra"],r["levantamento"]),reverse=True)[:limite]
