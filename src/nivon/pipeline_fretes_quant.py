"""Pipeline offline em lote: anúncios -> grupos econômicos -> R01 + Quant.

Uma única entrada para consolidar fontes já coletadas e autorizadas,
sem API, rede ou persistência. Não mistura valores municipais; os
resultados são individuais por ponto/transportadora e escopo comercial.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Mapping, Sequence

from .fretes_registros import OfertaFrete, consolidar_ofertas, ErroRegistroFrete
from .fretes_integracao_r01 import tendencia_ofertas_pareadas
from .fretes_raw_ponte_quant import preparar_fretes_quant_com_raw
from .integracao_frete_quant import preparar_serie_frete_anunciado
from .quant_core import ErroQuantitativo


def executar_lote_fretes_quant(
    ofertas: Sequence[OfertaFrete], *, as_of: datetime,
    raws: Mapping[str, bytes] | None = None,
    recibos: Mapping[str, Mapping] | None = None,
    chave_captura: bytes | None = None,
    emissor_esperado: str | None = None,
    janela_r01: int = 6, minimo_pares_r01: int = 2,
    verificacao_semantica: str | None = None,
) -> dict:
    """Roda o fluxo completo offline, mantendo gates separados por domínio.

    Modo SEM RAW: tendência R01 apenas descritiva; cada série Quant retorna
    bloqueio por SHA ausente. Modo COM RAW: exige TODOS os recibos válidos
    e chave HMAC externa para TODAS as linhas; nenhuma série é publicada.
    Nunca mistura registros com pedagio não informado e adicional; não
    substitui auditoria de licenciamento, captação, direito ou fonte real.
    """
    if not isinstance(ofertas, (list, tuple)) or not 1 <= len(ofertas) <= 10000:
        raise ErroRegistroFrete("lote de anúncios inválido ou excessivo")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ErroRegistroFrete("as_of timezone-aware obrigatório")
    if type(janela_r01) is not int or not 4 <= janela_r01 <= 365:
        raise ErroRegistroFrete("janela R01 inválida")
    if type(minimo_pares_r01) is not int or not 2 <= minimo_pares_r01 <= 100:
        raise ErroRegistroFrete("minimo_pares_r01 inválido")
    proved = raws is not None or recibos is not None
    if verificacao_semantica is not None and not proved:
        raise ErroRegistroFrete(
            "semântica de RAW estruturado exige bytes e recibos capturados"
        )
    if proved and (not isinstance(raws, Mapping) or not isinstance(recibos, Mapping)
                   or not chave_captura or not emissor_esperado):
        raise ErroRegistroFrete("modo RAW exige recibos, bytes e emissor/chave confiáveis")
    base = consolidar_ofertas(ofertas)
    registros = base["registros"]
    if proved:
        esperados = {row["registro_id"] for row in registros}
        if set(raws) != esperados or set(recibos) != esperados:
            raise ErroRegistroFrete(
                "cobertura RAW deve corresponder exatamente ao lote consolidado; "
                "não aceitar arquivos extras, omissões nem rebroadcast sem prova"
            )
    # P0: chaves completas. Nunca usar município isolado para preços.
    por_identidade: dict[tuple, list] = defaultdict(list)
    por_corredor_estrito: dict[tuple, list[OfertaFrete]] = defaultdict(list)
    for row in registros:
        key = tuple(row[k] for k in (
            "municipio_ibge", "pickup_entity_id", "transportadora_id",
            "destino_ibge", "descarga_entity_id", "produto",
            "equipamento", "regime",
        ))
        por_identidade[key].append(row)
    for oferta in ofertas:
        if not isinstance(oferta, OfertaFrete):
            raise ErroRegistroFrete("oferta não é contrato tipado")
        chave_painel = (
            oferta.municipio_ibge, oferta.destino_ibge, oferta.descarga_entity_id,
            oferta.produto, oferta.equipamento, oferta.regime,
            "ADICIONAL" if oferta.pedagio_brl_t is not None else "NAO_INFORMADO",
        )
        por_corredor_estrito[chave_painel].append(oferta)

    series = []
    corte = as_of.isoformat()
    for key, rows in sorted(por_identidade.items()):
        chave = dict(zip((
            "municipio_ibge", "pickup_entity_id", "transportadora_id",
            "destino_ibge", "descarga_entity_id", "produto",
            "equipamento", "regime",
        ), key))
        fontes = {x["fonte_id"] for x in rows}
        if len(fontes) != 1:
            # Uma fonte diferente precisa de outra série e vintage próprio:
            # não escolher uma fonte nem fazer média implícita.
            raise ErroRegistroFrete("mesma identidade com fontes diferentes: reconciliação obrigatória")
        tipo = "CHEIO" if all(x["pedagio_brl_t"] is not None
                               and x["frete_cheio_brl_t"] is not None
                               for x in rows) else "BASE"
        if proved:
            ids = {x["registro_id"] for x in rows}
            r = preparar_fretes_quant_com_raw(
                rows, raws={i: raws[i] for i in ids if i in raws},
                recibos={i: recibos[i] for i in ids if i in recibos},
                chave_captura=chave_captura,
                emissor_esperado=emissor_esperado,
                chave_economica=chave, fonte_id=next(iter(fontes)),
                tipo_valor=tipo, as_of=corte,
                verificacao_semantica=verificacao_semantica,
            )
        else:
            r = preparar_serie_frete_anunciado(
                rows, chave=chave, fonte_id=next(iter(fontes)),
                tipo_valor=tipo, as_of=corte,
            )
        series.append({
            "chave_economica": chave, "registros": len(rows),
            "resultado": r,
        })
    tendencia = []
    for key, rows in sorted(por_corredor_estrito.items()):
        mun, dest, descarga, produto, equipamento, regime, pedagio = key
        r = tendencia_ofertas_pareadas(
            rows, origem_ibge=mun, destino_ibge=dest,
            descarga_entity_id=descarga, produto=produto,
            equipamento=equipamento, regime=regime, pedagio=pedagio,
            as_of=as_of, janela=janela_r01, minimo_pares=minimo_pares_r01,
        )
        tendencia.append({
            "condicoes": {
                "municipio_ibge": mun, "destino_ibge": dest,
                "descarga_entity_id": descarga, "produto": produto,
                "equipamento": equipamento, "regime": regime,
                "pedagio": pedagio,
            },
            "resultado": r,
        })
    return {
        "status": "LOTE_FRETE_OFFLINE_NAO_HOMOLOGADO",
        "natureza": "FRETE_ANUNCIADO_NAO_CONTRATADO",
        "total_publicacoes_recebidas": base["total_publicacoes_recebidas"],
        "total_registros_divulgados": base["total_registros_divulgados"],
        "total_registros_individuais_deduplicados": base["total_registros_individuais_deduplicados"],
        "pontos_unicos_por_municipio": base["pontos_unicos_por_municipio"],
        "n_series_individuais": len(series),
        "n_paineis_comerciais": len(tendencia),
        "series_quantitativas": series,
        "tendencias_pareadas": tendencia,
        "raw_assinado_verificado_no_lote": bool(proved),
        "verificacao_semantica_executada": verificacao_semantica,
        "registros_semantica_estruturada_conferidos": sum(
            x["resultado"].get("campos_estruturados_comparados", 0)
            for x in series
        ),
        "semantica_whatsapp_livre_comprovada": False,
        "licencas_e_origem_externa_homologadas": False,
        "publicavel": False,
        "uso_preditivo_real_autorizado": False,
    }
