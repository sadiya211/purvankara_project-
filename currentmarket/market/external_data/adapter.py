"""Provider-response adapter boundary.

This module does not perform HTTP and does not contain a KRERA field map,
endpoint, or sample response. A caller supplies the confirmed keys. Until
that map exists, UnconfirmedProviderAdapter returns no records.

Parsing never writes a row. Validation stays in prepare_record().
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Protocol

from external_data.ingestion import prepare_record
from external_data.models import (
    MarketData,
    PreparedRecord,
    ProjectData,
    ProvenanceData,
    RentData,
    StandardRecord,
)

SCHEMA_NOT_CONFIRMED_MESSAGE = "Provider response schema is not confirmed."
_MALFORMED_PAYLOAD = "Provider response is not a JSON object or list."
_MISSING_RECORD_LIST = "Provider response has no list under the mapped record key."
_RECORD_LIST_TYPE = "Provider record list is not a list."
_EMPTY_MESSAGE = "Provider response contained no records."
_NOT_AN_OBJECT = "Record is not an object."

_GROUPS = {
    "project": ProjectData,
    "rent": RentData,
    "market": MarketData,
    "provenance": ProvenanceData,
}
_KNOWN_FIELDS = frozenset(
    f"{group}.{item.name}"
    for group, model in _GROUPS.items()
    for item in fields(model)
)


@dataclass(frozen=True)
class AdapterIssue:
    message: str
    index: int | None = None


@dataclass
class AdapterParseResult:
    status: str
    message: str
    records: list[StandardRecord]
    issues: list[AdapterIssue]


@dataclass(frozen=True)
class ProviderFieldMap:
    """Confirmed provider keys for StandardRecord attributes.

    ``fields`` maps an internal name such as ``project.project_name`` to the
    provider's key. ``record_key`` is the payload key that holds the list of
    record objects. When it is omitted, a JSON list is the record list and a
    JSON object is one record. This class does not name a KRERA key.
    """

    fields: dict[str, str]
    record_key: str | None = None


@dataclass
class AdaptedRecords:
    status: str
    message: str
    records: list[StandardRecord]
    prepared: list[PreparedRecord]
    issues: list[AdapterIssue]
    persisted: bool = False


class ProviderAdapter(Protocol):
    def parse(self, payload: Any) -> AdapterParseResult:
        """Turn one provider payload into candidate records. Do not persist."""


class UnconfirmedProviderAdapter:
    """Placeholder until the API owner supplies a response schema.

    The payload is not interpreted. No project name or other fact is read
    from it.
    """

    def parse(self, payload: Any) -> AdapterParseResult:
        return AdapterParseResult(
            status="schema_not_confirmed",
            message=SCHEMA_NOT_CONFIRMED_MESSAGE,
            records=[],
            issues=[],
        )


class MappedProviderAdapter:
    """Apply a caller-supplied field map. Missing keys stay missing."""

    def __init__(self, field_map: ProviderFieldMap) -> None:
        self.field_map = _checked_map(field_map)

    def parse(self, payload: Any) -> AdapterParseResult:
        found, problem = _record_objects(payload, self.field_map.record_key)
        if problem is not None:
            return AdapterParseResult(
                status="malformed",
                message=problem,
                records=[],
                issues=[AdapterIssue(problem)],
            )
        if not found:
            return AdapterParseResult(
                status="empty",
                message=_EMPTY_MESSAGE,
                records=[],
                issues=[],
            )

        records: list[StandardRecord] = []
        issues: list[AdapterIssue] = []
        for index, item in enumerate(found):
            if not isinstance(item, dict):
                issues.append(AdapterIssue(_NOT_AN_OBJECT, index=index))
                continue
            record, field_issues = _record_from_object(item, self.field_map.fields, index)
            records.append(record)
            issues.extend(field_issues)

        if not records:
            return AdapterParseResult(
                status="malformed",
                message=_NOT_AN_OBJECT,
                records=[],
                issues=issues,
            )
        return AdapterParseResult(status="ok", message="", records=records, issues=issues)


def adapt_provider_payload(payload: Any, adapter: ProviderAdapter) -> AdaptedRecords:
    """Parse and run each candidate through prepare_record(). Never persists."""
    parsed = adapter.parse(payload)
    prepared = [prepare_record(record) for record in parsed.records]
    return AdaptedRecords(
        status=parsed.status,
        message=parsed.message,
        records=parsed.records,
        prepared=prepared,
        issues=list(parsed.issues),
        persisted=False,
    )


def _checked_map(field_map: ProviderFieldMap) -> ProviderFieldMap:
    if not field_map.fields:
        raise ValueError("A provider field map needs at least one confirmed field.")
    unknown = sorted(name for name in field_map.fields if name not in _KNOWN_FIELDS)
    if unknown:
        raise ValueError("Unknown standard field: " + ", ".join(unknown))
    cleaned: dict[str, str] = {}
    for name, source_key in field_map.fields.items():
        key = str(source_key).strip() if source_key is not None else ""
        if not key:
            raise ValueError(f"Confirmed provider key for {name} is blank.")
        cleaned[name] = key
    record_key = field_map.record_key
    if record_key is not None:
        record_key = str(record_key).strip()
        if not record_key:
            raise ValueError("Confirmed record list key is blank.")
    return ProviderFieldMap(fields=cleaned, record_key=record_key)


def _record_objects(payload: Any, record_key: str | None) -> tuple[list[Any] | None, str | None]:
    if payload is None or not isinstance(payload, (dict, list)):
        return None, _MALFORMED_PAYLOAD
    if record_key is None:
        if isinstance(payload, list):
            return payload, None
        return [payload], None
    if not isinstance(payload, dict):
        return None, _MALFORMED_PAYLOAD
    if record_key not in payload or payload[record_key] is None:
        if record_key not in payload:
            return None, _MISSING_RECORD_LIST
        return [], None
    records = payload[record_key]
    if not isinstance(records, list):
        return None, _RECORD_LIST_TYPE
    return records, None


def _record_from_object(
    item: dict[str, Any],
    field_map: dict[str, str],
    index: int,
) -> tuple[StandardRecord, list[AdapterIssue]]:
    grouped: dict[str, dict[str, Any]] = {name: {} for name in _GROUPS}
    issues: list[AdapterIssue] = []
    for internal_name, source_key in field_map.items():
        if source_key not in item or item[source_key] is None:
            continue
        value = item[source_key]
        group, attr = internal_name.split(".", 1)
        if isinstance(value, (dict, list)):
            issues.append(
                AdapterIssue(
                    f"{internal_name} is not a single value and was left missing.",
                    index=index,
                )
            )
            continue
        grouped[group][attr] = value
    return (
        StandardRecord(
            project=ProjectData(**grouped["project"]),
            rent=RentData(**grouped["rent"]),
            market=MarketData(**grouped["market"]),
            provenance=ProvenanceData(**grouped["provenance"]),
        ),
        issues,
    )
