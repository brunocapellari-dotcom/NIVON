"""Bridge from NIVON officially acquired line-up document to Maritime engines.

Offline, no I/O. Never infer a precise ETA from a date-only publication.
An authority's scheduled maneuver never becomes a performed port operation.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any

from nivon.portos_automaticos import ContratoPorto, processar_documento_porto, ErroPorto
from nivon._agrolog_portos_html import parse_official_lineup_html
from nivon._agrolog_portos_pdf import (
    extract_pdf_tables, parse_itaqui_tables, parse_paranagua_tables,
)
from nivon.maritime.shipping_reconciliation import LineupCall

# The pilot authorities publish local operational timestamps. Time zones must be
# versioned per source; a fixed BR offset is explicitly a pilot-only contract.
_PORT_ZONE = {
    "SANTOS": timezone(timedelta(hours=-3)),
    "SANTAREM": timezone(timedelta(hours=-3)),
    "BARCARENA_VILA_DO_CONDE": timezone(timedelta(hours=-3)),
    "ITAQUI": timezone(timedelta(hours=-3)),
    "PARANAGUA": timezone(timedelta(hours=-3)),
}


@dataclass(frozen=True)
class PdfProgramReference:
    """Published PDF programme reference, not verified DUV or realized visit."""
    source_row: int
    vessel_name: str
    programme_number: str | None
    explicit_duv: str | None
    eta_text: str | None
    eta_fully_declared: bool
    product: str | None
    planned_volume_t: float | None
    evidence_class: str = "PROGRAMME_REFERENCE_NOT_PORT_CALL"


@dataclass(frozen=True)
class LineupBridgeResult:
    port_id: str
    source_id: str
    source_url: str
    document_sha256: str
    collected_at: str
    candidates: tuple[LineupCall, ...]
    excluded: tuple[dict[str, str], ...]
    source_rows: int
    state: str = "SHADOW_NOT_HOMOLOGATED"
    publication_allowed: bool = False
    realized_cargo_claimed: bool = False
    pdf_program_rows: tuple[PdfProgramReference, ...] = ()

    def summary(self) -> dict[str, Any]:
        return {
            "port_id": self.port_id,
            "source_id": self.source_id,
            "source_sha256": self.document_sha256,
            "collected_at": self.collected_at,
            "total_programmed_rows": self.source_rows,
            "usable_eta_calls": len(self.candidates),
            "excluded_without_safe_eta_or_call_id": len(self.excluded),
            "state": self.state,
            "publication_allowed": False,
            "excluded": self.excluded,
            "pdf_program_reference_rows": len(self.pdf_program_rows),
            "programme_references_are_verified_port_calls": False,
        }


def _instant_utc(raw: str, local_tz: timezone, *, collected_at: datetime) -> datetime:
    """Only full date + clock time, with explicit source-local zone where absent."""
    value = str(raw).strip()
    # A date-only ETA does not establish hour/minutes: fail closed.
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("eta_date_only")
    try:
        if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}(?::\d{2})?", value):
            parsed = datetime.strptime(value, "%d/%m/%Y %H:%M:%S" if value.count(":") == 2 else "%d/%m/%Y %H:%M")
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("eta_format_unsupported") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    result = parsed.astimezone(timezone.utc)
    # Outliers/future years may signal layout or date parsing problems. Short
    # historical delay is allowed, but implausible distant ETA requires review.
    if result < collected_at - timedelta(days=90) or result > collected_at + timedelta(days=180):
        raise ValueError("eta_outside_authority_window")
    return result


def bridge_official_html_document(*, contract: ContratoPorto, document: dict,
                                  captured_before: str | datetime | None = None) -> LineupBridgeResult:
    """Use the existing validated collector instead of building a competing scraper.

    Only preacquired bytes with a verified official source hash are accepted.
    A raw source row and official call ID must exist before making LineupCall.
    Missing ETA or DUV creates an explicit excluded row, not a fabricated event.
    """
    if not contract.modo.startswith("HTML"):
        raise ErroPorto("bridge HTML exige contrato HTML da autoridade")
    parsed = processar_documento_porto(contract, document)
    stamp = datetime.fromisoformat(parsed["capturado_em"].replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ErroPorto("timestamp sem timezone")
    stamp = stamp.astimezone(timezone.utc)
    if captured_before is not None:
        cutoff = captured_before if isinstance(captured_before, datetime) else datetime.fromisoformat(str(captured_before).replace("Z", "+00:00"))
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ErroPorto("cutoff sem timezone")
        if stamp > cutoff.astimezone(timezone.utc):
            raise ErroPorto("coleta posterior ao corte temporal")
    source_rows = parse_official_lineup_html(document["conteudo"].decode("utf-8-sig"), contract.modo)
    if len(source_rows) != len(parsed["registros"]):
        raise ErroPorto("parser divergente do coletor canônico")
    zone = _PORT_ZONE.get(contract.porto)
    if zone is None:
        raise ErroPorto("fuso do porto sem contrato")
    excluded: list[dict[str, str]] = []
    calls: list[LineupCall] = []
    seen: set[str] = set()
    for index, row in enumerate(source_rows, start=1):
        if row.get("status") not in {"PROGRAMMED", "ESPERADO"}:
            raise ErroPorto("evento físico não pode virar line-up")
        # APS uses DUV as individual call identifier. CDP may publish a WDT row id.
        # Ship name, IMO, date or line ordinal are not valid call identifiers.
        official_id = str(row.get("duv") or row.get("call_id") or "").strip()
        if not official_id or len(official_id) > 128:
            excluded.append({"row": str(index), "reason": "official_call_id_missing"})
            continue
        call_id = f"{contract.porto}:{contract.fonte.fonte_id}:{official_id}"
        if call_id in seen:
            excluded.append({"row": str(index), "reason": "duplicate_call_id"})
            continue
        seen.add(call_id)
        try:
            eta = _instant_utc(row.get("eta", ""), zone, collected_at=stamp)
        except ValueError as exc:
            excluded.append({"row": str(index), "reason": str(exc)})
            continue
        program = parsed["registros"][index - 1]
        if program.navio != row["navio"] or program.status != "PROGRAMADO":
            raise ErroPorto("discordância com programação normalizada")
        calls.append(LineupCall(
            call_id=call_id, port_id=contract.porto, vessel_name=program.navio,
            eta=eta.isoformat(), collected_at=stamp.isoformat(),
            terminal_id=row.get("terminal") or None,
            imo=program.imo, product=program.produto,
            planned_volume_t=program.toneladas_programadas,
            source_id=contract.fonte.fonte_id, lineup_status="PROGRAMMED",
        ))
    return LineupBridgeResult(
        port_id=contract.porto, source_id=contract.fonte.fonte_id,
        source_url=contract.fonte.url, document_sha256=parsed["documento_sha256"],
        collected_at=stamp.isoformat(), candidates=tuple(calls),
        excluded=tuple(excluded), source_rows=len(source_rows),
    )


def bridge_official_pdf_document(
    *, contract: ContratoPorto, document: dict,
    captured_before: str | datetime | None = None,
) -> LineupBridgeResult:
    """Parse an already acquired PDF without inventing a DUV or ETA clock.

    Reuses the original authorized collector for URL, bytes, SHA, MIME and
    rights checks. Then compares the PDF parsed rows to the collector's output.
    N. Prog (Paranagua) and IMO are NOT DUV/port-call identities; if the
    document does not expose an actual DUV, keep the row excluded and flag
    the edition as incomplete for vintage publication/homologation.

    PDF source layouts, local timezone contract and ID semantics remain
    unhomologated until independently reviewed against real official PDFs.
    """
    if not isinstance(contract, ContratoPorto) or contract.modo not in {"PDF_PARANAGUA", "PDF_ITAQUI"}:
        raise ErroPorto("bridge PDF requires registered Paranagua/Itaqui contract")
    payload = document.get("conteudo") if isinstance(document, dict) else None
    if not isinstance(payload, bytes) or not (0 < len(payload) <= 20_000_000):
        raise ErroPorto("PDF original missing or over 20MB offline limit")
    validated = processar_documento_porto(contract, document)
    stamp = datetime.fromisoformat(validated["capturado_em"].replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ErroPorto("PDF collection timestamp missing timezone")
    stamp = stamp.astimezone(timezone.utc)
    if captured_before is not None:
        cutoff = captured_before if isinstance(captured_before, datetime) else datetime.fromisoformat(
            str(captured_before).replace("Z", "+00:00")
        )
        if cutoff.tzinfo is None or cutoff.utcoffset() is None or stamp > cutoff.astimezone(timezone.utc):
            raise ErroPorto("PDF acquired after as-of cutoff or missing cutoff timezone")

    tables = extract_pdf_tables(payload)
    if contract.modo == "PDF_ITAQUI":
        source_rows = [
            row for row in parse_itaqui_tables(tables, reference_date=contract.data_referencia)
            if row["status"] == "ESPERADO"
        ]
    else:
        source_rows = parse_paranagua_tables(
            tables, reference_date=contract.data_referencia, series=contract.serie
        )

    scheduled = validated["registros"]
    if not source_rows or len(source_rows) != len(scheduled):
        raise ErroPorto("PDF source rows inconsistent with canonical collector")
    zone = _PORT_ZONE.get(contract.porto)
    if zone is None:
        raise ErroPorto("PDF port has no explicit pilot timezone")

    used: set[str] = set()
    candidates: list[LineupCall] = []
    excluded: list[dict[str, str]] = []
    programme_rows: list[PdfProgramReference] = []
    for index, (source, normalized) in enumerate(zip(source_rows, scheduled), 1):
        if (source.get("navio") != normalized.navio
                or source.get("duv", "").strip() != (normalized.duv or "")
                or source.get("carga") != (normalized.produto or "")
                or (source.get("imo") or None) != normalized.imo):
            raise ErroPorto("PDF parser disagrees with normalized collector")
        if source.get("status") not in {"PROGRAMMED", "ESPERADO"}:
            raise ErroPorto("PDF physical event cannot become lineup schedule")
        programme_number = (
            (str(source.get("call_id") or "").strip() or None)
            if contract.porto == "PARANAGUA" else None
        )
        programme_rows.append(PdfProgramReference(
            source_row=index,
            vessel_name=normalized.navio,
            programme_number=programme_number,
            explicit_duv=(source.get("duv") or "").strip() or None,
            eta_text=source.get("eta") or None,
            eta_fully_declared=bool(
                source.get("eta") and not source.get("eta_year_inferred", True)
            ),
            product=normalized.produto,
            planned_volume_t=normalized.toneladas_programadas,
        ))
        # The Paranagua parser call_id from N.PROG is a programme reference,
        # NEVER substitute it for explicit DUV without independent mapping.
        duv = (source.get("duv") or "").strip()
        if not duv or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", duv):
            excluded.append({"row": str(index), "reason": "explicit_duv_missing_or_invalid"})
            continue
        call_id = f"{contract.porto}:{contract.fonte.fonte_id}:{duv}"
        if call_id in used:
            excluded.append({"row": str(index), "reason": "duplicate_duv_requires_cargo_row_normalization"})
            continue
        used.add(call_id)
        if not source.get("eta"):
            excluded.append({"row": str(index), "reason": "precise_pdf_eta_missing_or_invalid"})
            continue
        # Source date must have contained day, month, four-digit year and clock;
        # a year computed from the PDF reference date is not a published ETA.
        if source.get("eta_year_inferred", True):
            excluded.append({"row": str(index), "reason": "pdf_eta_year_not_explicit"})
            continue
        try:
            eta = _instant_utc(source.get("eta", ""), zone, collected_at=stamp)
        except (ValueError, TypeError):
            excluded.append({"row": str(index), "reason": "precise_pdf_eta_missing_or_invalid"})
            continue
        # Programmed tonnage remains a declaration, not an operational event.
        candidates.append(LineupCall(
            call_id=call_id, port_id=contract.porto, source_id=contract.fonte.fonte_id,
            vessel_name=normalized.navio, imo=normalized.imo,
            eta=eta.isoformat(), collected_at=stamp.isoformat(),
            product=normalized.produto, planned_volume_t=normalized.toneladas_programadas,
            terminal_id=source.get("terminal") or None,
            lineup_status="PROGRAMMED",
        ))
    return LineupBridgeResult(
        port_id=contract.porto, source_id=contract.fonte.fonte_id,
        source_url=validated["fonte"], document_sha256=validated["documento_sha256"],
        collected_at=stamp.isoformat(), candidates=tuple(candidates),
        excluded=tuple(excluded), source_rows=len(source_rows),
        pdf_program_rows=tuple(programme_rows),
    )
