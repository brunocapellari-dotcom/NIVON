"""Execução coordenada local dos incrementais CONAB LAB + SAGyP.

Não implementa cron, acesso remoto, GCP nem publicação. A execução real usa
RAWs privados já presentes, com duas bases SQLite independentes. Não há
transação distribuída: cada fonte preserva sua atomicidade individual.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .sincronizacao_incremental_argentina_local import (
    sincronizar_raw_argentina_local,
)
from .sincronizacao_incremental_conab_lab import (
    sincronizar_incremental_lab,
)


class ErroLoteAgro(ValueError):
    pass


def _manifesto_json(path):
    f = Path(path)
    if f.is_symlink() or not f.is_file() or f.stat().st_size > 1_000_000:
        raise ErroLoteAgro("manifesto ausente, simbólico ou excessivo")
    def sem_duplicatas(pares):
        obj = {}
        for k, v in pares:
            if k in obj:
                raise ErroLoteAgro("chave JSON duplicada no manifesto")
            obj[k] = v
        return obj
    try:
        with f.open("r", encoding="utf-8") as arquivo:
            value = json.load(arquivo, object_pairs_hook=sem_duplicatas,
                              parse_constant=lambda v: (_ for _ in ()).throw(
                                  ErroLoteAgro("constante JSON não permitida")
                              ))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ErroLoteAgro("manifesto JSON não confiável") from exc
    if not isinstance(value, dict):
        raise ErroLoteAgro("manifesto JSON deve ser objeto")
    return value


def executar_fontes_incrementais(
    *, conab: dict | None = None, argentina: dict | None = None,
    executar: bool = False, direitos_argentina_verificados: bool = False,
):
    """Uma rodada; sem publicação nem cloud. Fontes independentes."""
    if conab is None and argentina is None:
        raise ErroLoteAgro("nenhuma fonte informada")
    if executar is not True:
        return {"estado": "EXECUCAO_DESABILITADA", "executado": False,
                "fontes_solicitadas": [
                    x for x, v in (("CONAB_LAB", conab), ("ARG_SAGYP", argentina))
                    if v is not None
                ], "rede_usada": False, "publicacao_permitida": False}
    if argentina is not None and direitos_argentina_verificados is not True:
        raise PermissionError("autorizações explícitas da Argentina não apresentadas")
    resultado = {"estado": "EXECUCAO_LOCAL_INCREMENTAL",
                 "rede_usada": False, "cloud_integrado": False,
                 "publicacao_permitida": False, "resultados": {}}
    # Todas as entradas devem ter shape completo ANTES da primeira escrita.
    for fonte, item, keys in (
        ("CONAB_LAB", conab, {"manifesto", "banco", "raw_dir", "backups"}),
        ("ARG_SAGYP", argentina, {"manifesto", "banco", "raw_dir"}),
    ):
        if item is not None and (not isinstance(item, dict) or set(item) != keys):
            raise ErroLoteAgro(f"{fonte}: configuração incompleta")
    if (conab is not None and argentina is not None
            and Path(conab["banco"]).resolve() == Path(argentina["banco"]).resolve()):
        raise ErroLoteAgro("CONAB e Argentina precisam de bases SQLite independentes")
    for source, config in (("CONAB_LAB", conab), ("ARG_SAGYP", argentina)):
        if config is None:
            continue
        catalogo = _manifesto_json(config["manifesto"])
        try:
            if source == "CONAB_LAB":
                result = sincronizar_incremental_lab(
                    catalogo, config["banco"], config["backups"],
                    arquivos_locais=config["raw_dir"],
                )
            else:
                result = sincronizar_raw_argentina_local(
                    catalogo, banco=config["banco"], pasta_raw=config["raw_dir"],
                    direitos_armazenamento_verificados=True,
                )
        except Exception as exc:
            # Sem prometer rollback entre dois bancos independentes.
            resultado["estado"] = "LOTE_PARCIAL_FALHOU_FECHADO"
            resultado["fonte_com_erro"] = source
            resultado["fontes_ja_confirmadas"] = sorted(resultado["resultados"])
            resultado["motivo_classe"] = type(exc).__name__
            return resultado
        resultado["resultados"][source] = {
            "estado": result.get("estado"),
            "edicoes_novas": result.get("edicoes_novas", 0),
            "observacoes_novas": result.get("observacoes_novas", 0),
            "publicacao_permitida": False,
        }
    resultado["estado"] = "FONTES_LOCAIS_CONFERIDAS_SEM_PROMOCAO"
    return resultado


def main(argv=None):
    p = argparse.ArgumentParser(
        description="NIVON: sincronização incremental de RAWs privados, sem rede"
    )
    p.add_argument("--executar", action="store_true")
    p.add_argument("--conab-manifesto")
    p.add_argument("--conab-banco")
    p.add_argument("--conab-raw-dir")
    p.add_argument("--conab-backups")
    p.add_argument("--argentina-manifesto")
    p.add_argument("--argentina-banco")
    p.add_argument("--argentina-raw-dir")
    p.add_argument("--direitos-argentina-verificados", action="store_true")
    a = p.parse_args(argv)
    conab_vals = [a.conab_manifesto, a.conab_banco,
                  a.conab_raw_dir, a.conab_backups]
    arg_vals = [a.argentina_manifesto, a.argentina_banco, a.argentina_raw_dir]
    if any(conab_vals) and not all(conab_vals):
        p.error("CONAB: quatro parâmetros obrigatórios em conjunto")
    if any(arg_vals) and not all(arg_vals):
        p.error("Argentina: três parâmetros obrigatórios em conjunto")
    conf_conab = dict(zip(("manifesto", "banco", "raw_dir", "backups"), conab_vals)) if all(conab_vals) else None
    conf_arg = dict(zip(("manifesto", "banco", "raw_dir"), arg_vals)) if all(arg_vals) else None
    try:
        result = executar_fontes_incrementais(
            conab=conf_conab, argentina=conf_arg,
            executar=a.executar, direitos_argentina_verificados=a.direitos_argentina_verificados,
        )
    except (ValueError, PermissionError, OSError) as exc:
        p.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["estado"] != "LOTE_PARCIAL_FALHOU_FECHADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
