"""Offline, separately scoped history of PDF PORT PROGRAMME references.

Programme number (N. Prog), IMO and ship name never prove a DUV, a unique
port call, a realized operation, vessel counts or exported tonnage.
The existing MaritimeStore owns the SQLite connection and backup/restore.
No network, collection, automatic licence checking or publication is enabled.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from .lineup_history import _aware_utc
from .maritime_store import MaritimeStore
from .official_lineup_bridge import LineupBridgeResult, PdfProgramReference


PDF_PORTS = frozenset({"PARANAGUA", "ITAQUI"})
PARANAGUA_SERIES = frozenset({"EXPORT_OESTE", "EXPORT_LESTE", "IMPORT_SOLIDOS"})
MAX_EDITION_BYTES = 2_000_000


@dataclass(frozen=True)
class PdfProgrammeEdition:
    """One acquired programme edition, including unmatchable/partial PDF rows.

    This deliberately does NOT subclass LineupVintage: a document lacking
    DUV still contains schedule evidence, but not a uniquely identified visit.
    """

    port_id: str
    source_id: str
    series: str | None
    source_url: str
    source_sha256: str
    collected_at: str | datetime
    reference_date: str
    competence: str
    source_rows: int
    rows: tuple[PdfProgramReference, ...]
    excluded_call_rows: int
    published_at: str | datetime | None = None
    publication_evidence_id: str | None = None

    def __post_init__(self) -> None:
        if self.port_id not in PDF_PORTS or not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("unsupported PDF authority or missing source")
        if self.port_id == "PARANAGUA" and self.series not in PARANAGUA_SERIES:
            raise ValueError("Paranagua source requires canonical series")
        if self.port_id == "ITAQUI" and self.series is not None:
            raise ValueError("Itaqui does not use Paranagua series")
        if not self.source_url or not self.source_url.startswith("https://"):
            raise ValueError("source URL required")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.source_sha256):
            raise ValueError("document SHA-256 required")
        acquired = _aware_utc(self.collected_at, "collected_at")
        try:
            referenced = date.fromisoformat(self.reference_date)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid reference_date") from exc
        if referenced > acquired.date():
            raise ValueError("reference_date cannot be after collection")
        if self.competence != self.reference_date[:7]:
            raise ValueError("competence must agree with reference_date month")
        has_pub = self.published_at is not None
        has_proof = bool(self.publication_evidence_id and self.publication_evidence_id.strip())
        if has_pub != has_proof:
            raise ValueError("publication timestamp requires evidence and vice versa")
        if has_pub and _aware_utc(self.published_at, "published_at") > acquired:
            raise ValueError("publication later than collection")
        if (type(self.source_rows) is not int or type(self.excluded_call_rows) is not int
                or self.source_rows < 1 or not 0 <= self.excluded_call_rows <= self.source_rows):
            raise ValueError("invalid source/excluded rows")
        if not isinstance(self.rows, tuple) or len(self.rows) != self.source_rows:
            raise ValueError("incomplete programme row accounting")
        identifiers: set[int] = set()
        for row in self.rows:
            if not isinstance(row, PdfProgramReference):
                raise ValueError("not a PDF programme reference")
            if (type(row.source_row) is not int or row.source_row < 1
                    or row.source_row > self.source_rows or row.source_row in identifiers):
                raise ValueError("duplicate/missing source row number")
            identifiers.add(row.source_row)
            if row.evidence_class != "PROGRAMME_REFERENCE_NOT_PORT_CALL":
                raise ValueError("PDF programme falsely promoted to port call")
            if not row.vessel_name or not row.vessel_name.strip():
                raise ValueError("vessel descriptor missing")
            if row.programme_number is not None and self.port_id != "PARANAGUA":
                raise ValueError("unscoped programme number for Itaqui")
            if row.programme_number is not None and not row.programme_number.startswith(self.series + ":"):
                raise ValueError("Paranagua programme number outside series")
            if row.planned_volume_t is not None and (
                not math.isfinite(row.planned_volume_t) or row.planned_volume_t < 0
            ):
                raise ValueError("invalid declared tonnage")

    @property
    def collected_utc(self) -> datetime:
        return _aware_utc(self.collected_at, "collected_at")

    @property
    def published_utc(self) -> datetime | None:
        return _aware_utc(self.published_at, "published_at") if self.published_at is not None else None

    def provenance(self) -> dict[str, object]:
        return {
            "port_id": self.port_id, "source_id": self.source_id,
            "series": self.series, "source_url": self.source_url,
            "source_sha256": self.source_sha256.lower(),
            "competencia": self.competence, "data_referencia": self.reference_date,
            "data_publicacao": self.published_utc.isoformat() if self.published_utc else None,
            "data_coleta": self.collected_utc.isoformat(),
            "publication_evidence_id": self.publication_evidence_id,
            "evidence_class": "PROGRAMME_REFERENCE_NOT_PORT_CALL",
        }


def edition_from_pdf_bridge(
    bridge: LineupBridgeResult, *,
    reference_date: str, competence: str,
    published_at: str | datetime | None = None,
    publication_evidence_id: str | None = None,
) -> PdfProgrammeEdition:
    """Transform an already SHA-verified PDF bridge, retaining excluded rows."""
    if not isinstance(bridge, LineupBridgeResult):
        raise TypeError("requires an official PDF bridge result")
    if bridge.port_id not in PDF_PORTS or bridge.state != "SHADOW_NOT_HOMOLOGATED":
        raise ValueError("unsupported or promoted PDF bridge")
    if bridge.publication_allowed or bridge.realized_cargo_claimed:
        raise ValueError("PDF bridge cannot claim published or performed operation")
    if bridge.source_rows <= 0 or len(bridge.pdf_program_rows) != bridge.source_rows:
        raise ValueError("incomplete PDF programme rows")
    if bridge.source_rows != len(bridge.candidates) + len(bridge.excluded):
        raise ValueError("PDF candidate and excluded row counts inconsistent")
    if (bridge.port_id == "PARANAGUA" and bridge.pdf_series not in PARANAGUA_SERIES
            or bridge.port_id == "ITAQUI" and bridge.pdf_series is not None):
        raise ValueError("missing/invalid PDF source series")
    return PdfProgrammeEdition(
        port_id=bridge.port_id,
        source_id=bridge.source_id,
        series=bridge.pdf_series,
        source_url=bridge.source_url,
        source_sha256=bridge.document_sha256,
        collected_at=bridge.collected_at,
        reference_date=reference_date,
        competence=competence,
        published_at=published_at,
        publication_evidence_id=publication_evidence_id,
        source_rows=bridge.source_rows,
        rows=bridge.pdf_program_rows,
        excluded_call_rows=len(bridge.excluded),
    )


@dataclass(frozen=True)
class ProgrammeAsOf:
    status: str
    as_of: str
    port_id: str
    source_id: str
    series: str | None
    edition: PdfProgrammeEdition | None

    def summary(self) -> dict[str, object]:
        item = self.edition
        return {
            "status": self.status, "as_of": self.as_of,
            "port_id": self.port_id, "source_id": self.source_id,
            "series": self.series,
            "programme_pdf_rows": item.source_rows if item else None,
            "programme_numbers_declared": (
                len({r.programme_number for r in item.rows if r.programme_number})
                if item else None
            ),
            "rows_not_mappable_to_duv": item.excluded_call_rows if item else None,
            "verified_port_call_count": None,
            "realized_volume_t": None, "actual_arrivals": None,
            "publication_allowed": False,
            "provenance": item.provenance() if item else None,
        }


class PdfProgrammeLedger:
    """Immutably save fully scoped PDF-programming editions, not port calls."""

    def __init__(self, store: MaritimeStore) -> None:
        if not isinstance(store, MaritimeStore):
            raise TypeError("requires MaritimeStore")
        self.db = store.db
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS maritime_pdf_programme_editions (
                    edition_id TEXT PRIMARY KEY,
                    port_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    series_key TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    published_at TEXT,
                    source_sha256 TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(port_id,source_id,series_key,collected_at)
                );
                CREATE INDEX IF NOT EXISTS idx_pdf_programme_asof
                  ON maritime_pdf_programme_editions(
                    port_id,source_id,series_key,collected_at DESC,published_at
                  );
            """)

    @staticmethod
    def _canonical(edition: PdfProgrammeEdition) -> tuple[str, str, str]:
        if not isinstance(edition, PdfProgrammeEdition):
            raise TypeError("requires validated PDF programme edition")
        # Revalidate even if callers bypass dataclass constructor through object tricks.
        edition.__post_init__()
        data: dict[str, Any] = {
            **edition.provenance(),
            "source_rows": edition.source_rows,
            "excluded_call_rows": edition.excluded_call_rows,
            "rows": [asdict(row) for row in edition.rows],
        }
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if len(raw.encode("utf-8")) > MAX_EDITION_BYTES:
            raise ValueError("PDF programme edition payload exceeds size limit")
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        series_key = edition.series or ""
        identity = hashlib.sha256(
            f"{edition.port_id}|{edition.source_id}|{series_key}|{edition.collected_utc.isoformat()}".encode("utf-8")
        ).hexdigest()
        return identity, checksum, raw

    def save(self, edition: PdfProgrammeEdition, *, storage_authorized: bool = False) -> bool:
        """Explicitly authorized storage: True new, False exact duplicate."""
        if not storage_authorized:
            raise PermissionError("PDF programme edition storage not authorized")
        key, checksum, raw = self._canonical(edition)
        scope = (edition.port_id, edition.source_id, edition.series or "", edition.collected_utc.isoformat())
        try:
            with self.db:
                self.db.execute("""
                    INSERT INTO maritime_pdf_programme_editions
                    (edition_id,port_id,source_id,series_key,collected_at,published_at,
                     source_sha256,payload_sha256,payload_json)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (key, *scope,
                      edition.published_utc.isoformat() if edition.published_utc else None,
                      edition.source_sha256.lower(), checksum, raw))
        except sqlite3.IntegrityError as exc:
            existing = self.db.execute("""
                SELECT payload_sha256,payload_json FROM maritime_pdf_programme_editions
                WHERE port_id=? AND source_id=? AND series_key=? AND collected_at=?
            """, scope).fetchone()
            if existing == (checksum, raw):
                return False
            raise ValueError("conflicting PDF programme edition at same collection instant") from exc
        return True

    @classmethod
    def _decode(cls, row: tuple[Any, ...]) -> PdfProgrammeEdition:
        identity, port, source, series_key, collected, published, digest, checksum, raw = row
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_EDITION_BYTES:
            raise ValueError("invalid PDF edition payload size")
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != checksum:
            raise ValueError("corrupted PDF edition payload checksum")
        try:
            parsed = json.loads(raw)
            item = PdfProgrammeEdition(
                port_id=parsed["port_id"], source_id=parsed["source_id"],
                series=parsed["series"], source_url=parsed["source_url"],
                source_sha256=parsed["source_sha256"],
                collected_at=parsed["data_coleta"], reference_date=parsed["data_referencia"],
                competence=parsed["competencia"], published_at=parsed["data_publicacao"],
                publication_evidence_id=parsed["publication_evidence_id"],
                source_rows=parsed["source_rows"], excluded_call_rows=parsed["excluded_call_rows"],
                rows=tuple(PdfProgramReference(**x) for x in parsed["rows"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid PDF programme edition payload") from exc
        expected_id, expected_sha, expected_raw = cls._canonical(item)
        if (expected_id != identity or expected_sha != checksum or expected_raw != raw
                or (port, source, series_key, collected, published, digest)
                != (item.port_id, item.source_id, item.series or "", item.collected_utc.isoformat(),
                    item.published_utc.isoformat() if item.published_utc else None,
                    item.source_sha256.lower())):
            raise ValueError("PDF programme edition identity/metadata mismatch")
        return item

    def select_asof(self, *, port_id: str, source_id: str, series: str | None,
                    as_of: str | datetime, read_authorized: bool = False) -> ProgrammeAsOf:
        """Never retrospectively expose a collection/publication from the future."""
        if not read_authorized:
            raise PermissionError("PDF programme history reading not authorized")
        if port_id not in PDF_PORTS or not source_id or not source_id.strip():
            raise ValueError("invalid port or source")
        if port_id == "PARANAGUA" and series not in PARANAGUA_SERIES:
            raise ValueError("Paranagua programme series required")
        if port_id == "ITAQUI" and series is not None:
            raise ValueError("Itaqui has no programme series")
        cutoff = _aware_utc(as_of, "as_of").isoformat()
        rows = self.db.execute("""
            SELECT edition_id,port_id,source_id,series_key,collected_at,published_at,
                   source_sha256,payload_sha256,payload_json
            FROM maritime_pdf_programme_editions
            WHERE port_id=? AND source_id=? AND series_key=? AND collected_at<=?
              AND published_at IS NOT NULL AND published_at<=?
            ORDER BY collected_at DESC LIMIT 1
        """, (port_id, source_id, series or "", cutoff, cutoff)).fetchall()
        edition = self._decode(rows[0]) if rows else None
        return ProgrammeAsOf(
            status="PROGRAMME_ONLY_NOT_PORT_CALL" if edition else "DATA_GATED",
            as_of=cutoff, port_id=port_id, source_id=source_id,
            series=series, edition=edition,
        )

    def count_editions(self, *, port_id: str, source_id: str, series: str | None,
                       read_authorized: bool = False) -> int:
        if not read_authorized:
            raise PermissionError("PDF programme history reading not authorized")
        if port_id not in PDF_PORTS or not source_id or not source_id.strip():
            raise ValueError("invalid port or source")
        if port_id == "PARANAGUA" and series not in PARANAGUA_SERIES:
            raise ValueError("Paranagua programme series required")
        if port_id == "ITAQUI" and series is not None:
            raise ValueError("Itaqui has no programme series")
        return self.db.execute("""
            SELECT COUNT(*) FROM maritime_pdf_programme_editions
            WHERE port_id=? AND source_id=? AND series_key=?
        """, (port_id, source_id, series or "")).fetchone()[0]
