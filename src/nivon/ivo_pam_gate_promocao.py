"""Contrato de passagem da auditoria PAM para uma fila de revisão independente.

Não implementa auto-promoção, assinatura ou gravação canônica. Somente gera
pedidos de evidência com SHA determinístico, a partir do manifesto offline.
As liberações reais dependem de identidade, licença, data e KMS externos.
"""
from __future__ import annotations

import hashlib
import json
import re


class ErroRevisaoPAM(ValueError):
    pass


SHA = re.compile(r"[a-f0-9]{64}\Z")
REQUISITOS = (
    "AUTENTICIDADE_DA_FONTE_E_DOCUMENTO_OFICIAL",
    "DATA_DE_PUBLICACAO_E_VINTAGE_ATESTADOS",
    "LICENCA_E_FINALIDADE_APROVADAS_POR_FONTE",
    "REVISAO_DOCUMENTAL_INDEPENDENTE_ASSINADA",
    "REGISTRO_IMUTAVEL_ANCORADO_EXTERNAMENTE",
    "PERMISSAO_HERMES_ATUAL_POR_TENANT_E_OPERACAO",
)


def _digest(x: object) -> str:
    try:
        data = json.dumps(x, sort_keys=True, ensure_ascii=False,
                          allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ErroRevisaoPAM("manifesto nao serializavel") from exc
    if len(data) > 500_000:
        raise ErroRevisaoPAM("manifesto extenso")
    return hashlib.sha256(data).hexdigest()


def preparar_fila_revisao_pam(manifesto: dict) -> dict:
    """Gera itens de trabalho por recorte, sem conferir assinaturas fictícias.

    Manipulação da entrada, resultado não offline ou flags de promoção
    indevidas causam recusa total antes de qualquer resposta de revisão.
    """
    if not isinstance(manifesto, dict):
        raise ErroRevisaoPAM("manifesto obrigatorio")
    recebido = dict(manifesto)
    informado = recebido.pop("manifesto_sha256", None)
    if not isinstance(informado, str) or SHA.fullmatch(informado) is None:
        raise ErroRevisaoPAM("SHA de manifesto ausente")
    if _digest(recebido) != informado:
        raise ErroRevisaoPAM("manifesto alterado")
    if (recebido.get("schema") != "nivon_ivo_pam_lote_offline_v1"
            or recebido.get("modo") != "SOMENTE_TRANSPORTE_INJETADO_NAO_COMPROVA_HTTP"
            or recebido.get("fonte") != "IBGE_PAM"
            or recebido.get("ledger_canonico_modificado") is not False
            or recebido.get("promocoes_realizadas") != 0
            or recebido.get("treino_executado") is not False
            or recebido.get("publicacao_realizada") is not False
            or recebido.get("homologacao_externa_comprovada") is not False):
        raise ErroRevisaoPAM("contrato nao homologado viola gate")
    itens = recebido.get("resultados")
    if not isinstance(itens, list) or not 1 <= len(itens) <= 25:
        raise ErroRevisaoPAM("itens de lote ausentes")
    if (type(recebido.get("solicitados")) is not int
            or type(recebido.get("processados")) is not int
            or recebido["processados"] != len(itens)
            or not 1 <= recebido["processados"] <= recebido["solicitados"] <= 25):
        raise ErroRevisaoPAM("quantitativos incoerentes")
    fila = []
    sucesso = erro = 0
    vistos = set()
    for item in itens:
        if not isinstance(item, dict):
            raise ErroRevisaoPAM("linha de lote invalida")
        key = tuple(item.get(x) for x in
                    ("municipio_ibge", "ano_civil", "categoria_c81", "variavel_sidra"))
        if (not isinstance(key[0], str) or not re.fullmatch(r"\d{7}", key[0])
                or type(key[1]) is not int
                or not isinstance(key[2], str)
                or not isinstance(key[3], str) or key in vistos):
            raise ErroRevisaoPAM("chave de municipio/cultura/periodo invalida")
        vistos.add(key)
        if item.get("passivel_promocao") is not False:
            raise ErroRevisaoPAM("promocao nao homologada em manifesto")
        estado = item.get("estado")
        if estado == "AUDITORIA_LOCAL_PENDENTE_HOMOLOGACAO":
            for campo in ("arquivo_sha256", "recibo_sha256", "auditoria_sha256"):
                if not isinstance(item.get(campo), str) or SHA.fullmatch(item[campo]) is None:
                    raise ErroRevisaoPAM("identidade de prova local invalida")
            b = item.get("bloqueios")
            if not isinstance(b, list) or not b or not all(isinstance(x, str) for x in b):
                raise ErroRevisaoPAM("auditoria sem bloqueios obrigatorios")
            sucesso += 1
            fila.append({
                "recorte": {"municipio_ibge": key[0], "ano_civil": key[1],
                            "categoria_c81": key[2], "variavel_sidra": key[3]},
                "objeto_sha256": item["arquivo_sha256"],
                "recibo_sha256": item["recibo_sha256"],
                "auditoria_sha256": item["auditoria_sha256"],
                "bloqueios_da_auditoria": sorted(set(b)),
                "provas_independentes_pendentes": list(REQUISITOS),
                "estado": "REVISAO_INDEPENDENTE_NAO_EXECUTADA",
            })
        elif estado == "ERRO_OPERACIONAL_ISOLADO":
            if item.get("dados_parciais_em_quarentena_possiveis") is not True:
                raise ErroRevisaoPAM("estado de falha incompleto")
            erro += 1
        else:
            raise ErroRevisaoPAM("estado inesperado")
    if (sucesso != recebido.get("auditorias")
            or erro != recebido.get("falhas")):
        raise ErroRevisaoPAM("contagens adulteradas")
    result = {
        "schema": "nivon_ivo_pam_fila_revisao_v1",
        "manifesto_lote_sha256": informado,
        "status": "AGUARDANDO_REVISAO_EXTERNA_NENHUMA_PROMOCAO",
        "itens_pendentes": fila,
        "quantidade_pendente": len(fila),
        "quantidade_falhas_na_coleta": erro,
        "registro_canonico_autorizado": False,
        "treinamento_autorizado": False,
        "pode_publicar": False,
        "provas_externas_verificadas": False,
    }
    return {**result, "fila_sha256": _digest(result)}
