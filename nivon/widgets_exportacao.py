"""Exportacao offline e auditavel de fontes primarias mapeadas aos 42 widgets.

A origem e a view nivon_widgets_origens_verificadas_v, NAO o HTML/JS dos widgets.
A saida segue nivon_core.observacoes (PR #84), mas nao cria datasets nem faz upload.
O SHA de origem identifica a linha serializada do Neon, NAO os bytes primarios da fonte.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sys

from nivon.cotacoes import carregar_catalogo

RAIZ = Path(__file__).resolve().parents[1]
MAPEAMENTO = {
    ("CEPEA", "soja_paranagua"): 121,
    ("CEPEA", "soja_parana"): 26,
    ("CEPEA", "milho_esalq_b3"): 91,
}
COLUNAS = {
    "id_widget", "fonte_original", "serie_origem", "produto", "praca",
    "detalhe_cotacao", "unidade", "valor", "data_referencia",
    "data_publicacao", "data_coleta", "natureza", "status_qualidade",
    "licenca", "url_fonte_original", "chave_origem", "hash_versao",
    "widget_coletado_diretamente",
}
LIMITE_LINHAS = 500_000


class ExportacaoBloqueada(ValueError):
    """Um contrato invalido nunca vira observacao analitica."""


def _texto(v: object, campo: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ExportacaoBloqueada("CAMPO_INVALIDO:" + campo)
    return v


def _data(v: object) -> str:
    s = _texto(v, "data_referencia")
    try:
        if len(s) != 10 or date.fromisoformat(s).isoformat() != s:
            raise ValueError
    except ValueError:
        raise ExportacaoBloqueada("DATA_REFERENCIA_INVALIDA") from None
    return s


def _instante(v: object, *, opcional: bool = False) -> str | None:
    if v is None and opcional:
        return None
    s = _texto(v, "timestamp")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        raise ExportacaoBloqueada("TIMESTAMP_SEM_FUSO_OU_INVALIDO") from None


def _valor(v: object) -> str:
    if isinstance(v, bool) or not isinstance(v, (str, int, Decimal)):
        raise ExportacaoBloqueada("VALOR_NAO_DECIMAL")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise ExportacaoBloqueada("VALOR_NAO_DECIMAL") from None
    if not d.is_finite() or d <= 0 or d.adjusted() > 20:
        raise ExportacaoBloqueada("VALOR_FORA_DA_FAIXA")
    return format(d.normalize(), "f")


def _sha(obj: object) -> str:
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def normalizar(linha: dict, catalogo: dict) -> dict:
    if not isinstance(linha, dict) or set(linha) != COLUNAS:
        raise ExportacaoBloqueada("CONTRATO_DA_VIEW_INVALIDO")
    widget = linha["id_widget"]
    if isinstance(widget, bool) or not isinstance(widget, int):
        raise ExportacaoBloqueada("WIDGET_INVALIDO")
    catalogados = {item["id"]: item for item in catalogo["indicadores"]}
    if widget not in catalogados:
        raise ExportacaoBloqueada("WIDGET_FORA_DO_CATALOGO")
    if linha["widget_coletado_diretamente"] is not False:
        raise ExportacaoBloqueada("COLETA_WIDGET_NAO_AUTORIZADA")
    origem = _texto(linha["fonte_original"], "fonte_original")
    serie = _texto(linha["serie_origem"], "serie_origem")
    if origem == "CEPEA":
        if MAPEAMENTO.get((origem, serie)) != widget:
            raise ExportacaoBloqueada("MAPEAMENTO_CEPEA_DIVERGENTE")
        if linha["status_qualidade"] != "VALIDADO":
            raise ExportacaoBloqueada("CEPEA_NAO_VALIDADO")
        url = _texto(linha["url_fonte_original"], "url_fonte_original")
        if not url.startswith("https://www.cepea.org.br/br/indicador/"):
            raise ExportacaoBloqueada("ORIGEM_CEPEA_NAO_VERIFICADA")
        hash_versao = _texto(linha["hash_versao"], "hash_versao")
        if len(hash_versao) != 64 or any(c not in "0123456789abcdef" for c in hash_versao):
            raise ExportacaoBloqueada("HASH_CEPEA_INVALIDO")
    elif origem == "BCB":
        if widget != 232 or serie not in {
            "ptax_USD_compra", "ptax_USD_venda",
            "ptax_EUR_compra", "ptax_EUR_venda",
        } or linha["status_qualidade"] != "REGISTRO_NEON":
            raise ExportacaoBloqueada("MAPEAMENTO_BCB_DIVERGENTE")
        if linha["url_fonte_original"] is not None or linha["hash_versao"] is not None:
            raise ExportacaoBloqueada("PROVENIENCIA_BCB_NAO_COMPROVADA")
        if not _texto(linha["chave_origem"], "chave_origem").startswith("neon_ptax_quotes:"):
            raise ExportacaoBloqueada("CHAVE_BCB_INVALIDA")
    else:
        raise ExportacaoBloqueada("FONTE_AINDA_NAO_HOMOLOGADA")
    if catalogados[widget]["fonte_original"] != origem:
        raise ExportacaoBloqueada("FONTE_DIVERGENTE_DO_CATALOGO")
    if linha["natureza"] != "INFORMADO":
        raise ExportacaoBloqueada("NATUREZA_NAO_COMPROVADA")
    data_ref = _data(linha["data_referencia"])
    data_coleta = _instante(linha["data_coleta"])
    data_publicacao = _instante(linha["data_publicacao"], opcional=True)
    if data_publicacao and data_publicacao > data_coleta:
        raise ExportacaoBloqueada("COLETA_ANTERIOR_A_PUBLICACAO")
    unidade = _texto(linha["unidade"], "unidade")
    produto = _texto(linha["produto"], "produto")
    licenca = _texto(linha["licenca"], "licenca")
    chave = _texto(linha["chave_origem"], "chave_origem")
    valor = _valor(linha["valor"])
    # SHA da LINHA NORMALIZADA DA VIEW. Nunca declarar checksum RAW da API.
    linha_canonica = dict(linha)
    linha_canonica["valor"] = valor
    linha_canonica["data_coleta"] = data_coleta
    linha_canonica["data_publicacao"] = data_publicacao
    linha_sha = _sha(linha_canonica)
    chave_logica = _sha([origem, serie, data_ref, chave])
    vintage = _sha([chave_logica, valor, linha["hash_versao"]])
    observacao_id = _sha([origem, serie, chave_logica, vintage])
    return {
        "observacao_id": observacao_id,
        "fonte_id": origem,
        "dataset_id": "neon_widgets_origens_verificadas",
        "indicador_id": serie,
        "produto_id": produto,
        "regiao_id": linha["praca"],
        "unidade": unidade,
        "valor": valor,
        "valor_texto": None,
        "competencia": data_ref[:7],
        "data_referencia": data_ref,
        "instante_referencia": None,
        "data_publicacao": data_publicacao,
        "data_coleta": data_coleta,
        "origem_sha256": linha_sha,
        "schema_versao": "1.0.0",
        "vintage_id": vintage,
        "natureza": "INFORMADO",
        "status_qualidade": linha["status_qualidade"],
        "amostra": None,
        "atributos": {
            "widget_id_de_referencia": widget,
            "coleta_direta_widget": False,
            "hash_tipo": "SHA256_LINHA_NORMALIZADA_VIEW_NEON",
            "hash_raw_fonte_primaria_disponivel": False,
            "chave_origem": chave,
            "hash_versao_neon": linha["hash_versao"],
            "licenca": licenca,
            "url_fonte_original": linha["url_fonte_original"],
            "detalhe_cotacao": linha["detalhe_cotacao"],
            "sem_inferir_publicacao": data_publicacao is None,
        },
    }


def cobertura(catalogo: dict, ids_com_dados: set[int] | None = None) -> dict:
    ids = ids_com_dados or set()
    return {
        "catalogados": len(catalogo["indicadores"]),
        "com_serie_primaria_neste_lote": sorted(ids),
        "sem_serie_primaria_neste_lote": sorted(
            item["id"] for item in catalogo["indicadores"] if item["id"] not in ids
        ),
        "widgets_coletados_diretamente": 0,
        "google_cloud_carregado": False,
    }


def converter(entrada: Path, saida: Path, catalogo: dict | None = None) -> dict:
    catalogo = catalogo or carregar_catalogo()
    entrada, saida = entrada.resolve(), saida.resolve()
    if entrada == saida or entrada.is_relative_to(RAIZ) or saida.is_relative_to(RAIZ):
        raise ExportacaoBloqueada("ARQUIVO_PRIVADO_FORA_DO_REPOSITORIO_OBRIGATORIO")
    if not entrada.is_file() or saida.exists():
        raise ExportacaoBloqueada("ARQUIVO_AUSENTE_OU_SAIDA_EXISTENTE")
    saida.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(saida, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    sha_saida = hashlib.sha256()
    contagem = Counter()
    chaves = set()
    try:
        with entrada.open("r", encoding="utf-8") as source, os.fdopen(fd, "w", encoding="utf-8") as target:
            for indice, linha in enumerate(source, 1):
                if indice > LIMITE_LINHAS:
                    raise ExportacaoBloqueada("LIMITE_DE_LINHAS_EXCEDIDO")
                try:
                    dados = json.loads(linha, parse_float=Decimal)
                    registro = normalizar(dados, catalogo)
                except (ValueError, TypeError, KeyError):
                    raise ExportacaoBloqueada(f"LINHA_INVALIDA:{indice}") from None
                if registro["observacao_id"] in chaves:
                    raise ExportacaoBloqueada("CHAVE_DUPLICADA_NO_SNAPSHOT")
                chaves.add(registro["observacao_id"])
                contagem[registro["atributos"]["widget_id_de_referencia"]] += 1
                payload = (json.dumps(registro, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                target.write(payload.decode("utf-8"))
                sha_saida.update(payload)
        if not chaves:
            raise ExportacaoBloqueada("SNAPSHOT_VAZIO")
    except BaseException:
        saida.unlink(missing_ok=True)
        raise
    resumo = cobertura(catalogo, set(contagem))
    resumo.update({
        "linhas_exportadas": sum(contagem.values()),
        "linhas_por_widget": dict(sorted(contagem.items())),
        "arquivo_sha256": sha_saida.hexdigest(),
        "status": "EXPORTACAO_LOCAL_PENDENTE_CONCILIACAO_E_CARGA_GCP",
    })
    return resumo


def main() -> int:
    p = argparse.ArgumentParser(description="Converte snapshot privado da view Neon para contrato BigQuery; SEM upload.")
    p.add_argument("--entrada", type=Path, required=True)
    p.add_argument("--saida", type=Path, required=True)
    a = p.parse_args()
    try:
        print(json.dumps(converter(a.entrada, a.saida), ensure_ascii=False, sort_keys=True))
        return 0
    except (ExportacaoBloqueada, OSError, UnicodeError):
        print("EXPORTACAO_BLOQUEADA: arquivo, permissao ou contrato invalido.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
