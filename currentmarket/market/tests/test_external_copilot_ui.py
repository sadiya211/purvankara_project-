"""Copilot and UI presentation of external evidence. No network and no model training."""

import json
from pathlib import Path
from unittest.mock import patch

from backend.copilot.llm_orchestrator import LLMOrchestrator
from backend.copilot.prompts import SYNTHESIS_PROMPT
from external_data.presentation import present_external_data

ROOT = Path(__file__).resolve().parents[1]


def _provenance():
    return {
        "source_system": "Fixture source",
        "source_api": "fixture-api",
        "source_record_id": "rec-1",
        "fetched_at": "2026-09-28",
        "source_updated_at": "2026-09-30",
    }


def _launch_payload(decision="Hold", extra=None):
    data = {
        "decision": decision,
        "executive_summary": "Existing decision evidence.",
        "composite_risk_score": 21.8,
    }
    if extra:
        data.update(extra)
    return {
        "tool": "get_dss_evidence",
        "status": "success",
        "data": data,
        "source": "Decision Engine",
    }


def test_launch_response_with_no_external_records():
    view = present_external_data(_launch_payload())
    assert view["decision"] == "Hold"
    assert view["decision_source"] == "Decision Engine"
    assert view["decision_changed_by_external_data"] is False
    assert view["external_data"] == "Not available"
    assert view["internal_data"] == "Available"
    assert view["message"] == "No external observations available."
    assert view["observations"] == []


def test_launch_response_keeps_external_evidence_separate_from_decision():
    payload = _launch_payload(
        extra={
            "external_evidence": [
                {
                    "evidence_type": "observed_sale_price",
                    "project_name": "Godrej Ananda III",
                    "observation_date": "2026-09-30",
                    "values": {"sale_price_per_sqft": 7200, "micro_market": "Bagalur"},
                    "provenance": _provenance(),
                }
            ],
            "existing_evidence": {"decision": "Hold", "external_data_changes_decision": False},
        }
    )
    view = present_external_data(payload)
    assert view["decision"] == "Hold"
    assert view["decision_changed_by_external_data"] is False
    assert view["observations"][0]["heading"] == "External observation"
    assert view["observations"][0]["price_label"] == "Observed external sale price"
    assert "predicted_price_per_sqft" not in view["observations"][0]
    assert "assumed_launch_price" not in json.dumps(view["observations"][0])
    assert "guaranteed" not in json.dumps(view).casefold()
    assert "model prediction" not in json.dumps(view).casefold()


def test_rental_is_not_presented_as_sale():
    payload = _launch_payload(
        extra={
            "external_evidence": [
                {
                    "evidence_type": "rental",
                    "project_name": "Godrej Ananda III",
                    "observation_date": "2026-09-30",
                    "values": {"rental_price": 28000, "rental_price_per_sqft": 22},
                    "provenance": _provenance(),
                }
            ]
        }
    )
    item = present_external_data(payload)["observations"][0]
    assert item["rental_label"] == "Observed external rental price"
    assert item["observed_external_rental_price"] == 28000
    assert "observed_external_sale_price" not in item
    assert "price_label" not in item


def test_competition_is_not_double_counted():
    payload = {
        "tool": "get_competitors",
        "data": {
            "competitor_count": 2,
            "competitors": [{"project_name": "Existing A"}, {"project_name": "Existing B"}],
            "external_competitor_observations": [
                {
                    "project_name": "Existing A",
                    "micro_market": "Bagalur",
                    "micro_market_status": "canonical",
                    "sale": {"sale_price_per_sqft": 7000, "sale_price_trusted": True},
                    "rental": None,
                    "provenance": _provenance(),
                }
            ],
        },
    }
    view = present_external_data(payload)
    assert view["existing_competitor_count"] == 2
    assert view["external_competitor_count"] == 1
    assert view["existing_competitor_count"] + 0 == 2
    competitors = [item for item in view["observations"] if item["kind"] == "competitor"]
    assert len(competitors) == 1
    assert competitors[0]["heading"] == "External observation"


def test_provenance_is_exposed_without_secrets():
    provenance = _provenance()
    provenance["source_api"] = "sk-or-v1-should-not-appear"
    provenance["source_record_id"] = "api_key=hidden"
    payload = _launch_payload(
        extra={
            "external_evidence": [
                {
                    "evidence_type": "observed_sale_price",
                    "project_name": "Shown project",
                    "observation_date": "2026-09-30",
                    "values": {"sale_price_per_sqft": 7100},
                    "provenance": provenance,
                }
            ]
        }
    )
    item = present_external_data(payload)["observations"][0]
    assert item["source"] == "Fixture source"
    assert item["fetched_at"] == "2026-09-28"
    assert item["source_updated_at"] == "2026-09-30"
    dumped = json.dumps(item)
    assert "sk-or-" not in dumped
    assert "api_key" not in dumped
    assert item["source_api"] is None
    assert item["source_record"] is None


def test_empty_external_table_shape_does_not_claim_data():
    payload = {"tool": "get_micro_market_profile", "data": {"micromarket_name": "Bagalur", "projects": []}}
    view = present_external_data(payload)
    assert view["external_data"] == "Not available"
    assert view["message"] == "No external observations available."
    assert view["observations"] == []


def test_unresolved_and_future_observations_are_labeled():
    payload = {
        "external_observations": [
            {
                "project_name": "Unknown place project",
                "micro_market": "Not A Corridor",
                "micro_market_status": "unresolved",
                "sale": {"sale_price_per_sqft": 9999, "sale_price_trusted": True},
                "rental": {"rental_price": 1000},
                "provenance": _provenance(),
            }
        ],
        "unavailable_data": [
            {
                "field": "observation_date",
                "reason": "Observation date is after the simulation as-of date.",
                "provenance": {"source_record_id": "future-1"},
            },
            {
                "field": "micro_market",
                "reason": "Micro-market is not recognized, so external rows are not used.",
                "provenance": {"source_record_id": "unresolved-1"},
            },
        ],
    }
    view = present_external_data(payload)
    unresolved = view["observations"][0]
    assert unresolved["availability"] == "Unresolved"
    assert "observed_external_sale_price" not in unresolved
    assert "observed_external_rental_price" not in unresolved
    labels = {item["availability"] for item in view["unavailable"]}
    assert "Future / excluded" in labels
    assert "Unresolved" in labels


def test_prompt_keeps_decision_engine_as_source_of_truth():
    assert "DecisionEngine" in SYNTHESIS_PROMPT
    assert "Observed external sale price" in SYNTHESIS_PROMPT
    assert "Observed external rental price" in SYNTHESIS_PROMPT
    assert "does not change the Decision Engine result" in SYNTHESIS_PROMPT
    decision_source = (ROOT / "backend" / "engine" / "decision_engine.py").read_text(encoding="utf-8")
    assert "absorption_pct >= 80.0 and gross_margin_pct >= 18.0 and composite_risk < 55.0" in decision_source
    assert "external_project_records" not in decision_source
    risk_source = (ROOT / "backend" / "engine" / "risk_engine.py").read_text(encoding="utf-8")
    assert "external_project_records" not in risk_source


def test_copilot_launch_responses_do_not_change_the_decision(monkeypatch=None):
    empty = _launch_payload()
    filled = _launch_payload(
        extra={
            "external_evidence": [
                {
                    "evidence_type": "observed_sale_price",
                    "project_name": "Godrej Ananda III",
                    "observation_date": "2026-09-30",
                    "values": {"sale_price_per_sqft": 7200},
                    "provenance": _provenance(),
                },
                {
                    "evidence_type": "rental",
                    "project_name": "Godrej Ananda III",
                    "observation_date": "2026-09-30",
                    "values": {"rental_price": 28000},
                    "provenance": {**_provenance(), "source_record_id": "rent-1"},
                },
            ]
        }
    )
    orchestrator = LLMOrchestrator()
    routing = {
        "intent": "DECISION_EVALUATION",
        "agents": ["dss_evidence_tool"],
        "tools": [{"name": "get_dss_evidence", "arguments": {"project_name": "Godrej Ananda III"}}],
        "parameters": {},
        "clarification_needed": False,
        "clarification_question": None,
    }
    synthesis = {"content": "Hold remains the Decision Engine result.", "raw": {}, "model_used": "mock"}

    def run(tool_payload):
        with patch.object(orchestrator.openrouter, "is_configured", return_value=True), patch.object(
            orchestrator.openrouter, "structured_completion", return_value=routing
        ), patch.object(orchestrator.openrouter, "chat_completion", return_value=synthesis), patch(
            "backend.copilot.llm_orchestrator.execute_tool", return_value=tool_payload
        ):
            return orchestrator.process_query("Can I launch Godrej Ananda III now?")

    empty_response = run(empty)
    filled_response = run(filled)
    assert empty_response["intent"] == "DECISION_EVALUATION"
    assert empty_response["tools_used"] == ["get_dss_evidence"]
    assert empty_response["answer"] == "Hold remains the Decision Engine result."
    assert empty_response["external_data"]["decision"] == "Hold"
    assert empty_response["external_data"]["external_data"] == "Not available"
    assert filled_response["external_data"]["decision"] == "Hold"
    assert filled_response["external_data"]["decision_changed_by_external_data"] is False
    labels = {item.get("price_label") or item.get("rental_label") for item in filled_response["external_data"]["observations"]}
    assert labels == {"Observed external sale price", "Observed external rental price"}
    dumped = json.dumps(filled_response["external_data"])
    assert "sk-or-" not in dumped
    assert "api_key" not in dumped


def test_frontend_keeps_external_evidence_separate():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "No external observations available." in app
    assert "Observed external sale price" in app
    assert "Observed external rental price" in app
    assert "External competitor observations are not added to that count." in app
    assert 'id="external-evidence-panel"' in page
    assert 'id="scen-external-panel"' in page
    assert "Income: insufficient disclosure" in app
