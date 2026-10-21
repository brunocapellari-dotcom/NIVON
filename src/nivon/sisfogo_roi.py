"""Contrato OFFLINE de dados públicos SISFOGO/IBAMA — ROI finalizado.

Fonte oficial: https://www.gov.br/conecta/catalogo/apis/registro-de-ocorrencia-de-incendio-florestal-roi
Somente normalização dos bytes fornecidos pelo chamador. Não realiza HTTP,
agendamento, coleta, geocodificação, publicação ou gravação em banco.
Não confundir registro ROI com foco ativo detectado por satélite.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

ORIGEM = "https://sisfogo.sistema.gov.br/api/v1/roi/publico"
DOC_OFICIAL = "https://www.gov.br/conecta/catalogo/apis/registro-de-ocorrencia-de-incendio-florestal-roi"
UF = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


class ErroSISFOGO(ValueError):
    """Payload, domínio ou paginação incompatível com o contrato oficial."""


def planejar_pagina_roi(*, page: int = 1, size: int = 10) -> str:
    """Consulta explícita e individual; não inicia varredura/busca por rede."""
    if type(page) is not int or page < 1 or page > 1_000_000:
        raise ErroSISFOGO("page deve iniciar em 1")
    if type(size) is not int or not 1 <= size <= 500:
        raise ErroSISFOGO("size deve estar entre 1 e 500")
    return f"{ORIGEM}?page={page}&size={size}"


def _unico(pares):
    out = {}
    for chave, valor in pares:
        if chave in out:
            raise ErroSISFOGO("JSON com chave repetida")
        out[chave] = valor
    return out


def _datahora(valor, campo, *, obrigatorio=False):
    if valor is None and not obrigatorio:
        return None
    if not isinstance(valor, str):
        raise ErroSISFOGO(campo + " inválido")
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroSISFOGO(campo + " inválido") from exc
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ErroSISFOGO(campo + " sem timezone")
    return instante.astimezone(timezone.utc).isoformat()


def _string(valor, campo, *, obrigatorio=False, limite=200):
    if valor is None and not obrigatorio:
        return None
    if not isinstance(valor, str) or not 1 <= len(valor.strip()) <= limite:
        raise ErroSISFOGO(campo + " ausente/inválido")
    if any(ord(c) < 32 for c in valor):
        raise ErroSISFOGO(campo + " contém controle")
    return valor.strip()


def _local(local):
    if local is None:
        return {"latitude": None, "longitude": None, "uf": None, "municipio": None,
                "codigo_ibge": None, "bioma": None, "amazonialegal_municipio": None}
    if not isinstance(local, dict):
        raise ErroSISFOGO("localIncendio deve ser objeto")
    lat, lon = local.get("latitude"), local.get("longitude")
    if (lat is None) != (lon is None):
        raise ErroSISFOGO("coordenadas incompletas")
    if lat is not None:
        if (type(lat) not in (int, float) or type(lon) not in (int, float)
                or not math.isfinite(lat) or not math.isfinite(lon)
                or not (-90 <= lat <= 90) or not (-180 <= lon <= 180)):
            raise ErroSISFOGO("coordenadas geográficas inválidas")
    mun = local.get("municipio")
    if mun is None:
        mun = {}
    if not isinstance(mun, dict):
        raise ErroSISFOGO("município inválido")
    estado = mun.get("unidadeFederativa") or {}
    if not isinstance(estado, dict):
        raise ErroSISFOGO("UF inválida")
    sigla = estado.get("siglaUnidadeFederativa")
    if sigla is not None and sigla not in UF:
        raise ErroSISFOGO("sigla de UF inválida")
    bioma = local.get("bioma") or {}
    if not isinstance(bioma, dict):
        raise ErroSISFOGO("bioma inválido")
    amazonia = mun.get("isAmazoniaLegal")
    if amazonia is not None and type(amazonia) is not bool:
        raise ErroSISFOGO("isAmazoniaLegal municipal deve ser booleano")
    return {"latitude": lat, "longitude": lon, "uf": sigla,
            "municipio": _string(mun.get("nomeMunicipio"), "nomeMunicipio"),
            # Não inferir código municipal IBGE a partir de nome de município.
            "codigo_ibge": None,
            "bioma": _string(bioma.get("nomeBioma"), "nomeBioma"),
            "amazonialegal_municipio": amazonia}


def _area(valor):
    if valor is None:
        return None
    if type(valor) not in (int, float):
        raise ErroSISFOGO("estimativaAreaQueimada não numérica")
    numero = Decimal(str(valor))
    if not numero.is_finite() or numero < 0:
        raise ErroSISFOGO("área queimada negativa ou não finita")
    return format(numero, "f")


def _lista(obj, campo):
    valor = obj.get(campo)
    if valor is None:
        return []
    if not isinstance(valor, list) or len(valor) > 20000:
        raise ErroSISFOGO(campo + " deve ser lista limitada")
    return valor


def _roi(item: dict, *, coleta: str, hash_pagina: str):
    if not isinstance(item, dict):
        raise ErroSISFOGO("ROI deve ser objeto")
    try:
        roi_id = str(uuid.UUID(item["id"]))
    except (KeyError, ValueError, AttributeError, TypeError) as exc:
        raise ErroSISFOGO("ID UUID do ROI inválido") from exc
    if roi_id != item["id"]:
        raise ErroSISFOGO("UUID não canônico")
    if item.get("statusRoi") != "FINALIZADO":
        raise ErroSISFOGO("ROI não finalizado deve ser rejeitado")
    if type(item.get("retificado")) is not bool or type(item.get("houveCombate")) is not bool:
        raise ErroSISFOGO("retificado/houveCombate exigem booleanos")
    criado = _datahora(item.get("dataHoraCriacao"), "dataHoraCriacao", obrigatorio=True)
    atualizado = _datahora(item.get("dataHoraUltimaAtualizacao"),
                            "dataHoraUltimaAtualizacao", obrigatorio=True)
    if atualizado < criado:
        raise ErroSISFOGO("atualização anterior à criação")
    datas = item.get("datasIncendio") or {}
    if not isinstance(datas, dict):
        raise ErroSISFOGO("datasIncendio inválido")
    inicio = _datahora(datas.get("dataInicioIncendio"), "dataInicioIncendio")
    deteccao = _datahora(datas.get("dataDeteccaoIncendio"), "dataDeteccaoIncendio")
    extincao = _datahora(datas.get("dataExtincaoIncendio"), "dataExtincaoIncendio")
    combate = item["houveCombate"]
    recursos = _lista(item, "combateRecursosHumanos")
    meios = _lista(item, "meiosLocomocaoCombateIncendioDiario")
    frentes = _lista(item, "frentesCombate")
    if not combate and (recursos or meios or any(
        datas.get(k) is not None for k in (
            "dataInicioDeslocamento", "dataPrimeiroAtaque", "dataControleIncendio"
        )
    )):
        raise ErroSISFOGO("ROI sem combate apresenta recursos ou datas de combate")
    pos = item.get("informacoesPosIncendio") or {}
    if not isinstance(pos, dict):
        raise ErroSISFOGO("informacoesPosIncendio inválido")
    vegetacao = _lista(pos, "vegetacoesAtingidas")
    vegs = []
    for v in vegetacao:
        if not isinstance(v, dict):
            raise ErroSISFOGO("vegetação atingida inválida")
        nome = _string(v.get("vegetacao"), "vegetacao", obrigatorio=True)
        vegs.append(nome)
    local = _local(item.get("localIncendio"))
    referencia = (inicio or deteccao)
    return {
        "dataset_id": "IBAMA_SISFOGO_ROI_FINALIZADOS",
        "fonte_id": "IBAMA_SISFOGO",
        "roi_id": roi_id,
        "numero_roi": _string(item.get("numeroRoi"), "numeroRoi"),
        "status_roi": "FINALIZADO",
        "retificado": item["retificado"],
        "houve_combate": combate,
        "criado_em_utc": criado,
        "ultima_atualizacao_em_utc": atualizado,
        "data_inicio_estimada_utc": inicio,
        "data_deteccao_utc": deteccao,
        "data_extincao_utc": extincao,
        "area_queimada_estimada_ha": _area(pos.get("estimativaAreaQueimada")),
        "vegetacoes_atingidas": vegs,
        "quantidade_dias_recursos_registrados": len(recursos),
        "quantidade_frentes_combate_registradas": len(frentes),
        "quantidade_registros_meios_locomocao": len(meios),
        **local,
        "referencia": referencia,
        "competencia": referencia[:7] if referencia else None,
        "publicacao": None,
        "coleta": coleta,
        "sha256_pagina_original": hash_pagina,
        "natureza": "REGISTRO_OFICIAL_DE_OCORRENCIA_FINALIZADA_AREA_ESTIMADA",
        "limite": "NAO_EQUIVALE_FOCO_SATELITE_NEM_CENSO_NACIONAL",
        "apto_publicacao": False,
    }


def normalizar_pagina_roi(payload: bytes, *, page: int, size: int,
                         coletado_em: str) -> dict:
    """Valida página individual contra contrato; não confunde exemplo page=0 com real."""
    url = planejar_pagina_roi(page=page, size=size)
    coleta = _datahora(coletado_em, "coletado_em", obrigatorio=True)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 8_000_000:
        raise ErroSISFOGO("resposta ausente ou acima de 8 MB")
    try:
        dados = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unico)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroSISFOGO("JSON ROI inválido") from exc
    if not isinstance(dados, dict):
        raise ErroSISFOGO("resposta paginada deve ser objeto")
    for nome in ("pagina", "tamanhoPagina", "totalItens", "totalPaginas"):
        if type(dados.get(nome)) is not int or dados[nome] < 0:
            raise ErroSISFOGO("metadados paginados inválidos: " + nome)
    total = dados["totalItens"]
    paginas = dados["totalPaginas"]
    esperado = (total + size - 1) // size
    if (dados["pagina"] != page or dados["tamanhoPagina"] != size
            or paginas != esperado or page > max(1, paginas)):
        raise ErroSISFOGO("paginação não corresponde à solicitação")
    itens = dados.get("itens")
    if not isinstance(itens, list) or len(itens) > size:
        raise ErroSISFOGO("itens ausentes ou acima de size")
    if total == 0 and itens:
        raise ErroSISFOGO("página vazia no total com registros")
    if total and page <= paginas and not itens:
        raise ErroSISFOGO("página não vazia esperada pela contagem")
    if page < paginas and len(itens) != size:
        raise ErroSISFOGO("página intermediária incompleta")
    sha = hashlib.sha256(payload).hexdigest()
    obs = [_roi(row, coleta=coleta, hash_pagina=sha) for row in itens]
    chaves = [o["roi_id"] for o in obs]
    if len(chaves) != len(set(chaves)):
        raise ErroSISFOGO("mesmo ROI duplicado na página")
    return {
        "dataset_id": "IBAMA_SISFOGO_ROI_FINALIZADOS",
        "fonte_id": "IBAMA_SISFOGO",
        "pagina": page,
        "tamanho_pagina": size,
        "total_itens_declarado": total,
        "total_paginas_declarado": paginas,
        "itens": obs,
        "consulta_url": url,
        "coleta": coleta,
        "sha256_original": sha,
        "estado": "NORMALIZADO_OFFLINE_NAO_HOMOLOGADO",
        "apto_publicacao": False,
    }


def conferir_lote_paginas(paginas: list[dict]) -> dict:
    """Audita cobertura lógica de um lote já coletado, sem iniciar requisições.

    Não assegura snapshot atômico remoto: paginação pode mudar durante uma varredura;
    revisões posteriores devem ser auditadas por id e dataHoraUltimaAtualizacao.
    """
    if not isinstance(paginas, list) or not 1 <= len(paginas) <= 10000:
        raise ErroSISFOGO("lote de páginas ausente ou grande demais")
    bases = paginas[0]
    total, n, tamanho = (bases.get("total_itens_declarado"),
                         bases.get("total_paginas_declarado"), bases.get("tamanho_pagina"))
    if n != len(paginas) and not (n == 0 and len(paginas) == 1):
        raise ErroSISFOGO("faltam páginas: lote incompleto")
    ids = set()
    linhas = 0
    for i, p in enumerate(paginas, start=1):
        if (p.get("pagina") != i or p.get("total_paginas_declarado") != n
                or p.get("total_itens_declarado") != total
                or p.get("tamanho_pagina") != tamanho):
            raise ErroSISFOGO("paginação instável/incompleta entre consultas")
        for item in p["itens"]:
            ident = item["roi_id"]
            if ident in ids:
                raise ErroSISFOGO("ROI duplicado entre páginas; possível deslocamento")
            ids.add(ident)
            linhas += 1
    if linhas != total:
        raise ErroSISFOGO("soma de páginas não confere com total de ROIs")
    return {"total_registros": linhas, "total_paginas": len(paginas),
            "coleta_atomica_remota_comprovada": False,
            "apto_publicacao": False, "estado": "PAGINACAO_CONSISTENTE_EM_LOTE_OFFLINE"}
