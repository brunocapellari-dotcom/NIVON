"""Preparação offline para painel pareado de FRETES ANUNCIADOS (PR #30).

Não calcula sinal de tendência nem faz mediana de preço municipal. Transforma
registros individuais NIVON em linhas comparáveis sob regras estritas; o motor
da PR #30 continua responsável pela estatística. Falha se houver mistura de
estabelecimento de descarga, regime, pedágio, produto ou valores conflitantes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from hashlib import sha256
from decimal import Decimal
from math import isfinite
import json
from typing import Sequence

from .fretes_registros import OfertaFrete, ErroRegistroFrete


class ErroPainelFrete(ErroRegistroFrete):
    pass


def preparar_painel_pr30(
    ofertas: Sequence[OfertaFrete], *,
    origem_ibge: str, destino_ibge: str, descarga_entity_id: str,
    produto: str, equipamento: str, regime: str,
    pedagio: str, as_of: datetime,
) -> dict:
    """Prepara entrada da PR #30 sem autorizar uso operacional.

    Datas de publicação/coleta são expressas em dias locais de Mato Grosso,
    após teste intradiário timezone-aware, para respeitar o calendário das
    datas de referência e evitar falsos bloqueios na virada UTC.
    A lista resultante inclui somente preço BASE anunciado; frete cheio e
    preço contratado são conceitos diferentes. A aplicação deve garantir
    previamente a autenticidade e direitos dos registros no canal confiável.
    """
    if not isinstance(ofertas, (tuple, list)) or not 1 <= len(ofertas) <= 10000:
        raise ErroPainelFrete("amostra de ofertas inválida ou acima do limite")
    if (not isinstance(as_of, datetime) or as_of.tzinfo is None
            or as_of.utcoffset() is None):
        raise ErroPainelFrete("as_of exige instante completo com timezone")
    corte = as_of.astimezone(timezone.utc)
    for ident in (origem_ibge, destino_ibge):
        if not isinstance(ident, str) or len(ident) != 7 or not ident.isascii() or not ident.isdecimal():
            raise ErroPainelFrete("município IBGE de 7 dígitos obrigatório")
    if (not isinstance(descarga_entity_id, str) or not descarga_entity_id.strip()
            or not isinstance(produto, str) or not produto.strip()
            or not isinstance(equipamento, str) or not equipamento.strip()
            or regime not in {"PF", "PJ", "NAO_INFORMADO"}
            or pedagio not in {"ADICIONAL", "NAO_INFORMADO"}):
        raise ErroPainelFrete("condições econômicas da rota obrigatórias")

    pontos: dict[tuple, OfertaFrete] = {}
    evidencias_por_par: dict[tuple, set[tuple[str, str, str]]] = {}
    registros_contabilizados: set[str] = set()
    repetidos = 0
    for x in ofertas:
        if not isinstance(x, OfertaFrete):
            raise ErroPainelFrete("evento não está no contrato OfertaFrete")
        if (x.data_publicacao.astimezone(timezone.utc) > corte
                or x.data_coleta.astimezone(timezone.utc) > corte):
            raise ErroPainelFrete("publicação/coleta futura ao corte temporal")
        if x.data_referencia != x.data_publicacao.astimezone(ZoneInfo("America/Cuiaba")).date():
            raise ErroPainelFrete("referência defasada da publicação original; validar nova oferta no dia")
        if any((x.municipio_ibge != origem_ibge,
                x.destino_ibge != destino_ibge,
                x.descarga_entity_id != descarga_entity_id,
                x.produto != produto, x.equipamento != equipamento,
                x.regime != regime)):
            raise ErroPainelFrete("mistura de estabelecimentos, descarga, produto, veículo ou regime")
        tipo = "ADICIONAL" if x.pedagio_brl_t is not None else "NAO_INFORMADO"
        if tipo != pedagio:
            raise ErroPainelFrete("mistura de regras de pedágio ou frete cheio")
        if x.registro_id in registros_contabilizados:
            raise ErroPainelFrete("registro_id duplicado; deduplicar por evento/versão antes do painel")
        registros_contabilizados.add(x.registro_id)
        identidade = (x.data_referencia, x.pickup_entity_id, x.transportadora_id)
        evidencias_por_par.setdefault(identidade, set()).add((
            x.registro_id, x.oferta_id, x.publicacao_id,
        ))
        old = pontos.get(identidade)
        if old is not None:
            if (old.frete_base_brl_t != x.frete_base_brl_t
                    or old.pedagio_brl_t != x.pedagio_brl_t
                    or old.frete_cheio_brl_t != x.frete_cheio_brl_t):
                raise ErroPainelFrete("preços ou pedágios conflitantes do mesmo ponto/transportadora/dia")
            repetidos += 1
            if x.registro_id < old.registro_id:
                pontos[identidade] = x
        else:
            pontos[identidade] = x

    linhas = []
    for (dia, pickup, transp), x in sorted(pontos.items()):
        evidencia_derivada = {
            "registro_id": x.registro_id, "oferta_id": x.oferta_id,
            "publicacao_id": x.publicacao_id, "fonte_id": x.fonte_id,
            "periodo": dia.isoformat(), "pickup_entity_id": pickup,
            "transportadora_id": transp, "preco_base_brl_t": str(x.frete_base_brl_t),
            "evidencias_mesmo_par": sorted(evidencias_por_par[(dia, pickup, transp)]),
        }
        # O motor Theil-Sen aceita números finitos, não Decimal textual.
        # Converter apenas quando a representação de ida/volta é exata.
        valor_analitico = float(x.frete_base_brl_t)
        if (not isfinite(valor_analitico)
                or Decimal(str(valor_analitico)) != x.frete_base_brl_t):
            raise ErroPainelFrete("precisão monetária não representável no motor estatístico")
        digest = sha256(json.dumps(evidencia_derivada, sort_keys=True,
                                   separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        linhas.append({
            "periodo": dia.isoformat(),
            "publicacao": x.data_publicacao.astimezone(ZoneInfo("America/Cuiaba")).date().isoformat(),
            "coleta": x.data_coleta.astimezone(ZoneInfo("America/Cuiaba")).date().isoformat(),
            "valor": valor_analitico,
            "fonte_id": x.fonte_id, "edicao_sha256": digest,
            "origem_ibge": origem_ibge, "destino_ibge": destino_ibge,
            "produto": produto, "veiculo": equipamento, "pedagio": pedagio,
            "natureza": "OFERTA", "unidade": "BRL/T",
            "lote_id": x.registro_id, "pickup_entity_id": pickup,
            "transportadora_id": transp,
            "descarga_entity_id": descarga_entity_id, "regime": regime,
            "preco_rs_t": str(x.frete_base_brl_t),
        })
    return {
        "status": "PREPARADO_OFFLINE_NAO_HOMOLOGADO",
        "motor_destino": "PR30_TENDENCIA_FRETE_PAREADO",
        "natureza": "FRETE_ANUNCIADO",
        "unidade": "BRL/T_BASE_SEM_PEDAGIO",
        "as_of": corte.isoformat(),
        "origem_ibge": origem_ibge, "destino_ibge": destino_ibge,
        "descarga_entity_id": descarga_entity_id,
        "produto": produto, "equipamento": equipamento,
        "regime": regime, "pedagio": pedagio,
        "quantidade_bruta": len(ofertas), "identidades_dia": len(linhas),
        "repeticoes_mesmo_ponto_e_preco": repetidos,
        "edicao_sha256_classe": "DIGEST_DERIVADO_NAO_PROVA_RAW",
        "origem_e_direitos_auditoria_externa": "PENDENTE_HOMOLOGACAO",
        "publicavel": False, "probabilidades_calibradas": None,
        "observacoes": linhas,
    }
