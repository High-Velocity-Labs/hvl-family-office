"""
Tests for AI Advisor Multi-Scenario Lookup by Name, Full Per-Scenario Event Visibility,
and the manage_scenario_life_event Gemini tool.
"""

from __future__ import annotations
import pytest
import forecast_engine
from services.advisor.context import _build_active_tab_snapshot
from services.advisor.fallback import _generate_rule_based_response
from services.advisor.tools_core import simulate_financial_scenario
from services.advisor.tools_operations import (
    get_private_markets_lp_book,
    manage_lp_commitment,
    update_tax_document_checklist_status,
)
from services.advisor.tools_scenarios import enrich_scenarios_and_events_payload, manage_scenario_life_event
from services.advisor.tools_tabs import (
    get_accounts_and_balance_sheet,
    get_compensation_and_tax_withholding,
    get_scenarios_and_forecast_plan,
)


def test_get_scenarios_and_forecast_plan_name_lookup_and_events_catalog():
    """Verify get_scenarios_and_forecast_plan supports name lookup and returns enriched scenario data."""
    # 1. family_id=0 isolation
    assert get_scenarios_and_forecast_plan(family_id=0) == {}
    assert enrich_scenarios_and_events_payload(family_id=0) == {}

    # 2. Family 1 baseline inspection
    plan_data = get_scenarios_and_forecast_plan(family_id=1)
    assert plan_data.get("active_plan_name")
    assert "scenarios_by_name" in plan_data
    scenarios_by_name = plan_data["scenarios_by_name"]
    assert isinstance(scenarios_by_name, dict)
    assert len(scenarios_by_name) >= 1

    # Verify per-scenario assumptions, metrics, and enabled_events
    for sc_name, sc_info in scenarios_by_name.items():
        assert "scenario_id" in sc_info
        assert "name" in sc_info
        assert "assumptions" in sc_info
        assump = sc_info["assumptions"]
        assert "retirement_age" in assump
        assert "annual_living_spend" in assump
        assert "spending_guardrail_mode" in assump
        assert "metrics" in sc_info
        metrics = sc_info["metrics"]
        assert "nw_65" in metrics
        assert "nw_85" in metrics
        assert "nw_95" in metrics
        assert "solvency" in metrics
        assert "enabled_events" in sc_info
        assert isinstance(sc_info["enabled_events"], list)

    # Verify all_household_events_catalog
    assert "all_household_events_catalog" in plan_data
    catalog = plan_data["all_household_events_catalog"]
    assert isinstance(catalog, list)
    for ev in catalog:
        assert "id" in ev
        assert "name" in ev
        assert "category" in ev
        assert "enabled_in_scenario_names" in ev
        assert isinstance(ev["enabled_in_scenario_names"], list)

    # 3. Case-insensitive name lookup (exact and lowercase)
    baseline_match = get_scenarios_and_forecast_plan(family_id=1, scenario_name="baseline")
    assert baseline_match.get("selected_scenario_id") == "scen_baseline"

    # Lookup by plan name substring
    first_scen_name = list(scenarios_by_name.keys())[0]
    sub_name = first_scen_name[:6].lower()
    matched = get_scenarios_and_forecast_plan(family_id=1, scenario_name=sub_name)
    assert matched.get("selected_scenario_id")


def test_manage_scenario_life_event_upsert_child_clone_and_modify():
    """Verify manage_scenario_life_event clones scenarios, creates events, reports cash flows, and modifies without duplicate."""
    # 1. family_id=0 isolation
    res_zero = manage_scenario_life_event(family_id=0, event_name="Personal Assistant", amount=85000.0)
    assert res_zero.get("status") == "unavailable"
    assert "error" in res_zero

    # 2. Add Personal Assistant recurring event into a new child scenario
    child_plan_name = "Assistant & Travel Plan"
    res_pa = manage_scenario_life_event(
        family_id=1,
        action="upsert",
        event_name="Personal Assistant",
        category="lifestyle",
        start_year=2027,
        end_year=2031,
        amount=85000.0,
        is_outflow=True,
        description="Household manager and personal assistant",
        create_child_scenario_name=child_plan_name,
    )
    assert res_pa.get("status") == "saved"
    assert res_pa.get("scenario_name") == child_plan_name
    child_scen_id = res_pa.get("scenario_id")
    assert child_scen_id and child_scen_id != "scen_baseline"

    ev = res_pa.get("event") or {}
    assert ev.get("name") == "Personal Assistant"
    assert ev.get("amount") == 85000.0
    assert ev.get("year") == 2027
    assert ev.get("end_year") == 2031

    # Verify Before vs After metrics
    before_m = res_pa.get("before_metrics") or {}
    after_m = res_pa.get("after_metrics") or {}
    assert "nw_age_65" in before_m and "nw_age_65" in after_m
    assert "solvency" in before_m and "solvency" in after_m

    # Verify event window cash flows
    window_cf = res_pa.get("event_window_cash_flow") or []
    assert len(window_cf) >= 5
    cf_2027 = next((r for r in window_cf if r["year"] == 2027), None)
    assert cf_2027 is not None
    assert "net_cash_flow" in cf_2027
    assert "events_outflow" in cf_2027
    assert "liquid_portfolio" in cf_2027

    # 3. Add Galapagos Vacation in 2027 to the same child scenario
    res_gala = manage_scenario_life_event(
        family_id=1,
        action="upsert",
        event_name="Galapagos Vacation",
        category="lifestyle",
        start_year=2027,
        end_year=2027,
        amount=25000.0,
        is_outflow=True,
        description="Family adventure cruise in the Galapagos",
        scenario_name=child_plan_name,
    )
    assert res_gala.get("status") == "saved"
    gala_cf = res_gala.get("event_window_cash_flow") or []
    cf_gala_2027 = next((r for r in gala_cf if r["year"] == 2027), None)
    assert cf_gala_2027 is not None
    # Both events are modeled in 2027 cash flow
    events_occ_str = " ".join(cf_gala_2027.get("events_occurred", []))
    assert "Galapagos" in events_occ_str or cf_gala_2027["events_outflow"] >= 100000.0 or cf_gala_2027["net_cash_flow"] < 0

    # 4. Modify existing Personal Assistant event to $95,000 without duplicate creation
    res_mod = manage_scenario_life_event(
        family_id=1,
        action="upsert",
        event_name="Personal Assistant",
        amount=95000.0,
        start_year=2027,
        end_year=2031,
        scenario_name=child_plan_name,
    )
    assert res_mod.get("status") == "saved"
    assert res_mod.get("event", {}).get("amount") == 95000.0

    # Verify no duplicate in catalog
    state = forecast_engine.load_scenario_state(family_id=1)
    pa_events = [e for e in state.get("events", []) if e.get("name") == "Personal Assistant"]
    assert len(pa_events) == 1
    assert pa_events[0]["amount"] == 95000.0


def test_manage_scenario_life_event_simulate_only():
    """Verify simulate_only returns before/after comparisons without persisting changes to disk."""
    state_before = forecast_engine.load_scenario_state(family_id=1)
    initial_event_ids = {e["id"] for e in state_before.get("events", [])}

    res_sim = manage_scenario_life_event(
        family_id=1,
        action="simulate_only",
        event_name="Simulated Mega Sabbatical",
        category="sabbatical",
        start_year=2028,
        end_year=2028,
        amount=250000.0,
        is_outflow=True,
    )
    assert res_sim.get("status") == "simulated_only"
    assert res_sim.get("before_metrics")
    assert res_sim.get("after_metrics")
    assert len(res_sim.get("event_window_cash_flow", [])) >= 1

    # Verify event was NOT persisted to disk
    state_after = forecast_engine.load_scenario_state(family_id=1)
    current_event_ids = {e["id"] for e in state_after.get("events", [])}
    assert initial_event_ids == current_event_ids
    assert not any(e.get("name") == "Simulated Mega Sabbatical" for e in state_after.get("events", []))


def test_manage_scenario_life_event_enable_disable_delete():
    """Verify enable, disable, and delete lifecycle actions on scenario life events."""
    # 1. Create a test event
    res_create = manage_scenario_life_event(
        family_id=1,
        action="upsert",
        event_name="Temporary Charity Gala",
        category="philanthropy_daf",
        start_year=2029,
        amount=50000.0,
    )
    assert res_create.get("status") == "saved"
    event_id = res_create["event"]["id"]
    scen_id = res_create["scenario_id"]

    # 2. Disable event from active scenario
    res_disable = manage_scenario_life_event(
        family_id=1,
        action="disable",
        event_id=event_id,
        scenario_id=scen_id,
    )
    assert res_disable.get("status") == "saved"
    state_dis = forecast_engine.load_scenario_state(family_id=1)
    target_scen = next(s for s in state_dis.get("scenarios", []) if s["id"] == scen_id)
    assert event_id not in target_scen.get("event_ids", [])
    # Event is still in catalog
    assert any(e["id"] == event_id for e in state_dis.get("events", []))

    # 3. Enable event back onto active scenario
    res_enable = manage_scenario_life_event(
        family_id=1,
        action="enable",
        event_id=event_id,
        scenario_id=scen_id,
    )
    assert res_enable.get("status") == "saved"
    state_en = forecast_engine.load_scenario_state(family_id=1)
    target_scen_en = next(s for s in state_en.get("scenarios", []) if s["id"] == scen_id)
    assert event_id in target_scen_en.get("event_ids", [])

    # 4. Permanently delete event
    res_del = manage_scenario_life_event(
        family_id=1,
        action="delete",
        event_id=event_id,
    )
    assert res_del.get("status") == "saved"
    state_del = forecast_engine.load_scenario_state(family_id=1)
    assert not any(e["id"] == event_id for e in state_del.get("events", []))


def test_advisor_fallback_with_scenario_events():
    """Verify deterministic fallback engine responds to event modeling and scenario queries with quantitative data."""
    ctx = {
        "family_id": 1,
        "family_name": "Test Household",
        "state": "WA",
        "annual_spending": 250000.0,
        "annual_savings": 100000.0,
        "retirement_age": 60,
        "active_tab": "section-scenarios",
        "net_worth_snapshot": {"net_worth": 10000000.0},
    }

    reply = _generate_rule_based_response(
        prompt="Model a personal assistant for 5 years and vacation to the Galapagos",
        ctx=ctx,
    )
    assert "Scenario Life Events Analysis" in reply
    assert "Net Worth at 65" in reply
    assert "manage_scenario_life_event" in reply


def test_private_markets_lp_book_and_management(monkeypatch):
    """Verify get_private_markets_lp_book and manage_lp_commitment for auth save and demo guards."""
    assert get_private_markets_lp_book(family_id=0) == {}
    assert manage_lp_commitment(family_id=0) == {}

    book = get_private_markets_lp_book(family_id=1)
    assert "summary" in book and "commitments" in book
    assert "standard_call_schedule_by_year" in book
    assert "accelerated_24m_call_schedule_by_year" in book
    assert len(book["commitments"]) >= 1
    existing_fund = book["commitments"][0]["fund_name"]

    # Demo mode simulation guard
    monkeypatch.setattr("services.advisor.tools_operations._is_read_only_mode", lambda: True)
    res_demo = manage_lp_commitment(family_id=1, action="upsert", fund_name="Apex Growth Partners IV", total_commitment=200000.0)
    assert res_demo.get("status") == "simulated_only"

    res_del_demo = manage_lp_commitment(family_id=1, action="delete", fund_name=existing_fund)
    assert res_del_demo.get("status") == "simulated_only"

    # Authenticated mode persistence
    monkeypatch.setattr("services.advisor.tools_operations._is_read_only_mode", lambda: False)
    res_save = manage_lp_commitment(
        family_id=1, action="upsert", fund_name="Apex Growth Partners IV",
        fund_type="Venture", total_commitment=250000.0, capital_called=50000.0,
    )
    assert res_save.get("status") == "saved"
    assert res_save.get("summary")

    res_del = manage_lp_commitment(family_id=1, action="delete", fund_name="Apex Growth Partners IV")
    assert res_del.get("status") == "deleted"


def test_tax_checklist_and_accounts_burn_calibration(monkeypatch):
    """Verify compensation includes checklist, status updates, and accounts includes core burn calibration."""
    comp = get_compensation_and_tax_withholding(family_id=1)
    assert "tax_season_checklist" in comp
    chk = comp["tax_season_checklist"]
    assert "checklist_items" in chk or "items" in chk

    assert update_tax_document_checklist_status(family_id=0) == {}
    res_nf = update_tax_document_checklist_status(family_id=1, item_id_or_name="nonexistent_document_xyz")
    assert res_nf.get("status") == "not_found"

    monkeypatch.setattr("services.advisor.tools_operations._is_read_only_mode", lambda: True)
    res_sim = update_tax_document_checklist_status(family_id=1, item_id_or_name="w-2", status="received")
    assert res_sim.get("status") == "simulated_only"

    monkeypatch.setattr("services.advisor.tools_operations._is_read_only_mode", lambda: False)
    res_auth = update_tax_document_checklist_status(family_id=1, item_id_or_name="w-2", status="received")
    assert res_auth.get("success") is True

    acc = get_accounts_and_balance_sheet(family_id=1)
    assert "monarch_core_burn_calibration" in acc
    assert "calibrated_core_burn" in acc["monarch_core_burn_calibration"]


def test_simulate_financial_scenario_drawdown_order_and_lp():
    """Verify simulate_financial_scenario accepts drawdown_order and accelerate_lp_calls."""
    assert simulate_financial_scenario(family_id=0) == {}
    res = simulate_financial_scenario(family_id=1, drawdown_order="roth_preservation", accelerate_lp_calls=True, trials=50)
    assert res.get("success") is True
    assert res.get("drawdown_order") == "roth_preservation"
    assert res.get("accelerate_lp_calls") is True


def test_build_active_tab_snapshots():
    """Verify active tab pre-grounding for holdings, estate, and overview sections."""
    assert _build_active_tab_snapshot(family_id=0, active_tab="section-holdings") == {}
    snap_h = _build_active_tab_snapshot(family_id=1, active_tab="section-holdings")
    assert "lp_commitment_book" in snap_h

    snap_est = _build_active_tab_snapshot(family_id=1, active_tab="section-estate")
    assert "estate_summary" in snap_est and "survivorship_audit" in snap_est

    snap_ov = _build_active_tab_snapshot(family_id=1, active_tab="section-overview")
    assert "survivorship_audit" in snap_ov
