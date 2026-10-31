"""Each plan's forecast run is cached under a digest of its inputs (forecast/plan_run_cache.py): a forecast reuses
the runs of plans whose inputs did not change, and a hit is exactly the run it replaces."""

from __future__ import annotations

import copy
import json

import pytest

from forecast import orchestrator, plan_run_cache
from forecast import waterfall_withdrawals
from forecast.storage import load_scenario_state

FID = 1


@pytest.fixture
def counted(monkeypatch):
    """Counts the plan runs a forecast actually computes (cache misses)."""
    calls = {"simulate": 0, "earliest": 0}
    real_sim, real_earliest = orchestrator.run_scenario_simulation, orchestrator.find_earliest_sustainable_retirement

    def sim(**kw):
        calls["simulate"] += 1
        return real_sim(**kw)

    def earliest(**kw):
        calls["earliest"] += 1
        return real_earliest(**kw)

    monkeypatch.setattr(orchestrator, "run_scenario_simulation", sim)
    monkeypatch.setattr(orchestrator, "find_earliest_sustainable_retirement", earliest)
    plan_run_cache.clear()
    yield calls
    plan_run_cache.clear()


def _state():
    return copy.deepcopy(load_scenario_state(family_id=FID))


def _plan_results(res):
    keys = ("scorecard", "comparison_curves", "scenario_schedules", "scenario_cash_flows")
    return json.dumps({k: res.get(k) for k in keys}, sort_keys=True, default=str)


def _leaf_plan(state):
    parents = {s.get("parent_id") for s in state["scenarios"]}
    return next(s for s in state["scenarios"] if s["id"] != "scen_baseline" and s["id"] not in parents)


def test_a_second_forecast_reuses_every_plans_run_and_gets_the_same_results(counted):
    first = orchestrator.simulate_multi_scenarios(family_id=FID)
    plans = len(first["scorecard"])
    assert counted == {"simulate": plans, "earliest": plans}
    second = orchestrator.simulate_multi_scenarios(family_id=FID)
    assert counted == {"simulate": plans, "earliest": plans}, "every plan's run comes from the cache"
    assert _plan_results(second) == _plan_results(first)


def test_editing_one_leaf_plan_reruns_only_that_plan(counted):
    state = _state()
    orchestrator.simulate_multi_scenarios(family_id=FID, scenario_state=state)
    before = dict(counted)
    leaf = _leaf_plan(state)
    leaf["annual_living_spend"] = float(leaf.get("annual_living_spend") or 100_000) + 12_345
    orchestrator.simulate_multi_scenarios(family_id=FID, scenario_state=state)
    assert counted["simulate"] - before["simulate"] == 1
    assert counted["earliest"] - before["earliest"] == 1


def test_switching_an_overlay_off_and_on_again_reuses_the_earlier_runs(counted):
    on = _state()
    baseline = next(s for s in on["scenarios"] if s["id"] == "scen_baseline")
    baseline["active_baseline_layers"] = [_leaf_plan(on)["id"]]
    baseline["suspended_baseline_layers"] = []
    off = copy.deepcopy(on)
    next(s for s in off["scenarios"] if s["id"] == "scen_baseline")["suspended_baseline_layers"] = [_leaf_plan(on)["id"]]

    first = orchestrator.simulate_multi_scenarios(family_id=FID, scenario_state=copy.deepcopy(on))
    after_on = dict(counted)
    orchestrator.simulate_multi_scenarios(family_id=FID, scenario_state=copy.deepcopy(off))
    after_off = dict(counted)
    assert 0 < after_off["simulate"] - after_on["simulate"] < after_on["simulate"], "off reruns only what it changes"
    again = orchestrator.simulate_multi_scenarios(family_id=FID, scenario_state=copy.deepcopy(on))
    assert counted == after_off, "switching back on reruns nothing"
    assert _plan_results(again) == _plan_results(first)


def test_a_cached_run_is_a_private_copy(counted):
    first = orchestrator.simulate_multi_scenarios(family_id=FID)
    plan_id = first["scorecard"][0]["id"]
    expected = json.dumps(first["scenario_schedules"][plan_id], sort_keys=True, default=str)
    for row in first["scenario_schedules"][plan_id]:
        row["total_net_worth"] = -1
    second = orchestrator.simulate_multi_scenarios(family_id=FID)
    assert json.dumps(second["scenario_schedules"][plan_id], sort_keys=True, default=str) == expected


def test_a_plan_run_reads_nothing_from_the_database(counted, monkeypatch):
    """The cache keys a run by its arguments only, which holds while the run never falls back to the database."""
    def fail(**_kwargs):
        raise AssertionError("a plan run read household data outside its arguments")

    monkeypatch.setattr(waterfall_withdrawals, "get_child_ledger_expense_for_year", fail)
    monkeypatch.setattr(waterfall_withdrawals, "child_has_tuition_ledger", fail)
    orchestrator.simulate_multi_scenarios(family_id=FID)


def test_the_key_keeps_key_types_apart_and_refuses_inputs_it_cannot_hash():
    assert plan_run_cache.run_key({1: "a"}) != plan_run_cache.run_key({"1": "a"})
    assert plan_run_cache.run_key({"a": 1, "b": 2}) == plan_run_cache.run_key({"b": 2, "a": 1})
    with pytest.raises(TypeError):
        plan_run_cache.run_key({"x": object()})
