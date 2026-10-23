"""ANTT: coleta do top-16 anual de fluxos RGI (Tabela 12, Anuário TRC 2025).
NÃO representa matriz rodoviária mensal completa, nem produto identificado.
Fonte pública oficial, versionamento por SHA e falha fechada em layout divergente.
"""
from __future__ import annotations
import hashlib
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, HTTPRedirectHandler, build_opener

PDF_URL = "https://www.gov.br/antt/pt-br/assuntos/cargas/dadostrc/anuario_trc_2025_antt.pdf"
PDF_LIMIT = 12 * 1024 * 1024
ROW = re.compile(
    r"^\s*([A-Z]{2}\s*[–-]\s*[^\d]+?)\s{2,}"
    r"([A-Z]{2}\s*[–-]\s*[^\d]+?)\s{2,}"
    r"([1-9]\d{0,2}(?:\.\d{3}){1,3})\s+(\d{1,2},\d{2})%\s*$")
RGI = re.compile(r"^([A-Z]{2})\s*[–-]\s*(.+)$")

class ErroAnuarioANTT(ValueError):
    pass

class _SemRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def baixar_pdf(url=PDF_URL, *, opener=None):
    if url != PDF_URL:
        raise ErroAnuarioANTT("Somente o PDF oficial fixo ANTT")
    req = Request(url, headers={"Accept":"application/pdf","User-Agent":"NIVON/0.1 dados publicos"})
    with (opener or build_opener(_SemRedirecionar())).open(req, timeout=35) as resp:
        mime = str(resp.headers.get("Content-Type","")).split(";")[0].strip().lower()
        if resp.status != 200 or resp.geturl() != url or mime not in ("application/pdf","application/octet-stream"):
            raise ErroAnuarioANTT("HTTP/MIME/redirecionamento não homologado")
        raw = resp.read(PDF_LIMIT + 1)
    if not 100 < len(raw) <= PDF_LIMIT or not raw.startswith(b"%PDF-"):
        raise ErroAnuarioANTT("Arquivo PDF não aceito")
    return raw

def texto_pdf(pdf, *, comando=None):
    if not pdf.startswith(b"%PDF-") or len(pdf) > PDF_LIMIT:
        raise ErroAnuarioANTT("PDF inválido")
    programa = comando or shutil.which("pdftotext")
    if not programa:
        # Runner Ubuntu mínimo pode não incluir Poppler. Alternativa auditável
        # pure Python, pypdf==5.9.0 (licença BSD-3-Clause).
        import io
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ErroAnuarioANTT("pypdf ausente; instalar dependência fixada") from exc
        try:
            reader=PdfReader(io.BytesIO(pdf), strict=True)
            if len(reader.pages)<64:
                raise ErroAnuarioANTT("PDF com páginas insuficientes")
            page=reader.pages[63]
            if not page.get_contents() or len(page.get_contents().get_data())>10_000_000:
                raise ErroAnuarioANTT("Stream de página excessivo")
            txt=page.extract_text(extraction_mode="layout")
        except ErroAnuarioANTT:
            raise
        except Exception as exc:
            raise ErroAnuarioANTT("PDF não pôde ser lido com pypdf") from exc
        if not txt or len(txt)>1_000_000:
            raise ErroAnuarioANTT("Extração de texto pypdf inválida")
        return txt
    p = subprocess.run([programa,"-layout","-f","64","-l","64","-","-"],
                       input=pdf,capture_output=True,check=False,timeout=20)
    if p.returncode or not p.stdout or len(p.stdout)>1_000_000:
        raise ErroAnuarioANTT("Extração PDF falhou")
    return p.stdout.decode("utf-8",errors="strict")

def _rgi(s):
    m = RGI.fullmatch(s.strip())
    if not m or len(m.group(2).strip()) < 2:
        raise ErroAnuarioANTT("RGI inválida")
    return m.group(1),m.group(2).strip()

def extrair_tabela_12(texto):
    if "Tabela 12" not in texto or "Principais Fluxos" not in texto or "2025" not in texto:
        raise ErroAnuarioANTT("Tabela 12/2025 ausente")
    escopo = texto.split("Tabela 12",1)[1].split("Fonte:",1)[0]
    linhas=[]
    for linha in escopo.splitlines():
        m=ROW.fullmatch(linha)
        if not m:
            continue
        a,b=_rgi(m.group(1)),_rgi(m.group(2))
        t=int(m.group(3).replace(".",""))
        cent=int(m.group(4).replace(",",""))
        if t<1 or not 1<=cent<=10000:
            raise ErroAnuarioANTT("Unidade/valor inconsistente")
        linhas.append(dict(
            ano=2025,origem_uf=a[0],origem_rgi=a[1],
            destino_uf=b[0],destino_rgi=b[1],toneladas=t,
            participacao_pct=f"{cent/100:.2f}",granularidade="RGI",
            escopo="TOP_16_FLUXOS_GERAIS_ANUAIS",produto=None,ncm=None,fonte=PDF_URL))
    if len(linhas)!=16 or len({(x["origem_uf"],x["origem_rgi"],x["destino_uf"],x["destino_rgi"]) for x in linhas})!=16:
        raise ErroAnuarioANTT(f"Linhas RGI não homologadas: {len(linhas)}")
    ancoras={
        ("SP","São Paulo","SP","São Paulo"):14403113,
        ("MT","Rondonópolis","MT","Sorriso"):9946350,
        ("PA","Itaituba","MT","Sinop"):6350618}
    for k,t in ancoras.items():
        if not any((x["origem_uf"],x["origem_rgi"],x["destino_uf"],x["destino_rgi"])==k
                   and x["toneladas"]==t for x in linhas):
            raise ErroAnuarioANTT("Âncora de validação alterada")
    return linhas

def preparar_bd(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS antt_anuario_rgi_lotes (
      sha256 TEXT PRIMARY KEY, url TEXT NOT NULL, data_coleta TEXT NOT NULL,
      ano INTEGER NOT NULL, data_referencia TEXT NOT NULL,
      competencia TEXT NOT NULL, data_publicacao TEXT, linhas INTEGER NOT NULL,
      classificacao TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS antt_anuario_rgi_fluxos (
      sha256 TEXT NOT NULL REFERENCES antt_anuario_rgi_lotes(sha256),
      ano INTEGER NOT NULL, origem_uf TEXT NOT NULL, origem_rgi TEXT NOT NULL,
      destino_uf TEXT NOT NULL, destino_rgi TEXT NOT NULL, toneladas INTEGER NOT NULL,
      participacao_pct TEXT NOT NULL,
      PRIMARY KEY(sha256,ano,origem_uf,origem_rgi,destino_uf,destino_rgi));
    """)

def persistir(banco, linhas, *, sha256, data_coleta):
    if not re.fullmatch(r"[a-f0-9]{64}",sha256) or len(linhas)!=16 or any(
        x.get("escopo")!="TOP_16_FLUXOS_GERAIS_ANUAIS" for x in linhas):
        raise ErroAnuarioANTT("Lote ou hash inválido")
    dt=datetime.fromisoformat(data_coleta.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ErroAnuarioANTT("Data de coleta sem fuso")
    with sqlite3.connect(banco,timeout=30) as db:
        db.execute("PRAGMA foreign_keys=ON")
        preparar_bd(db)
        novo=db.execute("SELECT sha256 FROM antt_anuario_rgi_lotes WHERE sha256=?",(sha256,)).fetchone() is None
        if novo:
            with db:
                db.execute("""INSERT INTO antt_anuario_rgi_lotes
                  (sha256,url,data_coleta,ano,data_referencia,competencia,data_publicacao,linhas,classificacao)
                  VALUES (?, ?, ?, 2025, '2025-12-31', '2025', NULL, 16, 'OBSERVADO_RELATORIO_OFICIAL_TOP16')""",
                  (sha256,PDF_URL,data_coleta))
                db.executemany("""INSERT INTO antt_anuario_rgi_fluxos
                  (sha256,ano,origem_uf,origem_rgi,destino_uf,destino_rgi,toneladas,participacao_pct)
                  VALUES (:sha256,:ano,:origem_uf,:origem_rgi,:destino_uf,:destino_rgi,:toneladas,:participacao_pct)""",
                  [{**x,"sha256":sha256} for x in linhas])
    return {"estado":"NOVO_SNAPSHOT" if novo else "IDEMPOTENTE",
            "sha256":sha256,"linhas":len(linhas),"ano":2025,
            "escopo":"TOP_16_FLUXOS_GERAIS_ANUAIS","origem":PDF_URL,"data_coleta":data_coleta}

def executar(banco, *, pdf=None, aberto_em=None):
    raw=pdf if pdf is not None else baixar_pdf()
    linhas=extrair_tabela_12(texto_pdf(raw))
    return persistir(banco,linhas,sha256=hashlib.sha256(raw).hexdigest(),
                     data_coleta=(aberto_em or datetime.now(timezone.utc)).isoformat())
