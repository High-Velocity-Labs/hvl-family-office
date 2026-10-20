"""
Unit & Integration Tests for RSU (Restricted Stock Unit) and Multi-Company Equity Support.
Verifies zero-strike calculations, ordinary tax spread modeling, company associations,
and forecasting growth trajectory integration.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app
import equity_engine
import forecast_engine


def get_authenticated_editor_client(family_id: int = 1):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Test Admin"
        sess["user_family_id"] = family_id
        sess["family_id"] = family_id
        sess["role"] = "admin"
        sess["universe"] = "beta"
        sess["is_demo"] = False
    return client


def test_equity_engine_rsu_math():
    """Verifies that an EquityGrant with grant_type='rsu' forces $0 strike and 100% spread."""
    rsu_grant = equity_engine.EquityGrant(
        grant_id="test_rsu_1",
        nickname="Retention RSU Grant",
        grant_date="2025-01-15",
        grant_type="rsu",
        strike_price=150.0,  # Should be overridden to 0.0 for RSU
        total_granted=1000.0,
        sold_quantity=0.0,
        owned_exercised=0.0,
        unexercised_vested=500.0,
        unvested=500.0,
        company_id=1,
        company_name="CloudFlow Systems",
    )

    res = rsu_grant.calculate_at_price(share_price=200.0, include_wa_tax=False)
    # Strike cost must be 0 for RSUs
    assert res["strike_price"] == 0.0
    assert res["strike_cost"] == 0.0
    # Spread is 100% of gross value (500 units * $200 = $100,000)
    assert res["spread"] == 100000.0
    # Ordinary tax applies
    assert res["total_tax_drag"] > 0.0
    assert res["true_net_value"] < res["spread"]
    assert res["true_net_value"] == res["spread"] - res["total_tax_drag"]


def test_api_equity_grants_includes_rsu_and_companies(monkeypatch):
    monkeypatch.setenv("APP_UNIVERSE", "beta")
    client = get_authenticated_editor_client(family_id=1)
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    comp_eq = (data.get("snapshot") or {}).get("company_equity") or {}
    assert "grants" in comp_eq
    companies = equity_engine.load_equity_companies_summary(family_id=1)
    assert len(companies) >= 1

    # In beta universe for family 1, CloudFlow Systems RSUs were seeded
    has_rsu = any(g.get("is_rsu") is True or g.get("grant_type") == "RSU" for g in comp_eq["grants"])
    assert has_rsu, "Family 1 should have pre-seeded RSU grant in demo universe"


def test_forecast_event_catalog_rsu_support():
    """Verifies forecast event catalog generates RSU liquidation events for families with RSUs."""
    catalog = forecast_engine.get_default_event_catalog(family_id=1)
    equity_events = [e for e in catalog if e.get("category") == "company_equity"]
    assert len(equity_events) >= 1
    # Check that event name or description contains RSU or Option
    names = " ".join(e.get("name", "") for e in equity_events)
    assert "RSU" in names or "Option" in names


def test_company_growth_presets_available():
    """Verifies company valuation growth presets are registered and defined."""
    assert "baseline_curve" in forecast_engine.COMPANY_GROWTH_PRESETS
    assert "conservative" in forecast_engine.COMPANY_GROWTH_PRESETS
    assert "moderate" in forecast_engine.COMPANY_GROWTH_PRESETS
    assert "aggressive" in forecast_engine.COMPANY_GROWTH_PRESETS
    assert forecast_engine.COMPANY_GROWTH_PRESETS["baseline_curve"]["growth_rate"] == 0.105


def test_equity_engine_iso_math():
    """Verifies that an EquityGrant with grant_type='iso' models LTCG (23.8%) qualifying disposition tax rate."""
    iso_grant = equity_engine.EquityGrant(
        grant_id="test_iso_1",
        nickname="Series Seed ISO",
        grant_date="2022-01-01",
        grant_type="iso",
        strike_price=2.00,
        total_granted=10000.0,
        sold_quantity=0.0,
        owned_exercised=0.0,
        unexercised_vested=10000.0,
        unvested=0.0,
        company_id=1,
        company_name="Aether Bio",
    )

    res = iso_grant.calculate_at_price(share_price=20.00, include_wa_tax=False)
    assert res["strike_price"] == 2.00
    assert res["strike_cost"] == 20000.0
    # Spread: (20.00 - 2.00) * 10,000 = $180,000
    assert res["spread"] == 180000.0
    # ISO tax uses preferential LTCG (23.8% Fed LTCG + NIIT), not 39.35% ordinary W-2 tax
    assert res["option_tax"]["is_iso"] is True
    assert res["option_tax"]["effective_rate"] == 23.8
    assert res["option_tax"]["total_tax"] == round(180000.0 * 0.238, 2)
    assert res["option_tax"]["amt_exercise_tax"] == round(180000.0 * 0.28, 2)
    assert res["true_net_value"] == round(180000.0 - (180000.0 * 0.238), 2)

    # ISO qualifying disposition with WA tax and spread > $1M: verifies marginal bracket (no cliff)
    res_wa = iso_grant.calculate_at_price(share_price=202.00, include_wa_tax=True)
    # Spread: (202.00 - 2.00) * 10,000 = $2,000,000.0
    assert res_wa["spread"] == 2000000.0
    # WA taxable gain: 2,000,000 - 278,000 = 1,722,000.
    # First $1M @ 7% = $70,000; next $722k @ 9.9% = $71,478 -> WA tax = $141,478
    assert res_wa["option_tax"]["state_tax"] == 141478.0
    assert res_wa["option_tax"]["federal_tax"] == 400000.0
    assert res_wa["option_tax"]["medicare_tax"] == 76000.0
    assert res_wa["option_tax"]["total_tax"] == 617478.0
    assert res_wa["option_tax"]["amt_exercise_tax"] == round(2000000.0 * 0.28, 2)


def test_api_equity_fmv_with_target_company_id(monkeypatch):
    """Verifies that POST /api/equity/fmv with company_id targets the specific company."""
    monkeypatch.setenv("APP_UNIVERSE", "beta")
    client = get_authenticated_editor_client(family_id=1)
    # First get companies for family 1
    companies = equity_engine.load_equity_companies_summary(family_id=1)
    assert len(companies) >= 2

    target_company = companies[1]  # e.g. CloudFlow Systems
    cid = target_company["company_id"]
    orig_price = float(target_company.get("current_fmv") or 11.5)
    new_price = 14.75

    try:
        fmv_resp = client.post("/api/equity/fmv", json={
            "company_id": cid,
            "price": new_price,
            "effective_date": "2026-10-15",
            "notes": "Q4 Verified Valuation"
        })
        assert fmv_resp.status_code == 200
        fmv_data = fmv_resp.get_json()
        assert fmv_data["success"] is True
        assert fmv_data["price"] == new_price

        # Verify query for this specific company returns the updated FMV
        assert equity_engine.get_company_409a_price(family_id=1, company_id=cid) == new_price
        frag_resp = client.get(f"/fragments/equity?company_id={cid}")
        assert frag_resp.status_code == 200
        assert f'data-share-price="{new_price}"' in frag_resp.get_data(as_text=True)
    finally:
        # Restore original price
        client.post("/api/equity/fmv", json={
            "company_id": cid,
            "price": orig_price,
            "effective_date": "2026-10-15",
            "notes": "Restored baseline"
        })


def test_simulate_valuation_scenario_scoped_by_company():
    """Verifies simulate_valuation_scenario recalculates the target company while preserving other companies' baseline."""
    companies = equity_engine.load_equity_companies_summary(family_id=1)
    if len(companies) >= 2:
        c1 = companies[0]
        c2 = companies[1]
        # Simulate c1 at 2x price
        sim = equity_engine.simulate_valuation_scenario(
            share_price=c1["current_fmv"] * 2.0,
            family_id=1,
            company_id=c1["company_id"]
        )
        assert sim["company_id"] == c1["company_id"]
        assert sim["share_price"] == c1["current_fmv"] * 2.0

        # Grants for c1 should use 2x price, grants for c2 should use c2's baseline current_fmv
        for g in sim["grants"]:
            if g["company_id"] == c1["company_id"]:
                assert g["share_price"] == c1["current_fmv"] * 2.0
            elif g["company_id"] == c2["company_id"]:
                assert g["share_price"] == c2["current_fmv"]


def test_simulate_multi_year_projections_scoped_by_company():
    """Verifies simulate_multi_year_projections computes scoped projections when company_id is provided."""
    companies = equity_engine.load_equity_companies_summary(family_id=1)
    if len(companies) >= 2:
        c1 = companies[0]
        proj = equity_engine.simulate_multi_year_projections(
            annual_growth_rate=0.10,
            years=3,
            family_id=1,
            company_id=c1["company_id"]
        )
        assert len(proj) == 4
        assert proj[0]["year"] == 2026
        assert proj[0]["gross_equity"] > 0
        assert proj[3]["gross_equity"] > proj[0]["gross_equity"]


def test_create_new_company_and_grant():
    """Verifies creating a grant with a new company name automatically registers the company and links the grant."""
    client = get_authenticated_editor_client(family_id=1)
    # 1. Test POST /api/equity/company endpoint
    resp = client.post("/api/equity/company", json={
        "company_name": "Stripe Payments",
        "current_fmv": 55.0,
        "fmv_date": "2026-06-01"
    })
    assert resp.status_code == 200
    cdata = resp.get_json()
    assert cdata["success"] is True
    assert cdata["company_name"] == "Stripe Payments"
    assert cdata["current_fmv"] == 55.0
    stripe_cid = cdata["company_id"]

    # 2. Test POST /api/equity/grant with new_company_name
    g_resp = client.post("/api/equity/grant", json={
        "nickname": "Anthropic Series B RSU",
        "grantDate": "2026-01-15",
        "quantityGranted": 1000.0,
        "grantType": "rsu",
        "new_company_name": "Anthropic AI",
        "new_company_fmv": 75.0
    })
    assert g_resp.status_code == 200
    gdata = g_resp.get_json()
    assert gdata["success"] is True
    assert gdata["company_id"] is not None

    # Verify both companies now appear in equity companies summary and /fragments/equity
    frag_resp = client.get("/fragments/equity")
    assert frag_resp.status_code == 200
    frag_html = frag_resp.get_data(as_text=True)
    assert "Stripe Payments" in frag_html
    assert "Anthropic AI" in frag_html

