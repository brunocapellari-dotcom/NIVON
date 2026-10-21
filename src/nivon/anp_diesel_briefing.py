"""Indicador de diesel da ANP para o briefing NIVON, sujeito à homologação.

Preço médio municipal amostral de REVENDAS (diesel B) NÃO é diesel A, PPI,
preço logístico, preço negociado ou cotação nacional. Sem autorização, não publica.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from .lineup_nacional import instante


class ErroDieselBriefing(ValueError):
    pass


def montar_indicadores_diesel(
    resultado: dict, *, gerado_em: str, publicado_em: str, dataset: dict,
    direitos: dict, layout_homologado: bool = False, max_dias_defasagem: int = 14,
    municipios: frozenset[str] | None = None,
) -> dict:
    agora=instante(gerado_em)
    pub=instante(publicado_em)
    if pub>agora:
        raise ErroDieselBriefing("data de publicação posterior à geração")
    if type(max_dias_defasagem) is not int or not 1<=max_dias_defasagem<=30:
        raise ErroDieselBriefing("limite de defasagem inválido")
    if (not isinstance(dataset,dict) or dataset.get("id")!="ANP_PRECO_REVENDA_DIESEL"
        or dataset.get("enabled") is not True or
        dataset.get("collection_authorized") is not True or
        dataset.get("commercial_redistribution_authorized") is not True):
        raise PermissionError("coleta e redistribuição ANP não homologadas")
    if (not isinstance(direitos,dict) or direitos.get("status")!="APROVADA"
        or not direitos.get("evidencia_id") or
        not {"LEITURA","COLETA","ARMAZENAMENTO","PUBLICACAO_DERIVADA"}.issubset(set(direitos.get("operacoes",[])))):
        raise PermissionError("direitos ANP de derivado não comprovados")
    if layout_homologado is not True or not direitos.get("layout_real_sha256"):
        raise PermissionError("layout XLSX real e prova de versão não homologados")
    if resultado.get("fonte")!="ANP_RESUMO_LPC_SEMANAL" or resultado.get("dataset_id")!="ANP_PRECO_REVENDA_DIESEL":
        raise ErroDieselBriefing("resumo não é a série semanal oficial esperada")
    if resultado.get("sha256")!=direitos["layout_real_sha256"]:
        raise ErroDieselBriefing("arquivo diverge da versão XLSX homologada")
    coleta=instante(resultado.get("coletado_em"))
    if pub>coleta or coleta>agora:
        raise ErroDieselBriefing("datas de publicação e coleta incompatíveis")
    if municipios is not None and (not isinstance(municipios,frozenset) or not municipios):
        raise ErroDieselBriefing("filtro de municípios inválido")
    permitidos=set(municipios) if municipios is not None else None
    obs=resultado.get("observacoes")
    if not isinstance(obs,list) or not obs:
        raise ErroDieselBriefing("arquivo sem observações semanais")
    atual=max(date.fromisoformat(r["semana_fim_oficial"]) for r in obs)
    calendario_br=ZoneInfo("America/Sao_Paulo")
    hoje_br=agora.astimezone(calendario_br).date()
    if atual>hoje_br or atual<hoje_br-timedelta(days=max_dias_defasagem):
        raise ErroDieselBriefing("série ANP defasada: não publicar como atual")
    if pub.astimezone(calendario_br).date()<atual:
        raise ErroDieselBriefing("publicação ANP anterior ao fim da semana pesquisada")
    linhas=[];vistos=set()
    for r in obs:
        if r["semana_fim_oficial"]!=atual.isoformat():
            continue
        if r["uf"]!="MT" or r["produto"] not in ("DIESEL","DIESEL S10"):
            raise ErroDieselBriefing("produto ou UF do agregado divergente")
        mun=r["municipio"]
        if permitidos is not None and mun not in permitidos:
            continue
        key=(mun,r["produto"])
        if key in vistos:
            raise ErroDieselBriefing("produto e município duplicados na última semana")
        vistos.add(key)
        preco=Decimal(str(r["preco_medio_revenda_rs_l"]))
        n=r["postos_pesquisados"]
        if not preco.is_finite() or not 0<preco<50 or type(n) is not int or n<1:
            raise ErroDieselBriefing("preço amostral/postos fora do contrato")
        start=date.fromisoformat(r["semana_inicio_oficial"])
        if (atual-start).days!=6:
            raise ErroDieselBriefing("semana com duração incorreta")
        valor=f"R$ {preco:.3f}/L (R$/L); semana {start:%d/%m}–{atual:%d/%m}; {n} postos"
        linhas.append({
            "fonte_id":"ANP","secao":"DIESEL","grupo":"ENERGIA",
            "titulo":f"{mun}/MT — {r['produto']} (revenda)",
            "valor":valor,"valor_num":str(preco), "unidade":"R$/L",
            "natureza":"INDICATIVO",
            "classe_estatistica":"MEDIA_AMOSTRAL_MUNICIPAL_REVENDA",
            "competencia":atual.isoformat(),
            "semana_inicio":start.isoformat(),"semana_fim":atual.isoformat(),
            "postos_pesquisados":n,
            "periodo_identificado":True,
            "referencia":pub.isoformat(),
            "publicado_em":pub.isoformat(),
            "coletado_em":coleta.isoformat(),
            "sha256_origem":resultado["sha256"],
            "fonte":"ANP — Levantamento de Preços (média municipal amostral)",
        })
    if not linhas:
        raise ErroDieselBriefing("sem dados da semana mais recente para municípios escolhidos")
    return {
        "indicadores":sorted(linhas,key=lambda x:x["titulo"]),
        "fontes":{"ANP":{"status_direitos":"APROVADA",
                         "operacoes":["LEITURA","PUBLICACAO_DERIVADA"],
                         "id_aprovacao":direitos["evidencia_id"]}},
        "evidencia":{
            "dataset_id":resultado["dataset_id"],"sha256":resultado["sha256"],
            "semana_inicio":(atual-timedelta(days=6)).isoformat(),
            "semana_fim":atual.isoformat(),
            "publicado_em":pub.isoformat(),
            "fonte_original":resultado.get("url_origem"),
            "tipo":"MEDIA_AMOSTRAL_MUNICIPAL_DIESEL_B_REVENDA",
            "documento_autorizacao":direitos["evidencia_id"],
            "coletado_em":coleta.isoformat(),
            "preco_nunca_agregado_em_media_entre_municipios":True,
        }
    }
