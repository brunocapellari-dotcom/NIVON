"""Coleta PONTUAL oficial de levantamento CONAB -> RAWs -> manifesto do lote.

Somente páginas de levantamentos explicitamente catalogados. Não agenda,
não faz crawling, não ativa produção e não pressupõe vintage histórica.
O resultado pode ser processado pelo worker de lotes já existente.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request
from urllib.error import HTTPError, URLError

from .conab_anexo_xlsx_levantamento import (
    ANEXO, ErroDocumentoConab, conferir_anexo_xlsx_levantamento, _govbr,
)
from .conab_levantamentos_candidatos import _validar_linha
from .conab_lote_offline import _json as _json_lote

_ROOT = Path(__file__).resolve().parents[2]
_CATALOGO = _ROOT / "config" / "conab_levantamentos_candidatos.v1.json"
_MAX = {"levantamento": 3_000_000, "anexo": 3_000_000, "xlsx": 15_000_000}


class ErroColetaPontualConab(ValueError):
    pass


class _RedirecionamentoConab(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _govbr(newurl, "redirecionamento oficial")
        except ErroDocumentoConab as exc:
            raise ErroColetaPontualConab("redirecionamento fora do gov.br CONAB") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _baixar(url: str, limite: int) -> dict:
    """HTTP GET explícito, sem proxy, cookie ou credencial herdados."""
    _govbr(url, "captura CONAB")
    opener = build_opener(ProxyHandler({}), _RedirecionamentoConab())
    req = Request(url, headers={
        "User-Agent": "NIVON/0.1 (captura pontual de documentos publicos)",
        "Accept": "text/html,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream",
        "Cache-Control": "no-cache",
    })
    try:
        with opener.open(req, timeout=25) as response:
            final_url = response.geturl()
            _govbr(final_url, "destino do download")
            if response.status != 200:
                raise ErroColetaPontualConab("HTTP não retorna 200")
            length = response.headers.get("Content-Length")
            if length and length.isascii() and length.isdecimal() and int(length) > limite:
                raise ErroColetaPontualConab("Content-Length excede limite")
            chunks, size = [], 0
            while True:
                chunk = response.read(min(65536, limite - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > limite:
                    raise ErroColetaPontualConab("resposta HTTP excede limite")
                chunks.append(chunk)
            return {
                "bytes": b"".join(chunks),
                "final_url": final_url,
                "content_type": response.headers.get("Content-Type", ""),
                "last_modified_http": response.headers.get("Last-Modified"),
                "etag_http": response.headers.get("ETag"),
                "coletado_em": datetime.now(timezone.utc).isoformat(),
                "status_http": response.status,
            }
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ErroColetaPontualConab("falha ao adquirir documento CONAB") from exc


def _conferir_resposta(arquivo: dict, *, tipo: str, url: str) -> bytes:
    if not isinstance(arquivo, dict) or arquivo.get("status_http") != 200:
        raise ErroColetaPontualConab("resposta de aquisição inválida")
    raw = arquivo.get("bytes")
    if not isinstance(raw, bytes) or not 10 <= len(raw) <= _MAX[tipo]:
        raise ErroColetaPontualConab("RAW recebido vazio, inválido ou excessivo")
    _govbr(arquivo.get("final_url"), "URL final")
    # Endereço efetivo pode incluir /@@download/file, mas deve continuar
    # dentro do mesmo documento inicial (sem substituir a edição).
    final_path = urlsplit(arquivo["final_url"]).path
    requested = urlsplit(url).path
    if not (final_path == requested or final_path.startswith(requested + "/")):
        raise ErroColetaPontualConab("URL efetiva não corresponde ao documento inicial")
    mime = str(arquivo.get("content_type") or "").lower().split(";")[0].strip()
    if tipo in ("levantamento", "anexo"):
        if mime not in ("text/html", "application/xhtml+xml") or b"<" not in raw[:200]:
            raise ErroColetaPontualConab("página oficial não é HTML")
    else:
        if mime not in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream", "application/zip"
        ) or not raw.startswith(b"PK\x03\x04"):
            raise ErroColetaPontualConab("arquivo obtido não é XLSX")
    iso=arquivo.get("coletado_em")
    if not isinstance(iso,str):
        raise ErroColetaPontualConab("instante de captura ausente")
    try:
        d=datetime.fromisoformat(iso.replace("Z","+00:00"))
        if d.tzinfo is None or d.utcoffset() is None:
            raise ValueError("sem fuso")
    except ValueError as exc:
        raise ErroColetaPontualConab("instante de captura sem fuso") from exc
    return raw


def _item_catalogo(*, catalogo: str | Path, safra: str, numero: int) -> dict:
    path=Path(catalogo)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ErroColetaPontualConab("catálogo de fontes ausente ou inseguro")
    try:
        entries=json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ErroColetaPontualConab("catálogo CONAB inválido") from exc
    if not isinstance(entries,list) or not 1<=len(entries)<=150:
        raise ErroColetaPontualConab("catálogo CONAB com tamanho inválido")
    matches=[]
    for e in entries:
        try:
            _validar_linha(e)
        except (ValueError,TypeError) as exc:
            raise ErroColetaPontualConab("catálogo CONAB adulterado ou inconsistente") from exc
        if e["safra"]==safra and e["numero_levantamento"]==numero:
            matches.append(e)
    if len(matches)!=1:
        raise ErroColetaPontualConab("edição não é única ou não consta no catálogo autorizado")
    return matches[0]


def coletar_uma_edicao(*, safra: str, numero: int,
                      output_root: str | Path, catalogo: str | Path = _CATALOGO) -> dict:
    """Captura só os 3 URLs de edição pré-catalogada e gera jobs.json.

    Nenhuma saída parcial é publicada: o diretório da edição é movido
    atomicamente depois de RAWs, SHA e vínculo serem verificados.
    """
    if type(numero) is not int or not 1<=numero<=12:
        raise ErroColetaPontualConab("número inválido")
    e=_item_catalogo(catalogo=catalogo,safra=safra,numero=numero)
    url=e["pagina_url"]
    base=url.rstrip("/")
    annex=base+"/"+ANEXO+"/view"
    xlsx=annex.removesuffix("/view")
    root=Path(output_root)
    if root.is_symlink() or not root.is_dir():
        raise ErroColetaPontualConab("diretório de destino ausente ou é link")
    folder=f"conab_{safra.replace('/','_')}_levantamento_{numero:02d}"
    final=root/folder
    if final.exists() or final.is_symlink():
        raise ErroColetaPontualConab("captura da edição já existe; não sobrescrever")
    urls={"levantamento":url,"anexo":annex,"xlsx":xlsx}
    received={}
    for typ in ("levantamento","anexo","xlsx"):
        response=_baixar(urls[typ],_MAX[typ])
        data=_conferir_resposta(response,tipo=typ,url=urls[typ])
        received[typ]=(response,data)
    ref_l, ref_a, ref_x = (received[t][0]["coletado_em"] for t in ("levantamento","anexo","xlsx"))
    html_l,html_a,bytes_x=(received[t][1] for t in ("levantamento","anexo","xlsx"))
    # O mesmo verificador RAW exigido pelo pipeline do staging.
    vinculo=conferir_anexo_xlsx_levantamento(
        safra=safra, numero_levantamento=numero,
        pagina_levantamento_url=url,pagina_anexo_url=annex,arquivo_xlsx_url=xlsx,
        html_levantamento_raw=html_l,html_anexo_raw=html_a,xlsx_raw=bytes_x,
        coletado_levantamento_em=ref_l,coletado_anexo_em=ref_a,coletado_xlsx_em=ref_x,
        sha256_xlsx_esperado=sha256(bytes_x).hexdigest(),
    )
    job={
        "job_id":f"conab_{safra.replace('/','_')}_l{numero:02d}",
        "safra":safra,"numero_levantamento":numero,
        "pagina_levantamento_url":url,"pagina_anexo_url":annex,
        "arquivo_xlsx_url":xlsx,
        "html_levantamento":"levantamento.html","html_anexo":"anexo.html",
        "xlsx":"tabela.xlsx",
        "sha256_html_levantamento":sha256(html_l).hexdigest(),
        "sha256_html_anexo":sha256(html_a).hexdigest(),
        "sha256_xlsx_esperado":sha256(bytes_x).hexdigest(),
        "coletado_levantamento_em":ref_l,
        "coletado_anexo_em":ref_a,
        "coletado_xlsx_em":ref_x,
    }
    audit={
        "status":"CAPTURA_OFICIAL_DECLARADA_SEM_PROVA_VINTAGE_ASOF",
        "urls":urls,
        "http":{t:{k:v for k,v in response.items() if k!="bytes"}
                for t,(response,_) in received.items()},
        "hashes_arquivos":{t:sha256(data).hexdigest()
                           for t,(_,data) in received.items()},
        "vinculo":vinculo,
        "origem_catalogo":"CONAB_GOVBR_INVENTARIO_PONTUAL",
        "publicacao_historica_provada":False,
        "dados_agricolas_extraidos":False,
        "habilita_backtest":False,"habilita_treino":False,
        "habilita_publicacao":False,
    }
    tmp=Path(tempfile.mkdtemp(prefix=".conab_tmp_",dir=root))
    try:
        for name,contents in (("levantamento.html",html_l),("anexo.html",html_a),
                              ("tabela.xlsx",bytes_x)):
            (tmp/name).write_bytes(contents)
        (tmp/"jobs.json").write_text(
            json.dumps({"schema_version":"1.0","jobs":[job]},ensure_ascii=False,indent=2)+"\n",
            encoding="utf-8",
        )
        (tmp/"captura_http.json").write_text(
            json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
            encoding="utf-8",
        )
        # Garante que não existe diretório de edição anterior.
        if final.exists() or final.is_symlink():
            raise ErroColetaPontualConab("destino apareceu durante coleta")
        tmp.rename(final)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    return {
        "status":"RAW_CAPTURADO_PONTUALMENTE_SEM_VINTAGE",
        "diretorio":str(final),"manifesto":str(final/"jobs.json"),
        "diretorio_raw":str(final),
        "documentos":3,
        "arquivo_sha256":sha256(bytes_x).hexdigest(),
        "disponibilidade_asof_comprovada":False,
        "habilita_backtest":False,"habilita_treino":False,
        "habilita_publicacao":False,
    }


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Captura pontual CONAB, sem crawlers, cron ou publicação")
    parser.add_argument("--safra",required=True)
    parser.add_argument("--levantamento",type=int,required=True)
    parser.add_argument("--destino",required=True)
    parser.add_argument("--catalogo",default=str(_CATALOGO))
    parser.add_argument("--dossie",help="se fornecido, executa pipeline offline em worker Linux")
    parser.add_argument("--sqlite",help="SQLite staging opcional com --dossie")
    args=parser.parse_args(argv)
    if args.sqlite and not args.dossie:
        parser.error("--sqlite requer --dossie")
    try:
        result=coletar_uma_edicao(
            safra=args.safra,numero=args.levantamento,output_root=args.destino,
            catalogo=args.catalogo,
        )
        print(json.dumps(result,ensure_ascii=False))
        if args.dossie:
            from .conab_lote_isolado import executar_worker_conab
            worker=executar_worker_conab(
                manifesto=result["manifesto"],base_dir=result["diretorio_raw"],
                saida=args.dossie,sqlite=args.sqlite,
            )
            print(f"PIPELINE={worker['exit_code']}")
            return 0 if worker["exit_code"]==0 else 2
        return 0
    except (ErroColetaPontualConab,ErroDocumentoConab,OSError,ValueError) as exc:
        print(f"CAPTURA CONAB REJEITADA: {exc}",file=__import__("sys").stderr)
        return 3


if __name__=="__main__":
    raise SystemExit(main())
