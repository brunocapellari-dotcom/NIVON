"""Primeiro produto interno NIVON: retrato de fontes REAIS ja verificadas.

Sem rede no renderizador, sem APIs públicas e sem promover SHADOW a dado
homologado. Nenhum detalhe de navios, trading, cargas privadas ou anuncios.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
import json


class ErroLancamento(ValueError):
    pass


def _instante(value):
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except (AttributeError,ValueError) as exc:
        raise ErroLancamento("corte deve ter data ISO e timezone") from exc
    if dt.utcoffset() is None:
        raise ErroLancamento("corte sem timezone")
    return dt.astimezone(timezone.utc).isoformat()


def _tu(value):
    try:
        number=Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ErroLancamento("toneladas uteis invalidas") from exc
    if not number.is_finite() or number < 0:
        raise ErroLancamento("toneladas negativas ou nao-finitas")
    return number


def _formato_numero(value):
    value=Decimal(str(value))
    parts=format(value.quantize(Decimal("0.01")),"f").split(".")
    inteiro=f"{int(parts[0]):,}".replace(",",".")
    return inteiro + ((","+parts[1]) if parts[1]!="00" else "")


def construir_retrato(painel, *, as_of, competencia_ferrovia="2026-08"):
    """Falha fechado se a leitura nao foi autenticada ou contraria o contrato.

    Este produto e diagnostico interno; nenhuma janela historica equivale a
    movimentacao na hora da consulta. Ausencia nao e convertida em zero.
    """
    as_of=_instante(as_of)
    if not isinstance(painel,dict) or painel.get("status")!="ANALISE_SHADOW_NAO_HOMOLOGADA":
        raise ErroLancamento("painel inesperado ou nao homologado")
    if painel.get("executou_bigquery") is not True:
        raise ErroLancamento("go-live nao aceita mock, fixture ou plano sem rede")
    rail=painel.get("ferrovia")
    if not isinstance(rail,dict) or (rail.get("estado")!="REVISAO_ATUAL_CONSULTADA_NAO_HOMOLOGADA"
                                   or rail.get("executado") is not True):
        raise ErroLancamento("leitura ferroviaria real ausente")
    if rail.get("competencia")!=competencia_ferrovia or rail.get("fonte")!="ANTT_SIADE_ORIGEM_DESTINO":
        raise ErroLancamento("fonte ou competencia ANTT incorreta")
    if rail.get("historico_pit_reconstruido") is not False or rail.get("transbordo_confirmado") is not False:
        raise ErroLancamento("vintage/transbordo ferroviario sem evidencias")
    if rail.get("publicavel") is not False or rail.get("arquivos_sha256") is None:
        raise ErroLancamento("fonte ferroviaria sem marcador de proveniencia")
    polos=rail.get("polos_ferroviarios")
    if not isinstance(polos,list) or not 1<=len(polos)<=100:
        raise ErroLancamento("polos ferroviarios ausentes ou excesso de linhas")
    grouped=[]
    ids=set()
    for row in polos:
        if not isinstance(row,dict) or row.get("terminal_comprovado") is not False:
            raise ErroLancamento("polo como terminal confirmado indevidamente")
        polo=row.get("polo")
        if not isinstance(polo,dict) or not isinstance(polo.get("id"),str):
            raise ErroLancamento("identidade polo ausente")
        id_=polo["id"]
        if id_ in ids or not id_.startswith("MT_"):
            raise ErroLancamento("polo nao unico ou fora de MT")
        ids.add(id_)
        grouped.append({"polo_id":id_,"toneladas_uteis":format(_tu(row.get("toneladas_ferroviarias")),"f")})
    grouped.sort(key=lambda r:(-_tu(r["toneladas_uteis"]),r["polo_id"]))
    series=painel.get("fontes_maritimas_bigquery")
    if not isinstance(series,list) or len(series)!=2:
        raise ErroLancamento("go-live precisa de Imbituba e PortWatch em recortes separados")
    by={}
    for x in series:
        if not isinstance(x,dict) or x.get("executado") is not True or x.get("publicavel") is not False:
            raise ErroLancamento("fonte maritima sem execucao read-only comprovada")
        key=x.get("fonte") or x.get("passagem")
        if key in by or key not in ("imbituba","panama"):
            raise ErroLancamento("fonte maritima divergente")
        by[key]=x
    if set(by)!={"imbituba","panama"}:
        raise ErroLancamento("contrato de 2 fontes maritimas incompleto")
    imp=by["imbituba"]
    if (imp.get("estado")!="PROGRAMACAO_HISTORICA_READONLY_SHADOW"
        or imp.get("vinculo_duv_confirmado") is not False
        or imp.get("navios_operados_confirmados") is not None
        or imp.get("toneladas_realizadas") is not None):
        raise ErroLancamento("Imbituba sem programacao validada ou inferencia proibida")
    pw=by["panama"]
    if pw.get("volume_movimentado_real") is not None:
        raise ErroLancamento("PortWatch nao pode representar tonelagem realizada")
    if pw.get("estado") not in ("PORTWATCH_TRANSITOS_ESTIMADOS_SHADOW",
                               "SEM_DADOS_NAO_EQUIVALE_A_ZERO"):
        raise ErroLancamento("PortWatch fora da taxonomia permitida")
    ids_programacao=imp.get("ids_programacao_distintos")
    rev=imp.get("revisoes_visiveis")
    if any(type(x) is not int or x<0 for x in (ids_programacao,rev)) or rev<ids_programacao:
        raise ErroLancamento("IDs/revisoes da programacao inconsistentes")
    n_pw=pw.get("revisoes_visiveis")
    if type(n_pw) is not int or n_pw<0:
        raise ErroLancamento("contagem PortWatch invalida")
    cond=("ATIVO_INTERNO_SHADOW" if pw["estado"]=="PORTWATCH_TRANSITOS_ESTIMADOS_SHADOW"
          else "ATIVO_COM_LACUNA_PORTWATCH")
    return {
        "produto":"NIVON | Painel Operacional Interno",
        "schema_version":"NIVON_INTERNO_1",
        "privacidade":"INTERNO_PRIVADO",
        "status":cond, "data_corte_utc":as_of,
        "ambiente":"GOOGLE_CLOUD_SOMENTE_LEITURA",
        "ferrovia":{
            "competencia":competencia_ferrovia,
            "natureza":"ANTT_SIADE_TONELADAS_UTEIS_DECLARADAS",
            "toneladas_recorte_polos":format(sum((_tu(r["toneladas_uteis"]) for r in grouped),
                                             Decimal("0")),"f"),
            "polos":grouped,"linhas_view":rail.get("linhas_view"),
            "source_lag":True,"historico_pit_reconstruido":False,
            "somar_com_rodovia":False,"terminal_comprovado":False,
        },
        "imbituba":{
            "natureza":"PROGRAMACAO_HISTORICA_INFORMADA",
            "ids_programacao":ids_programacao,
            "revisoes":rev,"navios_realizados":None,
            "toneladas_realizadas":None,
        },
        "portwatch":{
            "natureza":"ESTIMATIVA_MODELO_FMI",
            "passagem":"PANAMA","revisoes":n_pw,
            "dias":pw.get("dias_distintos"),
            "volume_estimado_modelo_t":pw.get("volume_estimado_modelo_t"),
            "volume_realizado_t":None,
            "status":pw["estado"],
        },
        "avisos":[
            "Uso interno. Medidas em modo SHADOW, nao homologadas para distribuicao.",
            "Ferrovia: competencia historica, nao movimento atual. Polos nao sao terminais comprovados.",
            "Imbituba: IDs de programacao nao sao DUV ou navios operados.",
            "PortWatch: transitos/volumes sao estimativas e revisoes, nao carga realizada.",
            "Sem somar modais, sem inferir atracacoes, sem probabilidade calibrada de fila.",
        ],
    }


def renderizar_html(retrato):
    """HTML estatico sem bibliotecas, imagens externas, dados brutos ou JS."""
    if not isinstance(retrato,dict) or retrato.get("privacidade")!="INTERNO_PRIVADO":
        raise ErroLancamento("relatorio fora do perfil interno")
    f=retrato["ferrovia"];m=retrato["imbituba"];p=retrato["portwatch"]
    polos=f["polos"]
    maior=max((_tu(row["toneladas_uteis"]) for row in polos),default=Decimal(1))
    bars="".join(
        '<div class="bar-row"><div class="bar-label"><span>'+escape(row["polo_id"].replace("MT_","").replace("_"," "))+
        '</span><strong>'+escape(_formato_numero(row["toneladas_uteis"]))+' t</strong></div>'+
        '<div class="track"><div class="fill" style="width:'+str(round(float(_tu(row["toneladas_uteis"])/max(maior,Decimal("1")))*100,1))+'%"></div></div></div>'
        for row in polos[:12]
    )
    warnings="".join("<li>"+escape(s)+"</li>" for s in retrato["avisos"])
    def card(label,value,subtitle):
        return '<article class="metric"><p>'+escape(label)+'</p><strong>'+escape(value)+'</strong><small>'+escape(subtitle)+'</small></article>'
    maritime=card("Imbituba — programação",str(m["ids_programacao"]),
        "IDs de programação; não equivalem a navios operados")+card(
        "PortWatch — Panamá",str(p["revisoes"]),"Revisões de estimativas, não carga realizada")
    raw=json.dumps({
        "gerado_em":retrato["data_corte_utc"],"status":retrato["status"],
        "competencia":f["competencia"],
    },ensure_ascii=False,sort_keys=True)
    return """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>NIVON — Painel Operacional Interno</title><style>
:root{color-scheme:light;--forest:#163c31;--leaf:#237452;--sand:#f5f2e9;--gold:#cfaa53;--ink:#1b2e29;--muted:#61756c}
*{box-sizing:border-box}body{margin:0;background:var(--sand);color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}
header{background:var(--forest);color:#f8f8f2;padding:30px max(24px,calc((100vw - 1160px)/2))}
.brand{font-weight:850;font-size:24px;letter-spacing:.08em}header h1{margin:10px 0 4px;font-size:clamp(25px,3vw,38px)}header p{margin:0;color:#d1dfd6}
main{max-width:1160px;margin:0 auto;padding:24px}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:11px;color:var(--leaf);font-weight:800}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.metric,.panel{background:#fff;border:1px solid #e3e6dc;border-radius:15px;padding:20px}
.metric p{margin:0;font-size:13px;color:var(--muted)}.metric strong{display:block;font-size:clamp(23px,3vw,34px);margin:7px 0;color:var(--forest);letter-spacing:-.05em}
.metric small{color:var(--muted);display:block}.layout{display:grid;grid-template-columns:1.25fr 1fr;gap:15px;margin-top:15px}
h2{font-size:19px;margin:4px 0 15px}h3{font-size:16px}.bar-row{margin:14px 0}.bar-label{display:flex;gap:6px;justify-content:space-between;font-size:12px;flex-wrap:wrap}
.track{margin-top:5px;height:9px;border-radius:9px;background:#ebeee8;overflow:hidden}.fill{height:100%;border-radius:9px;background:var(--leaf)}
.note{border-left:4px solid var(--gold);padding:10px 14px;background:#fbf7ec;border-radius:5px;color:#584922}
footer{margin:20px 0;color:var(--muted);font-size:12px}.stamp{font-size:12px;color:#d1dfd6}
ul{padding-left:18px}li{margin:7px 0}.flag{display:inline-block;background:#d9e6dc;color:#17462c;padding:4px 11px;border-radius:15px;font-weight:750;font-size:11px}
@media(max-width:760px){.grid,.layout{grid-template-columns:1fr}main{padding:14px}header{padding:24px 16px}.metric{padding:14px}}
</style></head><body><header><div class="brand">NIVON<span style="color:#cfaa53"> /</span></div>
<h1>Inteligência agroindustrial e logística</h1>
<p>Painel gerencial interno de dados reais — primeira edição limitada</p>
<div class="stamp">Corte UTC: """+escape(retrato["data_corte_utc"])+""" · Restrito ao ambiente autorizado</div></header><main>
<p class="eyebrow">Visão operacional <span class="flag">SHADOW • NÃO HOMOLOGADO</span></p>
<div class="grid">"""+card("ANTT/SIADE — volume ferroviário",_formato_numero(f["toneladas_recorte_polos"])+" t",
"Somente polos selecionados · competência "+f["competencia"])+maritime+"""</div>
<div class="layout"><section class="panel"><p class="eyebrow">Mato Grosso / ferrovia</p>
<h2>Movimentação declarada por polo</h2><p class="note">Toneladas úteis por estação de origem,
sem interpretação como transbordo ou soma intermodal. Competência histórica.</p>"""+bars+"""</section>
<section class="panel"><p class="eyebrow">Marítimo / proveniência</p><h2>Programação × estimativa</h2>
<h3>Imbituba</h3><p>"""+str(m["revisoes"])+""" revisões de programação; nenhum evento concluído confirmado neste painel.</p>
<h3>PortWatch — Panamá</h3><p>"""+str(p["revisoes"])+""" revisões consultadas.</p>
<p class="note">Uma fonte apresenta programação informada. A outra apresenta estimativas
de trânsito. Não possuem a mesma unidade, e não são somadas.</p></section></div>
<section class="panel" style="margin-top:15px"><p class="eyebrow">Governança da informação</p>
<h2>Ressalvas e escopo</h2><ul>"""+warnings+"""</ul></section>
<footer>Documento gerado para acesso interno. Ausência de dado não significa zero.
Nenhum número representa operação AIS confirmada.</footer></main></body></html>"""
