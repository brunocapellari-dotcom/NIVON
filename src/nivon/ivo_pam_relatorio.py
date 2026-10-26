"""Relatório operacional pronto para leitura do IVO/PAM, sem novas fontes.

Transforma EXCLUSIVAMENTE a entrega estruturada e seu radar de revisões
em HTML estático e Markdown. Não inventa dados, nomes de municípios,
data de publicação, comparação com safra CONAB ou inferência preditiva.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path


class ErroRelatorioPAM(ValueError):
    pass


def _validar(entrega):
    if (not isinstance(entrega, dict)
            or entrega.get("estado") != "ENTREGA_ESTRUTURADA_PAM_PARA_IVO"
            or entrega.get("fonte") != "IBGE_PAM"
            or entrega.get("calendario") != "ANO_CIVIL"
            or entrega.get("previsao_gerada") is not False
            or entrega.get("data_oficial_publicacao_conhecida") is not False):
        raise ErroRelatorioPAM("entrega PAM anual incompatível ou sem limites de proveniência")
    linhas=entrega.get("linhas")
    eventos=entrega.get("eventos_relevantes")
    if (not isinstance(linhas,list) or not 1<=len(linhas)<=30
            or not isinstance(eventos,list) or len(eventos)>500
            or entrega.get("celulas_unicas")!=len(linhas)
            or entrega.get("alteracoes_materiais_neste_ciclo")!=len(eventos)):
        raise ErroRelatorioPAM("linhas/eventos incompletos ou inconsistentes")
    chaves=set()
    for r in linhas:
        if not isinstance(r,dict):
            raise ErroRelatorioPAM("linha PAM inválida")
        ident=(r.get("municipio_ibge"),r.get("ano_civil"),
               r.get("categoria_c81"),r.get("variavel"))
        if ident in chaves:
            raise ErroRelatorioPAM("célula PAM duplicada")
        chaves.add(ident)
        if (not isinstance(ident[0],str) or len(ident[0])!=7
            or not ident[0].isdigit() or type(ident[1]) is not int
            or not 1974<=ident[1]<=2100
            or not isinstance(ident[2],str) or not ident[2].isdigit()
            or ident[3] not in ("109","214")
            or not isinstance(r.get("unidade"),str)
            or r.get("rotulo")!="ESTATISTICA_PAM_ANUAL_INFORMADA_NAO_CERTIFICADA"):
            raise ErroRelatorioPAM("identidade/unidade ou classificação PAM inválida")
        value=r.get("valor_candidato")
        if value is not None and (type(value) not in (float,int)
                                  or not math.isfinite(value) or value<0):
            raise ErroRelatorioPAM("valor numérico PAM inválido")
        if value is not None and r.get("estado")!="OBSERVADO_NUMERICO":
            raise ErroRelatorioPAM("marcador SIDRA não pode ser representado como número")
        if (not isinstance(r.get("sha256_original"),str)
                or len(r["sha256_original"])!=64
                or any(c not in "0123456789abcdef" for c in r["sha256_original"])):
            raise ErroRelatorioPAM("linha não possui SHA de origem verificável")
        when=r.get("ultima_coleta_em")
        if not isinstance(when,str) or not when:
            raise ErroRelatorioPAM("hora de coleta ausente")
        try:
            dt=datetime.fromisoformat(when.replace("Z","+00:00"))
        except ValueError as exc:
            raise ErroRelatorioPAM("timestamp de captura inválido") from exc
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ErroRelatorioPAM("fuso de captura ausente")
    for event in eventos:
        if not isinstance(event,dict) or event.get("tipo") not in ("VALOR_ALTERADO","ESTADO_ALTERADO"):
            raise ErroRelatorioPAM("radar incluiu evento não relevante")
    return linhas,eventos


def _n(v):
    if v is None:
        return "Não disponível"
    n=f"{v:,.2f}".replace(",","X").replace(".",",").replace("X",".")
    return n.removesuffix(",00")


def _s(v):
    return html.escape(str(v),quote=True)


def preparar_relatorio_pam(entrega, *, gerado_em=None):
    """Gera saída autocontida e reproduzível com dados de um ciclo aprovado."""
    linhas,eventos=_validar(entrega)
    instant=gerado_em or datetime.now(timezone.utc)
    if not isinstance(instant,datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ErroRelatorioPAM("data de geração exige fuso")
    quando=instant.astimezone(timezone.utc).isoformat()
    latest=max(r["ultima_coleta_em"] for r in linhas)
    head=f"NIVON | PAM/IBGE — boletim de capturas anuais"
    advisory=("Valores anuais da PAM/SIDRA obtidos nas datas indicadas; não são "
              "medições mensais, previsões ou prova da versão publicada em cada ano. "
              "As mudanças são entre capturas, não na data oficial de publicação.")
    columns=("Município (IBGE)","Ano civil","Produto","Indicador","Valor",
             "Unidade","Última coleta UTC","Fonte SHA-256")
    records=[]
    for r in sorted(linhas,key=lambda r:(r["municipio_ibge"],r["ano_civil"],
                                         r["categoria_c81"],r["variavel"])):
        records.append((
            r["municipio_ibge"],str(r["ano_civil"]),r["produto"],
            r["indicador"],_n(r["valor_candidato"]),r["unidade"],
            r["ultima_coleta_em"],r["sha256_original"]))
    title="NIVON • PAM/IBGE — boletim anual"
    tr="".join("<tr>"+"".join("<td>"+_s(v)+"</td>" for v in rec)+"</tr>" for rec in records)
    thead="".join("<th scope='col'>"+_s(x)+"</th>" for x in columns)
    notes="<p class='notice'>"+_s(advisory)+"</p>"
    event_lines=[]
    for e in eventos:
        delta=_n(e.get("variacao_absoluta")) if e.get("variacao_absoluta") is not None else "sem comparação numérica"
        event_lines.append(f"{e['municipio_ibge']} · {e['ano_civil']} · {e['tipo']} · Δ {delta} {e['unidade']} · {e['coletado_em']}")
    li=("".join("<li>"+_s(line)+"</li>" for line in event_lines)
        if event_lines else "<li>Nenhuma alteração de valor ou de estado detectada neste ciclo.</li>")
    style=("body{font:16px system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:24px;"
           "color:#152b39;background:#f8fafb}header{border-bottom:3px solid #176c78;margin-bottom:18px}"
           "h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:25px}"
           ".meta{color:#465c65}.notice{background:#e9f3f2;padding:14px;border-left:4px solid #176c78}"
           ".tablebox{overflow-x:auto}table{border-collapse:collapse;width:100%;background:#fff}"
           "th,td{padding:10px;border-bottom:1px solid #d5e1e4;text-align:left;font-size:.88rem}"
           "th{background:#e9f3f2}td:last-child{font-family:ui-monospace,monospace;font-size:.72rem}"
           "footer{margin-top:25px;font-size:.82rem;color:#596a72}")
    html_doc=(
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>"+_s(title)+"</title><style>"+style+"</style></head><body>"
        "<header><h1>"+_s(head)+"</h1>"
        "<p class='meta'>Gerado em UTC: "+_s(quando)+" · Última coleta UTC: "+_s(latest)+"</p>"
        "<p class='meta'>Fonte: IBGE / SIDRA, tabela 1612 · "
        +str(len(linhas))+" células · "+str(len(eventos))+" alterações relevantes</p></header>"
        +notes+"<h2>Estatísticas anuais divulgadas</h2>"
        "<div class='tablebox'><table><thead><tr>"+thead+"</tr></thead><tbody>"+tr
        +"</tbody></table></div><h2>Revisões detectadas desde a última execução</h2>"
        "<ul>"+li+"</ul><footer>Referência temporal: coleta UTC; publicação oficial não reconstituída. "
        "Sem previsão homologada. Uso informativo interno NIVON.</footer></body></html>")
    markdown=(
        "# "+head+"\n\n"
        "Gerado em UTC: "+quando+" · Última coleta UTC: "+latest+"\n\n"
        "**Fonte:** IBGE/SIDRA tabela 1612. **Células:** "+str(len(linhas))+
        ". **Alterações relevantes:** "+str(len(eventos))+".\n\n"
        "> "+advisory+"\n\n"
        "| "+" | ".join(columns)+" |\n| "+" | ".join(["---"]*len(columns))+" |\n"
        + "".join("| "+" | ".join(str(v).replace("|","\\|").replace("\n"," ") for v in rec)+" |\n"
                  for rec in records)+"\n"
        "## Revisões entre capturas\n\n"
        +("".join("- "+x+"\n" for x in event_lines) if event_lines else
          "Nenhuma alteração de valor ou estado detectada neste ciclo.\n"))
    return {
        "estado":"RELATORIO_PAM_GERADO",
        "gerado_em_utc":quando,
        "ultima_coleta_utc":latest,
        "celulas":len(linhas),"alteracoes_relevantes":len(eventos),
        "html":html_doc,"markdown":markdown,
        "modelo_preditivo_usado":False,"referencia_data_publicacao_verificada":False,
    }


def salvar_relatorio_pam(entrega,*,diretorio,gerado_em=None):
    pasta=Path(diretorio)
    if not pasta.is_dir() or pasta.is_symlink():
        raise ErroRelatorioPAM("diretório de saída precisa existir sem symlink")
    resultado=preparar_relatorio_pam(entrega,gerado_em=gerado_em)
    for nome,campo in (("relatorio_pam.html","html"),("relatorio_pam.md","markdown")):
        p=pasta/nome
        if p.exists() or p.is_symlink():
            raise ErroRelatorioPAM("não sobrescrever relatório existente: "+nome)
        p.write_text(resultado[campo],encoding="utf-8")
    return {k:v for k,v in resultado.items() if k not in ("html","markdown")}


def main(argv=None):
    parser=argparse.ArgumentParser(description="NIVON PAM: JSON estruturado -> relatório HTML e Markdown")
    parser.add_argument("--entrega",type=Path,required=True)
    parser.add_argument("--saida",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        data=json.loads(args.entrega.read_text(encoding="utf-8"))
        result=salvar_relatorio_pam(data,diretorio=args.saida)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({"estado":"BLOQUEADO","erro":str(exc)[:250]},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
