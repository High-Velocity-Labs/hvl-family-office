"""
Tests for Multi-Strategy Company Equity Exercise Events & Scenario Assumptions in AI Advisor Tools.
Verifies shared-event catalog isolation, distinct trajectories across the option strategies
(cashless repurchase, hold with cash cover, hold with sell-to-cover, 10-year staged exercise,
two-stage exercise & hold + secondary sale), annual cash-flow detail fields, scenario-scoped
Monte Carlo stress tests, and custom equity growth / bulk child scenario cleanup.
"""

from __future__ import annotations
import copy
import re
import pytest

import db
import security
import forecast_engine
from services.advisor.tools_chief_of_staff import get_annual_cash_flow_detail
from services.advisor.tools_core import get_monte_carlo_stress_test
from services.advisor.tools_scenarios import (
    enrich_scenarios_and_events_payload,
    manage_scenario_life_event,
)
from services.advisor.tools_scenarios_equity import (
    normalize_custom_equity_growth_rate,
    normalize_equity_action,
    update_scenario_assumptions,
)
from services.advisor.tools_tabs import ALL_ADVISOR_TOOLS, get_scenarios_and_forecast_plan


def _parse_currency_str(val_str: str) -> float:
    """Parses formatted currency strings like '$14.2M', '$850K', or '$1,234,567' into float."""
    if not val_str or val_str == "--":
        return 0.0
    s = str(val_str).strip().upper().replace(",", "").replace("$", "")
    mult = 1.0
    if s.endswith("M"):
        mult = 1e6
        s = s[:-1]
    elif s.endswith("B"):
        mult = 1e9
        s = s[:-1]
    elif s.endswith("K"):
        mult = 1e3
        s = s[:-1]
    m = re.search(r"[-+]?\d*\.?\d+", s)
    return float(m.group(0)) * mult if m else 0.0


@pytest.fixture(autouse=True)
def restore_family1_scenario_state():
    """Preserves and restores Family 1 scenario state around each test."""
    orig_state = copy.deepcopy(forecast_engine.load_scenario_state(family_id=1))
    yield
    forecast_engine.save_scenario_state(orig_state, family_id=1)


def test_equity_helper_normalization_and_tool_registration():
    """Verify action/growth normalization and registration of update_scenario_assumptions."""
    tool_names = {t.__name__ for t in ALL_ADVISOR_TOOLS}
    assert "manage_scenario_life_event" in tool_names
    assert "update_scenario_assumptions" in tool_names

    assert normalize_equity_action("cashless_repurchase") == "cashless_repurchase"
    assert normalize_equity_action("sell_all") == "cashless_repurchase"
    assert normalize_equity_action("exercise_and_hold_cash") == "exercise_and_hold_cash"
    assert normalize_equity_action("hold_cash_cover") == "exercise_and_hold_cash"
    assert normalize_equity_action("exercise_and_hold_sell_to_cover") == "exercise_and_hold_sell_to_cover"
    assert normalize_equity_action("sell_to_cover") == "exercise_and_hold_sell_to_cover"
    assert normalize_equity_action("sell_held_shares") == "sell_held_shares"
    assert normalize_equity_action("secondary_sale") == "sell_held_shares"

    assert normalize_custom_equity_growth_rate(None) is None
    assert normalize_custom_equity_growth_rate(14.0) == pytest.approx(0.14)
    assert normalize_custom_equity_growth_rate(0.085) == pytest.approx(0.085)

    assert update_scenario_assumptions(family_id=0).get("status") == "unavailable"


def test_four_company_equity_strategies_isolation_and_trajectories():
    """
    Verify creating 4 child scenarios via manage_scenario_life_event with the same event_name
    produces 4 independent scenarios with distinct event IDs (zero shared-event mutation)
    and distinct liquid portfolio / company equity / net worth trajectories.
    """
    shared_event_title = "Exercise Vested Company Options"

    res_sell = manage_scenario_life_event(
        family_id=1, action="upsert", create_child_scenario_name="Strategy A: Sell All 2027",
        event_name=shared_event_title, category="company_equity",
        equity_action="cashless_repurchase", start_year=2027, end_year=2027,
    )
    res_hold_cash = manage_scenario_life_event(
        family_id=1, action="upsert", create_child_scenario_name="Strategy B: Hold (Cash Cover)",
        event_name=shared_event_title, category="company_equity",
        equity_action="exercise_and_hold_cash", start_year=2027, end_year=2027,
    )
    res_hold_stc = manage_scenario_life_event(
        family_id=1, action="upsert", create_child_scenario_name="Strategy C: Hold (Sell-to-Cover)",
        event_name=shared_event_title, category="company_equity",
        equity_action="exercise_and_hold_sell_to_cover", start_year=2027, end_year=2027,
    )
    res_staged = manage_scenario_life_event(
        family_id=1, action="upsert", create_child_scenario_name="Strategy D: 10-Yr Staged (2027-2036)",
        event_name=shared_event_title, category="company_equity",
        equity_action="cashless_repurchase", start_year=2027, end_year=2036,
    )

    ev_ids = {
        res_sell["event"]["id"], res_hold_cash["event"]["id"],
        res_hold_stc["event"]["id"], res_staged["event"]["id"],
    }
    assert len(ev_ids) == 4

    state = forecast_engine.load_scenario_state(family_id=1)
    events_by_id = {e["id"]: e for e in state.get("events", [])}
    assert events_by_id[res_sell["event"]["id"]]["action"] == "cashless_repurchase"
    assert events_by_id[res_hold_cash["event"]["id"]]["action"] == "exercise_and_hold_cash"
    assert events_by_id[res_hold_stc["event"]["id"]]["action"] == "exercise_and_hold_sell_to_cover"
    assert events_by_id[res_staged["event"]["id"]]["end_year"] == 2036

    cf_sell_2027 = res_sell["event_window_cash_flow"][0]
    cf_cash_2027 = res_hold_cash["event_window_cash_flow"][0]
    cf_stc_2027 = res_hold_stc["event_window_cash_flow"][0]
    cf_staged_window = res_staged["event_window_cash_flow"]

    assert cf_sell_2027["events_inflow"] > 0
    assert cf_sell_2027["liquid_portfolio"] > cf_stc_2027["liquid_portfolio"] > cf_cash_2027["liquid_portfolio"]
    assert cf_cash_2027["events_outflow"] > cf_stc_2027["events_outflow"]
    assert cf_stc_2027["events_outflow"] == pytest.approx(cf_sell_2027["events_outflow"])
    assert cf_cash_2027["company_equity"] > cf_stc_2027["company_equity"] > cf_sell_2027["company_equity"]
    assert len(cf_staged_window) == 10
    assert 0 < cf_staged_window[0]["events_inflow"] < cf_sell_2027["events_inflow"]


def test_update_scenario_assumptions_equity_growth_divergence_and_delete():
    """
    Verify update_scenario_assumptions adjusts custom_equity_growth_rate on an exercise_and_hold
    scenario and causes its long-term net worth (nw_age_65, nw_age_85) to diverge upward.
    """
    res_sell = manage_scenario_life_event(
        family_id=1, action="upsert", create_child_scenario_name="Sell All Baseline Growth",
        event_name="Sell All Options", category="company_equity",
        equity_action="cashless_repurchase", start_year=2027, end_year=2027,
    )
    manage_scenario_life_event(
        family_id=1, action="upsert", create_child_scenario_name="Hold Shares Growth Test",
        event_name="Hold Options STC", category="company_equity",
        equity_action="exercise_and_hold_sell_to_cover", start_year=2027, end_year=2027,
    )

    low_growth = update_scenario_assumptions(
        family_id=1, scenario_name="Hold Shares Growth Test", custom_equity_growth_rate=0.05,
    )
    high_growth = update_scenario_assumptions(
        family_id=1, scenario_name="Hold Shares Growth Test", custom_equity_growth_rate=14.0,
    )
    assert high_growth["assumptions"]["custom_equity_growth_rate"] == pytest.approx(0.14)

    nw65_sell = _parse_currency_str(res_sell["after_metrics"]["nw_age_65"])
    nw65_low = _parse_currency_str(low_growth["after_metrics"]["nw_age_65"])
    nw65_high = _parse_currency_str(high_growth["after_metrics"]["nw_age_65"])
    nw85_sell = _parse_currency_str(res_sell["after_metrics"]["nw_age_85"])
    nw85_high = _parse_currency_str(high_growth["after_metrics"]["nw_age_85"])

    assert nw65_high > nw65_low
    assert nw65_high > nw65_sell
    assert nw85_high > nw85_sell

    enriched = enrich_scenarios_and_events_payload(family_id=1, scenario_name="Hold Shares Growth Test")
    hold_info = enriched["scenarios_by_name"]["Hold Shares Growth Test"]
    assert hold_info["assumptions"]["custom_equity_growth_rate"] == pytest.approx(0.14)
    assert hold_info["assumptions"]["equity_growth_preset"] == "aggressive"

    forbid_del = update_scenario_assumptions(family_id=1, scenario_id="scen_baseline", delete_scenario=True)
    assert forbid_del["status"] == "forbidden"


def test_two_stage_hold_and_sell_held_shares_plus_cf_detail_mc_and_cleanup():
    """
    Verify two-stage strategy (exercise_and_hold_cash in 2027 + sell_held_shares in 2032),
    get_annual_cash_flow_detail fields, scenario-scoped get_monte_carlo_stress_test,
    and delete_all_child_scenarios cleanup.
    """
    plan_name = "Two-Stage Hold 2027 & Sell 2032"
    stage1 = manage_scenario_life_event(
        family_id=1, action="upsert", create_child_scenario_name=plan_name,
        event_name="2027 Exercise & Hold", category="company_equity",
        equity_action="exercise_and_hold_cash", start_year=2027, end_year=2027,
    )
    assert stage1["status"] == "saved"

    stage2 = manage_scenario_life_event(
        family_id=1, action="upsert", scenario_name=plan_name,
        event_name="2032 Secondary Sale", category="company_equity",
        equity_action="sell_held_shares", start_year=2032, end_year=2032,
        cost_basis_per_share=12.50,
    )
    assert stage2["status"] == "saved"
    assert stage2["event"]["action"] == "sell_held_shares"
    assert stage2["event"]["cost_basis_per_share"] == pytest.approx(12.50)

    # Both events coexist on the same scenario
    enriched = enrich_scenarios_and_events_payload(family_id=1, scenario_name=plan_name)
    scen_evts = enriched["scenarios_by_name"][plan_name]["enabled_events"]
    eq_actions = {e.get("action") for e in scen_evts if e.get("category") == "company_equity"}
    assert {"exercise_and_hold_cash", "sell_held_shares"}.issubset(eq_actions)

    # Check get_annual_cash_flow_detail in 2027 (hold) vs 2031 (pre-sale) vs 2032 (sale)
    cf_2027 = get_annual_cash_flow_detail(family_id=1, year=2027, scenario_name=plan_name)
    cf_2031 = get_annual_cash_flow_detail(family_id=1, year=2031, scenario_name=plan_name)
    cf_2032 = get_annual_cash_flow_detail(family_id=1, year=2032, scenario_name=plan_name)

    assert "company_equity" in cf_2027 and "event_inflows" in cf_2027 and "events_outflow" in cf_2027
    assert cf_2027["events_outflow"] > 0
    assert cf_2031["company_equity"] > 0
    assert cf_2032["company_equity"] == pytest.approx(0.0)
    assert cf_2032["event_inflows"] > 0
    assert cf_2032["liquid_portfolio"] > cf_2031["liquid_portfolio"]

    # Scenario-scoped Monte Carlo stress test
    mc_res = get_monte_carlo_stress_test(family_id=1, trials=100, scenario_name=plan_name)
    assert mc_res.get("scenario_name") == plan_name
    assert mc_res.get("scenario_id") == stage1["scenario_id"]

    # Bulk child scenario cleanup preserves only Baseline
    del_all = update_scenario_assumptions(family_id=1, delete_all_child_scenarios=True)
    assert del_all["status"] == "deleted_all_children"
    assert del_all["deleted_count"] >= 1
    assert plan_name in del_all["deleted_scenario_names"]

    after_plan = get_scenarios_and_forecast_plan(family_id=1)
    assert plan_name not in after_plan["scenarios_by_name"]
    assert any(s.get("is_baseline") for s in after_plan["scenarios_by_name"].values())


def test_unmatched_scenario_name_promotes_to_child_with_clean_overrides_and_numbered_isolation():
    """
    Verify calling manage_scenario_life_event with an unmatched scenario_name (without create_child_scenario_name)
    creates a new child scenario off Baseline with 0 default overrides and a descriptive equity event name,
    isolates numbered scenario prefixes ('1. ...' vs '2. ...'), and setting custom_equity_growth_rate=12
    produces exactly 1 override ('custom_equity_growth_rate').
    """
    res1 = manage_scenario_life_event(
        family_id=1,
        action="upsert",
        scenario_name="1. Pre-2028 Exercise & Sell All",
        category="company_equity",
        equity_action="cashless_repurchase",
        start_year=2027,
        end_year=2027,
    )
    assert res1["status"] == "saved"
    assert res1["scenario_name"] == "1. Pre-2028 Exercise & Sell All"
    assert res1["scenario_id"] != "scen_baseline"
    assert res1["event"]["name"] == "Exercise & Sell Options (2027)"

    res2 = manage_scenario_life_event(
        family_id=1,
        action="upsert",
        scenario_name="2. Pre-2028 Exercise & Sell All",
        category="company_equity",
        equity_action="exercise_and_hold_cash",
        start_year=2027,
        end_year=2027,
    )
    assert res2["status"] == "saved"
    assert res2["scenario_name"] == "2. Pre-2028 Exercise & Sell All"
    assert res2["scenario_id"] not in ("scen_baseline", res1["scenario_id"])
    assert res2["event"]["name"] == "Exercise & Hold (Cash Cover, 2027)"

    state = forecast_engine.load_scenario_state(family_id=1)
    s1 = next(s for s in state["scenarios"] if s["id"] == res1["scenario_id"])
    base_s = next(s for s in state["scenarios"] if s.get("is_baseline") or s["id"] == "scen_baseline")
    assert s1.get("overrides") == {}
    assert res1["event"]["id"] not in (base_s.get("event_ids") or [])

    upd = update_scenario_assumptions(
        family_id=1,
        scenario_name="1. Pre-2028 Exercise & Sell All",
        custom_equity_growth_rate=12.0,
    )
    assert upd["status"] == "saved"
    state_after = forecast_engine.load_scenario_state(family_id=1)
    s1_after = next(s for s in state_after["scenarios"] if s["id"] == res1["scenario_id"])
    assert s1_after.get("overrides") == {"custom_equity_growth_rate": pytest.approx(0.12)}
