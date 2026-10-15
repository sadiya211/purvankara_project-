"""External ML preparation. In-memory records only. No training and no network."""

import hashlib
import json
from pathlib import Path

from ml.external_data.prepare import (
    CURRENT_MODEL_FEATURES,
    TARGET_FIELD,
    build_external_feature_rows,
    prepare_external_ml_records,
)
from ml.price.infer import predict_price_per_sqft

ROOT = Path(__file__).resolve().parents[1]
PRICE_DIR = ROOT / "ml" / "price"
ARTIFACTS = [
    PRICE_DIR / "price_model_v2.pkl",
    PRICE_DIR / "price_model_v2_1.pkl",
    PRICE_DIR / "price_model.pkl",
    PRICE_DIR / "model_metadata_v2.json",
    PRICE_DIR / "model_metadata_v2_1.json",
    PRICE_DIR / "verified_price_training_dataset.csv",
    ROOT / "ml" / "market" / "market_demand_model.pkl",
    ROOT / "ml" / "buyer" / "buyer_segment_model.pkl",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(**kwargs):
    base = {
        "project_name": "Palm Retreat",
        "developer": "Palm Developers",
        "micro_market": "Kanakapura Road",
        "property_type": "Residential",
        "property_segment": "Premium",
        "bhk": "3BHK",
        "units": 200,
        "unit_size": 1550,
        "sale_price_per_sqft": 7200,
        "sale_price_trusted": True,
        "price_type": "new_launch",
        "launch_date": "2024-03-15",
        "provenance": {
            "source_system": "external_real_estate_api",
            "source_api": "projects",
            "source_record_id": "src-1",
            "fetched_at": "2026-10-08T00:00:00Z",
            "source_updated_at": "2026-10-07T00:00:00Z",
        },
    }
    base.update(kwargs)
    return base


def test_valid_feature_mapping_market_bhk_segment_units_and_launch():
    row = build_external_feature_rows([_record(micro_market="kanakpura")], as_of="2026-10-08")[0]
    features = row["model_features"]
    assert features["units"] == 200
    assert features["bhk"] == 3.0
    assert features["unit_size"] == 1550
    assert features["is_luxury"] == 0
    assert features["is_premium"] == 1
    assert features["is_mid"] == 0
    assert features["zone_south"] == 1
    assert features["zone_north"] == 0
    assert row["observations"]["canonical_micro_market"] == "Kanakapura Road"
    assert row["observations"]["launch_year"] == 2024
    assert row["observations"]["launch_month"] == 3
    assert row["observations"]["launch_quarter"] == 1
    assert "launch_year" not in features
    assert row["eligibility"]["status"] == "historical_training_candidate"
    assert row["validation"]["accepted_for_current_model"] is True


def test_missing_values_stay_missing():
    row = build_external_feature_rows(
        [_record(units=None, bhk=None, property_segment=None, unit_size=None, micro_market=None)],
        as_of="2026-10-08",
    )[0]
    features = row["model_features"]
    assert features["units"] is None
    assert features["bhk"] is None
    assert features["unit_size"] is None
    assert features["is_luxury"] is None
    assert features["is_premium"] is None
    assert features["is_mid"] is None
    assert features["zone_north"] is None
    assert row["eligibility"]["status"] == "unsuitable"
    assert 0 not in (
        features["units"],
        features["bhk"],
        features["is_luxury"],
        features["zone_north"],
    )


def test_bhk_range_is_not_averaged():
    row = build_external_feature_rows([_record(bhk="2-3 BHK")], as_of="2026-10-08")[0]
    assert row["model_features"]["bhk"] is None
    assert row["eligibility"]["status"] == "unsuitable"


def test_provenance_is_retained():
    record = _record()
    record["provenance"]["fetched_at"] = None
    row = build_external_feature_rows([record], as_of="2026-10-08")[0]
    provenance = row["provenance"]
    assert provenance["source_system"] == "external_real_estate_api"
    assert provenance["source_api"] == "projects"
    assert provenance["source_record_id"] == "src-1"
    assert provenance["fetched_at"] is None
    assert provenance["source_updated_at"] == "2026-10-07T00:00:00Z"


def test_sale_price_is_a_label_and_not_a_feature():
    row = build_external_feature_rows([_record()], as_of="2026-10-08")[0]
    assert row["label"][TARGET_FIELD] == 7200
    assert row["label"]["usable_as_feature"] is False
    assert TARGET_FIELD not in row["model_features"]
    assert "sale_price_per_sqft" not in row["model_features"]
    assert "price_per_sqft" not in row["model_features"]
    assert all(value != 7200 for value in row["model_features"].values())
    leaked = dict(row)
    leaked["model_features"] = dict(row["model_features"])
    leaked["model_features"]["sale_price_per_sqft"] = 7200
    validation = prepare_external_ml_records([])
    assert validation["retrained"] is False
    from ml.external_data.prepare import validate_external_ml_features

    checked = validate_external_ml_features(leaked)
    assert checked["valid_schema"] is False
    assert checked["accepted_for_current_model"] is False


def test_rental_and_post_launch_fields_are_excluded():
    row = build_external_feature_rows(
        [
            _record(
                rental_price=18000,
                rental_price_per_sqft=22,
                absorbed_units=40,
                available_units=160,
                percentage_sold=20,
                project_status="ongoing",
                project_phase="Phase 2",
                completion_date="2028-06-01",
                latitude=12.9,
                longitude=77.5,
                rera_registered=True,
                rera_number="PRM/KA/EXAMPLE",
            )
        ],
        as_of="2026-10-08",
    )[0]
    names = {item["field"] for item in row["excluded_from_model_features"]}
    assert {
        "rental_price",
        "rental_price_per_sqft",
        "absorbed_units",
        "available_units",
        "percentage_sold",
        "project_status",
        "latitude",
        "rera_registered",
    } <= names
    assert "rental_price" not in row["model_features"]
    assert row["market_context"]["included_in_model_features"] is False
    assert row["market_context"]["status"] == "as_of_eligible"
    assert row["market_context"]["absorbed_units"] == 40


def test_untrusted_price_is_not_a_label():
    row = build_external_feature_rows(
        [_record(sale_price_per_sqft=None, reported_sale_price=9999, sale_price_trusted=False, price_type="asking")],
        as_of="2026-10-08",
    )[0]
    assert row["label"][TARGET_FIELD] is None
    assert all(value != 9999 for value in row["model_features"].values())


def test_future_observation_is_not_historical():
    row = build_external_feature_rows(
        [_record(launch_date="2027-01-01", absorbed_units=10)],
        as_of="2026-10-08",
    )[0]
    assert row["eligibility"]["status"] == "runtime_only"
    assert row["eligibility"]["historical_training"] is False
    assert row["market_context"]["status"] == "future_excluded"
    assert "absorbed_units" not in row["model_features"]


def test_synthetic_row_is_unsuitable():
    row = build_external_feature_rows(
        [_record(project_name="Kanakapura Comparable Project 4")],
        as_of="2026-10-08",
    )[0]
    assert row["eligibility"]["status"] == "unsuitable"
    assert row["observations"]["synthetic"] is True


def test_feature_schema_and_artifacts_remain_unchanged():
    before = {path.name: _sha(path) for path in ARTIFACTS}
    prediction_before = predict_price_per_sqft("Bagalur", "Mid", "Residential", "3BHK", 300)
    prepared = prepare_external_ml_records([_record()], as_of="2026-10-08")
    prediction_after = predict_price_per_sqft("Bagalur", "Mid", "Residential", "3BHK", 300)
    metadata = json.loads((PRICE_DIR / "model_metadata_v2.json").read_text(encoding="utf-8"))
    assert list(CURRENT_MODEL_FEATURES) == metadata["features"]
    assert prepared["feature_schema"] == metadata["features"]
    assert prepared["retrained"] is False
    assert prepared["training_dataset_modified"] is False
    assert {path.name: _sha(path) for path in ARTIFACTS} == before
    assert prediction_after == prediction_before
    assert prediction_after["model_version"] == "v2.0.0-ridge"
    assert prediction_after["coverage_status"] == "OBSERVED_MARKET"
