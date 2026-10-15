"""Prepare external records and orchestrate a supplied provider response.

ingest() does not call the network and does not write. A confirmed endpoint
and response schema are not registered. ingest_response() validates a response
the caller already has and writes only when that caller explicitly enables
persistence. It does not represent live KRERA collection.
"""

from __future__ import annotations

from dataclasses import dataclass

from external_data.client import ExternalRealEstateAPIClient
from external_data.config import PROVIDER_NOT_CONFIGURED_MESSAGE
from external_data.mapper import map_record
from external_data.models import PreparedRecord, StandardRecord
from external_data.normalizer import collapse_whitespace, normalize_record, resolve_micro_market
from external_data.validator import validate_record

_SYNTHETIC_PREFIX = "kanakapura comparable project"
_UPDATE_ORIGINS = {"external"}


@dataclass
class ExistingProject:
    """In-memory identity of a row the future matcher might see."""

    project_name: str
    developer: str | None = None
    micro_market: str | None = None
    project_phase: str | None = None
    rera_number: str | None = None
    origin: str = "external"


def prepare_record(record: StandardRecord) -> PreparedRecord:
    """Validate, normalize, and map one caller-supplied record. Does not persist it."""
    normalized, normalization_issues = normalize_record(record)
    issues = validate_record(record, normalized, normalization_issues)
    if issues:
        return PreparedRecord(accepted=False, issues=issues, record=normalized, mapping=None)
    return PreparedRecord(
        accepted=True,
        issues=[],
        record=normalized,
        mapping=map_record(normalized),
    )


def decide_write(incoming: StandardRecord, existing: list[ExistingProject]) -> dict[str, str]:
    """Choose insert, update, or skip without touching the database.

    RERA number wins when both sides have one. Otherwise the match is
    normalized project name, developer, canonical micro-market, and phase.
    Seed, research, and synthetic Kanakapura comparable rows are never updated.
    """
    normalized, _issues = normalize_record(incoming)
    incoming_key = _identity(
        normalized.project.project_name,
        normalized.project.developer,
        normalized.project.micro_market,
        normalized.project.project_phase,
        normalized.project.rera_number,
    )

    for item in existing:
        if not _rera_equal(incoming_key["rera"], item.rera_number):
            continue
        return _decision(item, "Matched on RERA number.")

    for item in existing:
        if not _fallback_equal(incoming_key, item):
            continue
        return _decision(item, "Matched on project name, developer, micro-market, and phase.")

    return {"action": "insert", "reason": "No matching external project."}


class ExternalDataIngestion:
    def __init__(self, client: ExternalRealEstateAPIClient | None = None, adapter=None) -> None:
        self.client = client or ExternalRealEstateAPIClient()
        if adapter is None:
            from external_data.adapter import UnconfirmedProviderAdapter

            adapter = UnconfirmedProviderAdapter()
        self.adapter = adapter

    def ingest(self) -> dict[str, object]:
        """Refuse live collection. No endpoint or response schema is confirmed."""
        missing = ["confirmed endpoint path", "confirmed provider response schema"]
        if not self.client.config.base_url:
            missing.insert(0, "EXTERNAL_REAL_ESTATE_API_URL")
        return {
            "status": "not_configured",
            "message": PROVIDER_NOT_CONFIGURED_MESSAGE,
            "detail": (
                "Live collection is not enabled. Missing: "
                + ", ".join(missing)
                + ". A test field map cannot enable live collection."
            ),
            "missing": missing,
            "persisted": False,
            "rows_written": 0,
            "rows_inserted": 0,
            "rows_updated": 0,
            "rows_rejected": 0,
            "live_collection": False,
            "data_origin": "not_collected",
        }

    def ingest_response(
        self,
        response: dict,
        *,
        field_map,
        db=None,
        persist: bool = False,
    ) -> dict[str, object]:
        """Validate a caller-supplied client result. Does not perform HTTP.

        ``field_map`` is required and is not a KRERA schema. Accepted records
        are stored only when ``persist`` is true and ``db`` is given. Invalid
        records are not written. ``projects`` is not modified.
        """
        from external_data.adapter import MappedProviderAdapter

        if not isinstance(response, dict) or response.get("status") != "ok":
            return _response_failure(response)
        try:
            adapter = MappedProviderAdapter(field_map)
        except ValueError as exc:
            return _pipeline_result(
                "not_configured",
                str(exc),
                data_origin="supplied_response",
            )

        parsed = adapter.parse(response.get("data"))
        if parsed.status == "malformed":
            return _pipeline_result(
                "malformed",
                parsed.message,
                issues=parsed.issues,
                data_origin="supplied_response",
            )
        if parsed.status == "empty":
            return _pipeline_result(
                "empty",
                parsed.message,
                data_origin="supplied_response",
            )

        rejected: list[dict[str, object]] = []
        accepted: list[PreparedRecord] = []
        for index, record in enumerate(parsed.records):
            prepared = self.prepare(record)
            if prepared.accepted:
                accepted.append(prepared)
            else:
                rejected.append(
                    {
                        "index": index,
                        "project_name": prepared.record.project.project_name,
                        "issues": [issue.message for issue in prepared.issues],
                    }
                )
        structural = [
            {"index": issue.index, "issues": [issue.message]}
            for issue in parsed.issues
        ]
        rejected.extend(structural)

        if persist and db is None:
            return _pipeline_result(
                "not_persisted",
                "Persistence was requested but no database was provided.",
                rows_rejected=len(rejected),
                rejected=rejected,
                data_origin="supplied_response",
            )
        if not persist:
            if accepted and not rejected:
                status = "validated"
                message = "Records passed validation and were not stored."
            elif accepted:
                status = "partial"
                message = "Some records failed validation. Nothing was stored."
            else:
                status = "rejected"
                message = "No records passed validation. Nothing was stored."
            return _pipeline_result(
                status,
                message,
                rows_rejected=len(rejected),
                rejected=rejected,
                data_origin="supplied_response",
            )

        inserted = 0
        updated = 0
        for prepared in accepted:
            stored = self.persist(db, prepared.record)
            if stored.status != "stored":
                rejected.append(
                    {
                        "index": None,
                        "project_name": prepared.record.project.project_name,
                        "issues": list(stored.issues),
                    }
                )
                continue
            if stored.action == "updated":
                updated += 1
            else:
                inserted += 1

        written = inserted + updated
        if written and rejected:
            status = "partial"
            message = (
                f"Stored {written} valid external record(s). "
                f"{len(rejected)} record(s) were rejected. Live provider collection did not run."
            )
        elif written and updated:
            status = "stored"
            message = (
                f"Stored {inserted} inserted and {updated} updated external record(s). "
                "Live provider collection did not run."
            )
        elif written:
            status = "stored"
            message = (
                f"Stored {inserted} external record(s). Live provider collection did not run."
            )
        else:
            status = "rejected"
            message = "No records were stored."
        return _pipeline_result(
            status,
            message,
            persisted=written > 0,
            rows_written=written,
            rows_inserted=inserted,
            rows_updated=updated,
            rows_rejected=len(rejected),
            rejected=rejected,
            data_origin="supplied_response",
        )

    def prepare(self, record: StandardRecord) -> PreparedRecord:
        return prepare_record(record)

    def persist(self, db, record: StandardRecord, raw_payload: dict | None = None):
        """Store one already-built record. Does not fetch a provider."""
        from external_data.storage import store_external_record

        return store_external_record(db, record, raw_payload=raw_payload)


def _response_failure(response: object) -> dict[str, object]:
    reason = None
    detail = None
    message = "External real-estate data unavailable."
    if isinstance(response, dict):
        reason = response.get("reason")
        detail = response.get("detail")
        supplied = response.get("message")
        if supplied:
            message = str(supplied)
    else:
        message = "Provider response was not a client result."
    return _pipeline_result(
        "request_failed",
        message,
        reason=reason,
        detail=detail if isinstance(detail, str) else None,
        data_origin="supplied_response",
    )


def _pipeline_result(
    status: str,
    message: str,
    *,
    persisted: bool = False,
    rows_written: int = 0,
    rows_inserted: int = 0,
    rows_updated: int = 0,
    rows_rejected: int = 0,
    rejected: list | None = None,
    issues: list | None = None,
    reason: str | None = None,
    detail: str | None = None,
    data_origin: str,
) -> dict[str, object]:
    body: dict[str, object] = {
        "status": status,
        "message": message,
        "persisted": persisted,
        "rows_written": rows_written,
        "rows_inserted": rows_inserted,
        "rows_updated": rows_updated,
        "rows_rejected": rows_rejected,
        "live_collection": False,
        "data_origin": data_origin,
    }
    if rejected is not None:
        body["rejected"] = rejected
    if issues is not None:
        body["issues"] = [{"index": issue.index, "message": issue.message} for issue in issues]
    if reason is not None:
        body["reason"] = reason
    if detail is not None:
        body["detail"] = detail
    return body


def _decision(item: ExistingProject, matched_reason: str) -> dict[str, str]:
    protected = _protected_reason(item)
    if protected is not None:
        return {"action": "skip_protected", "reason": protected}
    return {"action": "update", "reason": matched_reason}


def _protected_reason(item: ExistingProject) -> str | None:
    name = collapse_whitespace(item.project_name or "").casefold()
    if item.origin == "synthetic" or name.startswith(_SYNTHETIC_PREFIX):
        return "Synthetic Kanakapura comparable project is not overwritten automatically."
    if item.origin not in _UPDATE_ORIGINS:
        return "Seed or research row is not overwritten automatically."
    return None


def _identity(
    project_name: str | None,
    developer: str | None,
    micro_market: str | None,
    project_phase: str | None,
    rera_number: str | None,
) -> dict[str, str | None]:
    return {
        "name": _fold(project_name),
        "developer": _fold(developer),
        "market": resolve_micro_market(micro_market) or _fold(micro_market),
        "phase": _fold(project_phase),
        "rera": _fold(rera_number),
    }


def _fallback_equal(incoming: dict[str, str | None], item: ExistingProject) -> bool:
    if not incoming["name"] or not incoming["developer"] or not incoming["market"]:
        return False
    other = _identity(item.project_name, item.developer, item.micro_market, item.project_phase, item.rera_number)
    if not other["name"] or not other["developer"] or not other["market"]:
        return False
    return (
        incoming["name"] == other["name"]
        and incoming["developer"] == other["developer"]
        and incoming["market"] == other["market"]
        and incoming["phase"] == other["phase"]
    )


def _rera_equal(incoming: str | None, stored: str | None) -> bool:
    other = _fold(stored)
    return bool(incoming and other and incoming == other)


def _fold(value: str | None) -> str | None:
    text = collapse_whitespace(value) if value else ""
    return text.casefold() or None
