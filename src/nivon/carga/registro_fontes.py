"""Registro das fontes do coletor `nivon-coletor` (primeira meta: 4 fontes).

Fica em `nivon.carga` para não colidir com os subpacotes de `nivon.fontes` (F2).

Cada fonte reaproveita, sem reescrever, o pipeline que já roda no GitHub
Actions: mesmos módulos e argumentos dos workflows `ptax-bcb-direto-gcp`,
`antt-ferrovia-gcp`, `conab-gcp-operacao` e `maritimo-gcp-primeiro-lote`.
Bruto com hash, carga idempotente e readback ficam com esses pipelines.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path


@dataclass(frozen=True)
class Contexto:
    projeto: str
    dataset: str
    bucket: str
    trabalho: Path
    ano: int


@dataclass(frozen=True)
class Fonte:
    nome: str
    descricao: str
    etapas: object  # Callable[[Contexto], list[list[str]]]
    intervalo: timedelta  # só roda se a última execução OK for mais antiga
    env: dict = field(default_factory=dict)


def _py(*args):
    return [sys.executable, "-m", *map(str, args)]


def _ptax(c):
    # O payload OData não é preservado byte a byte (origem_sha256=None no script).
    return [_py("scripts.ptax_bcb_bigquery_direto", "--arquivo", c.trabalho / "ptax.jsonl",
                "--dias", 10, "--carregar")]


def _antt(c):
    return [_py("nivon.antt_gcp_pipeline", "--staging", c.trabalho / "antt",
                "--projeto", c.projeto, "--dataset", c.dataset, "--bucket", c.bucket,
                "--inicio", c.ano - 1, "--fim", c.ano, "--live")]


def _conab(c):
    banco, raw, stage = c.trabalho / "conab.sqlite", c.trabalho / "conab_raw", c.trabalho / "conab.jsonl"
    return [
        # Sem --aplicar: só verifica a tabela existente, nunca cria.
        _py("nivon.conab_gcp_schema", "--projeto", c.projeto, "--dataset", c.dataset),
        _py("nivon.conab_incremental", "--banco", banco, "--pasta-raw", raw, "--quantidade", 2,
            "--executar", "--direitos-consulta", "--direitos-coleta", "--direitos-armazenamento"),
        _py("nivon.conab_gcs_archive", "--banco", banco, "--pasta-raw", raw, "--bucket", c.bucket,
            "--executar", "--direitos-armazenamento", "--custos-autorizados"),
        _py("nivon.agro_bigquery_stage", "--banco", banco, "--saida", stage),
        _py("nivon.agro_bigquery_loader", "--arquivo", stage, "--projeto", c.projeto,
            "--dataset", c.dataset, "--executar", "--custos-autorizados",
            "--armazenamento-autorizado", "--licencas-conferidas"),
    ]


def _maritimo(c):
    return [_py("nivon.maritimo_gcp_job")]


FONTES = {
    "ptax": Fonte("ptax", "PTAX BCB -> nivon_core.ptax_quotes (MERGE por quote_id)", _ptax,
                  timedelta(hours=6)),
    "antt_ferrovia": Fonte("antt_ferrovia", "ANTT SIADE ferroviário -> GCS por SHA + BigQuery",
                           _antt, timedelta(days=7)),
    "conab": Fonte("conab", "CONAB XLSX oficiais -> GCS por SHA + BigQuery só novos", _conab,
                   timedelta(hours=24)),
    "maritimo": Fonte("maritimo", "Imbituba + PortWatch -> GCS + BigQuery idempotente",
                      _maritimo, timedelta(hours=6), env={"NIVON_MARITIMO_COLETA_HABILITADA": "true",
                                      "NIVON_MARITIMO_FONTES": "imbituba",
                                      "NIVON_PORTWATCH_COLETA_HABILITADA": "true"}),
}
