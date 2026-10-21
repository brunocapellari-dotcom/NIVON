"""Conservative offline revision comparison for PDF port PROGRAMME references.

This module never turns N. Prog into DUV, a vessel visit, a realized operation,
a cancellation or exported tonnes. Programme IDs are comparable only within
the SAME official port, source, series, competence and reference date. Without
stable lot-level identities, duplicate products are explicitly ambiguous.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .lineup_history import _aware_utc
from .pdf_programme_ledger import PdfProgrammeEdition, PdfProgrammeLedger
from .official_lineup_bridge import PdfProgramReference


CLASSIFICATION = "PROGRAMME_REVISION_NOT_CONFIRMED_OPERATION"


@dataclass(frozen=True)
class ProgrammeChange:
    programme_number: str | None
    field: str
    before: str | float | int | bool | None
    after: str | float | int | bool | None
    previous_row: int | None = None
    current_row: int | None = None
    classification: str = CLASSIFICATION

    def summary(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProgrammeRevision:
    """A historical snapshot comparison; never a claim of a vessel movement."""

    status: str
    earlier_as_of: str
    later_as_of: str
    port_id: str
    source_id: str
    series: str | None
    previous: PdfProgrammeEdition | None
    current: PdfProgrammeEdition | None
    changes: tuple[ProgrammeChange, ...] | None

    def summary(self) -> dict[str, object]:
        return {
            "status": self.status,
            "earlier_as_of": self.earlier_as_of,
            "later_as_of": self.later_as_of,
            "port_id": self.port_id, "source_id": self.source_id,
            "series": self.series,
            "previous_source_sha256": self.previous.source_sha256 if self.previous else None,
            "current_source_sha256": self.current.source_sha256 if self.current else None,
            "source_document_changed": (
                self.previous.source_sha256.lower() != self.current.source_sha256.lower()
                if self.previous is not None and self.current is not None else None
            ),
            "change_count": len(self.changes) if self.changes is not None else None,
            "changes": [change.summary() for change in self.changes] if self.changes is not None else None,
            "confirmed_port_calls": None,
            "realized_tonnage_t": None,
            "confirmed_departures": None,
            "confirmed_cancellations": None,
            "publication_allowed": False,
            "evidence_class": CLASSIFICATION,
        }


def _by_programme(edition: PdfProgrammeEdition) -> tuple[
    dict[str, tuple[PdfProgramReference, ...]], int
]:
    identified: dict[str, list[PdfProgramReference]] = {}
    unknown = 0
    for row in edition.rows:
        if not row.programme_number:
            unknown += 1
            continue
        identified.setdefault(row.programme_number, []).append(row)
    return (
        {programme: tuple(sorted(lines, key=lambda item: item.source_row))
         for programme, lines in identified.items()},
        unknown,
    )


def _compare_rows(
    programme: str,
    previous: PdfProgramReference,
    current: PdfProgramReference,
) -> list[ProgrammeChange]:
    """Pair only safely matched rows. ETA stays source-declared, not actual."""
    fields = (
        ("eta_text_declared", previous.eta_text, current.eta_text),
        ("eta_fully_declared", previous.eta_fully_declared, current.eta_fully_declared),
        ("planned_volume_t_declared", previous.planned_volume_t, current.planned_volume_t),
        ("product_declared", previous.product, current.product),
        ("vessel_name_declared", previous.vessel_name, current.vessel_name),
        ("explicit_duv_field", previous.explicit_duv, current.explicit_duv),
    )
    return [
        ProgrammeChange(
            programme_number=programme, field=field, before=before, after=after,
            previous_row=previous.source_row, current_row=current.source_row,
        )
        for field, before, after in fields if before != after
    ]


def _compare_programme_group(
    programme: str,
    old: tuple[PdfProgramReference, ...],
    new: tuple[PdfProgramReference, ...],
) -> list[ProgrammeChange]:
    if len(old) == len(new) == 1:
        # A single programme row at each edition can be tentatively compared
        # by N. Prog even if a product label was edited. This is still NOT
        # a stable vessel identity or proof that the underlying lot persisted.
        return _compare_rows(programme, old[0], new[0])

    # In multi-lot programmes the product label is the strongest available
    # weak key. It is usable only when present, nonempty and UNIQUE on BOTH
    # sides. Duplicate same-product lot lines cannot be paired safely.
    def product_index(rows: tuple[PdfProgramReference, ...]) -> dict[str, PdfProgramReference] | None:
        result: dict[str, PdfProgramReference] = {}
        for row in rows:
            key = (row.product or "").strip().casefold()
            if not key or key in result:
                return None
            result[key] = row
        return result

    left = product_index(old)
    right = product_index(new)
    if left is None or right is None:
        return [ProgrammeChange(
            programme, "ambiguous_product_lot_lines_unmatched",
            len(old), len(new),
        )]

    changes: list[ProgrammeChange] = []
    for key in sorted(left.keys() & right.keys()):
        changes.extend(_compare_rows(programme, left[key], right[key]))

    # A new/absent product *label* does not prove a lot was added, removed,
    # loaded or cancelled: it could have been renamed or reclassified.
    if left.keys() != right.keys():
        changes.append(ProgrammeChange(
            programme, "unmatched_product_labels_unconfirmed",
            ", ".join(sorted(left.keys() - right.keys())) or None,
            ", ".join(sorted(right.keys() - left.keys())) or None,
        ))
    return changes


def compare_pdf_programme_editions(
    previous: PdfProgrammeEdition,
    current: PdfProgrammeEdition,
) -> tuple[ProgrammeChange, ...]:
    """Only compare same-document-scope revisions with later collection time.

    Requires the SAME reference date. Programme numbers may be recycled in
    different days or months; cross-day identity requires external evidence.
    No string similarity, IMO matching or row-index joining is performed.
    """
    if not isinstance(previous, PdfProgrammeEdition) or not isinstance(current, PdfProgrammeEdition):
        raise TypeError("requires two validated PDF programme editions")
    if (previous.port_id, previous.source_id, previous.series) != (
        current.port_id, current.source_id, current.series
    ):
        raise ValueError("PDF programme editions must share port, source and series")
    if previous.competence != current.competence or previous.reference_date != current.reference_date:
        raise ValueError("programme IDs not proven stable across reference dates")
    if previous.collected_utc >= current.collected_utc:
        raise ValueError("new programme edition must be collected strictly later")

    before, unidentified_old = _by_programme(previous)
    after, unidentified_new = _by_programme(current)
    changes: list[ProgrammeChange] = []
    if unidentified_old or unidentified_new:
        # Even when the number is unchanged, unidentified rows are not
        # reconciled or implicitly counted as the same shipment.
        changes.append(ProgrammeChange(
            None, "unidentified_rows_not_reconciled",
            unidentified_old, unidentified_new,
        ))

    for programme in sorted(before.keys() | after.keys()):
        old, new = before.get(programme), after.get(programme)
        if old is None:
            changes.append(ProgrammeChange(
                programme, "new_programme_reference_not_new_vessel",
                None, len(new),
            ))
        elif new is None:
            changes.append(ProgrammeChange(
                programme, "programme_not_listed_in_later_edition_unconfirmed",
                len(old), None,
            ))
        else:
            changes.extend(_compare_programme_group(programme, old, new))
    return tuple(changes)


def compare_pdf_programme_asof(
    ledger: PdfProgrammeLedger, *, port_id: str, source_id: str,
    series: str | None, earlier_as_of: str | datetime,
    later_as_of: str | datetime, read_authorized: bool = False,
) -> ProgrammeRevision:
    """Read only available published editions at both historical cutoffs.

    An unavailable edition produces DATA_GATED and null deltas, never zero.
    """
    if not read_authorized:
        raise PermissionError("PDF programme revision history reading not authorized")
    earlier = _aware_utc(earlier_as_of, "earlier_as_of")
    later = _aware_utc(later_as_of, "later_as_of")
    if earlier >= later:
        raise ValueError("later_as_of must strictly follow earlier_as_of")
    old_result = ledger.select_asof(
        port_id=port_id, source_id=source_id, series=series,
        as_of=earlier, read_authorized=read_authorized,
    )
    new_result = ledger.select_asof(
        port_id=port_id, source_id=source_id, series=series,
        as_of=later, read_authorized=read_authorized,
    )
    old, new = old_result.edition, new_result.edition
    if old is None or new is None:
        return ProgrammeRevision(
            "DATA_GATED", earlier.isoformat(), later.isoformat(),
            port_id, source_id, series, old, new, None,
        )
    if old.collected_utc == new.collected_utc:
        # Same known revision at two cutoffs: no new change. No evidence of
        # actual movement, even if ETA date has now passed.
        changes: tuple[ProgrammeChange, ...] = ()
        status = "SAME_PROGRAMME_EDITION"
    else:
        changes = compare_pdf_programme_editions(old, new)
        status = "PROGRAMME_REVISION_ONLY_NOT_PHYSICAL_OPERATION"
    return ProgrammeRevision(
        status, earlier.isoformat(), later.isoformat(),
        port_id, source_id, series, old, new, changes,
    )
