"""Ensaio E2E em um comando: PTAX legado -> RAW -> backup -> restore.

SEM internet/credenciais, sem arquivos permanentes, sem publicação ou
deploy. Usa somente fixtures sintéticas. Deve rodar em cada PR na CI.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from nivon.captura_ptax_http import capturar_ptax_odata
from nivon.continuidade_ptax import (
    criar_pacote_backup_ptax, restaurar_pacote_backup_ptax,
    planejar_migracao_ptax,
)
from nivon.orquestracao_ptax_lote import executar_lote_ptax
from nivon.pipeline_api_dados import ingerir_json_local, observar_asof_coleta
from nivon.ptax_historico_decimal import selecionar_ptax_decimal_asof
from nivon.ptax_migracao_reversa import materializar_visao_legada_em_copia
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.ptax_raw_sqlite import guardar_raw_ptax
from nivon.registro_snapshots import abrir_registro


T = datetime(2026,10,20,18,0,tzinfo=timezone.utc)
CAT = {"datasets":[{"id":"BCB_PTAX","source_id":"BCB"}]}
PLANO = planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-20",fim="2026-10-20")[0]
RAW = (b'{"value":[{"cotacaoCompra":5.10000,"cotacaoVenda":5.12000,'
       b'"dataHoraCotacao":"2026-10-20 13:03:00"}]}')


def mock(_url):
    return 200, {"content-type":"application/json",
                 "content-length":str(len(RAW))}, RAW


def executar() -> dict:
    legado = abrir_registro(":memory:")
    inicial = None
    restaurado = None
    isolado = None
    visao = None
    try:
        inserir = ingerir_json_local(
            legado,CAT,dataset_id="BCB_PTAX",payload=RAW,plano=PLANO,
            coletado_em=T.isoformat(),
        )
        assert inserir["linhas"] == 1
        lote = executar_lote_ptax(
            legado,CAT,planos=[PLANO],
            transporte_injetado=mock,relogio=lambda:T,
        )
        assert lote["inventario"]["total_snapshots"] == 1
        assert lote["resultados"][0]["adotou_snapshot_legado"]
        plano=planejar_migracao_ptax(legado)
        assert plano["documentos_a_recuperar"] == 0
        legado.commit()
        pacote=criar_pacote_backup_ptax(legado)
        restaurado=restaurar_pacote_backup_ptax(pacote)
        decimal=selecionar_ptax_decimal_asof(
            restaurado,corte=T.isoformat(),incluir_sinteticos=True,
        )
        assert decimal["compra_decimal"] == "5.10000"
        antigo=observar_asof_coleta(
            restaurado,dataset_id="BCB_PTAX",
            corte_coleta=T.isoformat(),incluir_sinteticos=True,
        )
        assert antigo["linhas"] == 1
        assert antigo["registros"][0]["observacao"][
            "cotacao_compra_brl_por_moeda"] == 5.1

        # Exercita a direção inversa RAW-first, sem escrever no banco-fonte.
        isolado=abrir_registro(":memory:")
        captura=capturar_ptax_odata(
            PLANO,transporte=mock,relogio=lambda:T,
        )
        salvo=guardar_raw_ptax(isolado,CAT,captura)
        isolado.commit()
        visao=materializar_visao_legada_em_copia(
            isolado,raw_sha256=salvo["sha256"],
        )
        convertido=observar_asof_coleta(
            visao["copia"],dataset_id="BCB_PTAX",
            corte_coleta=T.isoformat(),incluir_sinteticos=True,
        )
        assert convertido["linhas"] == 1
        assert isolado.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='nivon_observacoes_api'"
        ).fetchone()[0] == 0
        assert visao["promocao_editorial_autorizada"] is False
        return {
            "estado":"ENSAIO_PTAX_E2E_APROVADO_APENAS_SINTETICO",
            "etapas_validadas":[
                "normalizacao_legada","ingestao_lote_raw",
                "coexistencia_mesmo_sha","auditoria_integridade",
                "backup_sqlite","restauracao_sqlite",
                "leitura_decimal_asof","leitura_legada_asof",
                "migracao_reversa_em_copia",
                "bloqueio_promocao_editorial",
            ],
            "capturas":lote["consultas_concluidas"],
            "raw_sha256":salvo["sha256"],
            "sha256_backup":pacote["manifesto"]["sha256"],
            "raw_compatibilizado":visao["linhas_compatibilizadas"],
            "fonte_real_coletada":False,
            "publicavel":False,
            "custo_cloud_realizado":False,
        }
    finally:
        if visao is not None:
            visao["copia"].close()
        if isolado is not None:
            isolado.close()
        if restaurado is not None:
            restaurado.close()
        legado.close()


if __name__ == "__main__":
    print(json.dumps(executar(),ensure_ascii=False,sort_keys=True))
