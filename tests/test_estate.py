"""
Unit and Integration Tests for Estate & Generational Wealth Engine.
Verifies:
- WA RCW 83.100 graduated estate tax calculation
- NY Tax Law § 952 105% cliff penalty
- Federal unified exemption & IRC § 2058 state tax deduction
- Trust architecture simulation (Status Quo vs SLAT vs IDGT vs GRAT vs ILIT)
- Multi-decade inheritance waterfall per child
- Multi-tenant isolation and demo read-only guardrails
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app
import estate_engine


def get_client_for_family(family_id: int = 1, role: str = "editor"):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = f"Family {family_id} User"
        sess["user_family_id"] = family_id
        sess["family_id"] = family_id
        sess["role"] = role
        sess["universe"] = "test"
        sess["is_demo"] = False
    return client


def test_wa_estate_tax_calculation():
    """Verify WA RCW 83.100 graduated bracket math and exclusions."""
    # Under exclusion: $0 tax
    tax_zero = estate_engine.calculate_wa_estate_tax(0.0)
    assert tax_zero == 0.0

    # $500,000 above exclusion: 10% bracket = $50,000
    tax_500k = estate_engine.calculate_wa_estate_tax(500_000.0)
    assert tax_500k == 50_000.0

    # $1.5M above exclusion: $1.0M @ 10% + $500k @ 14% = $100k + $70k = $170k
    tax_1_5m = estate_engine.calculate_wa_estate_tax(1_500_000.0)
    assert tax_1_5m == 170_000.0

    # State calculator helper
    st_res_mfj = estate_engine.calculate_state_estate_tax(gross_estate=10_000_000.0, state="WA", is_mfj=True, has_ab_trust=True)
    assert st_res_mfj["has_estate_tax"] is True
    assert st_res_mfj["exclusion"] == estate_engine.WA_ESTATE_EXCLUSION_MFJ
    assert st_res_mfj["tax_liability"] > 0


def test_ny_estate_tax_cliff():
    """Verify NY 105% cliff penalty eliminates exclusion when breached."""
    # Below $6.94M: $0 tax
    ny_below = estate_engine.calculate_ny_estate_tax(5_000_000.0)
    assert ny_below == 0.0

    # Above 105% cliff ($7.287M): e.g. $8.0M is taxed from dollar 1
    ny_above = estate_engine.calculate_ny_estate_tax(8_000_000.0)
    assert ny_above > 600_000.0  # Significant liability due to lost exemption


def test_zero_estate_tax_states():
    """Verify states like CA, TX, FL, NV report $0 estate tax."""
    for st in ("CA", "TX", "FL", "NV", "WY"):
        res = estate_engine.calculate_state_estate_tax(gross_estate=50_000_000.0, state=st)
        assert res["has_estate_tax"] is False
        assert res["tax_liability"] == 0.0
        assert res["exclusion"] is None


def test_irc_2058_deduction_and_federal_tax():
    """Verify state death taxes paid reduce federal gross estate before calculating federal tax."""
    gross = 40_000_000.0
    res_wa = estate_engine.calculate_comprehensive_estate_tax(gross_estate=gross, state="WA", is_mfj=True)
    st_tax = res_wa["state_estate_tax"]
    assert st_tax > 0

    # IRC § 2058 deduction must equal state tax paid
    assert res_wa["irc_2058_state_tax_deduction"] == st_tax
    adj_gross = gross - st_tax
    expected_fed_taxable = max(0.0, adj_gross - estate_engine.FEDERAL_ESTATE_EXEMPTION_2026_MFJ)
    assert abs(res_wa["federal_taxable_estate"] - expected_fed_taxable) < 1.0
    assert abs(res_wa["federal_estate_tax"] - round(expected_fed_taxable * 0.40, 2)) < 1.0


def test_trust_vehicle_sandboxing():
    """Verify trust vehicles show quantifiable tax savings over Status Quo."""
    gross = 35_000_000.0
    res = estate_engine.simulate_trust_architectures(gross_estate=gross, state="WA", is_mfj=True)
    assert "status_quo" in res
    assert "vehicles" in res
    assert len(res["vehicles"]) == 5

    sq = next(v for v in res["vehicles"] if v["id"] == "status_quo")
    slat = next(v for v in res["vehicles"] if v["id"] == "slat")
    idgt = next(v for v in res["vehicles"] if v["id"] == "idgt")

    assert sq["tax_savings"] == 0.0
    assert slat["tax_savings"] > 0
    assert idgt["tax_savings"] > 0
    assert slat["estate_tax_due"] < sq["estate_tax_due"]


def test_api_get_estate_endpoint():
    """Verify GET /api/estate returns complete profile and handles query overrides."""
    client = get_client_for_family(family_id=1)
    resp = client.get("/api/estate")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["family_id"] == 1
    assert "current_estate_tax" in data
    assert "projections" in data
    assert len(data["projections"]) == 4  # Ages 80, 85, 90, 95
    assert "trust_sandbox" in data
    assert "state_comparisons" in data

    # Verify strict RFC 8259 JSON compliance (no Infinity, -Infinity, or NaN tokens)
    raw_text = resp.data.decode("utf-8")
    assert "Infinity" not in raw_text
    assert "NaN" not in raw_text

    # Test state query override to CA
    resp_ca = client.get("/api/estate?state=CA")
    assert resp_ca.status_code == 200
    data_ca = resp_ca.get_json()
    assert data_ca["state"] == "CA"
    assert data_ca["current_estate_tax"]["state_estate_tax"] == 0.0


def test_api_post_estate_settings():
    """Verify POST /api/estate/settings persists preferences for editor and enforces guardrails."""
    client = get_client_for_family(family_id=1, role="editor")
    payload = {
        "apply_tcja_sunset": True,
        "charitable_pct": 0.10,
        "trust_preferences": ["slat", "idgt"],
    }
    resp = client.post("/api/estate/settings", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["estate_planning"]["apply_tcja_sunset"] is True
    assert data["estate_planning"]["charitable_pct"] == 0.10


def test_api_post_estate_settings_demo_blocked():
    """Verify demo mode sessions are rejected with 403 Forbidden."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Demo Guest"
        sess["role"] = "viewer"
        sess["is_demo"] = True
        sess["universe"] = "beta"
        sess["family_id"] = 1

    resp = client.post("/api/estate/settings", json={"apply_tcja_sunset": True})
    assert resp.status_code == 403
    data = resp.get_json()
    assert "error" in data
    assert any(term in data["error"].lower() for term in ("demo", "forbidden", "read-only"))


def test_estate_empty_state_isolation():
    """Verify family_id 0 and 999 return empty defaults without leaking Family 1 data."""
    prof0 = estate_engine.get_family_estate_profile(family_id=0)
    assert prof0["success"] is True
    assert prof0["children_count"] == 0

    prof999 = estate_engine.get_family_estate_profile(family_id=999)
    assert prof999["success"] is True
    assert prof999["children_count"] == 0


def test_household_survivorship_audit_engine_and_estate_card():
    """Verify evaluate_household_risks engine, AI advisor tool, and #estate-survivorship-audit-card SSR output."""
    from services.household_audit_service import evaluate_household_risks, audit_household_risks
    from ssr.planning import build_ssr_estate
    from ssr.widgets import build_overview_widgets

    # 1. Zero family isolation
    risk0 = evaluate_household_risks(family_id=0)
    assert risk0["has_data"] is False
    assert risk0["readiness_score"] == 100
    assert risk0["critical_count"] == 0
    assert risk0["warning_count"] == 0
    assert risk0["findings"] == []

    adv0 = audit_household_risks(family_id=0)
    assert adv0 == {}

    # 2. Seeded family evaluation
    risk1 = evaluate_household_risks(family_id=1)
    assert isinstance(risk1["readiness_score"], int)
    assert 0 <= risk1["readiness_score"] <= 100
    assert "status_badge" in risk1
    assert "critical_count" in risk1
    assert "warning_count" in risk1
    assert "info_count" in risk1
    assert isinstance(risk1["findings"], list)
    for f in risk1["findings"]:
        assert "id" in f
        assert f["severity"] in ("critical", "warning", "info")
        assert "category" in f
        assert "title" in f
        assert "detail" in f
        assert "action_label" in f
        assert "action_nav" in f
        assert "verify_label" in f
        assert "is_verified" in f

    # 3. Advisor tool returns data for seeded family
    adv1 = audit_household_risks(family_id=1)
    assert adv1.get("has_data") is True
    assert "readiness_score" in adv1

    # 4. SSR view-model contains survivorship_audit
    ssr_est = build_ssr_estate(family_id=1)
    assert "survivorship_audit" in ssr_est
    assert ssr_est["survivorship_audit"]["has_data"] is True

    # 5. Estate fragment contains the survivorship audit card and interactive action buttons
    client = get_client_for_family(family_id=1, role="editor")
    resp = client.get("/fragments/estate")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="estate-survivorship-audit-card"' in html
    assert "Survivorship, Probate &amp; Household Readiness Audit" in html or "Survivorship, Probate & Household Readiness Audit" in html
    assert "/100 Readiness" in html
    assert "btn-audit-nav" in html
    assert "btn-audit-verify" in html

    # 6. Verify one-click audit verification endpoint toggles finding & updates readiness score
    actionable = [f for f in risk1["findings"] if f["original_severity"] in ("critical", "warning")]
    if actionable:
        target_id = actionable[0]["id"]
        v_resp = client.post("/api/estate/audit_verify", json={"finding_id": target_id, "verified": True})
        assert v_resp.status_code == 200
        v_data = v_resp.get_json()
        assert v_data["success"] is True
        assert v_data["verified"] is True
        assert target_id in v_data["verified_audit_ids"]

        risk_after = evaluate_household_risks(family_id=1)
        assert risk_after["verified_count"] >= 1
        matched = next(f for f in risk_after["findings"] if f["id"] == target_id)
        assert matched["is_verified"] is True

        # Unverify to restore clean state
        u_resp = client.post("/api/estate/audit_verify", json={"finding_id": target_id, "verified": False})
        assert u_resp.status_code == 200
        assert u_resp.get_json()["verified"] is False

    # 7. Overview widgets analytics includes needs_attention
    ov_widgets = build_overview_widgets(family_id=1, snapshot=None)
    assert "needs_attention" in ov_widgets["analytics"]
    assert ov_widgets["analytics"]["needs_attention"]["has_data"] is True
