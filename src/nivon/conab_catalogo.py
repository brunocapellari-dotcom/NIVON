"""Descoberta OFFLINE de planilhas da série histórica de grãos da CONAB.

Lê uma página HTML já adquirida licitamente e resolve somente links
publicados nos domínios oficiais. Não abre XLS nem infere números.
"""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class ErroCatalogoConab(ValueError):
    pass


PAGINAS = {
    "SOJA": "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/series-historicas/graos/soja/",
    "MILHO": "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/series-historicas/graos/milho",
    "GERGELIM": "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/series-historicas/graos/gergelim",
}
ESPERADOS = {
    "SOJA": {"SojaSerieHist.xls"},
    "MILHO": {"Milho1aSerieHist.xls", "Milho2aSerieHist.xls",
              "Milho3aSerieHist.xls", "MilhoTotalSerieHist.xls"},
    "GERGELIM": {"GergelimSerieHist.xls"},
}
DOMINIOS_PERMITIDOS = frozenset({"www.gov.br", "conab.gov.br", "www.conab.gov.br"})


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._rotulo = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._rotulo = []

    def handle_data(self, value):
        if self._href is not None:
            self._rotulo.append(value)

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            if self._href is not None:
                self.links.append((self._href, " ".join(" ".join(self._rotulo).split())))
            self._href = None
            self._rotulo = []


def descobrir_planilhas(html: str, produto: str) -> list[dict]:
    if produto not in PAGINAS:
        raise ErroCatalogoConab("produto fora do catálogo")
    if not isinstance(html, str) or not html.strip() or len(html) > 3_000_000:
        raise ErroCatalogoConab("página HTML ausente ou excessiva")
    parser = _Links()
    parser.feed(html)
    parser.close()
    encontrados = {}
    for href, rotulo in parser.links:
        if rotulo not in ESPERADOS[produto]:
            continue
        destino = urljoin(PAGINAS[produto], href)
        endereco = urlsplit(destino)
        if (endereco.scheme != "https" or endereco.hostname not in DOMINIOS_PERMITIDOS
                or endereco.username or endereco.password or endereco.fragment):
            raise ErroCatalogoConab("link fora do domínio oficial permitido")
        if rotulo in encontrados and encontrados[rotulo] != destino:
            raise ErroCatalogoConab("documento com URLs incompatíveis")
        encontrados[rotulo] = destino
    faltando = ESPERADOS[produto] - set(encontrados)
    if faltando:
        raise ErroCatalogoConab("planilha oficial ausente: " + ", ".join(sorted(faltando)))
    return [
        {"produto": produto, "arquivo": rotulo, "url": encontrados[rotulo],
         "pagina_publicacao": PAGINAS[produto],
         "natureza": "LINK_OFICIAL_DESCOBERTO_NAO_DADO_IMPORTADO",
         "coleta_habilitada": False}
        for rotulo in sorted(encontrados)
    ]
