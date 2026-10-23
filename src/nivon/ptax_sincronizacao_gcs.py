"""Arquivamento PTAX idempotente em Google Cloud Storage, condicionado.

Compara GCS com objetos locais antes e depois de cada operação.
Nunca faz overwrite (if_generation_match=0); upload parcial pode ser
retomado, mas objetos DIVERGENTES interrompem a operação. A consulta e
a escrita podem gerar cobrança, logo exigem opt-in e referência de custo.
Nenhum uso deste módulo habilita ou homologa publicação de taxas.
"""
from __future__ import annotations

import re
from typing import Mapping

from .ptax_google_cloud import ErroExportacaoPTAX
from .ptax_reconciliacao_gcs import reconciliar_gcs_ptax


def sincronizar_pacote_ptax_gcs(
    pacote: Mapping, *, permitir_upload: bool = False,
    referencia_direitos: str | None = None,
    referencia_custo: str | None = None,
    cliente=None,
) -> dict:
    """Reconcilia, completa objetos ausentes, verifica restauração.

    Fronteira de confiança: chamadas GCS só com autorização operacional
    e de orçamento. Não cria bucket ou projeto; nenhuma transação entre
    GCS e SQLite é alegada. Persistir o recibo externamente é trabalho
    da camada de observabilidade.
    """
    if not permitir_upload:
        raise PermissionError("sincronização GCS desativada")
    if not isinstance(referencia_direitos, str) or not re.fullmatch(
        r"[A-Za-z0-9_./:-]{8,150}", referencia_direitos
    ) or not isinstance(referencia_custo, str) or not re.fullmatch(
        r"[A-Za-z0-9_./:-]{8,150}", referencia_custo
    ):
        raise PermissionError("referências de direitos e orçamento obrigatórias")
    if not isinstance(pacote, Mapping) or (
        pacote.get("status") != "EXPORTACAO_GCS_PREPARADA_SEM_ENVIO"
    ):
        raise ErroExportacaoPTAX("pacote GCS incompatível")
    if cliente is None:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise ErroExportacaoPTAX("SDK GCS ausente") from exc
        cliente = storage.Client()
    anterior = reconciliar_gcs_ptax(
        pacote, cliente=cliente, permitir_leitura=True,
        referencia_custo=referencia_custo,
    )
    if anterior["objetos_divergentes"]:
        raise ErroExportacaoPTAX(
            "objeto preexistente divergente: não sobrescrever"
        )
    por_chave = {o["chave"]: o for o in pacote["objetos"]}
    faltantes = [o["chave"] for o in anterior["resultados"]
                 if o["estado"] == "AUSENTE"]
    adicionados = []
    if faltantes:
        bucket = cliente.bucket(pacote["bucket"])
        for chave in faltantes:
            item = por_chave[chave]
            try:
                bucket.blob(chave).upload_from_string(
                    item["bytes"], content_type=item["mime"],
                    if_generation_match=0, timeout=30,
                )
            except Exception as exc:
                raise ErroExportacaoPTAX(
                    "upload incompleto, reconciliar antes de tentar de novo"
                ) from exc
            adicionados.append(chave)
    depois = reconciliar_gcs_ptax(
        pacote, cliente=cliente, permitir_leitura=True,
        referencia_custo=referencia_custo,
    )
    if not depois["integridade_bytes_gcs_local_confirmada"]:
        raise ErroExportacaoPTAX(
            "upload não foi confirmado por leitura e SHA"
        )
    return {
        "status": "GCS_PTAX_SINCRONIZADO_SEM_HOMOLOGACAO_EDITORIAL",
        "objetos_ja_presentes": anterior["objetos_conferidos"],
        "objetos_novos": len(adicionados),
        "total_conferidos": depois["objetos_conferidos"],
        "chaves_novas": adicionados,
        "integridade_bytes_revalidada": True,
        "fonte_bcb_autenticada_por_este_metodo": False,
        "liberado_para_publicacao": False,
        "publicavel": False,
    }
