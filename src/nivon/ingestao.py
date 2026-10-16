"""Leitura CSV local com direitos por operação e proveniência: sem rede e sem persistência externa."""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .motores import DadoInvalido, validar_fonte


@dataclass(frozen=True)
class ContratoCSV:
    fonte_id: str
    campos_obrigatorios: tuple[str, ...]
    status_fonte: str = "PENDENTE"
    operacoes_autorizadas: frozenset[str] = frozenset()
    tamanho_maximo: int = 5_000_000
    linhas_maximas: int = 100_000


def ler_csv_local(caminho: str | Path, contrato: ContratoCSV, *,
                  referencia: str, publicacao: str | None, competencia: str) -> dict:
    """Carrega um CSV explicitamente elegível; falha fechado em esquema, limites e valores nulos.

    Retorna as linhas apenas em memória. Nenhum arquivo da fonte é salvo no GitHub.
    """
    validar_fonte(status=contrato.status_fonte, operacao="LEITURA_LOCAL",
                  operacoes_autorizadas=set(contrato.operacoes_autorizadas))
    if not contrato.fonte_id.strip() or not contrato.campos_obrigatorios:
        raise DadoInvalido("contrato de fonte incompleto")
    if not competencia or not referencia:
        raise DadoInvalido("competência e referência são obrigatórias")
    arquivo = Path(caminho)
    if arquivo.is_symlink() or not arquivo.is_file() or arquivo.suffix.lower() != ".csv":
        raise DadoInvalido("arquivo CSV regular necessário; links simbólicos proibidos")
    if contrato.tamanho_maximo <= 0 or contrato.linhas_maximas <= 0:
        raise DadoInvalido("limites inválidos")
    with arquivo.open("rb") as stream:
        payload = stream.read(contrato.tamanho_maximo + 1)
    if len(payload) > contrato.tamanho_maximo:
        raise DadoInvalido("CSV maior que limite permitido")
    try:
        texto = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise DadoInvalido("CSV não UTF-8") from exc
    linhas = []
    leitor = csv.DictReader(io.StringIO(texto, newline=""), delimiter=";")
    campos = leitor.fieldnames or []
    if not campos or len(campos) != len(set(campos)) or not set(contrato.campos_obrigatorios) <= set(campos):
        raise DadoInvalido("cabeçalho CSV ausente, duplicado ou incompatível")
    for numero, linha in enumerate(leitor, start=2):
        if len(linhas) >= contrato.linhas_maximas:
            raise DadoInvalido("CSV excede limite de linhas")
        if None in linha or any(linha.get(campo) is None or not str(linha[campo]).strip()
                                for campo in contrato.campos_obrigatorios):
            raise DadoInvalido(f"CSV linha {numero}: coluna obrigatória ausente")
        linhas.append(linha)
    return {
        "fonte_id": contrato.fonte_id,
        "linhas": linhas,
        "linhas_lidas": len(linhas),
        "hash_sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "datas": {"competencia": competencia, "referencia": referencia,
                  "publicacao": publicacao,
                  "coleta": datetime.now(timezone.utc).isoformat()},
        "classificacao": "ARQUIVO_LOCAL_NAO_HOMOLOGA_FONTE",
        "parser_versao": "csv-local-0.1",
    }
