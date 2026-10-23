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
            "secao": reg.get("secao"),  # Política de frescor por seção real
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
            "classe_estatistica": reg.get("classe_estatistica"),
            "semana_inicio": reg.get("semana_inicio"),
            "semana_fim": reg.get("semana_fim"),
            "postos_pesquisados": reg.get("postos_pesquisados"),
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
            "pickup_entity_id", "ponto_embarque", "local_descarga",
            "transportadora", "produto", "equipamento",
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


CHAVES_IMUTAVEIS = {
    "noticias": frozenset({
        "fonte_id", "titulo", "url", "publicado_em", "coletado_em",
        "sha256_origem", "direitos_publicacao", "evidencia_direitos_id",
    }),
    "cotacoes": frozenset({"fonte_id", "titulo", "secao", "direitos_publicacao",
                           "evidencia_direitos_id", "classe_estatistica",
                           "semana_inicio", "semana_fim", "postos_pesquisados"}),
    "fretes": frozenset({
        "fonte_id", "tipo", "origem", "uf_origem", "destino", "uf_destino",
        "pickup_entity_id", "ponto_embarque", "local_descarga",
        "transportadora", "produto", "equipamento", "regime_pf_pj",
        "condicao_pedagio", "valor_rs_t", "referencia_em",
        "volume_t_dia", "classificacao_volume", "volume_realizado",
        "publicado_em", "coletado_em", "sha256_origem",
        "direitos_publicacao", "evidencia_direitos_id",
    }),
}
# Chaves explicitamente editáveis pelo operador apenas com declaração externa.
COMPLEMENTOS = {
    "noticias": frozenset({"evento_id", "publicacao_original_verificada",
                            "evidencia_publicacao_original_id",
                            "evidencia_evento_id"}),
    "cotacoes": frozenset({
        "grupo", "valor", "unidade", "competencia", "natureza",
        "referencia_em", "publicado_em", "coletado_em", "sha256_origem",
        "sessao_fechamento", "ultima_sessao_concluida", "fechamento_confirmado",
        "periodo_identificado", "valor_anterior", "variacao_pct",
        "evidencia_sessao_id",
    }),
    "fretes": frozenset({
        "pickup_entity_id", "transportadora", "produto", "equipamento",
        "regime_pf_pj", "condicao_pedagio", "publicado_em", "coletado_em",
        "sha256_origem", "volume_t_dia", "classificacao_volume",
        "volume_realizado", "evidencia_registro_id",
    }),
}


def conciliar_complementos(candidatos: dict, complemento: dict) -> dict:
    """Aplica somente evidências suplementares; preserva o que o pipeline conhece.

    O complemento deve ser indexado exatamente como a auditoria, sem adições
    silenciosas de matérias, preços ou fretes. É prova declarada e NÃO valida
    independentemente a licença ou o calendário da fonte.
    """
    if not isinstance(candidatos, dict) or candidatos.get("estado") != "CANDIDATOS_NAO_HOMOLOGADOS":
        raise ValueError("pacote automático inválido")
    if not isinstance(complemento, dict) or complemento.get("sha256_edicao") != candidatos.get("sha256_edicao"):
        raise ValueError("complemento não está vinculado ao SHA da edição")
    saida = {}
    for categoria in ("noticias", "cotacoes", "fretes"):
        base = candidatos.get(categoria)
        extra = complemento.get(categoria)
        if not isinstance(base, list) or not isinstance(extra, list) or len(base) != len(extra):
            raise ValueError("tamanho da seção editorial divergente: " + categoria)
        combinados = []
        for index, (original, adicional) in enumerate(zip(base, extra)):
            if not isinstance(original, dict) or not isinstance(adicional, dict):
                raise ValueError("prova não estruturada")
            for chave in CHAVES_IMUTAVEIS[categoria]:
                if chave in adicional and adicional[chave] != original.get(chave):
                    raise ValueError("proveniência imutável divergente: " + categoria + "/" + chave)
            novo = dict(original)
            for chave, valor in adicional.items():
                if chave not in COMPLEMENTOS[categoria] and chave not in CHAVES_IMUTAVEIS[categoria]:
                    raise ValueError("campo suplementar não autorizado: " + chave)
                if chave in COMPLEMENTOS[categoria]:
                    anterior = original.get(chave)
                    if anterior not in (None, False) and anterior != valor:
                        raise ValueError("alteração de fato conhecido: " + categoria + "/" + chave)
                    novo[chave] = valor
            if categoria == "noticias":
                if novo.get("publicacao_original_verificada") is True:
                    raise ValueError("ID isolado não comprova publicação original; exige RSS, página e atestados assinados")
                if novo.get("evento_id") and not novo.get("evidencia_evento_id"):
                    raise ValueError("evento editorial não vinculado a decisão documentada")
            if categoria == "cotacoes" and novo.get("fechamento_confirmado") is True:
                if not isinstance(novo.get("evidencia_sessao_id"), str) or len(novo["evidencia_sessao_id"]) < 8:
                    raise ValueError("sessão declarada sem evidência externa")
            combinados.append(novo)
        saida[categoria] = combinados
    return saida
