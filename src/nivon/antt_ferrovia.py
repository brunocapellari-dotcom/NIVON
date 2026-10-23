"""Leitura por streaming do XLSX ANTT de origem-destino FERROVIÁRIO.

Não é o painel rodoviário MDF-e. 'Estação' não equivale a município.
Apenas dados de fluxo ferroviário TU/TKU com fonte e versão identificadas.
"""
from __future__ import annotations
import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

MAIN="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACK="http://schemas.openxmlformats.org/package/2006/relationships"
SHEET_RE=re.compile(r"20\d{2}")
PERIODO_RE=re.compile(r"^(0[1-9]|1[0-2])/(20\d{2})$")
UFS=set("AC AL AP AM BA CE DF ES GO MA MG MS MT PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())

class ErroFerrovia(ValueError): pass


def _arquivos(dados):
    if not dados.startswith(b"PK"):raise ErroFerrovia("não é XLSX")
    z=zipfile.ZipFile(io.BytesIO(dados))
    members=z.infolist()
    if len(members)>2500 or sum(x.file_size for x in members)>200_000_000:
        z.close();raise ErroFerrovia("XLSX maior que limite")
    names=set(z.namelist())
    if any(n.startswith("/") or ".." in n.split("/") for n in names):
        z.close();raise ErroFerrovia("entrada zip insegura")
    return z,names


def _strings(z,names):
    if "xl/sharedStrings.xml" not in names:return []
    raw=z.read("xl/sharedStrings.xml")
    root=ET.fromstring(raw)
    return ["".join(t.text or "" for t in si.iter(f"{{{MAIN}}}t"))
            for si in root.findall(f"{{{MAIN}}}si")]


def _abas(z,names):
    wb=ET.fromstring(z.read("xl/workbook.xml"))
    rels=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    links={n.attrib.get("Id"):n.attrib.get("Target")
           for n in rels.findall(f"{{{PACK}}}Relationship")}
    result=[]
    for s in wb.findall(f".//{{{MAIN}}}sheet"):
        nome=s.attrib.get("name")
        if not nome or not SHEET_RE.fullmatch(nome):
            raise ErroFerrovia("aba sem ano válido")
        target=links.get(s.attrib.get(f"{{{REL}}}id"))
        if not target:raise ErroFerrovia("aba sem relação")
        path=target.lstrip("/") if target.startswith("/") else "xl/"+target
        if path not in names:raise ErroFerrovia("XML de planilha ausente")
        result.append((nome,path))
    if not 15<=len(result)<=25:raise ErroFerrovia("quantidade inesperada de abas")
    return result


def _conteudo(c,strings):
    raw=c.find(f"{{{MAIN}}}v")
    if raw is not None:
        if c.attrib.get("t")=="s":
            try:return strings[int(raw.text)]
            except (IndexError,TypeError,ValueError) as exc:raise ErroFerrovia("shared string inválida") from exc
        return raw.text or ""
    node=c.find(f"{{{MAIN}}}is")
    return "".join(t.text or "" for t in node.iter(f"{{{MAIN}}}t")) if node is not None else ""


def _linha(row,strings):
    x={}
    for cell in row.findall(f"{{{MAIN}}}c"):
        ref=cell.attrib.get("r","")
        m=re.match(r"^([A-Z]+)\d+$",ref)
        if not m:continue
        col=0
        for char in m.group(1):col=col*26+ord(char)-64
        if col<=9:x[col]=_conteudo(cell,strings)
    return x


def _numero(valor,nome):
    if not re.fullmatch(r"\d+(?:\.\d+)?",str(valor).strip()):
        raise ErroFerrovia(f"{nome} inválido")
    n=float(valor)
    if not math.isfinite(n) or n<0:raise ErroFerrovia(f"{nome} inválido")
    return n


def extrair_registros(dados:bytes, *, sha256:str):
    if not re.fullmatch(r"[a-f0-9]{64}",sha256):raise ErroFerrovia("hash da fonte inválido")
    z,names=_arquivos(dados)
    try:
        strings=_strings(z,names)
        for ano,path in _abas(z,names):
            with z.open(path) as stream:
                # iterparse evita construir a memória de centenas de milhares de linhas
                for event,elem in ET.iterparse(stream, events=("end",)):
                    if elem.tag!=f"{{{MAIN}}}row":continue
                    campos=_linha(elem,strings)
                    elem.clear()
                    periodo=str(campos.get(1,"")).strip()
                    if not PERIODO_RE.fullmatch(periodo):continue
                    mes,ano_raw=PERIODO_RE.fullmatch(periodo).groups()
                    if ano_raw!=ano:raise ErroFerrovia("mês não corresponde à aba")
                    origem_uf=str(campos.get(5,"")).upper().strip()
                    destino_uf=str(campos.get(7,"")).upper().strip()
                    if origem_uf not in UFS or destino_uf not in UFS:
                        raise ErroFerrovia("UF inválida")
                    orig=str(campos.get(4,"")).strip()
                    dest=str(campos.get(6,"")).strip()
                    merc=str(campos.get(3,"")).strip()
                    ferrovia=str(campos.get(2,"")).strip()
                    if not orig or not dest or not merc or not ferrovia:
                        raise ErroFerrovia("estação, carga ou ferrovia ausente")
                    yield {
                        "periodo":f"{ano}-{mes}",
                        "ferrovia":ferrovia,"mercadoria_antt":merc,
                        "origem_estacao":orig,"origem_uf":origem_uf,
                        "destino_estacao":dest,"destino_uf":destino_uf,
                        "tu_t":_numero(campos.get(8,""),"TU"),
                        "tku":_numero(campos.get(9,""),"TKU"),
                        "modal":"FERROVIARIO",
                        "local_tipo":"ESTACAO_NAO_MUNICIPIO",
                        "arquivo_sha256":sha256,
                    }
    finally:
        z.close()


def sumarizar_mercadorias(registros):
    """Resumo apenas da fonte ferroviária; não inferir fluxo rodoviário."""
    grupos=defaultdict(lambda:{"linhas":0,"tu":0.0,"tku":0.0})
    estacoes=defaultdict(lambda:{"linhas":0,"tu":0.0})
    total=0
    for r in registros:
        total+=1
        if total>400_000:raise ErroFerrovia("limite de linhas excedido")
        g=grupos[r["mercadoria_antt"].upper()]
        g["linhas"]+=1;g["tu"]+=r["tu_t"];g["tku"]+=r["tku"]
        # Estações apenas, sem correspondência automática com cidade
        if r["origem_uf"]=="MT":
            key=(r["mercadoria_antt"].upper(),r["origem_estacao"],r["destino_estacao"],r["destino_uf"])
            estacoes[key]["linhas"]+=1
            estacoes[key]["tu"]+=r["tu_t"]
    return {
        "linhas_ferroviarias":total,
        "mercadorias_distintas":len(grupos),
        "mercadorias_relevantes":[
            {"produto_fonte":p,"linhas":x["linhas"],"tu_t":round(x["tu"],1)}
            for p,x in sorted(grupos.items()) if any(t in p for t in ("SOJA","MILHO","FERTILIZANTE"))
        ],
        "top_10_estacoes_sairam_MT":[
            {"mercadoria_fonte":k[0],"origem_estacao":k[1],
             "destino_estacao":k[2],"destino_uf":k[3],
             "linhas":v["linhas"],"tu_t":round(v["tu"],1)}
            for k,v in sorted(estacoes.items(),key=lambda kv:-kv[1]["tu"])[:10]
        ],
        "aviso":"FERROVIARIO_TU_E_ESTACAO_NAO_SAO_MDFe_RODOVIARIO_NEM_MUNICIPIO_CONSUMIDOR",
    }
