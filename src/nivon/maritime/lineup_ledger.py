"""Offline SQLite ledger for authorized official line-up editions.

Uses the existing MaritimeStore connection, backup and restore facilities.
No collection, publication, cloud operation or automatic AIS rights implied.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Any

from .lineup_history import LineupVintage, LineupAsOf, _aware_utc, select_lineup_asof
from .maritime_store import MaritimeStore
from .shipping_reconciliation import LineupCall


class LineupVintageLedger:
    """Persist editions, never actual cargo volumes or asserted port operations.

    Identity of one edition is (port, authority, collection instant).
    A conflicting second edition with that identity fails closed, even if the
    underlying bytes differ. One edition has one or more scheduled calls and
    each call may have its own future ETA. Same IMO in different DUVs is valid.
    """

    MAX_PAYLOAD_BYTES = 2_000_000

    def __init__(self, store: MaritimeStore) -> None:
        if not isinstance(store, MaritimeStore):
            raise TypeError("requires a MaritimeStore connection")
        self.store = store
        self.db = store.db
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS maritime_lineup_vintages (
                    vintage_id TEXT PRIMARY KEY,
                    port_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    published_at TEXT,
                    reference_date TEXT NOT NULL,
                    competence TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    publication_evidence_id TEXT,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(port_id, source_id, collected_at)
                );
                CREATE INDEX IF NOT EXISTS idx_maritime_vintages_asof
                ON maritime_lineup_vintages(port_id, source_id, collected_at DESC, published_at);
            """)

    @staticmethod
    def _canonical(vintage: LineupVintage) -> tuple[str, str, str]:
        if not isinstance(vintage, LineupVintage):
            raise TypeError("only validated LineupVintage accepted")
        calls: list[dict[str, Any]] = []
        for call in vintage.calls:
            item = asdict(call)
            item["eta"] = _aware_utc(call.eta, "call.eta").isoformat()
            item["collected_at"] = _aware_utc(call.collected_at, "call.collected_at").isoformat()
            calls.append(item)
        data: dict[str, Any] = {
            "port_id": vintage.port_id.strip().upper(),
            "source_id": vintage.source_id,
            "source_sha256": vintage.source_sha256.lower(),
            "collected_at": vintage.collected_utc.isoformat(),
            "published_at": vintage.published_utc.isoformat() if vintage.published_utc else None,
            "reference_date": vintage.reference_date,
            "competence": vintage.competence,
            "publication_evidence_id": vintage.publication_evidence_id,
            "calls": calls,
        }
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) > LineupVintageLedger.MAX_PAYLOAD_BYTES:
            raise ValueError("lineup vintage exceeds size limit")
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        key = hashlib.sha256(
            f"{data['port_id']}|{data['source_id']}|{data['collected_at']}".encode("utf-8")
        ).hexdigest()
        return key, checksum, raw

    def save(self, vintage: LineupVintage, *, storage_authorized: bool = False) -> bool:
        """Return True for a new edition, False for an exact duplicate.

        Explicit permission is required for each write. A license/source
        decision must be made upstream and cannot be inferred from this flag.
        """
        if not storage_authorized:
            raise PermissionError("lineup historical storage requires explicit authorization")
        key, checksum, payload = self._canonical(vintage)
        port = vintage.port_id.strip().upper()
        collected = vintage.collected_utc.isoformat()
        published = vintage.published_utc.isoformat() if vintage.published_utc else None
        try:
            with self.db:
                self.db.execute("""
                    INSERT INTO maritime_lineup_vintages
                    (vintage_id,port_id,source_id,collected_at,published_at,
                     reference_date,competence,source_sha256,publication_evidence_id,
                     payload_sha256,payload_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (key, port, vintage.source_id, collected, published,
                      vintage.reference_date, vintage.competence,
                      vintage.source_sha256.lower(), vintage.publication_evidence_id,
                      checksum, payload))
        except sqlite3.IntegrityError as exc:
            # Collision is only idempotent when the complete stored edition is
            # byte-for-byte equivalent. Never overwrite a historical witness.
            row = self.db.execute("""
                SELECT payload_sha256,payload_json
                FROM maritime_lineup_vintages
                WHERE port_id=? AND source_id=? AND collected_at=?
            """, (port, vintage.source_id, collected)).fetchone()
            if row and row == (checksum, payload):
                return False
            raise ValueError("conflicting lineup vintage at same collection instant") from exc
        return True

    @classmethod
    def _decode(cls, row: tuple[Any, ...]) -> LineupVintage:
        (
            stored_vintage_id, stored_port, stored_source, collected, published,
            reference_date, competence, source_sha256, publication_evidence_id,
            checksum, payload,
        ) = row
        if not isinstance(payload, str) or len(payload.encode("utf-8")) > cls.MAX_PAYLOAD_BYTES:
            raise ValueError("invalid historical payload size")
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != checksum:
            raise ValueError("historical payload checksum mismatch")
        try:
            data = json.loads(payload)
            if not isinstance(data, dict) or not isinstance(data["calls"], list):
                raise ValueError("invalid historical snapshot structure")
            calls = tuple(LineupCall(**entry) for entry in data["calls"])
            snapshot = LineupVintage(
                port_id=data["port_id"], source_id=data["source_id"],
                source_sha256=data["source_sha256"], collected_at=data["collected_at"],
                published_at=data["published_at"],
                publication_evidence_id=data["publication_evidence_id"],
                reference_date=data["reference_date"], competence=data["competence"],
                calls=calls,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("historical lineup payload not valid") from exc
        if (
            snapshot.port_id.strip().upper() != stored_port
            or snapshot.source_id != stored_source
            or snapshot.collected_utc.isoformat() != collected
            or (snapshot.published_utc.isoformat() if snapshot.published_utc else None) != published
            or snapshot.reference_date != reference_date
            or snapshot.competence != competence
            or snapshot.source_sha256.lower() != source_sha256
            or snapshot.publication_evidence_id != publication_evidence_id
        ):
            raise ValueError("historical lineup metadata mismatch")
        derived_id, derived_checksum, derived_payload = cls._canonical(snapshot)
        if (derived_id != stored_vintage_id or derived_checksum != checksum
                or derived_payload != payload):
            raise ValueError("historical lineup identity or canonical payload mismatch")
        return snapshot

    def select_asof(
        self, *, port_id: str, source_id: str, as_of: datetime | str,
        read_authorized: bool = False,
    ) -> LineupAsOf:
        """Query only already-known editions for one authority at one port."""
        if not read_authorized:
            raise PermissionError("lineup historical reading requires authorization")
        if not port_id or not port_id.strip() or not source_id or not source_id.strip():
            raise ValueError("port_id and source_id required")
        cutoff = _aware_utc(as_of, "as_of").isoformat()
        rows = self.db.execute("""
            SELECT vintage_id,port_id,source_id,collected_at,published_at,reference_date,
                   competence,source_sha256,publication_evidence_id,
                   payload_sha256,payload_json
            FROM maritime_lineup_vintages
            WHERE port_id=? AND source_id=? AND collected_at<=?
              AND published_at IS NOT NULL AND published_at<=?
            ORDER BY collected_at DESC LIMIT 1
        """, (port_id.strip().upper(), source_id, cutoff, cutoff)).fetchall()
        snapshots = tuple(self._decode(row) for row in rows)
        return select_lineup_asof(
            snapshots, as_of=cutoff, port_id=port_id.strip().upper(), source_id=source_id
        )

    def count_editions(self, *, port_id: str, source_id: str, read_authorized: bool = False) -> int:
        if not read_authorized:
            raise PermissionError("lineup historical reading requires authorization")
        if not port_id or not port_id.strip() or not source_id or not source_id.strip():
            raise ValueError("port_id and source_id required")
        return self.db.execute("""
            SELECT COUNT(*) FROM maritime_lineup_vintages WHERE port_id=? AND source_id=?
        """, (port_id.strip().upper(), source_id)).fetchone()[0]
