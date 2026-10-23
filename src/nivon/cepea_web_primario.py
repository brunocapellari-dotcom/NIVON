"""Consulta contida às páginas primárias de preço do CEPEA (CC BY-NC 4.0).

Não usa Notícias Agrícolas ou outros fallbacks. Não contorna bloqueios,
não presume frescor e não escreve no banco durante a coleta/validação.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.request import Request
from html.parser import HTMLParser
from urllib.parse import urlparse
import re
import ssl

URL_SOJA = "https://www.cepea.org.br/br/indicador/soja.aspx"
URL_MILHO = "https://www.cepea.org.br/br/indicador/milho.aspx"
FONTE="CEPEA"
SERIES = {
    "soja_paranagua": {"produto":"soja", "praca":"Paranaguá/PR", "unidade":"BRL/sc60kg", "assinatura":"SOJA CEPEA/ESALQ - PARANAGUÁ"},
    "soja_parana": {"produto":"soja", "praca":"Paraná", "unidade":"BRL/sc60kg", "assinatura":"SOJA CEPEA/ESALQ - PARANÁ"},
    "milho_esalq_b3": {"produto":"milho", "praca":"Campinas/SP", "unidade":"BRL/sc60kg", "assinatura":"MILHO ESALQ/BM&FBOVESPA"},
}
ROW = re.compile(r"^\d{2}/\d{2}/20\d{2}$")


class CepeaNaoHomologado(ValueError):
    pass


def valor_real(texto):
    if not isinstance(texto,str):
        raise CepeaNaoHomologado("Cotação sem unidade numérica")
    t=texto.strip().replace("\xa0","").replace(" ","")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{1,6}|\d+,\d{1,6}",t):
        raise CepeaNaoHomologado("Formato monetário não brasileiro ou ambíguo")
    try:
        n=Decimal(t.replace(".","").replace(",","."))
    except InvalidOperation as exc:
        raise CepeaNaoHomologado("Cotação inválida") from exc
    if not n.is_finite() or n <= 0 or n > 1000000:
        raise CepeaNaoHomologado("Preço fora de limites")
    return format(n,"f")


def consultar_pagina_primaria(url: str, *, open_url=None):
    if url not in (URL_SOJA,URL_MILHO):
        raise CepeaNaoHomologado("Somente URL primária CEPEA homologada")
    if open_url is None or not callable(open_url):
        raise PermissionError("EGRESS_CEPEA_NAO_HOMOLOGADO: transporte HTTPS obrigatório")
    req=Request(url,headers={"User-Agent":"NIVON-Research/1.0 (personal noncommercial; one page per test)", "Accept":"text/html"})
    with open_url(req,timeout=18) as r:
        returned=r.geturl()
        parsed=urlparse(returned)
        if parsed.scheme!="https" or parsed.hostname not in ("www.cepea.org.br","cepea.org.br") or parsed.path!=urlparse(url).path:
            raise CepeaNaoHomologado("Redirecionamento fora do canal CEPEA")
        html=r.read(1_000_001)
        if len(html)>1_000_000:
            raise CepeaNaoHomologado("Página muito grande")
        charset=r.headers.get_content_charset() or "utf-8"
    return html.decode(charset,errors="replace")


class _TabelasCEPEA(HTMLParser):
    """Parser mínimo sem rede; associa tabela à última seção de título HTML.

    Estrutura desconhecida, títulos ambíguos ou tabelas duplicadas são
    rejeitados posteriormente, nunca atribuídos por busca textual global.
    """
    _TITULOS = frozenset(("h1","h2","h3","h4","h5","h6"))
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tabelas=[]
        self._heading=None
        self._heading_data=[]
        self._last_heading=""
        self._table_depth=0
        self._table_heading=""
        self._rows=[]
        self._row=None
        self._cell=None

    def handle_starttag(self,tag,attrs):
        if tag in self._TITULOS and self._table_depth==0:
            self._heading=tag
            self._heading_data=[]
        if tag=="table":
            if self._table_depth==0:
                self._table_heading=self._last_heading
                self._rows=[]
            self._table_depth+=1
        elif tag=="tr" and self._table_depth==1:
            self._row=[]
        elif tag in ("td","th") and self._table_depth==1 and self._row is not None:
            self._cell=[]

    def handle_data(self,data):
        if self._heading is not None and self._table_depth==0:
            self._heading_data.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self,tag):
        if tag==self._heading and self._table_depth==0:
            self._last_heading=" ".join(" ".join(self._heading_data).upper().split())
            self._heading=None
            self._heading_data=[]
        if tag in ("td","th") and self._cell is not None:
            self._row.append(" ".join(" ".join(self._cell).split()))
            self._cell=None
        elif tag=="tr" and self._table_depth==1:
            if self._row is not None:
                self._rows.append(self._row)
            self._row=None
        elif tag=="table" and self._table_depth:
            self._table_depth-=1
            if self._table_depth==0:
                self.tabelas.append((self._table_heading,self._rows))
                self._rows=[]

def extrair_precos_html(html: str, identificadores:tuple[str,...], *,
                        hoje:date|None=None, coleta:datetime|None=None):
    if not isinstance(html,str) or len(html)>1_000_000:
        raise CepeaNaoHomologado("HTML inválido ou fora do limite")
    hoje=hoje or date.today()
    coleta=coleta or datetime.now(timezone.utc)
    if coleta.tzinfo is None or coleta.utcoffset() is None:
        raise CepeaNaoHomologado("Coleta sem timezone")
    parser=_TabelasCEPEA()
    parser.feed(html)
    parser.close()
    dados=[]
    for serie_id in identificadores:
        if serie_id not in SERIES:
            raise CepeaNaoHomologado("ID de série desconhecido")
        spec=SERIES[serie_id]
        achados=[]
        for titulo,linhas_brutas in parser.tabelas:
            if "INDICADOR" not in titulo or spec["assinatura"] not in titulo:
                continue
            linhas=[]
            for cells in linhas_brutas:
                if len(cells)<2 or not ROW.fullmatch(cells[0]):
                    continue
                try:
                    ref=datetime.strptime(cells[0],"%d/%m/%Y").date()
                except ValueError as exc:
                    raise CepeaNaoHomologado("Data inválida na tabela CEPEA") from exc
                if ref>hoje:
                    raise CepeaNaoHomologado("Cotação com data futura")
                linhas.append((ref,valor_real(cells[1])))
            if linhas:
                achados.append(linhas)
        if len(achados)!=1:
            raise CepeaNaoHomologado(
                f"CEPEA série {serie_id}: tabelas detectadas {len(achados)}, esperado 1")
        for ref,valor in achados[0]:
            dados.append({
                "fonte":"CEPEA","serie_id":serie_id,
                "produto":spec["produto"],"praca":spec["praca"],
                "unidade":spec["unidade"],"valor":valor,
                "data_referencia":ref.isoformat(),
                "data_publicacao":None,
                "data_coleta":coleta.isoformat(),
                "competencia":ref.strftime("%Y-%m"),
                "qualidade":"CANDIDATO_NAO_GRAVADO",
                "origem_url": URL_SOJA if serie_id.startswith("soja") else URL_MILHO,
                "licenca":"CC BY-NC 4.0",
            })
    if not dados:
        raise CepeaNaoHomologado("Nenhuma observação CEPEA original validada")
    keys=[(x["serie_id"],x["data_referencia"]) for x in dados]
    if len(keys)!=len(set(keys)):
        raise CepeaNaoHomologado("Observações duplicadas na mesma tabela")
    return sorted(dados,key=lambda x:(x["serie_id"],x["data_referencia"]))
