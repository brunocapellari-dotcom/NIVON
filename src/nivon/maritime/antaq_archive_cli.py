"""Manual, offline ANTAQ annual ZIP validator; never downloads or runs schedulers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from dataclasses import asdict

from .antaq_archive import MAX_ZIP_BYTES, AntaqArchiveSummary, analyze_antaq_archive


def inspect_local_antaq_archive(
    filename: str | Path, *, year: int, source_id: str,
    collected_at: str, rights_verified: bool = False,
    source_published_at: str | None = None,
    publication_evidence_id: str | None = None,
    as_of: str | None = None,
) -> dict:
    """Small summary only: no raw data is copied or published by this API."""
    if not rights_verified:
        raise PermissionError("analise de arquivo ANTAQ requer verificacao documental de direitos")
    source = Path(filename)
    if source.suffix.lower() != ".zip" or not source.is_file() or source.is_symlink():
        raise ValueError("arquivo local deve ser ZIP regular, nao symlink")
    if not 0 < source.stat().st_size <= MAX_ZIP_BYTES:
        raise ValueError("arquivo ZIP fora do limite")
    result = analyze_antaq_archive(
        source.read_bytes(), year=year, source_id=source_id,
        collected_at=collected_at, rights_to_read=rights_verified,
        source_published_at=source_published_at,
        publication_evidence_id=publication_evidence_id,
        as_of=as_of,
    )
    return {
        "source_id": result.source_id,
        "archive_year": result.archive_year,
        "archive_sha256": result.archive_sha256,
        "source_published_at": result.source_published_at,
        "collected_at": result.collected_at,
        "classification": result.classification,
        "status": result.status,
        "count_atracacoes_distinct": result.count_atracacoes_distinct,
        "count_carga_rows": result.count_carga_rows,
        "count_carga_without_atracacao": result.count_carga_without_atracacao,
        "count_aggregated_groups": result.count_aggregated_groups,
        "warnings": list(result.warnings),
        "publication_allowed": False,
        "file_persisted_to_nivon": False,
        "results_persisted_to_nivon": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="NIVON: valida ZIP ANTAQ local SEM baixar ou publicar")
    parser.add_argument("--zip", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--collected-at", required=True)
    parser.add_argument("--source-published-at")
    parser.add_argument("--publication-evidence-id")
    parser.add_argument("--as-of")
    parser.add_argument("--rights-verified", action="store_true",
                        help="declare verificacao efetiva dos direitos; nao equivale prova automatica")
    args = parser.parse_args(argv)
    report = inspect_local_antaq_archive(
        args.zip, year=args.year, source_id=args.source_id,
        collected_at=args.collected_at, rights_verified=args.rights_verified,
        source_published_at=args.source_published_at,
        publication_evidence_id=args.publication_evidence_id,
        as_of=args.as_of,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
