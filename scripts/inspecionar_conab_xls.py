"""Inspecionar fontes oficiais CONAB sem salvar dados ou publicar séries brutas.

Somente metadados de XLS e primeiras células de cabeçalho para desenvolver
parsers com layouts comprovados. A consulta NÃO homologa a redistribuição.
"""
from __future__ import annotations
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from nivon.conab_catalogo import descobrir_planilhas, PAGINAS
from nivon.conab_series import normalizar_livro, conferir_total_milho

MAX_HTML=4_000_000
MAX_XLS=5_000_000

def baixar(url: str, limite: int) -> tuple[bytes,str,str]:
    requisicao=Request(url,headers={"User-Agent":"NIVON/0.2 (+inspecao-dados-publicos)", "Accept":"text/html,application/vnd.ms-excel,application/octet-stream"})
    with urlopen(requisicao,timeout=25) as resposta:
        destino=resposta.geturl()
        p=urlparse(destino)
        if p.scheme!="https" or p.hostname not in {"www.gov.br","gov.br","conab.gov.br","www.conab.gov.br"}:
            raise ValueError("redirecionamento para host não autorizado")
        if resposta.status!=200:
            raise ValueError("resposta HTTP diferente de 200")
        dados=resposta.read(limite+1)
        if not dados or len(dados)>limite:
            raise ValueError("arquivo vazio ou excedeu limite")
        return dados,destino,resposta.headers.get("Content-Type","")

def inspectar_xls(data: bytes)->dict:
    if not data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise ValueError("arquivo não tem assinatura OLE XLS")
    import xlrd
    book=xlrd.open_workbook(file_contents=data, on_demand=True)
    out=[]
    for sheet in book.sheets():
        # Apenas primeiras 12 linhas, 8 colunas: descobrir estrutura e unidades.
        sample=[]
        for r in range(min(sheet.nrows,12)):
            vals=[]
            for c in range(min(sheet.ncols,8)):
                v=sheet.cell_value(r,c)
                vals.append(str(v)[:90] if v!="" else "")
            sample.append(vals)
        out.append({"nome":sheet.name,"linhas":sheet.nrows,"colunas":sheet.ncols,"cabecalho_amostra":sample})
    return {"abas":out}

def executar():
    resultados=[]
    todas=[]
    for produto in ("SOJA","MILHO"):
        html,url,_=baixar(PAGINAS[produto],MAX_HTML)
        planilhas=descobrir_planilhas(html.decode("utf-8",errors="replace"),produto)
        for p in planilhas:
            link=p["url"]
            # Portal Plone pode expor link /view; seguir link e baixar o objeto pela rota pública.
            candidatos=[link]
            if link.endswith("/view"):
                candidatos=[link[:-5]+"/@@download/file",link[:-5]+"/@@download",link]
            erros=[]
            resumo=None
            for candidato in candidatos:
                try:
                    conteudo,url_final,mime=baixar(candidato,MAX_XLS)
                    sha=hashlib.sha256(conteudo).hexdigest()
                    import xlrd
                    livro=xlrd.open_workbook(file_contents=conteudo,on_demand=True)
                    normalizados=normalizar_livro(
                        livro,p["arquivo"],sha256=sha,
                        capturado_em=datetime.now(timezone.utc).isoformat()
                    )
                    todas.extend(normalizados)
                    safra_final=max(z["safra"] for z in normalizados)
                    finais=[
                        {"uf":x["regiao_uf"],"indicador":x["indicador"],
                         "valor":x["valor"],"unidade":x["unidade"]}
                        for x in normalizados
                        if x["safra"]==safra_final and x["regiao_uf"] in ("BR","MT")
                    ]
                    resumo={"abas":[{"nome":aba.name,"linhas":aba.nrows,
                                     "colunas":aba.ncols}
                                     for aba in livro.sheets()],
                            "total_observacoes_extraidas":len(normalizados),
                            "ultimo_ano_safra":safra_final,"indicadores_finais":finais}
                    resumo.update({"produto":produto,"arquivo":p["arquivo"],
                                  "url":url_final,"bytes":len(conteudo),
                                  "sha256":sha,"mime":mime})
                    break
                except Exception as exc:
                    erros.append({"tipo":type(exc).__name__,"url":candidato})
            if resumo is None:
                resumo={"produto":produto,"arquivo":p["arquivo"],"estado":"NAO_ACESSIVEL","tentativas":erros}
            resultados.append(resumo)
    conciliacao=conferir_total_milho(todas)
    erros=[x for x in conciliacao if x["status"]=="DIVERGENTE"]
    return {"fonte":"CONAB","finalidade":"VALIDACAO_EXTRAÇÃO_SEM_REDISTRIBUIÇÃO",
            "planilhas":resultados,"linhas_normalizadas":len(todas),
            "conciliacao_milho":{"checagens":len(conciliacao),
                                 "divergencias":len(erros),
                                 "amostra_divergencias":erros[:5],
                                 "sem_parcela":sum(x["status"]=="NAO_COMPARAVEL_PARCELA_AUSENTE" for x in conciliacao)}}

if __name__=="__main__":
    print(json.dumps(executar(),ensure_ascii=False,indent=2))
