"""NIVON/IVO — execução em lote inteiramente OFFLINE de candidatos PAM/SIDRA.

Encadeia planos canônicos -> transporte INJETADO -> quarentena -> auditoria.
A entrada é contrato do servidor, nunca prompt/LLM. Não aceita transporte
de rede implícito, não escreve em banco canônico e não promove informação.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .ivo_pam_coletor_pontual import (
    ErroColetaPAM, _fonte_liberada, _url, coletar_candidato_pam,
)
from .ivo_pam_pacote_auditoria import ErroPacotePAM, preparar_pacote_pam_quarentena
from .ivo_pam_quarentena import ErroQuarentenaPAM, arquivar_candidato_pam
from .ivo_pam_semantica import ErroSemanticaPAM, conferir_semantica_pam_1612
from .sidra_pam import ErroSIDRAPAM, planejar_pam_1612


class ErroLotePAM(ValueError):
    """Entrada inválida: rejeitar TODO o lote antes de gravar."""


@dataclass(frozen=True)
class PedidoPAM:
    municipio_ibge: str
    ano: int
    categoria_c81: str
    variavel: str
    pdf_url: str | None = None
    publicacao_declarada: str | None = None
    versao_anterior_sha256: str | None = None


def _json_canonico(dado: object) -> bytes:
    return json.dumps(
        dado, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _validar_pedidos(pedidos: list[PedidoPAM]) -> list[tuple[PedidoPAM, dict]]:
    if not isinstance(pedidos, list) or not 1 <= len(pedidos) <= 25:
        raise ErroLotePAM("lote deve ter entre 1 e 25 consultas explicitas")
    vistos: set[tuple[str, int, str, str]] = set()
    planos = []
    for pedido in pedidos:
        if type(pedido) is not PedidoPAM:
            raise ErroLotePAM("pedido tipado obrigatorio")
        try:
            plano = planejar_pam_1612(
                municipio_ibge=pedido.municipio_ibge,
                ano=pedido.ano,
                codigo_produto_c81=pedido.categoria_c81,
                codigo_variavel=pedido.variavel,
            )
            conferir_semantica_pam_1612(
                variavel=pedido.variavel, categoria_c81=pedido.categoria_c81,
                unidade="Toneladas" if pedido.variavel == "214" else "Hectares",
            )
            if pedido.pdf_url is not None:
                _url(pedido.pdf_url, tipo="PDF_IBGE")
            if pedido.publicacao_declarada is not None:
                # Validar antes de qualquer escrita; auditoria confere também
                # que a data não é posterior à captura declarada.
                from datetime import date
                if (type(pedido.publicacao_declarada) is not str or
                        len(pedido.publicacao_declarada) != 10 or
                        date.fromisoformat(pedido.publicacao_declarada).isoformat()
                        != pedido.publicacao_declarada):
                    raise ErroLotePAM("dia de publicacao invalido")
            if pedido.versao_anterior_sha256 is not None:
                import re
                if (type(pedido.versao_anterior_sha256) is not str or not
                        re.fullmatch(r"[a-f0-9]{64}", pedido.versao_anterior_sha256)):
                    raise ErroLotePAM("hash historico invalido")
        except (ErroSIDRAPAM, ErroSemanticaPAM, ValueError) as exc:
            raise ErroLotePAM("pedido PAM nao homologado semanticamente") from exc
        chave = (pedido.municipio_ibge, pedido.ano,
                 pedido.categoria_c81, pedido.variavel)
        if chave in vistos:
            raise ErroLotePAM("consulta pontual duplicada no mesmo lote")
        vistos.add(chave)
        planos.append((pedido, plano))
    return planos


def executar_lote_pam_offline(
    *, pedidos: list[PedidoPAM], catalogo: dict, direitos: dict,
    raiz: str | Path, coletado_em: datetime,
    transporte: Callable[[str, int, int], tuple[bytes, str]],
    limite_total_bytes: int = 64 * 1024 * 1024, continuar_apos_falha: bool = True,
) -> dict:
    """Executa e audita candidatos, sem ativar HTTP real ou promover ao ledger.

    Preflight é atômico para contratos inválidos. Falhas operacionais de um
    pedido podem ser isoladas; bytes já arquivados permanecem em quarentena.
    A propriedade de idempotência aplica-se a bytes e recibos, não a HTTP.
    """
    if not callable(transporte):
        raise ErroLotePAM("transporte offline injetado obrigatorio; HTTP real desabilitado")
    if type(continuar_apos_falha) is not bool:
        raise ErroLotePAM("politica de falha invalida")
    if (not isinstance(coletado_em, datetime)
            or coletado_em.tzinfo is None
            or coletado_em.utcoffset() is None):
        raise ErroLotePAM("instante de coleta com fuso obrigatorio")
    if type(limite_total_bytes) is not int or not 1024 <= limite_total_bytes <= 1024**3:
        raise ErroLotePAM("quota de quarentena invalida")
    if not isinstance(raiz, (str, Path)):
        raise ErroLotePAM("destino de quarentena obrigatorio")
    # Uma licença declarada de testes nao significa licença comprovada.
    # Ainda assim, os controles do coletor são obrigatorios.
    try:
        _fonte_liberada(catalogo, direitos)
    except (ValueError, PermissionError, TypeError) as exc:
        raise ErroLotePAM("coleta sem fonte e direitos declarados elegiveis") from exc
    trabalhos = _validar_pedidos(pedidos)
    horario = coletado_em.astimezone(timezone.utc).isoformat()
    resultados = []
    for pedido, plano in trabalhos:
        identificacao = {
            "municipio_ibge": pedido.municipio_ibge, "ano_civil": pedido.ano,
            "categoria_c81": pedido.categoria_c81,
            "variavel_sidra": pedido.variavel, "url": plano["url"],
        }
        try:
            candidato = coletar_candidato_pam(
                catalogo=catalogo, direitos=direitos, tipo="SIDRA_JSON",
                plano=plano, coletado_em=coletado_em, transporte=transporte,
            )
            recibo = arquivar_candidato_pam(
                raiz=raiz, candidato=candidato, limite_total_bytes=limite_total_bytes,
            )
            pdf_recibo = None
            if pedido.pdf_url is not None:
                pdf = coletar_candidato_pam(
                    catalogo=catalogo, direitos=direitos, tipo="PDF_IBGE",
                    url_documento=pedido.pdf_url, coletado_em=coletado_em,
                    transporte=transporte,
                )
                pdf_recibo = arquivar_candidato_pam(
                    raiz=raiz, candidato=pdf, limite_total_bytes=limite_total_bytes,
                )["recibo_sha256"]
            auditoria = preparar_pacote_pam_quarentena(
                raiz=raiz, recibo_sidra=recibo["recibo_sha256"], plano=plano,
                recibo_pdf=pdf_recibo,
                data_publicacao_declarada=pedido.publicacao_declarada,
                versao_anterior_sha256=pedido.versao_anterior_sha256,
            )
            # Sem valor numérico no indice operacional; apenas em dossie
            # segregado e não homologado no contrato de auditoria.
            conclusao = {
                **identificacao,
                "estado": "AUDITORIA_LOCAL_PENDENTE_HOMOLOGACAO",
                "arquivo_sha256": candidato["sha256"],
                "recibo_sha256": recibo["recibo_sha256"],
                "recibo_pdf_sha256": pdf_recibo,
                "auditoria_sha256": hashlib.sha256(_json_canonico(auditoria)).hexdigest(),
                "estado_valor": auditoria["celula_sidra"]["estado_valor"],
                "bloqueios": sorted(set(auditoria["bloqueios"])),
                "passivel_promocao": False,
            }
        except Exception as exc:
            # Nunca devolver URL interna do transporte, payload ou segredos
            # de mensagens de erro. Fall closed: possivel quarentena parcial.
            conclusao = {
                **identificacao, "estado": "ERRO_OPERACIONAL_ISOLADO",
                "erro_classe": type(exc).__name__,
                "dados_parciais_em_quarentena_possiveis": True,
                "passivel_promocao": False,
            }
            resultados.append(conclusao)
            if not continuar_apos_falha:
                break
        else:
            resultados.append(conclusao)
    publicavel = {
        "schema": "nivon_ivo_pam_lote_offline_v1",
        "modo": "SOMENTE_TRANSPORTE_INJETADO_NAO_COMPROVA_HTTP",
        "fonte": "IBGE_PAM", "executado_em_declarado": horario,
        "solicitados": len(trabalhos), "processados": len(resultados),
        "auditorias": sum(x["estado"] == "AUDITORIA_LOCAL_PENDENTE_HOMOLOGACAO"
                         for x in resultados),
        "falhas": sum(x["estado"] == "ERRO_OPERACIONAL_ISOLADO"
                      for x in resultados),
        "resultados": resultados,
        "ledger_canonico_modificado": False,
        "promocoes_realizadas": 0,
        "treino_executado": False,
        "publicacao_realizada": False,
        "homologacao_externa_comprovada": False,
        "proxima_etapa": "REVISAO_INDEPENDENTE_COM_DIREITOS_E_PROVENIENCIA",
    }
    return {**publicavel,
            "manifesto_sha256": hashlib.sha256(_json_canonico(publicavel)).hexdigest()}
