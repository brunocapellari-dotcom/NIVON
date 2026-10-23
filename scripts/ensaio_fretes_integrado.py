"""Ensaio executável Fretes R01 + Quant: somente fixtures em memória.

O workflow usa esta orquestração em lote sem fontes externas, sem gravação
em disco, sem serviços pagos e sem credenciais. Uma chave HMAC de fixture
NÃO equivale a autenticação de publicação ou direito de uso.
"""
from __future__ import annotations

import hmac
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

from nivon.fretes_atestacoes import serializacao_canonica
from nivon.fretes_raw_ponte_quant import DOMINIO
from nivon.fretes_registros import OfertaFrete
from nivon.pipeline_fretes_quant import executar_lote_fretes_quant
from nivon.quant_core import ErroQuantitativo

AS_OF = datetime(2026, 10, 21, 20, tzinfo=timezone.utc)
CHAVE_FIXTURE = b"CHAVE_HMAC_SOMENTE_ENSAIO_" + b"9" * 32


def _amostra() -> list[OfertaFrete]:
    data_base = date(2026, 10, 1)
    linhas = []
    for regime in ("PF", "PJ"):
        for dia_idx in range(7):
            dia = data_base + timedelta(days=dia_idx)
            publicado = datetime(dia.year, dia.month, dia.day, 16, tzinfo=timezone.utc)
            for ponto in (1, 2):
                identificador = f"{regime}:{dia}:{ponto}"
                preco = Decimal(130 + 10 * ponto + 3 * dia_idx)
                linhas.append(OfertaFrete(
                    publicacao_id="teste:pub:" + identificador,
                    registro_id="teste:reg:" + identificador,
                    oferta_id="teste:of:" + identificador,
                    municipio_ibge="5107925",
                    pickup_entity_id=f"fazenda:{ponto}",
                    transportadora_id=f"transportadora:{ponto}",
                    destino_ibge="5107602",
                    descarga_entity_id="terminal:001",
                    produto="MILHO", equipamento="RODOTREM", regime=regime,
                    frete_base_brl_t=preco,
                    pedagio_brl_t=Decimal("10"),
                    frete_cheio_brl_t=preco + Decimal("10"),
                    data_referencia=dia,
                    data_publicacao=publicado,
                    data_coleta=publicado + timedelta(hours=1),
                    fonte_id="ENSAIO_OFFLINE_FRETES",
                ))
    return linhas


def _recibos(linhas: list[OfertaFrete]) -> tuple[dict, dict]:
    raw, recibos = {}, {}
    for linha in linhas:
        conteudo = (
            f"MENSAGEM ORIGINAL SINTÉTICA {linha.registro_id} "
            f"{linha.frete_base_brl_t} {linha.regime}"
        ).encode("utf-8")
        raw[linha.registro_id] = conteudo
        envelope = {
            "versao": 1, "emissor_id": "COLETOR_EXCLUSIVO_ENSAIO",
            "registro_id": linha.registro_id,
            "oferta_id": linha.oferta_id,
            "publicacao_id": linha.publicacao_id,
            "fonte_id": linha.fonte_id,
            "raw_sha256": sha256(conteudo).hexdigest(),
            "publicado_em": linha.data_publicacao.isoformat(),
            "capturado_em": (
                linha.data_publicacao + timedelta(minutes=10)
            ).isoformat(),
            "emitido_em": (
                linha.data_publicacao + timedelta(minutes=20)
            ).isoformat(),
        }
        envelope["assinatura_hmac_sha256"] = hmac.new(
            CHAVE_FIXTURE, DOMINIO + serializacao_canonica(envelope),
            sha256,
        ).hexdigest()
        recibos[linha.registro_id] = envelope
    return raw, recibos


def executar() -> dict:
    entradas = _amostra()
    declaradas = executar_lote_fretes_quant(
        entradas, as_of=AS_OF, janela_r01=6, minimo_pares_r01=2,
    )
    assert declaradas["total_publicacoes_recebidas"] == 28
    assert declaradas["total_registros_divulgados"] == 28
    assert declaradas["n_series_individuais"] == 4
    assert declaradas["n_paineis_comerciais"] == 2
    assert {x["condicoes"]["regime"]
            for x in declaradas["tendencias_pareadas"]} == {"PF", "PJ"}
    assert all(x["resultado"]["tendencia"] == "ALTA"
               for x in declaradas["tendencias_pareadas"])
    assert all(
        x["resultado"]["motor_r01_canonico"]
        == "PAINEL_PAREADO_ESTABELECIMENTO_TRANSPORTADORA"
        for x in declaradas["tendencias_pareadas"]
    )
    assert all(
        x["resultado"]["status"] == "BLOQUEADO_SHA_EDICAO_AUSENTE"
        for x in declaradas["series_quantitativas"]
    )
    raws, recibos = _recibos(entradas)
    integrado = executar_lote_fretes_quant(
        entradas, as_of=AS_OF, raws=raws, recibos=recibos,
        chave_captura=CHAVE_FIXTURE,
        emissor_esperado="COLETOR_EXCLUSIVO_ENSAIO",
        janela_r01=6, minimo_pares_r01=2,
    )
    assert integrado["n_paineis_comerciais"] == 2
    assert integrado["n_series_individuais"] == 4
    assert all(x["resultado"]["integridade_hmac_coletor_verificada"]
               for x in integrado["series_quantitativas"])
    assert sum(x["resultado"]["recibos_raw_conferidos"]
               for x in integrado["series_quantitativas"]) == 28
    assert not integrado["publicavel"]
    assert not integrado["uso_preditivo_real_autorizado"]
    assert all(not x["resultado"]["asof_pronto"]
               for x in integrado["series_quantitativas"])
    primeiro = entradas[0].registro_id
    raws[primeiro] += b"\x00ALTERADO"
    try:
        executar_lote_fretes_quant(
            entradas, as_of=AS_OF, raws=raws, recibos=recibos,
            chave_captura=CHAVE_FIXTURE,
            emissor_esperado="COLETOR_EXCLUSIVO_ENSAIO",
            janela_r01=6, minimo_pares_r01=2,
        )
    except ErroQuantitativo:
        adulteracao_bloqueada = True
    else:
        raise AssertionError("RAW adulterado não bloqueou lote")
    assert adulteracao_bloqueada
    assert "media_municipal" not in str(integrado)
    return {
        "estado": "ENSAIO_FRETES_R01_QUANT_APROVADO_APENAS_SINTETICO",
        "etapas_validadas": [
            "receber_eventos_individuais", "consolidar_publicacoes",
            "segmentar_regime_pf_pj", "parear_estabelecimento_transportadora",
            "bloquear_serie_quant_sem_raw",
            "verificar_digest_bytes_raw", "verificar_recibos_hmac",
            "preparar_series_offline", "rejeitar_raw_adulterado",
            "impedir_uso_preditivo_publicacao",
        ],
        "publicacoes_sinteticas": 28,
        "series_economicas_individuais": 4,
        "paineis_r01": 2,
        "recibos_raw_conferidos": 28,
        "raw_original_de_fonte_real": False,
        "direitos_publicacao_verificados": False,
        "servico_externo_acionado": False,
        "publicavel": False,
    }


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, sort_keys=True))
