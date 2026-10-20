"""Orquestração offline NIVON: snapshots RSS licenciados + curadoria -> briefing.

A edição é preparada SEM envio, agendamento, consulta HTTP ou deploy. O núcleo
preserva datas originais e direitos e mantém os blocos portuários bloqueados
quando não há dados reais homologados.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime

from .briefing_composto import montar_briefing
from .curadoria_radar import preparar_noticias_feed
from .integracao_portos_briefing import montar_briefing_com_portos
from .lineup_nacional import instante
from .rss_radar import MAX_BYTES, ler_feed_xml
from .ptax_briefing import normalizar_snapshot_ptax, construir_indicador_ptax


class ErroPipelineBriefing(ValueError):
    pass


def gerar_edicao_offline(*, gerado_em: str, feeds: list[dict],
                         snapshots_xml: dict[str, bytes],
                         db: sqlite3.Connection,
                         indicadores: list[dict] | None = None,
                         fontes_indicadores: dict | None = None,
                         fretes: list[dict] | None = None,
                         registros_portuarios: list[dict] | None = None,
                         licencas_portuarias: dict | None = None,
                         ptax_snapshots: list[dict] | None = None,
                         catalogo: dict | None = None, escopo: dict | None = None) -> dict:
    """Gera texto WhatsApp/auditoria a partir de dados offline já autorizados.

    Configurações de aprovação são insumos de governança, não derivadas dos XMLs.
    O chamador responde pela persistência do SQLite, das decisões e do texto.
    """
    instante(gerado_em)
    if not isinstance(feeds,list) or len(feeds)>30:
        raise ErroPipelineBriefing("feeds inválidos ou acima do limite por edição")
    if not isinstance(snapshots_xml,dict):
        raise ErroPipelineBriefing("snapshots não informados")
    if indicadores is None:indicadores=[]
    else: indicadores=list(indicadores)  # nunca mutar a lista do chamador
    if fontes_indicadores is None:fontes_indicadores={}
    if fretes is None:fretes=[]
    if registros_portuarios is None:registros_portuarios=[]
    if licencas_portuarias is None:licencas_portuarias={}
    if (not isinstance(indicadores,list) or not isinstance(fontes_indicadores,dict)
        or not isinstance(fretes,list) or not isinstance(registros_portuarios,list)
        or not isinstance(licencas_portuarias,dict)):
        raise ErroPipelineBriefing("entradas numéricas/portuárias inválidas")
    if ptax_snapshots is None:
        ptax_snapshots = []
    if not isinstance(ptax_snapshots,list) or len(ptax_snapshots)>2:
        raise ErroPipelineBriefing("snapshots de câmbio excedem USD/EUR permitidos")
    moedas=set()
    moeda_infos=[]
    # Licenças e dataset NÃO são inferidos do snapshot; seu gestor é externo.
    # O CLI de homologação não altera o catálogo canônico.
    for source in ptax_snapshots:
        if not isinstance(source,dict) or not all(k in source for k in (
                "plano","snapshot","dataset","direitos")):
            raise ErroPipelineBriefing("PTAX requer plano, snapshot e autorização externa")
        ptax=normalizar_snapshot_ptax(source["snapshot"],source["plano"])
        if ptax["moeda"] in moedas:
            raise ErroPipelineBriefing("moeda PTAX duplicada no briefing")
        moedas.add(ptax["moeda"])
        result=construir_indicador_ptax(ptax,gerado_em=gerado_em,
                        dataset=source["dataset"],direitos=source["direitos"])
        # Uma fonte canônica para USD/EUR: dois indicadores, um contrato.
        if "BCB_PTAX" in fontes_indicadores:
            raise ErroPipelineBriefing("PTAX já declarada manualmente entre os indicadores")
        indicadores.append(result["indicador"])
        moeda_infos.append(result["evidencia"])
    if moeda_infos:
        fontes_indicadores=dict(fontes_indicadores)
        fontes_indicadores.update(result["fonte_briefing"])
    ids=set();noticias=[];fontes=dict(fontes_indicadores);issues=[];boletins=[]
    for pos,f in enumerate(feeds):
        if not isinstance(f,dict):
            raise ErroPipelineBriefing("contrato de feed inválido")
        fid=f.get("fonte_id")
        if not isinstance(fid,str) or fid in ids:
            raise ErroPipelineBriefing("feed sem identificador ou duplicado")
        ids.add(fid)
        snapshot=snapshots_xml.get(fid)
        if not isinstance(snapshot,bytes) or not 20<=len(snapshot)<=MAX_BYTES:
            raise ErroPipelineBriefing("snapshot RSS não fornecido ou grande demais: "+fid)
        politica=f.get("politica")
        avaliacoes=f.get("avaliacoes",{})
        publicado=ler_feed_xml(
            snapshot,fonte_id=fid,
            dominios_artigos=set(f.get("dominios_artigos",[])),
            coletado_em=f.get("coletado_em"),
            url_feed=f.get("url_feed"),
        )
        if publicado["fonte_id"]!=fid:
            raise ErroPipelineBriefing("feed com fonte divergente")
        curadoria=preparar_noticias_feed(
            db,publicado,politica_fonte=politica,
            avaliacoes=avaliacoes,gerado_em=gerado_em,
        )
        if fid in fontes:
            raise ErroPipelineBriefing("mesmo ID no cadastro de cotação/indicador e no radar")
        fontes.update(curadoria["fontes_briefing"])
        noticias.extend(curadoria["noticias"])
        issues.extend({"etapa":"RSS","fonte_id":fid,"motivo":x["motivo"]}
                      for x in publicado["rejeicoes"])
        issues.extend({"etapa":"CURADORIA","fonte_id":fid,"motivo":x["motivo"]}
                      for x in curadoria["rejeicoes"])
        boletins.append({
            "fonte_id":fid,"snapshot_sha256":hashlib.sha256(snapshot).hexdigest(),
            "candidatos":len(publicado["candidatos"]),
            "noticias_curadas":len(curadoria["noticias"]),
            "republicacoes_na_memoria":curadoria["historico"]["republicacoes"],
        })
    briefing=montar_briefing_com_portos(
        noticias=noticias, fontes_noticias=fontes,
        indicadores=indicadores, registros_portuarios=registros_portuarios,
        licencas_portuarias=licencas_portuarias,
        gerado_em=gerado_em,fretes=fretes,catalogo=catalogo,escopo=escopo,
    )
    indicadores_ausentes=not indicadores and not registros_portuarios
    return {
        "estado":"EDICAO_OFFLINE_PREPARADA_SEM_ENVIO",
        "gerado_em":instante(gerado_em).isoformat(),
        "sha256":briefing["sha256"],"texto":briefing["texto"],
        "status_portuario":briefing["status_portuario"],
        "fontes_rss":boletins,
        "evidencias_cambio":moeda_infos,
        "noticias_recebidas_curadas":len(noticias),
        "indicadores_incluidos":briefing["indicadores_incluidos"],
        "fretes_incluidos":briefing["fretes_incluidos"],
        "rejeicoes":issues+briefing["rejeicoes"],
        "cobertura":{"indicadores_ausentes":indicadores_ausentes,
                     "fontes_rss_sem_aprovacao":len(feeds)==0},
        "enviado":False,
        "advertencia":"Edição offline; dados incompletos podem ser omitidos. Não publicar sem gates de fonte, licença e revisão.",
    }
