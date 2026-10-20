"""CONAB semanal: delta entre índices históricos, OFFLINE e sem disparar downloads.

Compara SOMENTE manifestos gerados por consolidar_paginas. Mudança de URL ou
texto de modificação NÃO comprova que dados de plantio/colheita mudaram.
Sem comprovante de captura integral da paginação, ausência não é remoção.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from datetime import date, datetime, timedelta

from .conab_progresso_indice import (
    ErroIndiceConab, MODIFICACAO, _tempo, _url_boletim, _url_pagina,
)

DATASET = "CONAB_PROGRESSO_SEMANAL"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_CAMPOS_PAGINA = {"indice_url", "indice_sha256", "capturado_em_utc"}
_CAMPOS_REGISTRO = {
    "dataset_id", "inicio_semana", "fim_semana", "url_boletim",
    "ultima_modificacao_texto", "publicacao_utc",
    "dados_agricolas_disponiveis", "natureza",
}
_NATUREZA = "LINK_PUBLICADO_NO_INDICE_NAO_VALIDADO_COMO_ARQUIVO"


def _manifesto(doc: dict) -> tuple[dict[str, dict], list[str], set[tuple[str, str]]]:
    """Valida manifesto local sem confiar em sinalização de autorização do chamador."""
    if not isinstance(doc, dict) or doc.get("dataset_id") != DATASET:
        raise ErroIndiceConab("manifesto fora do dataset CONAB")
    if (doc.get("coleta_real_dos_boletins") is not False
            or doc.get("publicacao_historica_comprovada") is not False):
        raise ErroIndiceConab("manifesto de links não pode atestar coleta/publicação")
    pages = doc.get("paginas_capturadas")
    records = doc.get("registros")
    if (not isinstance(pages, list) or not 1 <= len(pages) <= 250
            or not isinstance(records, list) or not 1 <= len(records) <= 5000
            or doc.get("boletins_identificados") != len(records)
            or type(doc.get("boletins_identificados")) is not int):
        raise ErroIndiceConab("contagem ou extensão inválida no manifesto")
    capturas = []
    index_urls = set()
    fingerprints = set()
    for p in pages:
        if not isinstance(p, dict) or set(p) != _CAMPOS_PAGINA:
            raise ErroIndiceConab("metadados do índice incompletos")
        url = _url_pagina(p["indice_url"])
        if url in index_urls:
            raise ErroIndiceConab("URL duplicada no manifesto")
        index_urls.add(url)
        sha = p["indice_sha256"]
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ErroIndiceConab("SHA de índice inválido")
        stamp = _tempo(p["capturado_em_utc"])
        if stamp != p["capturado_em_utc"]:
            raise ErroIndiceConab("captura do manifesto deve estar em UTC canônico")
        capturas.append(stamp)
        fingerprints.add((url, sha))
    mapa = {}
    for r in records:
        if not isinstance(r, dict) or set(r) != _CAMPOS_REGISTRO:
            raise ErroIndiceConab("campos de boletim alterados")
        if (r["dataset_id"] != DATASET or r["publicacao_utc"] is not None
                or r["dados_agricolas_disponiveis"] is not False
                or r["natureza"] != _NATUREZA):
            raise ErroIndiceConab("manifesto de links simula valores/publicação")
        try:
            inicio, fim = date.fromisoformat(r["inicio_semana"]), date.fromisoformat(r["fim_semana"])
        except (TypeError, ValueError) as exc:
            raise ErroIndiceConab("data de referência inválida") from exc
        if (inicio.isoformat() != r["inicio_semana"]
                or fim.isoformat() != r["fim_semana"]
                or fim - inicio != timedelta(days=6) or inicio.weekday() != 0):
            raise ErroIndiceConab("semana irregular no manifesto")
        if _url_boletim(r["url_boletim"]) != r["url_boletim"]:
            raise ErroIndiceConab("URL de boletim divergente")
        mod = r["ultima_modificacao_texto"]
        if mod is not None and (not isinstance(mod, str) or not MODIFICACAO.fullmatch(mod)):
            raise ErroIndiceConab("modificação textual inválida")
        if r["fim_semana"] in mapa:
            raise ErroIndiceConab("dupla representação da semana")
        mapa[r["fim_semana"]] = r
    if not isinstance(doc.get("lacunas_na_sequencia"), list):
        raise ErroIndiceConab("lacunas não especificadas")
    seq = set()
    cursor = date.fromisoformat(min(mapa))
    final = date.fromisoformat(max(mapa))
    while cursor < final:
        cursor += timedelta(days=7)
        if cursor.isoformat() not in mapa:
            seq.add(cursor.isoformat())
    if (len(doc["lacunas_na_sequencia"]) != len(seq)
            or set(doc["lacunas_na_sequencia"]) != seq):
        raise ErroIndiceConab("lacunas inconsistentes com semanas capturadas")
    return mapa, capturas, fingerprints


def planejar_delta(anterior: dict | None, atual: dict) -> dict:
    """Produz candidatos de VERIFICAÇÃO, não uma fila autorizada de coleta.

    O índice não contém hash dos boletins. Portanto 'inalterado' significa
    apenas URL/texto idênticos, jamais bytes equivalentes ou valores estáveis.
    """
    novo, ts_novo, fp_novo = _manifesto(atual)
    if anterior is None:
        velho, ts_velho, fp_velho = {}, [], set()
    else:
        velho, ts_velho, fp_velho = _manifesto(anterior)
        if min(ts_novo) < max(ts_velho):
            raise ErroIndiceConab("capturas intercaladas: comparar só vintages íntegros e ordenados")
        if min(ts_novo) == max(ts_velho) and novo != velho:
            raise ErroIndiceConab("dois manifestos divergentes na mesma hora de captura")
    itens = []
    for semana in sorted(set(velho) | set(novo)):
        a, b = velho.get(semana), novo.get(semana)
        if a is None:
            fase = "NOVO_LINK"
        elif b is None:
            fase = "NAO_VISIVEL_NA_AMOSTRA_ATUAL"
        elif a["url_boletim"] != b["url_boletim"]:
            fase = "URL_ALTERADA"
        elif a["ultima_modificacao_texto"] != b["ultima_modificacao_texto"]:
            fase = "METADADO_ALTERADO"
        else:
            fase = "SEM_ALTERACAO_VISIVEL"
        # O link pode apontar para arquivo alterado sem modificação do índice.
        itens.append({
            "fim_semana": semana,
            "situacao": fase,
            "url_anterior": a["url_boletim"] if a else None,
            "url_atual": b["url_boletim"] if b else None,
            "candidato_verificacao_manual": fase in {"NOVO_LINK","URL_ALTERADA","METADADO_ALTERADO"},
            "arquivo_original_verificado": False,
            "direito_de_coleta_verificado": False,
        })
    c = Counter(r["situacao"] for r in itens)
    return {
        "dataset_id": DATASET,
        "tipo": "PLANO_INCREMENTAL_OFFLINE_NAO_EXECUTAVEL",
        "captura_anterior_utc": max(ts_velho) if ts_velho else None,
        "captura_atual_utc": max(ts_novo),
        "boletins_visiveis_atual": len(novo),
        "por_situacao": dict(sorted(c.items())),
        "indice_alterado_sem_delta_visivel": bool(anterior is not None and
                                                  fp_novo != fp_velho and
                                                  set(c) == {"SEM_ALTERACAO_VISIVEL"}),
        "escopo_paginacao_completo_comprovado": False,
        "remocao_de_boletins_comprovada": False,
        "dados_de_progresso_coletados": 0,
        "autorizacao_execucao": False,
        "itens": itens,
        "proxima_acao": "HOMOLOGAR_DIREITOS_RAW_E_COMPARAR_BYTES_DOS_BOLETINS_AUTORIZADOS",
    }


def _chaves_unicas(pares):
    out = {}
    for key, val in pares:
        if key in out:
            raise ErroIndiceConab("manifesto JSON com chave duplicada")
        out[key] = val
    return out


def _ler_manifesto(path: str) -> dict:
    arquivo = Path(path)
    if arquivo.is_symlink() or not arquivo.is_file():
        raise ErroIndiceConab("manifesto deve ser arquivo JSON regular, sem symlink")
    if not 0 < arquivo.stat().st_size <= 2_000_000:
        raise ErroIndiceConab("manifesto ultrapassa limite de 2 MB")
    try:
        obj = json.loads(arquivo.read_text(encoding="utf-8"),
                         object_pairs_hook=_chaves_unicas)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroIndiceConab("manifesto JSON inválido") from exc
    if not isinstance(obj, dict):
        raise ErroIndiceConab("manifesto deve ser objeto JSON")
    return obj


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CONAB: comparar índices sem HTTP, download ou DB")
    parser.add_argument("--atual", required=True, help="Manifesto de consolidar_paginas")
    parser.add_argument("--anterior", help="Manifesto de consolidar_paginas anterior")
    args = parser.parse_args(argv)
    try:
        antigo = _ler_manifesto(args.anterior) if args.anterior else None
        atual = _ler_manifesto(args.atual)
        out = planejar_delta(antigo, atual)
    except (OSError, ErroIndiceConab) as exc:
        parser.error(str(exc))
    print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
