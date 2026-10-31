"""
Test entry point to the single-scenario engine.

`forecast.waterfall.run_scenario_simulation` has no defaults for the plan values (they come from the scenario's
`EffectivePlan`). A test that exercises the waterfall with only the inputs it cares about calls `run_simulation`,
which supplies the plan below for everything the test leaves out and keeps the `retirement_age` / `ss_claim_age`
shorthands of the tests' older style.
"""

from __future__ import annotations

from typing import Any, Dict

from forecast.capital_market_assumptions import DEFAULT_EDUCATION_INFLATION_RATE
from forecast.waterfall import run_scenario_simulation

TEST_PLAN: Dict[str, Any] = {
    "primary_retirement_age": 65,
    "spouse_retirement_age": 65,
    "annual_spending": 0.0,
    "annual_savings": 0.0,
    "inflation_rate": 0.025,
    "primary_ss_claim_age": 67,
    "spouse_ss_claim_age": 67,
    "education_inflation_rate": DEFAULT_EDUCATION_INFLATION_RATE,
}


def run_simulation(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """`run_scenario_simulation` with `TEST_PLAN` filling every plan value the caller did not pass."""
    retirement_age = kwargs.pop("retirement_age", None)
    if retirement_age is not None:
        kwargs.setdefault("primary_retirement_age", retirement_age)
        kwargs.setdefault("spouse_retirement_age", retirement_age)
    ss_claim_age = kwargs.pop("ss_claim_age", None)
    if ss_claim_age is not None:
        kwargs.setdefault("primary_ss_claim_age", ss_claim_age)
        kwargs.setdefault("spouse_ss_claim_age", ss_claim_age)
    return run_scenario_simulation(*args, **{**TEST_PLAN, **kwargs})
