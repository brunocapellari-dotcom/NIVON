"""Adaptador tabular nacional para páginas de portos sem parser específico.

Sem inventar endpoints: o adaptador só interpreta HTML já adquirido e exige
contrato de layout explícito. Ativação remota requer escopo oficial com
endpoint_verified e autorização de direitos específicos.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from ._agrolog_portos_html import extract_tables
from .coleta_web import FonteWeb, adquirir_fonte
from .lineup_nacional import normalizar_linha, instante


class ErroPortoTabular(ValueError):
    pass


_CANONICOS = frozenset({
    "navio","duv","imo","produto","toneladas_programadas",
    "terminal","eta","lote_id",
})


def _cabecalho(txt: str) -> str:
    cleaned=unicodedata.normalize("NFKD",txt)
    ascii_txt="".join(ch for ch in cleaned if not unicodedata.combining(ch))
    return re.sub(r"\s+"," ",ascii_txt).strip().casefold()


@dataclass(frozen=True)
class ContratoTabular:
    porto_id: str
    fonte: FonteWeb
    cabecalhos: dict[str, str]
    publicado_em: str

    def validar(self, escopo: dict, *, remoto: bool = False) -> dict:
        if not isinstance(self.cabecalhos,dict) or not self.cabecalhos:
            raise ErroPortoTabular("contrato sem cabeçalhos")
        if not {"navio","produto"} <= set(self.cabecalhos) or not set(self.cabecalhos) <= _CANONICOS:
            raise ErroPortoTabular("colunas obrigatórias ausentes ou desconhecidas")
        values=[_cabecalho(v) for v in self.cabecalhos.values()]
        if len(set(values))!=len(values) or any(not v for v in values):
            raise ErroPortoTabular("colunas do contrato duplicadas")
        porto=next((p for p in escopo.get("ports",[]) if p.get("id")==self.porto_id),None)
        if porto is None:
            raise ErroPortoTabular("porto fora do catálogo nacional")
        publicado=instante(self.publicado_em)
        if remoto:
            self.fonte.verificar()
            if (porto.get("endpoint_verified") is not True or
                porto.get("parser_homologated") is not True or
                porto.get("commercial_rights") != "APPROVED" or
                porto.get("lineup_source_url") != self.fonte.url):
                raise PermissionError("porto sem endpoint, parser ou direitos homologados")
        return porto


def analisar_html_nacional(html: str, contrato: ContratoTabular, *,
                          escopo: dict, coletado_em: str) -> dict:
    """Interpretação de documento autorizado/sintético; não coleta na rede."""
    contrato.validar(escopo)
    if not isinstance(html,str) or not html.strip() or len(html)>8_000_000:
        raise ErroPortoTabular("HTML vazio ou excessivo")
    capturado=instante(coletado_em)
    pub=instante(contrato.publicado_em)
    if pub > capturado:
        raise ErroPortoTabular("publicação posterior à captura")
    selecionadas=[]
    for tabela in extract_tables(html):
        for pos,row in enumerate(tabela.rows):
            nomes=[_cabecalho(x) for x in row]
            if len(nomes)!=len(set(nomes)):
                continue
            if all(v in nomes for v in [_cabecalho(t) for t in contrato.cabecalhos.values()]):
                selecionadas.append((tabela,pos,nomes))
    if len(selecionadas)!=1:
        raise ErroPortoTabular(
            f"tabelas compatíveis: {len(selecionadas)}; exige exatamente uma")
    tabela,pos,headers=selecionadas[0]
    idx={k:headers.index(_cabecalho(v)) for k,v in contrato.cabecalhos.items()}
    rows=[]
    for i,row in enumerate(tabela.rows[pos+1:],start=pos+2):
        if len(row)!=len(headers):
            raise ErroPortoTabular(f"linha {i} com colunas divergentes")
        campos={k:str(row[at]).strip() for k,at in idx.items()}
        if not campos["navio"] or not campos["produto"]:
            raise ErroPortoTabular("linha sem identidade de navio ou produto")
        volume=None
        if campos.get("toneladas_programadas"):
            from .importadores import decimal_ptbr
            try:
                volume=decimal_ptbr(campos["toneladas_programadas"])
            except ValueError as exc:
                raise ErroPortoTabular("toneladas com unidade/locale incompatível") from exc
        raw={
            "porto_id":contrato.porto_id,
            "navio":campos["navio"],"duv":campos.get("duv"),
            "imo":campos.get("imo"),"produto":campos["produto"],
            "toneladas_programadas":volume,"toneladas_realizadas":None,
            "situacao":"PROGRAMADO","classe_evidencia":"LINEUP_INFORMADO",
            "lote_id":campos.get("lote_id"),"fonte_url":contrato.fonte.url,
            "publicado_em":pub.isoformat(),"coletado_em":capturado.isoformat(),
        }
        validado=normalizar_linha(raw,escopo)
        # Campos de programação complementares permanecem orientados a
        # documento, sem afirmar ETA real nem operação efetiva.
        validado["eta_programado_documental"]=campos.get("eta") or None
        validado["terminal_informado"]=campos.get("terminal") or None
        rows.append(validado)
    if not rows:
        raise ErroPortoTabular("tabela sem embarcações")
    return {"status":"EXTRAIDO_NAO_HOMOLOGADO",
            "porto":contrato.porto_id,"fonte":contrato.fonte.url,
            "total":len(rows),"registros":rows,
            "classificacao":"LINEUP_PROGRAMADO_NAO_REALIZADO"}


def coletar_html_nacional(contrato: ContratoTabular, *, escopo: dict,
                         abridor=None) -> dict:
    """Remoto somente após fonte e layout serem marcados homologados por auditoria."""
    contrato.validar(escopo,remoto=True)
    doc=adquirir_fonte(contrato.fonte,abridor=abridor)
    return analisar_html_nacional(
        doc["conteudo"].decode("utf-8-sig",errors="strict"),
        contrato,escopo=escopo,coletado_em=doc["capturado_em"])
