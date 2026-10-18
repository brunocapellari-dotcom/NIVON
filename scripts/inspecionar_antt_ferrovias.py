"""Inspeção efêmera de XLSX de origem/destino FERROVIÁRIO da ANTT.

Metadados e amostra mínima de cabeçalhos; não confundir com MDF-e rodoviário.
"""
from __future__ import annotations
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from nivon.antt_ferrovia import extrair_registros, sumarizar_mercadorias
from urllib.request import urlopen, Request
from urllib.parse import urlsplit
from hashlib import sha256

URL=("https://www.gov.br/antt/pt-br/assuntos/ferrovias/"
     "dados-de-producao-do-transporte-de-carga-origem-destino/"
     "transporte-de-carga-origem-destino-2006-agosto-2026.xlsx/@@download/file")
MAIN="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACK="http://schemas.openxmlformats.org/package/2006/relationships"

def resumo_zip(dados: bytes)->dict:
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        arquivos=z.infolist()
        if len(arquivos)>2500 or sum(i.file_size for i in arquivos)>200_000_000:
            raise ValueError("XLSX excede limites de descompressão")
        if any(i.filename.startswith("/") or ".." in i.filename.split("/") for i in arquivos):
            raise ValueError("entrada insegura no XLSX")
        nomes=set(z.namelist())
        if "xl/workbook.xml" not in nomes or "xl/_rels/workbook.xml.rels" not in nomes:
            raise ValueError("workbook e relações ausentes")
        strings=[]
        if "xl/sharedStrings.xml" in nomes:
            root=ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{MAIN}}}si"):
                strings.append("".join(n.text or "" for n in si.iter(f"{{{MAIN}}}t")))
        wb=ET.fromstring(z.read("xl/workbook.xml"))
        rels=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        referencias={
            e.attrib.get("Id"):e.attrib.get("Target")
            for e in rels.findall(f"{{{PACK}}}Relationship")
        }
        sheets=[]
        for sh in wb.findall(f".//{{{MAIN}}}sheet"):
            rid=sh.attrib.get(f"{{{REL}}}id")
            target=referencias.get(rid)
            if not target:raise ValueError("planilha sem relação")
            # Alvo pode ser /xl/worksheets/... ou worksheets/...
            path=target.lstrip("/") if target.startswith("/") else "xl/"+target
            if path not in nomes: raise ValueError("alvo inexistente")
            xml=ET.fromstring(z.read(path))
            cells=[]
            for row in xml.findall(f".//{{{MAIN}}}sheetData/{{{MAIN}}}row")[:10]:
                vals=[]
                for c in list(row)[:14]:
                    raw=c.find(f"{{{MAIN}}}v")
                    if raw is None: 
                        inline=c.find(f"{{{MAIN}}}is")
                        v="".join(x.text or "" for x in inline.iter(f"{{{MAIN}}}t")) if inline is not None else ""
                    elif c.attrib.get("t")=="s":
                        v=strings[int(raw.text)] if raw.text is not None else ""
                    else:v=raw.text or ""
                    vals.append({"celula":c.attrib.get("r"),"valor":str(v)[:85]})
                cells.append(vals)
            sheets.append({"aba":sh.attrib.get("name"),"amostra_primeiras_linhas":cells,
                           "dimensao_declarada":xml.find(f"{{{MAIN}}}dimension").attrib.get("ref") if xml.find(f"{{{MAIN}}}dimension") is not None else None})
        return {"abas":sheets,"strings":len(strings)}

def executar():
    req=Request(URL,headers={"User-Agent":"NIVON/0.2 (inspecao ferroviaria ANTT)",
                             "Accept":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream"})
    with urlopen(req,timeout=45) as response:
        end=response.geturl();p=urlsplit(end)
        if response.status!=200 or p.scheme!="https" or p.hostname!="www.gov.br":
            raise ValueError("fonte/redirecionamento não autorizado")
        conteudo=response.read(18_000_001)
        if not conteudo or len(conteudo)>18_000_000:raise ValueError("XLSX vazio ou excessivo")
    if not conteudo.startswith(b"PK"):raise ValueError("assinatura XLSX ausente")
    x=resumo_zip(conteudo)
    x["resumo_fluxos_ferroviarios"]=sumarizar_mercadorias(extrair_registros(conteudo,sha256=sha256(conteudo).hexdigest()))
    x["abas"]=[{"aba":z["aba"],"dimensao_declarada":z["dimensao_declarada"]} for z in x["abas"]]
    x.update({"fonte":"ANTT_FERROVIAS_OD","url":end,
              "tamanho_bytes":len(conteudo),"sha256":sha256(conteudo).hexdigest(),
              "classificacao":"ESQUEMA_FERROVIARIO_NAO_MDFe","dados_persistidos":False})
    return x

if __name__=="__main__":
    print(json.dumps(executar(),ensure_ascii=False,indent=2))
