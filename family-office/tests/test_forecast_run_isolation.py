"""
Forecast runs are isolated from each other: per-scenario run parameters travel as explicit
arguments (never module globals), simulate-only plans never touch the household forecast cache,
and private-markets data is never invented.
"""

from __future__ import annotations

import copy
import threading

import pytest

from forecast import cache as forecast_cache
from forecast import engine as forecast_engine
from plan_kwargs import run_simulation


def _simulate_with_lp_calls(lp_call_schedule, drawdown_order):
    return run_simulation(
        events=[], liquid_start=1_000_000.0, retirement_start=0.0, real_estate_start=0.0,
        mortgage_start=0.0, other_start=0.0, family_id=1, view_mode="nominal",
        lp_call_schedule=lp_call_schedule, drawdown_order=drawdown_order,
    )


def test_concurrent_simulations_keep_their_own_lp_calls_and_drawdown_order():
    """F-ENG-1: two simulations running at once never see each other's LP call schedule."""
    schedules = {
        "a": ({2026: 50_000.0}, "taxable_first"),
        "b": ({2027: 80_000.0}, "pretax_first"),
    }
    results = {}
    start = threading.Barrier(len(schedules))

    def _run(name):
        start.wait()
        results[name] = [_simulate_with_lp_calls(*schedules[name]) for _ in range(5)]

    threads = [threading.Thread(target=_run, args=(n,)) for n in schedules]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for name, (lp_schedule, _) in schedules.items():
        for sim in results[name]:
            calls = {
                row["year"]: row["yearly_outflow"]
                for row in sim["schedule"]
                if any("Private LP Capital Call" in e for e in row["events_occurred"])
            }
            assert calls == lp_schedule


def test_simulation_without_lp_schedule_projects_no_capital_calls():
    sim = _simulate_with_lp_calls(None, None)
    assert not any("Private LP Capital Call" in e for row in sim["schedule"] for e in row["events_occurred"])


@pytest.mark.usefixtures("household_1")
def test_simulate_only_plan_never_reads_or_writes_the_household_forecast_cache():
    """F-ENG-9: a hypothetical plan is simulated from explicit state, and the real cached plan is untouched."""
    from services.request_context import get_current_universe
    from ssr.scenarios import build_ssr_scenarios

    real_ssr, real_raw = build_ssr_scenarios(family_id=1)
    assert real_raw
    base_key = forecast_cache.make_cache_key(1, get_current_universe(), {})
    cached_before = forecast_cache.get_simulation(base_key)
    assert cached_before is not None

    hypothetical = copy.deepcopy(forecast_engine.load_scenario_state(family_id=1))
    for scen in hypothetical.get("scenarios", []):
        scen["annual_living_spend"] = 9_999_999.0
    _, hypo_raw = build_ssr_scenarios(family_id=1, scenario_state=hypothetical)

    hypo_spend = {s["annual_living_spend"] for s in hypo_raw["scenarios"]}
    real_spend = {s["annual_living_spend"] for s in real_raw["scenarios"]}
    assert hypo_spend == {9_999_999.0}
    assert 9_999_999.0 not in real_spend
    assert forecast_cache.get_simulation(base_key) == cached_before
    assert forecast_engine.load_scenario_state.__module__ == "forecast.storage"


def test_private_accounts_seed_lp_positions_without_invented_terms(monkeypatch, tmp_path):
    """F-ENG-2: a connected private account carries only its NAV; no commitment, calls, vintage or mark date are made up."""
    import security
    import services.private_markets_service as pms
    import ssr.formatting

    monkeypatch.setattr(
        ssr.formatting, "get_private_investments_data",
        lambda family_id=0: {"items": [{"account_id": "acct-1", "name": "Seed Fund", "current_value": 400_000.0}]},
    )
    monkeypatch.setattr(security, "db_load_encrypted", lambda *a, **k: None)

    items = pms.get_lp_commitments(family_id=42)
    assert len(items) == 1
    fund = items[0]
    assert fund["current_nav"] == 400_000.0
    assert fund["total_commitment"] == 0.0
    assert fund["capital_called"] == 0.0
    assert fund["unfunded_commitment"] == 0.0
    assert fund["distributions_received"] == 0.0
    assert fund["vintage_year"] is None
    assert fund["last_mark_date"] == ""
    assert pms.get_lp_call_schedule(family_id=42) == {}


def test_household_without_lp_data_gets_no_demo_funds(monkeypatch):
    """F-ENG-2: no household (including family 1) falls back to demo LP commitments at runtime."""
    import security
    import services.private_markets_service as pms
    import ssr.formatting

    monkeypatch.setattr(ssr.formatting, "get_private_investments_data", lambda family_id=0: {"items": []})
    monkeypatch.setattr(security, "db_load_encrypted", lambda *a, **k: None)

    assert pms.get_lp_commitments(family_id=1) == []
    assert pms.get_lp_call_schedule(family_id=1) == {}


def test_advisor_fund_update_keeps_every_field_it_was_not_given(monkeypatch):
    """Updating one field of a stored fund never resets its type, vintage, horizon, K-1 status or account link."""
    from services.advisor import tools_operations

    stored = {
        "id": "lp_acc_1", "account_id": "acct-1", "fund_name": "Seed Fund", "fund_type": "Venture",
        "vintage_year": 2019, "total_commitment": 500_000.0, "capital_called": 300_000.0,
        "unfunded_commitment": 150_000.0, "distributions_received": 20_000.0, "current_nav": 400_000.0,
        "last_mark_date": "2026-06-30", "expected_call_horizon_years": 2, "k1_status": "Received", "notes": "terms",
    }
    saved = {}
    monkeypatch.setattr(tools_operations, "_resolve_tool_family_id", lambda family_id=0: 42)
    monkeypatch.setattr(tools_operations, "_is_read_only_mode", lambda: False)
    monkeypatch.setattr(tools_operations.pms, "get_lp_commitments", lambda family_id=0: [dict(stored)])
    monkeypatch.setattr(tools_operations.pms, "save_lp_commitment", lambda family_id=0, item_data=None: saved.update(item_data) or item_data)
    monkeypatch.setattr(tools_operations, "get_private_markets_lp_book", lambda family_id=0: {"summary": {}})

    tools_operations.manage_lp_commitment(action="upsert", commitment_id="lp_acc_1", current_nav=450_000.0)

    assert saved["current_nav"] == 450_000.0
    for key in ("id", "account_id", "fund_type", "vintage_year", "total_commitment", "capital_called",
                "unfunded_commitment", "distributions_received", "last_mark_date",
                "expected_call_horizon_years", "k1_status", "notes"):
        assert saved[key] == stored[key], key


def test_advisor_fund_update_recomputes_unfunded_when_terms_change(monkeypatch):
    from services.advisor import tools_operations

    stored = {"id": "lp_1", "fund_name": "Seed Fund", "total_commitment": 500_000.0,
              "capital_called": 300_000.0, "unfunded_commitment": 200_000.0}
    saved = {}
    monkeypatch.setattr(tools_operations, "_resolve_tool_family_id", lambda family_id=0: 42)
    monkeypatch.setattr(tools_operations, "_is_read_only_mode", lambda: False)
    monkeypatch.setattr(tools_operations.pms, "get_lp_commitments", lambda family_id=0: [dict(stored)])
    monkeypatch.setattr(tools_operations.pms, "save_lp_commitment", lambda family_id=0, item_data=None: saved.update(item_data) or item_data)
    monkeypatch.setattr(tools_operations, "get_private_markets_lp_book", lambda family_id=0: {"summary": {}})

    tools_operations.manage_lp_commitment(action="upsert", commitment_id="lp_1", capital_called=450_000.0)

    assert saved["unfunded_commitment"] == 50_000.0


def test_monte_carlo_never_swaps_a_failed_unsaved_plan_for_the_stored_one(monkeypatch):
    from forecast import monte_carlo
    import forecast.orchestrator as orchestrator

    def _must_not_run(**_kwargs):
        raise AssertionError("stored plan was simulated in place of the supplied one")

    monkeypatch.setattr(orchestrator, "simulate_multi_scenarios", _must_not_run)
    res = monte_carlo.run_monte_carlo_simulation(family_id=42, trials=100, precomputed_sim={"success": False}, sandbox=False)
    assert res["success"] is False


def test_position_without_mark_date_is_unknown_not_stale():
    import services.private_markets_service as pms

    item = pms._compute_metrics({"current_nav": 1.0, "last_mark_date": ""})
    assert item["is_mark_unknown"] is True
    assert item["is_mark_stale"] is False
