"""Ensaio funcional de análise local, NÃO acessa APIs de Agrobr ou dados reais."""
from __future__ import annotations
import argparse
from importlib import metadata
import json
import math
import os


class ProbeBlocked(ValueError):
    pass


def validar_previsao(values: list[object], *, expected: float) -> None:
    if not isinstance(values, list) or len(values) != 2:
        raise ProbeBlocked("previsão sintética sem horizonte esperado")
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (float, int)):
            raise ProbeBlocked("resultado da previsão não numérico")
        if not math.isfinite(item) or not math.isclose(item, expected, abs_tol=0.000001):
            raise ProbeBlocked("modelo Naive divergiu da referência determinística")


def checar_imports_e_previsao() -> dict:
    # A execução ocorre somente em contêiner --network none, com arquivos de
    # testes sintéticos; não há chamadas agrobr.conab/CEPEA/IMEA ou credenciais.
    import agrobr  # noqa: F401
    import pandas as pd
    from statsforecast import StatsForecast
    from statsforecast.models import Naive

    agro_version = metadata.version("agrobr")
    if agro_version != "2.0.0":
        raise ProbeBlocked("versão de Agrobr diferente do contrato")
    if not metadata.version("statsforecast").startswith("2."):
        raise ProbeBlocked("versão de StatsForecast fora do intervalo")
    if not metadata.version("pandas").startswith("2."):
        raise ProbeBlocked("versão de pandas fora do intervalo")
    data = pd.DataFrame({
        "unique_id": ["SINTETICO"] * 8,
        "ds": pd.date_range("2026-01-01", periods=8, freq="D"),
        "y": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
    })
    model = StatsForecast(models=[Naive()], freq="D", n_jobs=1)
    predictions = model.forecast(df=data, h=2)
    validar_previsao(predictions["Naive"].tolist(), expected=8.0)
    if len(predictions) != 2 or predictions["unique_id"].tolist() != ["SINTETICO"] * 2:
        raise ProbeBlocked("identificador/horizonte sintético incorreto")
    return {
        "schema": "nivon.infrastructure.analytics_synthetic_probe.v1",
        "forecast": "NAIVE_TWO_STEP_DETERMINISTIC_OK",
        "horizon": 2,
        "agrobr_import": "OK_NO_API_CALLS",
        "no_external_agro_data": True,
        "no_real_collectors_started": True,
        "source_credentials_used": False,
        "production_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ensaio analítico local sem dados externos")
    p.add_argument("--offline-synthetic", action="store_true")
    args = p.parse_args(argv)
    if not args.offline_synthetic:
        print(json.dumps({"status": "DISABLED_BY_DEFAULT", "production_authorized": False}))
        return 0
    if any(os.environ.get(key, "false").lower() != "false" for key in (
        "NIVON_RUNTIME_ENABLED", "NIVON_COLLECTORS_ENABLED",
        "NIVON_BACKUP_ENABLED", "NIVON_PUBLICATION_ENABLED",
    )):
        print(json.dumps({"status": "BLOCKED_FLAGS", "production_authorized": False}))
        return 2
    try:
        result = checar_imports_e_previsao()
    except (ImportError, ValueError, KeyError, RuntimeError):
        print(json.dumps({"status": "ANALYTICS_EXPERIMENT_FAILED", "production_authorized": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
