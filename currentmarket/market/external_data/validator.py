"""Validation gate for a standardized external record.

Missing values stay empty. This module does not substitute zero, a status,
a RERA flag, or a coordinate.
"""

from __future__ import annotations

from external_data.models import StandardRecord, ValidationIssue
from external_data.normalizer import CANONICAL_PRICE_UNIT

CURRENCY_REQUIRED = "Currency must be known before storing sale price."
PRICE_UNIT_INVALID = "Sale price unit is not INR per sq.ft."


def validate_record(
    original: StandardRecord,
    normalized: StandardRecord,
    normalization_issues: list[ValidationIssue],
) -> list[ValidationIssue]:
    issues = list(normalization_issues)
    project = normalized.project

    if not project.project_name:
        issues.append(ValidationIssue("project_name", "Project name is required."))

    if not _provided(original.project.city) and not _has_field(issues, "city"):
        issues.append(ValidationIssue("city", "City is required."))

    if not _provided(original.project.micro_market) and not _has_field(issues, "micro_market"):
        issues.append(ValidationIssue("micro_market", "Micro-market is required."))

    if project.sale_price_per_sqft is not None:
        if project.currency != "INR":
            message = CURRENCY_REQUIRED if project.currency is None else "Currency must be INR before storing sale price."
            issues.append(ValidationIssue("currency", message))
        if project.price_unit != CANONICAL_PRICE_UNIT:
            issues.append(ValidationIssue("price_unit", PRICE_UNIT_INVALID))

    return issues


def _has_field(issues: list[ValidationIssue], field: str) -> bool:
    return any(issue.field == field for issue in issues)


def _provided(value: object) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())
