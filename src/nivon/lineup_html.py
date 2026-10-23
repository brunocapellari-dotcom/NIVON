"""Interpretação OFFLINE de tabelas HTML de programação portuária.

Não acessa a internet e não promove programação para realização.
Só aceita layouts mapeados explicitamente e falha fechado em tabelas ambíguas.
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Mapping

from .portos import Programacao


class ErroLineup(ValueError):
    pass


class _Tabelas(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabelas: list[list[list[str]]] = []
        self._tabela: list[list[str]] | None = None
        self._linha: list[str] | None = None
        self._celula: list[str] | None = None
        self._invalida = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            if self._tabela is not None:
                raise ErroLineup("tabela HTML aninhada não suportada")
            self._tabela = []
        elif self._tabela is not None and tag == "tr":
            if self._linha is not None:
                raise ErroLineup("linha HTML aninhada")
            self._linha = []
        elif self._linha is not None and tag in ("th", "td"):
            if self._celula is not None:
                raise ErroLineup("célula HTML aninhada")
            attrs_map = dict(attrs)
            if "rowspan" in attrs_map or "colspan" in attrs_map:
                raise ErroLineup("rowspan/colspan exige parser especializado")
            self._celula = []

    def handle_data(self, data):
        if self._celula is not None:
            self._celula.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("th", "td") and self._celula is not None:
            self._linha.append(" ".join(" ".join(self._celula).split()))
            self._celula = None
        elif tag == "tr" and self._linha is not None:
            if self._linha:
                self._tabela.append(self._linha)
            self._linha = None
        elif tag == "table" and self._tabela is not None:
            if self._linha is not None or self._celula is not None:
                raise ErroLineup("tabela HTML malformada")
            if self._tabela:
                self.tabelas.append(self._tabela)
            self._tabela = None


@dataclass(frozen=True)
class ContratoTabela:
    porto: str
    cabecalhos: Mapping[str, str]
    fonte: str
    coletado_em: str
    tipo_publicacao: str = "PROGRAMACAO"

    def __post_init__(self):
        if self.tipo_publicacao != "PROGRAMACAO":
            raise ErroLineup("este parser só aceita programação; eventos físicos exigem outro contrato")
        if "navio" not in self.cabecalhos or not self.fonte.strip() or not self.coletado_em.strip():
            raise ErroLineup("contrato sem navio, fonte ou data")
        if not set(self.cabecalhos) <= {"navio", "duv", "imo", "produto", "toneladas", "situacao"}:
            raise ErroLineup("campo canônico desconhecido")
        if len(set(self.cabecalhos.values())) != len(self.cabecalhos):
            raise ErroLineup("mapeamento para colunas duplicadas")


def analisar_html_lineup(html: str, contrato: ContratoTabela) -> dict:
    """Extrai tabelas de uma única edição oficial já salva.

    A tabela selecionada deve ser única, com cabeçalhos explícitos. Tabela
    incompatível é erro em vez de devolver silenciosamente 0 navios.
    """
    if not isinstance(html, str) or not html.strip() or len(html) > 8_000_000:
        raise ErroLineup("HTML vazio ou excessivo")
    parser = _Tabelas()
    parser.feed(html)
    parser.close()
    tabelas = []
    for tabela in parser.tabelas:
        cabecalho = tabela[0]
        if len(cabecalho) != len(set(cabecalho)):
            continue
        if all(valor in cabecalho for valor in contrato.cabecalhos.values()):
            tabelas.append((cabecalho, tabela[1:]))
    if len(tabelas) != 1:
        raise ErroLineup(f"tabelas compatíveis: {len(tabelas)}; esperado exatamente uma")
    header, linhas = tabelas[0]
    if not linhas:
        raise ErroLineup("tabela sem registros")
    indices = {campo: header.index(coluna) for campo, coluna in contrato.cabecalhos.items()}
    saida = []
    for i, linha in enumerate(linhas, start=2):
        if len(linha) != len(header):
            raise ErroLineup(f"linha {i}: comprimento diferente do cabeçalho")
        dados = {campo: linha[indice].strip() for campo, indice in indices.items()}
        if not dados.get("navio"):
            raise ErroLineup(f"linha {i}: navio ausente")
        if "situacao" in dados and dados["situacao"].upper() not in ("PROGRAMADO", "PREVISTO", "ESPERADO"):
            raise ErroLineup(f"linha {i}: situacao física incompatível com programação")
        toneladas = dados.get("toneladas")
        if toneladas:
            from .importadores import decimal_ptbr, ErroMapeamento
            try:
                valor = decimal_ptbr(toneladas)
            except ErroMapeamento as exc:
                raise ErroLineup(f"linha {i}: tonelagem incompatível") from exc
        else:
            valor = None
        saida.append(Programacao(
            porto=contrato.porto, navio=dados["navio"],
            duv=dados.get("duv") or None,
            imo=dados.get("imo") or None,
            produto=dados.get("produto") or None,
            toneladas_programadas=valor, fonte=contrato.fonte,
            coletado_em=contrato.coletado_em, status="PROGRAMADO",
        ))
    return {"registros": saida, "quantidade_linhas": len(saida),
            "classificacao": "INFORMADO_PROGRAMADO",
            "fonte": contrato.fonte, "coletado_em": contrato.coletado_em}
