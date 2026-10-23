"""Ponte determinística: séries CONAB/line-up armazenados -> briefing NIVON.

SEM rede, sem LLM e sem acesso a dados secretos. Não prediz evolução semanal
a partir de dois pontos nem soma tonelagem portuária sem identidade de lote.
Informações sem evidência temporal/direitos são omitidas e documentadas.
"""
from __future__ import annotations

from datetime import datetime, timedelta, date, timezone
from math import isfinite
import sqlite3

from .progresso_store import consultar_progresso_asof
from .portos_store import historico_porto


class ErroPonte(ValueError):
    pass


def _instante(value: str) -> datetime:
    if not isinstance(value, str):
        raise ErroPonte("instante ausente")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroPonte("instante inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroPonte("instante precisa ter fuso")
    return dt.astimezone(timezone.utc)


def _direitos(fontes: dict, chave: str) -> bool:
    if not isinstance(fontes, dict) or not isinstance(fontes.get(chave),dict):
        return False
    direito = fontes[chave]
    return (
        direito.get("status_direitos") == "APROVADA"
        and {"LEITURA","PUBLICACAO_DERIVADA"}.issubset(
            set(direito.get("operacoes") or [])
        )
    )


def indicador_conab(
    db: sqlite3.Connection, *,
    cultura: str, safra: str, operacao: str, uf: str, semana: str,
    gerado_em: str, fontes: dict, max_idade_dias: int = 21,
) -> dict:
    """Consulta versões históricas sem look-ahead e compara semana equivalente."""
    agora = _instante(gerado_em)
    if not isinstance(max_idade_dias, int) or not 1 <= max_idade_dias <= 90:
        raise ErroPonte("idade limite inválida")
    if operacao not in {"Semeadura","Colheita"} or not cultura or not safra:
        raise ErroPonte("safra/operação inválida")
    if uf != "MEDIA_ESTADOS" and (len(uf) != 2 or uf != uf.upper()):
        raise ErroPonte("UF inválida")
    try:
        reference = date.fromisoformat(semana)
    except (TypeError,ValueError) as exc:
        raise ErroPonte("semana inválida") from exc
    if reference > agora.date():
        raise ErroPonte("semana futura")
    if not _direitos(fontes,"CONAB"):
        return {"status":"BLOQUEADO_DIREITOS","motivo":"CONAB sem publicação derivada autorizada"}
    args=dict(cultura=cultura,safra=safra,operacao=operacao,uf=uf,
              corte_coleta=agora.isoformat(),corte_publicacao=agora.isoformat())
    atual=consultar_progresso_asof(db,semana=semana,**args)
    if not atual:
        return {"status":"SEM_OBSERVACAO_ASOF","motivo":"sem edição CONAB publicada e coletada até o corte"}
    publicado=_instante(atual["publicacao"])
    if publicado > agora or agora-publicado > timedelta(days=max_idade_dias):
        return {"status":"DADO_VENCIDO","motivo":"publicação CONAB fora da janela"}
    obs=atual["observacao"]
    frac=obs.get("pct_semana_atual")
    if type(frac) not in (int,float) or not isfinite(frac) or not 0<=frac<=1:
        return {"status":"DADO_INVALIDO","motivo":"percentual atual ausente/incorreto"}
    anterior_semana=(reference-timedelta(days=7)).isoformat()
    anterior=consultar_progresso_asof(db,semana=anterior_semana,**args)
    deltapct=None
    if anterior:
        v=anterior["observacao"].get("pct_semana_atual")
        if type(v) in (int,float) and isfinite(v) and 0<=v<=1:
            deltapct=round((frac-v)*100,2)
    texto=f"{frac*100:.1f}% informado"
    if deltapct is not None:
        texto+=f"; {deltapct:+.1f} p.p. vs. semana anterior"
    else:
        texto+="; comparação semanal indisponível"
    if uf=="MEDIA_ESTADOS":
        texto+="; média dos estados informantes (NÃO Brasil)"
    titulo=f"{cultura.upper()} — {operacao} {uf} ({safra})"
    return {
        "status":"INDICADOR_VERIFICADO_TEMPO",
        "indicador":{
            "fonte_id":"CONAB","secao":"SAFRA","titulo":titulo,
            "valor":texto,"referencia":publicado.isoformat(),
            "fonte":f"CONAB Progresso Semanal, competência {semana}",
        },
        "evidencia":{
            "cultura":cultura,"uf":uf,"semana":semana,
            "fonte_url":obs["source_url"],"edicao_sha256":atual["sha256"],
            "coleta":atual["coleta"],"publicacao":atual["publicacao"],
            "comparacao_observada":deltapct is not None,
            "comparacao_sha256":anterior["sha256"] if anterior and deltapct is not None else None,
            "modelo":"VARIACAO_CONTABIL_NAO_PREDITIVA",
        },
    }


def indicador_porto(
    db: sqlite3.Connection, *,
    porto: str, gerado_em: str, fontes: dict, max_idade_horas: int = 72,
) -> dict:
    """Produz apenas CONTAGEM de navios programados com DUV, não toneladas."""
    agora=_instante(gerado_em)
    if not isinstance(max_idade_horas,int) or not 1<=max_idade_horas<=168:
        raise ErroPonte("limite portuário inválido")
    if not _direitos(fontes,"LINEUP_"+porto):
        return {"status":"BLOQUEADO_DIREITOS","motivo":"line-up sem licença de publicação derivada"}
    rows=historico_porto(db,porto=porto,corte_coleta=agora.isoformat())
    if not rows:
        return {"status":"SEM_OBSERVACAO_ASOF","motivo":"porto sem documento até o corte"}
    latest=_instante(rows[0]["captura_consultada"])
    if latest>agora or agora-latest>timedelta(hours=max_idade_horas):
        return {"status":"DADO_VENCIDO","motivo":"captura portuária antiga"}
    if any(r.get("status")!="PROGRAMADO" for r in rows):
        return {"status":"DADO_INVALIDO","motivo":"registro não é programação"}
    duvs={r["duv"] for r in rows if r.get("duv")}
    faltantes=sum(not r.get("duv") for r in rows)
    valor=f"{len(duvs)} escalas programadas com DUV; {faltantes} linhas sem DUV"
    return {
        "status":"INDICADOR_VERIFICADO_TEMPO",
        "indicador":{
            "fonte_id":"LINEUP_"+porto, "secao":"PORTOS",
            "titulo":f"Line-up {porto}", "valor":valor,
            "referencia":latest.isoformat(),
            "fonte":"Documento portuário (captura; não prova embarque)",
        },
        "evidencia":{
            "porto":porto,"coleta":latest.isoformat(),
            "sha256_documento":rows[0]["documento_sha256"],
            "fonte_url":rows[0].get("fonte"),
            "classificacao":"PROGRAMACAO_NAO_REALIZADA",
            "volume_reportado_t":None,
            "limitacao":"data de publicação desconhecida; não usar para backtest as-of por publicação",
        },
    }


def compor_pacote_historico(*, db_conab: sqlite3.Connection | None,
                           db_portos: sqlite3.Connection | None,
                           db_mercados: sqlite3.Connection | None = None,
                           incluir_ptax_usd: bool = False,
                           modo_ptax: str = "LEGADO",
                           db_ptax_raw: sqlite3.Connection | None = None,
                           db_diesel: sqlite3.Connection | None = None,
                           diesel_localidades: list[dict] | None = None,
                           cotacoes_licenciadas: list[dict] | None = None,
                           licencas_verificadas: dict | None = None,
                           fontes: dict, gerado_em: str,
                           noticias: list[dict] | None = None,
                           indicadores_externos: list[dict] | None = None,
                           fretes: list[dict] | None = None,
                           culturas: list[dict] | None = None,
                           portos: list[str] | None = None) -> dict:
    """Passa indicadores já validados ao briefing, sem tentar adquirir dados."""
    _instante(gerado_em)
    if modo_ptax not in {"LEGADO", "AUDITAR_RAW"}:
        raise ErroPonte("modo PTAX não reconhecido")
    resultados=[]
    if noticias is None: noticias=[]
    if indicadores_externos is None: indicadores_externos=[]
    if fretes is None: fretes=[]
    indicadores=list(indicadores_externos)
    for contrato in culturas or []:
        if db_conab is None:
            r={"status":"SEM_HISTORICO","motivo":"banco CONAB não configurado"}
        else:
            r=indicador_conab(db_conab,gerado_em=gerado_em,
                              fontes=fontes,**contrato)
        resultados.append({"origem":"CONAB",**r})
        if r["status"]=="INDICADOR_VERIFICADO_TEMPO":
            indicadores.append(r["indicador"])
    for port in portos or []:
        if db_portos is None:
            r={"status":"SEM_HISTORICO","motivo":"banco portuário não configurado"}
        else:
            r=indicador_porto(db_portos,porto=port,gerado_em=gerado_em,
                              fontes=fontes)
        resultados.append({"origem":"PORTOS",**r})
        if r["status"]=="INDICADOR_VERIFICADO_TEMPO":
            indicadores.append(r["indicador"])
    if incluir_ptax_usd:
        if modo_ptax == "AUDITAR_RAW":
            # Via paralela somente de diagnóstico. Mesmo com paridade, a
            # data de publicação BCB e autorização editorial independente
            # permanecem não comprovadas, portanto NÃO insere indicador.
            if db_mercados is None or db_ptax_raw is None:
                r={"status":"SEM_HISTORICO","motivo":"faltam banco legado ou RAW",
                   "publicavel":False}
            else:
                from .auditoria_migracao_ptax import auditar_migracao_ptax
                from .ptax_cobertura_mercados import diagnosticar_cobertura_ptax
                try:
                    paridade=auditar_migracao_ptax(
                        db_mercados,db_ptax_raw,gerado_em=gerado_em,
                        fontes=fontes,moeda="USD")
                    cobertura=diagnosticar_cobertura_ptax(
                        db_ptax_raw,corte=gerado_em,moeda="USD")
                    r={
                        "status":"AUDITORIA_PTAX_RAW_SEM_LIBERACAO_EDITORIAL",
                        "paridade":paridade,
                        "cobertura":cobertura,
                        "motivo":"captura nao comprova horario de publicacao",
                        "publicavel":False,
                        "apto_backtest_por_publicacao":False,
                    }
                except (ValueError,sqlite3.Error):
                    r={
                        "status":"PTAX_BLOQUEADA_INTEGRIDADE",
                        "motivo":"erro na validacao de RAW ou legado",
                        "publicavel":False,
                    }
            resultados.append({"origem":"BCB_PTAX",**r})
        else:
            if db_mercados is None:
                r={"status":"SEM_HISTORICO","motivo":"banco PTAX não configurado"}
            else:
                from .indicador_ptax import indicador_ptax_sqlite
                r=indicador_ptax_sqlite(db_mercados,gerado_em=gerado_em,
                                       fontes=fontes,moeda="USD")
            resultados.append({"origem":"BCB_PTAX",**r})
            if r["status"]=="INDICADOR_VERIFICADO_TEMPO":
                indicadores.append(r["indicador"])
    for local in diesel_localidades or []:
        if db_diesel is None:
            r={"status":"SEM_HISTORICO","motivo":"banco municipal diesel não configurado"}
        else:
            from .anp_diesel_store import indicador_diesel_municipal
            r=indicador_diesel_municipal(
                db_diesel,gerado_em=gerado_em,fontes=fontes,**local)
        resultados.append({"origem":"ANP_DIESEL",**r})
        if r["status"]=="INDICADOR_VERIFICADO_TEMPO":
            indicadores.append(r["indicador"])
    if cotacoes_licenciadas:
        from .cotacoes_briefing import preparar_cotacoes_licenciadas
        resultado_mercado=preparar_cotacoes_licenciadas(
            cotacoes=cotacoes_licenciadas,
            licencas_verificadas=licencas_verificadas or {},
            gerado_em=gerado_em)
        if resultado_mercado["recusados"]:
            resultados.append({
                "origem":"MERCADOS_LICENCIADOS",
                "status":"BLOQUEADO_COTACOES",
                "motivo":"uma ou mais observações externas foram recusadas",
                "indices_recusados":[r["indice"] for r in resultado_mercado["recusados"]],
            })
        else:
            indicadores.extend(resultado_mercado["indicadores"])
            resultados.append({
                "origem":"MERCADOS_LICENCIADOS",
                "status":"INDICADOR_VERIFICADO_TEMPO",
                "evidencias":resultado_mercado["evidencias"],
                "observacoes":len(resultado_mercado["indicadores"]),
            })
    return {
        "pacote":{
            "noticias":noticias, "indicadores":indicadores,
            "fretes":fretes, "fontes":fontes,
        },
        "resultados":resultados,
        "status":"PACOTE_OFFLINE_SEM_ENVIO",
    }
