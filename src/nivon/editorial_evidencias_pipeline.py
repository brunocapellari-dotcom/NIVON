"""Adaptação de evidências já existentes no pipeline para pré-homologação.

Não concede direitos nem inventa sessões, preços, evento ou verificações de
publicação original. Campos faltantes ficam ausentes e bloqueiam o preflight.
O pacote nunca deve ser considerado evidência externa independente.
"""
from __future__ import annotations

import hashlib
from .briefing_diario import selecionar_noticias


def montar_candidatos_evidencias(
    *, gerado_em: str, sha256_edicao: str,
    noticias: list[dict], fontes: dict, feeds: list[dict],
    snapshots_xml: dict[str, bytes],
    indicadores: list[dict], fontes_indicadores: dict,
    fretes: list[dict],
) -> dict:
    """Projeção read-only, com proveniência real do snapshot já processado.

    A seleção de notícias usa a mesma rotina do renderer para não devolver
    fatos que foram deduplicados por tema na edição.
    """
    selecionadas, _ = selecionar_noticias(noticias, fontes, gerado_em=gerado_em)
    metadados = {
        item["fonte_id"]: {
            "sha256_origem": hashlib.sha256(snapshots_xml[item["fonte_id"]]).hexdigest(),
            "coletado_em": item.get("coletado_em"),
            "politica": item.get("politica") if isinstance(item.get("politica"), dict) else {},
        }
        for item in feeds
    }
    provas_noticias = []
    for noticia in selecionadas:
        fonte_id = noticia["fonte_id"]
        origem = metadados.get(fonte_id)
        if origem is None:
            # Se o registro não tem snapshot no lote, não afirmar nenhuma origem.
            origem = {"sha256_origem": None, "coletado_em": None, "politica": {}}
        politica = origem["politica"]
        operacoes = politica.get("operacoes", [])
        permitido = (politica.get("status_direitos") == "APROVADA"
                     and isinstance(operacoes, list)
                     and "PUBLICACAO_DERIVADA" in operacoes)
        provas_noticias.append({
            "fonte_id": fonte_id, "titulo": noticia["titulo"],
            "url": noticia["url"], "publicado_em": noticia["publicado_em"].isoformat(),
            "coletado_em": origem["coletado_em"],
            "sha256_origem": origem["sha256_origem"],
            "direitos_publicacao": permitido,  # declaração do cadastro, não licença homologada
            "evidencia_direitos_id": politica.get("licenca_id"),
            # Não fazer equivaler RSS published à verificação independente.
            "publicacao_original_verificada": False,
            # A identidade do acontecimento precisa de decisão editorial explícita.
            "evento_id": None,
        })

    provas_cotacoes = []
    for reg in indicadores:
        if not isinstance(reg, dict):
            continue
        fonte = fontes_indicadores.get(reg.get("fonte_id"))
        fonte = fonte if isinstance(fonte, dict) else {}
        operacoes = fonte.get("operacoes", [])
        autorizado = (fonte.get("status_direitos") == "APROVADA"
                      and isinstance(operacoes, list)
                      and "PUBLICACAO_DERIVADA" in operacoes)
        provas_cotacoes.append({
            "fonte_id": reg.get("fonte_id"), "titulo": reg.get("titulo"),
            "grupo": reg.get("grupo"),  # BOLSAS não prova que é CME ou ICE
            "valor": reg.get("valor_num"),  # nunca extrair numeral de string formatada
            "unidade": reg.get("unidade"), "competencia": reg.get("competencia"),
            "natureza": reg.get("natureza"),
            "referencia_em": reg.get("referencia"),
            "publicado_em": reg.get("publicado_em"),
            "coletado_em": reg.get("coletado_em"),
            "sha256_origem": reg.get("sha256_origem"),
            "direitos_publicacao": autorizado,
            "evidencia_direitos_id": fonte.get("id_aprovacao") or fonte.get("licenca_id"),
            # Estes campos são apenas cópias de evidências independentes, se existentes;
            # jamais devem ser derivados da data de referência.
            "sessao_fechamento": reg.get("sessao_fechamento"),
            "ultima_sessao_concluida": reg.get("ultima_sessao_concluida"),
            "fechamento_confirmado": reg.get("fechamento_confirmado") is True,
            "periodo_identificado": reg.get("periodo_identificado") is True,
        })
        for extra in ("valor_anterior", "variacao_pct"):
            if extra in reg:
                provas_cotacoes[-1][extra] = reg[extra]

    provas_fretes = []
    for reg in fretes:
        if not isinstance(reg, dict):
            continue
        fonte = fontes.get(reg.get("fonte_id"))
        fonte = fonte if isinstance(fonte, dict) else {}
        operacoes = fonte.get("operacoes", [])
        autorizado = (fonte.get("status_direitos") == "APROVADA"
                      and isinstance(operacoes, list)
                      and "PUBLICACAO_DERIVADA" in operacoes)
        candidato = {campo: reg.get(campo) for campo in (
            "fonte_id", "tipo", "origem", "uf_origem", "destino", "uf_destino",
            "pickup_entity_id", "transportadora", "produto", "equipamento",
            "regime_pf_pj", "condicao_pedagio", "valor_rs_t",
            "volume_t_dia", "classificacao_volume", "volume_realizado",
            "publicado_em", "coletado_em", "sha256_origem",
        )}
        candidato.update({
            "referencia_em": reg.get("referencia"),
            "direitos_publicacao": autorizado,
            "evidencia_direitos_id": fonte.get("id_aprovacao") or fonte.get("licenca_id"),
        })
        provas_fretes.append(candidato)
    return {
        "estado": "CANDIDATOS_NAO_HOMOLOGADOS",
        "gerado_em": gerado_em,
        "sha256_edicao": sha256_edicao,
        "noticias": provas_noticias,
        "cotacoes": provas_cotacoes,
        "fretes": provas_fretes,
        "aviso": ("Metadados extraídos apenas de material já processado; "
                  "não constituem prova independente de licença, publicação "
                  "original, calendário de bolsa ou transporte realizado."),
    }
