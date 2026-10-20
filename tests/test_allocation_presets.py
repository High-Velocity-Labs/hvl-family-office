"""
Unit & Integration Tests for Investment Policy Statement (IPS) Presets & Deviations.
Tests preset mathematical models, tolerance drift bands, policy persistence,
and multi-tenant isolation.
"""

import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app


def get_authenticated_editor_client(family_id: int = 1, universe: str = "beta"):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Test Editor"
        sess["user_family_id"] = family_id
        sess["family_id"] = family_id
        sess["role"] = "admin" if universe == "beta" else "editor"
        sess["universe"] = universe
        sess["is_demo"] = False
    return client


def get_demo_viewer_client(family_id: int = 1):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Demo Guest"
        sess["family_id"] = family_id
        sess["role"] = "viewer"
        sess["universe"] = "beta"
        sess["is_demo"] = True
    return client


def test_get_holdings_policy():
    client = get_authenticated_editor_client(family_id=1)
    resp = client.get("/api/holdings/policy")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "policy" in data
    assert "presets" in data
    assert data["policy"]["family_id"] == 1
    assert "anchor_preset" in data["policy"]
    assert "drift_tolerance" in data["policy"]
    assert "deviations_rationale" in data["policy"]


def test_update_holdings_policy_authenticated():
    client = get_authenticated_editor_client(family_id=1)
    payload = {
        "anchor_preset": "boglehead_80_20",
        "drift_tolerance": 0.04,
        "deviations_rationale": "Tilting 80/20 growth with 5% physical gold satellite for macro hedging.",
    }
    resp = client.post("/api/holdings/policy", json=payload)
    assert resp.status_code == 200
    res = resp.get_json()
    assert res["success"] is True
    assert res["policy"]["anchor_preset"] == "boglehead_80_20"
    assert res["policy"]["drift_tolerance"] == 0.04
    assert "physical gold" in res["policy"]["deviations_rationale"]

    # Verify retrieval
    get_resp = client.get("/api/holdings/policy")
    assert get_resp.status_code == 200
    get_data = get_resp.get_json()
    assert get_data["policy"]["anchor_preset"] == "boglehead_80_20"
    assert get_data["policy"]["drift_tolerance"] == 0.04
    assert "physical gold" in get_data["policy"]["deviations_rationale"]


def test_update_holdings_policy_demo_guardrail():
    client = get_demo_viewer_client(family_id=1)
    payload = {
        "anchor_preset": "boglehead_90_10",
        "drift_tolerance": 0.03,
        "deviations_rationale": "Attempted unauthorized overwrite in demo mode.",
    }
    resp = client.post("/api/holdings/policy", json=payload)
    # Demo or viewer role should be rejected by @editor_required with 403 Forbidden
    assert resp.status_code == 403
    data = resp.get_json()
    assert "error" in data


def test_invalid_policy_preset_rejected():
    client = get_authenticated_editor_client(family_id=1)
    payload = {
        "anchor_preset": "crypto_degen_yolo_100",
        "drift_tolerance": 0.05,
        "deviations_rationale": "Invalid preset test",
    }
    resp = client.post("/api/holdings/policy", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_update_holdings_policy_all_presets():
    client = get_authenticated_editor_client(family_id=1)
    for preset_key in ("all_equity_90_10", "glidepath_60_40", "core_satellite", "boglehead_80_20", "core_four_reit"):
        resp = client.post("/api/holdings/policy", json={
            "anchor_preset": preset_key,
            "drift_tolerance": 0.05,
            "deviations_rationale": f"Testing preset {preset_key}"
        })
        assert resp.status_code == 200
        res = resp.get_json()
        assert res["success"] is True
        assert res["policy"]["anchor_preset"] == preset_key


def test_core_four_reit_preset_and_real_estate():
    client = get_authenticated_editor_client(family_id=1)
    resp = client.get("/api/holdings/policy")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "core_four_reit" in data["presets"]
    cf = data["presets"]["core_four_reit"]
    assert cf["target"]["real_estate"] == 0.08
    assert cf["target"]["us_equity"] == 0.48
    assert cf["target"]["intl_equity"] == 0.24
    assert cf["target"]["bonds"] == 0.20

    # Verify /fragments/holdings renders and monarch_service returns detailed asset allocation with real_estate
    h_resp = client.get("/fragments/holdings")
    assert h_resp.status_code == 200
    import monarch_service
    snap = monarch_service.get_financial_snapshot(family_id=1)
    totals = snap["detailed_asset_allocation"]["totals"]
    assert "real_estate" in totals
    assert totals["real_estate"] >= 0.0

