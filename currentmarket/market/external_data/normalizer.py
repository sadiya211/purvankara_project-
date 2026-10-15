"""Normalization rules from the Phase 2 data contract.

Unrecognized micro-markets are not stored and are not created.
Only explicit aliases are accepted. Similar spellings are not guessed.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import date, datetime

from external_data.models import (
    MarketData,
    ProjectData,
    ProvenanceData,
    RentData,
    StandardRecord,
    ValidationIssue,
)

MICRO_MARKET_NOT_RECOGNIZED = "Micro-market not recognized"
SQFT_PER_SQM = 10.76391041671
CANONICAL_PRICE_UNIT = "INR/sq.ft"

# Names seeded by backend/db/ingest.py. Do not add a 26th corridor here.
CANONICAL_MICRO_MARKETS: dict[str, str] = {
    "MM01": "CBD Lavelle-MG-Richmond",
    "MM02": "Off-Central Frazer-Benson-Richards-Dollars Colony",
    "MM03": "Indiranagar-Richmond Town-Vasanth Nagar",
    "MM04": "Whitefield",
    "MM05": "Old Airport Road-Marathahalli-KR Puram",
    "MM06": "Old Madras Road-Budigere Cross",
    "MM07": "Hoskote",
    "MM08": "Sarjapur Road",
    "MM09": "ORR Marathahalli-Sarjapur-HSR",
    "MM10": "Hosur Road-Begur",
    "MM11": "Koramangala",
    "MM12": "JP Nagar-Jayanagar-Banashankari",
    "MM13": "Bannerghatta Road",
    "MM14": "Kanakapura Road",
    "MM15": "BTM Layout",
    "MM16": "Electronic City",
    "MM17": "Attibele-Chandapur",
    "MM18": "Hebbal-Bellary Road",
    "MM19": "Thanisandra-Hennur",
    "MM20": "Jakkur-Yelahanka",
    "MM21": "Devanahalli-Airport Road",
    "MM22": "Bagalur",
    "MM23": "Malleshwaram-Rajajinagar-Yeshwanthpur",
    "MM24": "Tumkur Road-Vijayanagar",
    "MM25": "Mysore Road-Uttarahalli-Magadi Road",
}

# Exact aliases only, after whitespace collapse and case folding.
# "kanakpura" is the one misspelling named in the Phase 2 contract.
MICRO_MARKET_ALIASES: dict[str, str] = {
    "bagaluru": "Bagalur",
    "bagalur": "Bagalur",
    "kanakapura": "Kanakapura Road",
    "kanakpura": "Kanakapura Road",
    "devanahalli": "Devanahalli-Airport Road",
    "outer ring road": "ORR Marathahalli-Sarjapur-HSR",
    "marathahalli": "ORR Marathahalli-Sarjapur-HSR",
    "panathur": "ORR Marathahalli-Sarjapur-HSR",
    "hsr": "ORR Marathahalli-Sarjapur-HSR",
    "orr": "ORR Marathahalli-Sarjapur-HSR",
    "sarjapur": "Sarjapur Road",
    "hennur": "Thanisandra-Hennur",
    "thanisandra": "Thanisandra-Hennur",
    "budigere": "Old Madras Road-Budigere Cross",
    "omr": "Old Madras Road-Budigere Cross",
    "old madras road": "Old Madras Road-Budigere Cross",
    "lavelle": "CBD Lavelle-MG-Richmond",
    "mg road": "CBD Lavelle-MG-Richmond",
    "cbd": "CBD Lavelle-MG-Richmond",
    "yelahanka": "Jakkur-Yelahanka",
    "jakkur": "Jakkur-Yelahanka",
    "hebbal": "Hebbal-Bellary Road",
    "bellary road": "Hebbal-Bellary Road",
    "kengeri": "Mysore Road-Uttarahalli-Magadi Road",
    "mysore road": "Mysore Road-Uttarahalli-Magadi Road",
    "electronic city": "Electronic City",
    "koramangala": "Koramangala",
    "indiranagar": "Indiranagar-Richmond Town-Vasanth Nagar",
    "richmond town": "Indiranagar-Richmond Town-Vasanth Nagar",
    "vasanth nagar": "Indiranagar-Richmond Town-Vasanth Nagar",
    "hosur road": "Hosur Road-Begur",
    "begur": "Hosur Road-Begur",
    "bommanahalli": "Hosur Road-Begur",
    "attibele": "Attibele-Chandapur",
    "chandapur": "Attibele-Chandapur",
    "chandapura": "Attibele-Chandapur",
    "btm": "BTM Layout",
    "bannerghatta": "Bannerghatta Road",
    "jp nagar": "JP Nagar-Jayanagar-Banashankari",
    "jayanagar": "JP Nagar-Jayanagar-Banashankari",
    "banashankari": "JP Nagar-Jayanagar-Banashankari",
    "malleshwaram": "Malleshwaram-Rajajinagar-Yeshwanthpur",
    "rajajinagar": "Malleshwaram-Rajajinagar-Yeshwanthpur",
    "yeshwanthpur": "Malleshwaram-Rajajinagar-Yeshwanthpur",
    "frazer town": "Off-Central Frazer-Benson-Richards-Dollars Colony",
    "dollars colony": "Off-Central Frazer-Benson-Richards-Dollars Colony",
    "old airport road": "Old Airport Road-Marathahalli-KR Puram",
    "kr puram": "Old Airport Road-Marathahalli-KR Puram",
    "tumkur road": "Tumkur Road-Vijayanagar",
    "vijayanagar": "Tumkur Road-Vijayanagar",
    "hoskote": "Hoskote",
    "whitefield": "Whitefield",
}

CITY_ALIASES = {
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "bengaluru urban": "Bengaluru",
}

PROPERTY_TYPES = {
    "residential": "Residential",
    "apartment": "Residential",
    "flat": "Residential",
    "residential apartment": "Residential",
    "villa": "Villa",
    "villament": "Villa",
    "plot": "Plot",
    "plotted": "Plot",
}

PROJECT_STATUSES = {
    "ongoing": "ongoing",
    "proposed": "proposed",
    "newly launched": "newly_launched",
    "newly_launched": "newly_launched",
    "completed": "completed",
    "unknown": "unknown",
}

_CANONICAL_BY_FOLD = {name.casefold(): name for name in CANONICAL_MICRO_MARKETS.values()}
_SQFT_UNITS = {
    "inr/sq.ft",
    "inr/sqft",
    "inr per sq.ft",
    "inr per sqft",
    "sq.ft",
    "sqft",
    "per sq.ft",
    "per sqft",
}
_SQM_UNITS = {
    "inr/sq.m",
    "inr/sqm",
    "inr per sq.m",
    "inr per sqm",
    "sq.m",
    "sqm",
    "per sq.m",
    "per sqm",
}
_INR_WORDS = {"inr", "rs", "rs.", "rupee", "rupees", "₹"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BHK_RE = re.compile(r"^(\d+(?:\.5)?)BHK$")
_BHK_RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)\s*BHK$", re.IGNORECASE)


def collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def resolve_micro_market(value: str | None) -> str | None:
    """Return the canonical corridor name, or None when it is not an explicit match."""
    text = _clean(value)
    if text is None:
        return None
    folded = text.casefold()
    if folded in _CANONICAL_BY_FOLD:
        return _CANONICAL_BY_FOLD[folded]
    return MICRO_MARKET_ALIASES.get(folded)


def normalize_record(record: StandardRecord) -> tuple[StandardRecord, list[ValidationIssue]]:
    """Return a new record. The caller's instance is left unchanged."""
    issues: list[ValidationIssue] = []
    project, project_issues = _normalize_project(record.project)
    issues.extend(project_issues)
    rent, rent_issues = _normalize_rent(record.rent)
    issues.extend(rent_issues)
    market, market_issues = _normalize_market(record.market)
    issues.extend(market_issues)
    provenance = _normalize_provenance(record.provenance)
    return StandardRecord(project=project, rent=rent, market=market, provenance=provenance), issues


def _normalize_project(project: ProjectData) -> tuple[ProjectData, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    data = ProjectData(**asdict(project))

    data.project_name = _clean(data.project_name)
    data.developer = _clean(data.developer)
    data.location = _clean(data.location)
    data.project_phase = _clean(data.project_phase)
    data.price_type = _clean(data.price_type)
    data.rera_number = _clean(data.rera_number)

    data.city, city_issue = _normalize_city(data.city)
    if city_issue:
        issues.append(city_issue)

    raw_market = data.micro_market
    resolved = resolve_micro_market(raw_market)
    if _clean(raw_market) is not None and resolved is None:
        issues.append(ValidationIssue("micro_market", MICRO_MARKET_NOT_RECOGNIZED))
    data.micro_market = resolved

    data.property_type, type_issue = _normalize_choice(
        data.property_type, PROPERTY_TYPES, "property_type", "Property type is not recognized."
    )
    if type_issue:
        issues.append(type_issue)

    data.property_segment, segment_issue = _normalize_segment(data.property_segment)
    if segment_issue:
        issues.append(segment_issue)

    data.bhk, bhk_issue = _normalize_bhk(data.bhk)
    if bhk_issue:
        issues.append(bhk_issue)

    data.project_status, status_issue = _normalize_choice(
        data.project_status, PROJECT_STATUSES, "project_status", "Project status is not recognized."
    )
    if status_issue:
        issues.append(status_issue)

    data.units, units_issue = _optional_int(data.units, "units")
    if units_issue:
        issues.append(units_issue)
    data.absorbed_units, absorbed_issue = _optional_int(data.absorbed_units, "absorbed_units")
    if absorbed_issue:
        issues.append(absorbed_issue)
    data.available_units, available_issue = _optional_int(data.available_units, "available_units")
    if available_issue:
        issues.append(available_issue)

    data.percentage_sold, percent_issue = _optional_percent(data.percentage_sold, "percentage_sold")
    if percent_issue:
        issues.append(percent_issue)

    data.sale_price_per_sqft, price_issue = _optional_price(data.sale_price_per_sqft, "sale_price_per_sqft")
    if price_issue:
        issues.append(price_issue)

    data.rera_registered, rera_issue = _normalize_bool(data.rera_registered, "rera_registered")
    if rera_issue:
        issues.append(rera_issue)

    for attr in ("launch_date", "expected_launch_date", "completion_date"):
        parsed, date_issue = _normalize_date(getattr(data, attr), attr)
        setattr(data, attr, parsed)
        if date_issue:
            issues.append(date_issue)

    data.latitude, data.longitude, coord_issue = _normalize_coordinates(data.latitude, data.longitude)
    if coord_issue:
        issues.append(coord_issue)

    data.currency = _normalize_currency(data.currency)
    data.sale_price_per_sqft, data.price_unit = _normalize_sale_unit(
        data.sale_price_per_sqft,
        data.price_unit,
        data.currency,
    )
    return data, issues


def _normalize_rent(rent: RentData) -> tuple[RentData, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    data = RentData(**asdict(rent))
    data.rental_price, price_issue = _optional_price(data.rental_price, "rental_price")
    if price_issue:
        issues.append(price_issue)
    data.rental_price_per_sqft, unit_issue = _optional_price(
        data.rental_price_per_sqft, "rental_price_per_sqft"
    )
    if unit_issue:
        issues.append(unit_issue)
    return data, issues


def _normalize_market(market: MarketData) -> tuple[MarketData, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    data = MarketData(**asdict(market))
    for attr in (
        "corridor_launched_units",
        "corridor_absorbed_units",
        "corridor_available_units",
        "corridor_project_count",
    ):
        parsed, issue = _optional_int(getattr(data, attr), attr)
        setattr(data, attr, parsed)
        if issue:
            issues.append(issue)
    data.corridor_sale_price_per_sqft, price_issue = _optional_price(
        data.corridor_sale_price_per_sqft, "corridor_sale_price_per_sqft"
    )
    if price_issue:
        issues.append(price_issue)
    data.corridor_percentage_sold, percent_issue = _optional_percent(
        data.corridor_percentage_sold, "corridor_percentage_sold"
    )
    if percent_issue:
        issues.append(percent_issue)
    return data, issues


def _normalize_provenance(provenance: ProvenanceData) -> ProvenanceData:
    data = ProvenanceData(**asdict(provenance))
    for attr in ("source_system", "source_api", "source_record_id", "fetched_at", "source_updated_at"):
        setattr(data, attr, _clean(getattr(data, attr)))
    return data


def _normalize_city(value: str | None) -> tuple[str | None, ValidationIssue | None]:
    text = _clean(value)
    if text is None:
        return None, None
    canonical = CITY_ALIASES.get(text.casefold())
    if canonical is None:
        return None, ValidationIssue("city", "City is outside the Bengaluru scope.")
    return canonical, None


def _normalize_choice(
    value: str | None,
    mapping: dict[str, str],
    field: str,
    message: str,
) -> tuple[str | None, ValidationIssue | None]:
    text = _clean(value)
    if text is None:
        return None, None
    canonical = mapping.get(text.casefold())
    if canonical is None:
        return None, ValidationIssue(field, message)
    return canonical, None


def _normalize_segment(value: str | None) -> tuple[str | None, ValidationIssue | None]:
    text = _clean(value)
    if text is None:
        return None, None
    folded = text.casefold()
    if "lux" in folded or "ultra" in folded:
        return "Luxury", None
    if "prem" in folded:
        return "Premium", None
    if folded in {"mid", "mid segment"}:
        return "Mid", None
    return None, ValidationIssue("property_segment", "Property segment is not recognized.")


def _normalize_bhk(value: str | None) -> tuple[str | None, ValidationIssue | None]:
    text = _clean(value)
    if text is None:
        return None, None
    compact = text.upper().replace(" ", "")
    range_match = _BHK_RANGE_RE.fullmatch(text) or _BHK_RANGE_RE.fullmatch(compact)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)} BHK", None
    single = _BHK_RE.fullmatch(compact)
    if single:
        return f"{single.group(1)}BHK", None
    return None, ValidationIssue("bhk", "BHK format is not recognized.")


def _normalize_currency(value: str | None) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    if text.casefold() in _INR_WORDS or text == "₹":
        return "INR"
    return text.upper()


def _normalize_sale_unit(
    price: float | None,
    unit: str | None,
    currency: str | None,
) -> tuple[float | None, str | None]:
    text = _clean(unit)
    if text is None:
        return price, None
    folded = text.casefold()
    if folded in _SQFT_UNITS:
        if currency not in (None, "INR"):
            return price, None
        return price, CANONICAL_PRICE_UNIT
    if folded in _SQM_UNITS:
        if price is not None and currency == "INR":
            return price / SQFT_PER_SQM, CANONICAL_PRICE_UNIT
        return price, None
    return price, text


def _normalize_date(value: object, field: str) -> tuple[str | None, ValidationIssue | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        return value.date().isoformat(), None
    if isinstance(value, date):
        return value.isoformat(), None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None, None
        if _DATE_RE.fullmatch(text) is None:
            return None, ValidationIssue(field, "Invalid date.")
        try:
            date.fromisoformat(text)
        except ValueError:
            return None, ValidationIssue(field, "Invalid date.")
        return text, None
    return None, ValidationIssue(field, "Invalid date.")


def _normalize_coordinates(
    latitude: object,
    longitude: object,
) -> tuple[float | None, float | None, ValidationIssue | None]:
    if _missing_number(latitude) and _missing_number(longitude):
        return None, None, None
    lat = _float_or_none(latitude)
    lon = _float_or_none(longitude)
    if lat is None or lon is None:
        return None, None, ValidationIssue("coordinates", "Invalid coordinates.")
    if not (12.5 <= lat <= 13.6 and 77.1 <= lon <= 78.1):
        return None, None, ValidationIssue("coordinates", "Invalid coordinates.")
    return lat, lon, None


def _normalize_bool(value: object, field: str) -> tuple[bool | None, ValidationIssue | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return value, None
    if isinstance(value, str):
        text = value.strip().casefold()
        if text == "":
            return None, None
        if text in {"1", "true", "yes", "y"}:
            return True, None
        if text in {"0", "false", "no", "n"}:
            return False, None
        return None, ValidationIssue(field, "RERA registration flag is not recognized.")
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 1:
            return True, None
        if value == 0:
            return False, None
    return None, ValidationIssue(field, "RERA registration flag is not recognized.")


def _optional_int(value: object, field: str) -> tuple[int | None, ValidationIssue | None]:
    if _missing_number(value):
        return None, None
    if isinstance(value, bool):
        return None, ValidationIssue(field, "Invalid number.")
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"\d+", text):
            return None, ValidationIssue(field, "Invalid number.")
        value = int(text)
    elif isinstance(value, float):
        if not value.is_integer():
            return None, ValidationIssue(field, "Invalid number.")
        value = int(value)
    if not isinstance(value, int) or value < 0:
        return None, ValidationIssue(field, "Invalid number.")
    return value, None


def _optional_price(value: object, field: str) -> tuple[float | None, ValidationIssue | None]:
    if _missing_number(value):
        return None, None
    number = _float_or_none(value)
    if number is None or number < 0:
        return None, ValidationIssue(field, "Invalid number.")
    return number, None


def _optional_percent(value: object, field: str) -> tuple[float | None, ValidationIssue | None]:
    if _missing_number(value):
        return None, None
    number = _float_or_none(value)
    if number is None or number < 0 or number > 100:
        return None, ValidationIssue(field, "Invalid number.")
    return number, None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if number != number:  # NaN
        return None
    return number


def _missing_number(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = collapse_whitespace(str(value))
    return text or None
