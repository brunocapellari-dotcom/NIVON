"""Leitura OFFLINE restrita de XLSX de progresso semanal CONAB.

O layout foi estudado a partir da especificação pública agrobr (MIT) e
testado com fixture de terceiros. Não coleta rede, não homologa origem
dos bytes, licença, dados reais ou migração. Nunca infere BR por média.
Sem dependências externas: ZIP/OOXML stdlib Python.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

from .conab_agrobr import normalizar_progresso, ErroProgresso
from .conciliacao_progresso_stores import _normalizar_registro, ErroConciliacaoConab

PARSER_ID = "NIVON_PROGRESSO_XLSX_OOXML_V1"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_BYTES = 20_000_000
MAX_CELLS = 150000
MAX_RECORDS = 5000
UF = {
    "ACRE":"AC","ALAGOAS":"AL","AMAPÁ":"AP","AMAZONAS":"AM",
    "BAHIA":"BA","CEARÁ":"CE","DISTRITO FEDERAL":"DF",
    "ESPÍRITO SANTO":"ES","GOIÁS":"GO","MARANHÃO":"MA",
    "MATO GROSSO":"MT","MATO GROSSO DO SUL":"MS","MINAS GERAIS":"MG",
    "PARÁ":"PA","PARAÍBA":"PB","PARANÁ":"PR","PERNAMBUCO":"PE",
    "PIAUÍ":"PI","RIO DE JANEIRO":"RJ","RIO GRANDE DO NORTE":"RN",
    "RIO GRANDE DO SUL":"RS","RONDÔNIA":"RO","RORAIMA":"RR",
    "SANTA CATARINA":"SC","SÃO PAULO":"SP","SERGIPE":"SE",
    "TOCANTINS":"TO",
}
_CULTURA = re.compile(r"^(.+?)\s*-\s*Safra\s+(\d{4}(?:/\d{2})?)\s*$",re.I)
_OPERACAO = re.compile(r"^(Semeadura|Colheita)\s*\*?\s*$",re.I)
_COBERTURA = re.compile(r"^\(Esses\s+(\d+)\s+estados\s+correspondem\s+a\s+(\d+(?:[,.]\d+)?)\s*%\s+da\s+área\s+cultivada\)$",re.I)
_AGREGADO = re.compile(r"^(\d+)\s+estados$",re.I)
_CELL = re.compile(r"^([A-Z]{1,3})([1-9]\d*)$")
_DATE_STYLES = {14,15,16,17,18,19,20,21,22}
_NUM = re.compile(r"^[+-]?\d+(?:[,.]\d+)?%?\s*\*?$")


class ErroXlsxProgresso(ValueError):
    pass


def _xml(z, name):
    try:
        info=z.getinfo(name)
        if info.file_size>10_000_000:
            raise ErroXlsxProgresso("XML descompactado acima do limite")
        return ET.fromstring(z.read(info))
    except (KeyError,ET.ParseError,RuntimeError) as exc:
        raise ErroXlsxProgresso("XML esperado ausente ou malformado: "+name) from exc


def _celulas_xlsx(payload: bytes):
    if not isinstance(payload,bytes) or not 0<len(payload)<=MAX_BYTES:
        raise ErroXlsxProgresso("bytes XLSX ausentes ou muito grandes")
    if not payload.startswith(b"PK\x03\x04"):
        raise ErroXlsxProgresso("não é pacote XLSX/ZIP")
    try:
        with ZipFile(io.BytesIO(payload)) as z:
            members=z.infolist()
            if (not 3 <= len(members) <= 4000 or len({m.filename for m in members}) != len(members)):
                raise ErroXlsxProgresso("membros XLSX vazios, repetidos ou excessivos")
            if sum(m.file_size for m in members) > 40_000_000:
                raise ErroXlsxProgresso("pacote XLSX com expansão total acima do limite")
            for m in members:
                if (m.flag_bits & 1 or m.file_size>15_000_000
                    or m.file_size>max(m.compress_size,1)*200
                    or m.filename.startswith("/") or ".." in m.filename.split("/")
                    or m.filename.lower().endswith((".exe",".bin",".vba"))):
                    raise ErroXlsxProgresso("ZIP inseguro ou com conteúdo executável")
            if "xl/vbaProject.bin" in z.namelist():
                raise ErroXlsxProgresso("XLSX com macro não permitido")
            wb=_xml(z,"xl/workbook.xml")
            props=wb.find(NS+"workbookPr")
            if props is not None and props.get("date1904","0").lower() in ("1","true"):
                raise ErroXlsxProgresso("calendário Excel 1904 requer parser específico")
            rels=_xml(z,"xl/_rels/workbook.xml.rels")
            sheets=wb.find(NS+"sheets")
            if sheets is None:
                raise ErroXlsxProgresso("livro sem abas")
            candidates=[s for s in sheets if "progresso" in s.get("name","").casefold()]
            if len(candidates)>1 or (not candidates and len(list(sheets))!=1):
                raise ErroXlsxProgresso("aba de progresso ambígua")
            sheet = candidates[0] if candidates else list(sheets)[0]
            rid=sheet.get(REL_NS+"id")
            relation=next((r for r in rels if r.get("Id")==rid),None)
            if relation is None or relation.get("TargetMode")=="External":
                raise ErroXlsxProgresso("relação de aba ausente/externa")
            target=relation.get("Target","")
            from posixpath import normpath, dirname
            path=normpath(("xl/"+target.lstrip("/")) if not target.startswith("/") else target.lstrip("/"))
            if not path.startswith("xl/worksheets/") or ".." in path.split("/"):
                raise ErroXlsxProgresso("relação de worksheet inválida")
            styles=[]
            if "xl/styles.xml" in z.namelist():
                style_root=_xml(z,"xl/styles.xml")
                custom={}
                fmts=style_root.find(NS+"numFmts")
                if fmts is not None:
                    custom={int(e.get("numFmtId")):e.get("formatCode","") for e in fmts}
                xf=style_root.find(NS+"cellXfs")
                if xf is not None:
                    for entry in xf:
                        fid=int(entry.get("numFmtId","0"))
                        fmt=re.sub(r'"[^"]*"','',custom.get(fid,"")).lower()
                        styles.append(fid in _DATE_STYLES or bool(re.search(r"[dmy]",fmt)))
            strings=[]
            if "xl/sharedStrings.xml" in z.namelist():
                ss=_xml(z,"xl/sharedStrings.xml")
                for item in ss.findall(NS+"si"):
                    strings.append("".join(t.text or "" for t in item.iter(NS+"t")))
            data=_xml(z,path)
            rows=[]
            n_cells=0
            for rr in data.iter(NS+"row"):
                cells={}
                for c in rr.findall(NS+"c"):
                    n_cells+=1
                    if n_cells>MAX_CELLS:
                        raise ErroXlsxProgresso("planilha acima do limite de células")
                    ref=c.get("r","")
                    m=_CELL.fullmatch(ref)
                    if not m:
                        raise ErroXlsxProgresso("referência de célula OOXML inválida")
                    index=0
                    for letter in m.group(1):
                        index=index*26+ord(letter)-ord("A")+1
                    index-=1
                    if index>=256 or index in cells:
                        raise ErroXlsxProgresso("coluna excessiva ou repetida")
                    if c.find(NS+"f") is not None:
                        raise ErroXlsxProgresso("planilha contém fórmula: recusar valor não reexecutado")
                    typ=c.get("t","n")
                    node=c.find(NS+"v")
                    if typ=="inlineStr":
                        inline=c.find(NS+"is")
                        val="".join(t.text or "" for t in inline.iter(NS+"t")) if inline is not None else ""
                    elif node is None:
                        val=None
                    elif typ=="s":
                        i=int(node.text)
                        if not 0<=i<len(strings):
                            raise ErroXlsxProgresso("sharedString inexistente")
                        val=strings[i]
                    elif typ in ("str","e"):
                        if typ=="e":
                            raise ErroXlsxProgresso("célula de erro OOXML")
                        val=node.text
                    elif typ=="b":
                        val=node.text=="1"
                    elif typ in ("n","d"):
                        if typ=="d":
                            val=datetime.fromisoformat(node.text)
                        else:
                            val=float(node.text)
                            if not math.isfinite(val):
                                raise ErroXlsxProgresso("valor não finito no XLSX")
                            s=int(c.get("s","0"))
                            if s<len(styles) and styles[s]:
                                val=datetime(1899,12,30)+timedelta(days=val)
                    else:
                        raise ErroXlsxProgresso("tipo de célula inesperado")
                    cells[index]=val
                rows.append(cells)
                if len(rows)>10000:
                    raise ErroXlsxProgresso("planilha com linhas excessivas")
            if not rows:
                raise ErroXlsxProgresso("worksheet vazia")
            return rows
    except (BadZipFile,OverflowError,IndexError,TypeError,ValueError) as exc:
        if isinstance(exc,ErroXlsxProgresso):
            raise
        raise ErroXlsxProgresso("pacote XLSX inválido") from exc


def _pct(value):
    if value is None or value=="":
        return None,False
    revisado=False
    if isinstance(value,str):
        t=value.strip()
        revisado=t.endswith("*")
        if revisado:
            t=t[:-1].strip()
        porcentagem="%" in t
        if not _NUM.fullmatch(t):
            raise ErroXlsxProgresso("percentual textual fora do formato")
        t=t.rstrip("%").strip().replace(",",".")
        try:num=float(t)
        except ValueError as exc:raise ErroXlsxProgresso("percentual inválido") from exc
        if porcentagem:num/=100
    elif type(value) in (float,int):
        num=float(value)
    else:
        raise ErroXlsxProgresso("percentual com tipo inválido")
    if not math.isfinite(num) or not 0<=num<=1:
        raise ErroXlsxProgresso("percentual fora de [0,1]")
    return num,revisado


def reexecutar_xlsx_conab(payload: bytes, *, sha256_origem: str,
                          url_origem: str, coletado_em: str,
                          publicado_em: str | None):
    """Interpreta XLSX restrito de progresso; assume metadados fornecidos."""
    if not isinstance(sha256_origem,str) or len(sha256_origem)!=64 or hashlib.sha256(payload).hexdigest()!=sha256_origem:
        raise ErroXlsxProgresso("SHA256 bruto inválido")
    try:
        coleta=datetime.fromisoformat(coletado_em.replace("Z","+00:00"))
        if coleta.tzinfo is None:
            raise ValueError("sem fuso")
        pub=datetime.fromisoformat(publicado_em.replace("Z","+00:00")) if publicado_em is not None else None
        if pub is not None and (pub.tzinfo is None or pub>coleta):
            raise ValueError("publicação no futuro/sem fuso")
    except (AttributeError,ValueError) as exc:
        raise ErroXlsxProgresso("timestamp de captura/publicação inválido") from exc
    rows=_celulas_xlsx(payload)
    culture=safra=op=week=None
    cobertura=None
    records=[]
    keys=set()
    block_start=0
    active=False
    for row in rows:
        name=str(row.get(1) or "").strip()
        mh=_CULTURA.fullmatch(name)
        if mh:
            if culture and (op is None or len(records)==block_start):
                raise ErroXlsxProgresso("bloco de cultura vazio")
            culture,safra=mh.group(1).strip(),mh.group(2)
            op=week=None
            cobertura=None
            active=False
            block_start=len(records)
            continue
        m=_COBERTURA.fullmatch(name)
        if m and culture and op is None:
            cobertura=(int(m.group(1)),float(m.group(2).replace(",","."))/100)
            continue
        m=_OPERACAO.fullmatch(name)
        if m and culture:
            if op and len(records)==block_start:
                raise ErroXlsxProgresso("bloco de operação sem dados")
            op=m.group(1).capitalize()
            active=False
            week=None
            block_start=len(records)
            continue
        dates=[row.get(k) for k in (2,3,4)]
        if culture and op and all(isinstance(v,datetime) for v in dates):
            if not dates[0]<dates[1]<dates[2]:
                raise ErroXlsxProgresso("três datas do progresso fora de ordem")
            week=dates[2].strftime("%Y-%m-%d")
            active=True
            continue
        if not active or not (culture and op and week) or not name:
            continue
        if name.startswith(("*","(")) or name.lower().startswith(("valores","percentual","estimativa")):
            continue
        if name.lower()=="brasil":
            # Nunca inferir Brasil por média; rejeitar se layout trouxer BR,
            # pois o store NIVON atual suporta somente UF ou MEDIA_ESTADOS.
            raise ErroXlsxProgresso("Brasil publicado requer contrato próprio; não tratar como média")
        aggregated=_AGREGADO.fullmatch(name)
        if aggregated:
            uf="MEDIA_ESTADOS"
            n=int(aggregated.group(1))
            if not 1<=n<=27 or (cobertura is not None and cobertura[0]!=n):
                raise ErroXlsxProgresso("média de estados com cobertura incoerente")
            n_estados=n
            coverage=cobertura[1] if cobertura else None
        else:
            uf=UF.get(name.upper())
            if uf is None:
                if name in ("Estado","Unidade da Federação"):
                    continue
                # Exceção para notas textuais não reconhecidas: suspender
                # leitura de bloco, sem tratar texto como dado numérico.
                if not any(row.get(k) is not None for k in (2,3,4,5)):
                    continue
                raise ErroXlsxProgresso("nome de UF/layout inesperado")
            n_estados=coverage=None
        nums=[]
        flags=[]
        for j in (2,3,4,5):
            n,rev=_pct(row.get(j))
            nums.append(n)
            flags.append(rev)
        if nums[2] is None:
            # Sem percentual semanal atual, não criar informação observada.
            continue
        key=(culture,safra,op,uf,week)
        if key in keys:
            raise ErroXlsxProgresso("chave duplicada")
        keys.add(key)
        records.append({
            "cultura":culture,"safra":safra,"operacao":op,"uf":uf,
            "semana_atual":week,
            "pct_ano_anterior":nums[0],"pct_semana_anterior":nums[1],
            "pct_semana_atual":nums[2],"pct_media_5_anos":nums[3],
            "revisado":any(flags),"n_estados":n_estados,
            "cobertura_area_pct":coverage,
        })
        if len(records)>MAX_RECORDS:
            raise ErroXlsxProgresso("limite de observações excedido")
    if culture and (op is None or len(records)==block_start):
        raise ErroXlsxProgresso("bloco final sem dados")
    if not records:
        raise ErroXlsxProgresso("sem observações válidas")
    try:
        normalized=normalizar_progresso(records,fonte_url=url_origem,
                                        coletado_em=coleta,publicado_em=pub.isoformat() if pub else None)
        semantic={}
        for item in normalized:
            row=dict(item)
            row.pop("coleta")
            key,content,_=_normalizar_registro(json.dumps(row,ensure_ascii=False,allow_nan=False))
            semantic[key]=content
    except (ErroProgresso,ErroConciliacaoConab) as exc:
        raise ErroXlsxProgresso("normalização do XLSX falhou") from exc
    return {"parser_id":PARSER_ID,
            "parser_codigo_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "raw_sha256":sha256_origem,
            "observacoes":len(semantic),"mapa_semantico":semantic,
            "arquivo_de_terceiro_sem_prova_de_origem":True,
            "direitos_de_uso_verificados":False,
            "publicacao_extraida_do_xlsx":False,
            "migracao_permitida":False}
