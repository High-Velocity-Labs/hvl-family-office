"""One resolver for the effective plan (F-ENG-7) and a safe Monte Carlo process pool (F-ENG-6)."""

import dataclasses
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool

import pytest

from forecast import monte_carlo
from forecast.hierarchy import EffectivePlan, normalize_guardrail_mode, resolve_effective_plan
from forecast.orchestrator_params import resolve_scenario_run_params

BASE = {
    "primary_retirement_age": 60, "spouse_retirement_age": 62, "annual_living_spend": 200_000.0,
    "annual_savings": 50_000.0, "inflation_rate": 0.03, "primary_ss_claim_age": 67,
    "spouse_ss_claim_age": 67, "spending_guardrail_mode": "moderate",
}
NO_FLAGS = {k: False for k in ("spending", "savings", "primary_ret", "spouse_ret", "inflation", "primary_ss", "spouse_ss", "guardrails")}


def test_deliberate_zero_is_kept_not_replaced_by_base():
    plan = resolve_effective_plan({"annual_living_spend": 0.0, "annual_savings": 0}, BASE, NO_FLAGS, True)
    assert plan.annual_living_spend == 0.0
    assert plan.annual_savings == 0
    assert plan.primary_retirement_age == 60


def test_explicit_run_argument_wins_only_on_the_target():
    flags = {**NO_FLAGS, "spending": True}
    scen = {"annual_living_spend": 90_000.0}
    assert resolve_effective_plan(scen, BASE, flags, True).annual_living_spend == 200_000.0
    assert resolve_effective_plan(scen, BASE, flags, False).annual_living_spend == 90_000.0


def test_ss_claim_age_precedence_and_guardrail_normalisation():
    plan = resolve_effective_plan({"ss_claim_age": 70, "spouse_ss_claim_age": 65}, BASE, NO_FLAGS, False)
    assert (plan.primary_ss_claim_age, plan.spouse_ss_claim_age) == (70, 65)
    assert resolve_effective_plan({"spending_guardrail_mode": "AGGRESSIVE"}, BASE, NO_FLAGS, False).spending_guardrail_mode == "aggressive"
    assert normalize_guardrail_mode(None) == normalize_guardrail_mode("bogus") == "off"


def test_effective_plan_is_frozen():
    plan = resolve_effective_plan({}, BASE, NO_FLAGS, True)
    assert isinstance(plan, EffectivePlan)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.annual_living_spend = 1.0


def test_run_params_use_the_resolver_and_keep_zero_savings():
    scen = {"id": "s1", "annual_savings": 0, "annual_living_spend": 120_000.0}
    p = resolve_scenario_run_params(scen, "s1", NO_FLAGS, {**BASE, "start_year": 2026}, None, [], (0.5, 0.2, 0.2, 0.1, 0.5, 0.3, 0.2), {})
    assert p["scen_savings"] == 0
    assert scen["annual_savings"] == 0
    assert p["scen_spending"] == 120_000.0


class _FakePool:
    def __init__(self, future):
        self.future, self.shutdowns, self.terminated = future, 0, 0

    def submit(self, fn, **kw):
        return self.future

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdowns += 1

    def terminate_workers(self):
        self.terminated += 1


class _TimedOut(Future):
    def result(self, timeout=None):
        raise FutureTimeoutError()


def test_pool_timeout_kills_workers_and_raises_without_inline_rerun(monkeypatch):
    pool = _FakePool(_TimedOut())
    monkeypatch.setattr(monte_carlo, "_MC_PROCESS_POOL", pool)
    monkeypatch.setattr(monte_carlo, "_execute_monte_carlo_kernel", lambda **kw: pytest.fail("inline re-run"))
    with pytest.raises(monte_carlo.MonteCarloPoolError):
        monte_carlo._run_kernel_in_pool({})
    assert (pool.terminated, pool.shutdowns) == (1, 1)
    assert monte_carlo._MC_PROCESS_POOL is None


def test_broken_pool_is_discarded_and_raises(monkeypatch):
    fut = Future()
    fut.set_exception(BrokenProcessPool("dead"))
    pool = _FakePool(fut)
    monkeypatch.setattr(monte_carlo, "_MC_PROCESS_POOL", pool)
    with pytest.raises(monte_carlo.MonteCarloPoolError):
        monte_carlo._run_kernel_in_pool({})
    assert monte_carlo._MC_PROCESS_POOL is None


def test_pool_uses_forkserver(monkeypatch):
    monkeypatch.setattr(monte_carlo, "_MC_PROCESS_POOL", None)
    try:
        pool = monte_carlo._get_mc_process_pool()
        assert pool._mp_context.get_start_method() == "forkserver"
        assert monte_carlo._get_mc_process_pool() is pool
    finally:
        monte_carlo._shutdown_mc_process_pool()
