"""Pipeline local multi-documento CONAB: RAW -> checks -> amostra -> dossiê.

Sem rede, cron, armazenamento de produção ou direitos presumidos.
Executar em processo isolado ao inspecionar anexos externos não confiáveis.
Uso: python -m nivon.conab_lote_offline --manifest JOBS.json --base-dir RAW --out DOSSIER.json

O resultado é um STAGING de auditoria, nunca uma série agrícola validada
ou um histórico temporal point-in-time. O arquivo de saída não sobrescreve.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from hmac import compare_digest
import json
from pathlib import Path
import re
import sys

from .conab_anexo_xlsx_levantamento import (
    ErroDocumentoConab, conferir_anexo_xlsx_levantamento,
)
from .conab_celulas_xlsx import ler_amostra_celulas_conab


class ErroLoteConab(ValueError):
    pass


_JOBS = frozenset({
    "job_id", "safra", "numero_levantamento",
    "pagina_levantamento_url", "pagina_anexo_url", "arquivo_xlsx_url",
    "html_levantamento", "html_anexo", "xlsx",
    "sha256_html_levantamento", "sha256_html_anexo", "sha256_xlsx_esperado",
    "coletado_levantamento_em", "coletado_anexo_em", "coletado_xlsx_em",
})
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MAX_BYTES = {"html_levantamento": 3_000_000, "html_anexo": 3_000_000, "xlsx": 15_000_000}


def _unicos(items):
    out = {}
    for k, v in items:
        if k in out:
            raise ErroLoteConab("JSON contém chave duplicada")
        out[k] = v
    return out


def _json(path: Path, limit: int) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ErroLoteConab("manifesto ausente, inseguro ou grande")
    try:
        result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unicos)
    except (ValueError, UnicodeError) as exc:
        raise ErroLoteConab("JSON do manifesto inválido") from exc
    if not isinstance(result, dict) or set(result) != {"schema_version", "jobs"}:
        raise ErroLoteConab("contrato de manifesto incompatível")
    if result["schema_version"] != "1.0":
        raise ErroLoteConab("versão do manifesto desconhecida")
    if not isinstance(result["jobs"], list) or not 1 <= len(result["jobs"]) <= 30:
        raise ErroLoteConab("lote requer entre 1 e 30 documentos")
    return result


def _ler_raw(base: Path, relative, kind: str) -> bytes:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise ErroLoteConab("caminho RAW inválido")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise ErroLoteConab("RAW deve ser caminho relativo simples sem traversal")
    target = base / candidate
    probe = base
    for part in candidate.parts:
        probe = probe / part
        if probe.is_symlink():
            raise ErroLoteConab("arquivo ou diretório RAW é link simbólico")
    root = base.resolve(strict=True)
    final = target.resolve(strict=True)
    if root not in final.parents or not final.is_file():
        raise ErroLoteConab("RAW fora do diretório autorizado")
    max_size = _MAX_BYTES[kind]
    if not 0 < final.stat().st_size <= max_size:
        raise ErroLoteConab("arquivo RAW vazio ou excessivo")
    with final.open("rb") as f:
        data = f.read(max_size + 1)
    if not 0 < len(data) <= max_size:
        raise ErroLoteConab("arquivo RAW alterado durante leitura")
    return data


def _validar_job(item: dict) -> None:
    if not isinstance(item, dict) or set(item) != _JOBS:
        raise ErroLoteConab("job com campos ausentes/extras")
    if not isinstance(item["job_id"], str) or not _ID.fullmatch(item["job_id"]):
        raise ErroLoteConab("job_id inválido")
    for field in ("sha256_html_levantamento", "sha256_html_anexo", "sha256_xlsx_esperado"):
        v = item[field]
        if not isinstance(v, str) or not _SHA.fullmatch(v):
            raise ErroLoteConab("hash de aquisição ausente: " + field)


def executar_lote_conab(*, manifesto: dict, base_dir: str | Path) -> dict:
    """Executa lote inteiro; falha em um job não libera os demais para produção."""
    if not isinstance(manifesto, dict) or set(manifesto) != {"schema_version", "jobs"}:
        raise ErroLoteConab("contrato de lote inválido")
    if manifesto["schema_version"] != "1.0" or not isinstance(manifesto["jobs"], list) or not 1 <= len(manifesto["jobs"]) <= 30:
        raise ErroLoteConab("lista de jobs inválida")
    base = Path(base_dir)
    if base.is_symlink() or not base.is_dir():
        raise ErroLoteConab("diretório RAW ausente ou inseguro")
    vistos_id, vistos_edicao = set(), set()
    results = []
    for job in manifesto["jobs"]:
        _validar_job(job)
        key = (job["safra"], job["numero_levantamento"])
        if job["job_id"] in vistos_id or key in vistos_edicao:
            raise ErroLoteConab("job ou edição duplicada no lote")
        vistos_id.add(job["job_id"])
        vistos_edicao.add(key)
        try:
            raw = {name: _ler_raw(base, job[name], name)
                   for name in ("html_levantamento", "html_anexo", "xlsx")}
            for kind, field in (
                ("html_levantamento", "sha256_html_levantamento"),
                ("html_anexo", "sha256_html_anexo"),
                ("xlsx", "sha256_xlsx_esperado"),
            ):
                if not compare_digest(sha256(raw[kind]).hexdigest(), job[field]):
                    raise ErroLoteConab("SHA informado difere do RAW: " + kind)
            vinculo = conferir_anexo_xlsx_levantamento(
                safra=job["safra"], numero_levantamento=job["numero_levantamento"],
                pagina_levantamento_url=job["pagina_levantamento_url"],
                pagina_anexo_url=job["pagina_anexo_url"],
                arquivo_xlsx_url=job["arquivo_xlsx_url"],
                html_levantamento_raw=raw["html_levantamento"],
                html_anexo_raw=raw["html_anexo"],
                xlsx_raw=raw["xlsx"],
                coletado_levantamento_em=job["coletado_levantamento_em"],
                coletado_anexo_em=job["coletado_anexo_em"],
                coletado_xlsx_em=job["coletado_xlsx_em"],
                sha256_xlsx_esperado=job["sha256_xlsx_esperado"],
            )
            amostra = ler_amostra_celulas_conab(
                manifesto_vinculo=vinculo, xlsx_raw=raw["xlsx"],
            )
            results.append({
                "job_id": job["job_id"], "resultado": "INSPECAO_OFFLINE_CONCLUIDA",
                "vinculo": vinculo, "amostra_layout": amostra,
                "edicao_historica_autenticada": False,
                "habilita_backtest": False, "habilita_treino": False,
                "habilita_publicacao": False,
            })
        except (ErroDocumentoConab, ErroLoteConab, FileNotFoundError,
                OSError, UnicodeError, ValueError) as exc:
            results.append({
                "job_id": job["job_id"], "resultado": "REJEITADO",
                "motivo": f"{type(exc).__name__}: {str(exc)[:150]}",
                "amostra_layout": None,
                "edicao_historica_autenticada": False,
                "habilita_backtest": False, "habilita_treino": False,
                "habilita_publicacao": False,
            })
    ok = sum(r["resultado"] == "INSPECAO_OFFLINE_CONCLUIDA" for r in results)
    return {
        "schema_version": "1.0", "status": "DOSSIER_STAGING_NAO_HOMOLOGADO",
        "total": len(results), "inspecionados": ok, "rejeitados": len(results) - ok,
        "resultados": results,
        "captura_real_verificada_externamente": False,
        "edicao_historica_autenticada": False,
        "habilita_backtest": False, "habilita_treino": False,
        "habilita_publicacao": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CONAB: inspeção offline em lote; sem ingestão/treino")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sqlite", help="arquivo SQLite de staging; sem backtest")
    args = parser.parse_args(argv)
    try:
        manifest = _json(Path(args.manifest), 200_000)
        result = executar_lote_conab(manifesto=manifest, base_dir=args.base_dir)
        destination = Path(args.out)
        if destination.is_symlink() or destination.exists() or not destination.parent.is_dir():
            raise ErroLoteConab("saída já existe ou diretório indisponível")
        if destination.resolve().is_relative_to(Path(args.base_dir).resolve()):
            raise ErroLoteConab("saída não pode sobrescrever ou residir dentro de RAW")
        if args.sqlite:
            import sqlite3
            from .conab_staging_sqlite import preparar_staging, gravar_dossie_conab
            store = Path(args.sqlite)
            if (store.is_symlink() or not store.parent.is_dir()
                    or store.resolve().is_relative_to(Path(args.base_dir).resolve())):
                raise ErroLoteConab("SQLite staging inseguro ou dentro dos RAWs")
            if result["rejeitados"]:
                # Dossiê de rejeições permanece legível e nunca é gravado no
                # armazém de inspeções completas.
                result["persistencia_staging"] = {
                    "estado": "NAO_PERSISTIDO_LOTE_COM_REJEICOES",
                    "inseridos": 0, "habilita_publicacao": False,
                }
            else:
                with sqlite3.connect(str(store), timeout=5) as db:
                    preparar_staging(db)
                    result["persistencia_staging"] = gravar_dossie_conab(db, result)
        # O_EXCL evita sobrescrita silenciosa de artefatos anteriores.
        with destination.open("x", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        print(f"INSPECIONADOS={result['inspecionados']} REJEITADOS={result['rejeitados']}")
        return 0 if result["rejeitados"] == 0 else 2
    except (ErroLoteConab, OSError, ValueError) as exc:
        print(f"Falha fechada no lote CONAB: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
