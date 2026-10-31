"""
Forecast modelling contracts: one capital-market-assumptions table drives the plan and Monte Carlo,
Monte Carlo uses the household's real allocation, the plan simulates in nominal dollars with
inflated flows (deflating only for display), and the projection and tax year follow the calendar.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecast import cache as forecast_cache
from forecast import monte_carlo, tax_indexing
from forecast.capital_market_assumptions import ASSET_CLASS_ASSUMPTIONS, resolve_portfolio_weights
from plan_kwargs import run_simulation


def _precomputed(weights, growth=None, factor=1.0):
    scen = {"id": "scen_baseline", "name": "Plan", "inflation_rate": 0.025, "portfolio_weights": weights, **(growth or {})}
    return {
        "success": True, "active_scenario_id": "scen_baseline", "scenarios": [scen],
        "scorecard": [{"id": "scen_baseline", "retirement_readiness": {"primary_planned_year": 2035}}],
        "scenario_schedules": {"scen_baseline": [
            {"year": 2026 + i, "age_primary": 50 + i, "liquid_assets": 2_000_000.0 if i == 0 else 0.0,
             "retirement_assets": 0.0, "real_estate_net": 0.0, "company_equity": 0.0,
             "net_cash_flow": -80_000.0, "to_todays_dollars": factor}
            for i in range(10)
        ]},
    }


def _mc(sim):
    res = monte_carlo.run_monte_carlo_simulation(family_id=0, trials=200, seed=7, precomputed_sim=sim, sandbox=False)
    assert res["success"] is True
    return res


def test_monte_carlo_uses_the_household_allocation_and_keeps_a_zero_weight_at_zero():
    """F-ENG-3: an all-cash household is simulated as all cash, not as the old fixed 60/20/15/5."""
    cash_only = _mc(_precomputed({"us_equity": 0.0, "intl_equity": 0.0, "bonds": 0.0, "cash": 1.0}))
    equity_only = _mc(_precomputed({"us_equity": 1.0, "intl_equity": 0.0, "bonds": 0.0, "cash": 0.0}))

    assert cash_only["portfolio_stats"]["w_us"] == 0.0
    assert cash_only["portfolio_stats"]["expected_return"] == ASSET_CLASS_ASSUMPTIONS["cash"]["mean"]
    assert equity_only["portfolio_stats"]["expected_return"] == ASSET_CLASS_ASSUMPTIONS["us_equity"]["mean"]


def test_monte_carlo_uses_the_scenario_return_assumptions_over_the_table():
    """F-ENG-3: Monte Carlo and the deterministic plan share one set of return assumptions."""
    res = _mc(_precomputed({"us_equity": 1.0}, growth={"growth_us_equity": 0.05}))
    assert res["portfolio_stats"]["expected_return"] == 0.05


def test_monte_carlo_without_an_allocation_fails_instead_of_assuming_one():
    sim = _precomputed({})
    res = monte_carlo.run_monte_carlo_simulation(family_id=0, trials=200, precomputed_sim=sim, sandbox=False)
    assert res["success"] is False


def test_monte_carlo_result_does_not_depend_on_the_view_mode():
    """F-ENG-4: the same plan shown in nominal and in today's dollars gives the same Monte Carlo result."""
    nominal = _precomputed({"us_equity": 0.6, "bonds": 0.4})
    real = _precomputed({"us_equity": 0.6, "bonds": 0.4})
    for i, (n_row, r_row) in enumerate(zip(nominal["scenario_schedules"]["scen_baseline"], real["scenario_schedules"]["scen_baseline"])):
        price_index = 1.025 ** i
        for key in ("liquid_assets", "net_cash_flow"):
            n_row[key] = r_row[key] * price_index
        n_row["to_todays_dollars"] = 1.0 / price_index

    n_res, r_res = _mc(nominal), _mc(real)
    assert n_res["success_rate_age_100"] == pytest.approx(r_res["success_rate_age_100"])
    assert n_res["success_rate_age_85"] == pytest.approx(r_res["success_rate_age_85"])


def _simulate(view_mode, **kwargs):
    params = dict(
        events=[], liquid_start=5_000_000.0, retirement_start=0.0, real_estate_start=0.0,
        mortgage_start=0.0, other_start=0.0, family_id=0, view_mode=view_mode,
        annual_spending=100_000.0, inflation_rate=0.03, primary_retirement_age=150, spouse_retirement_age=150,
        start_year=2026,
    )
    params.update(kwargs)
    return run_simulation(**params)


def test_spending_grows_with_inflation_and_real_view_shows_it_in_todays_dollars():
    """F-ENG-4: spending is inflated in the simulation and deflated exactly once for display."""
    nominal = _simulate("nominal")["schedule"]
    real = _simulate("real")["schedule"]

    assert nominal[10]["living_spending"] == pytest.approx(100_000.0 * 1.03 ** 10, rel=1e-6)
    assert real[10]["living_spending"] == pytest.approx(100_000.0, rel=1e-6)
    for n_row, r_row in zip(nominal, real):
        assert n_row["liquid_assets"] * n_row["to_todays_dollars"] == pytest.approx(r_row["liquid_assets"], rel=1e-6)
        assert r_row["to_todays_dollars"] == 1.0


def test_projection_starts_in_the_given_year_and_defaults_to_this_year():
    """F-ENG-5: the first projected year is the as-of year, not a hard-coded 2026."""
    assert _simulate("nominal", start_year=2031)["schedule"][0]["year"] == 2031
    assert _simulate("nominal", start_year=None)["schedule"][0]["year"] == date.today().year


def test_tax_thresholds_are_indexed_for_later_years():
    """F-ENG-5: a raise that only keeps pace with inflation does not push the household into a higher bracket.
    (Kept below the fixed $250k Additional Medicare threshold, which is deliberately not indexed.)"""
    base = tax_indexing.household_take_home_pay(150_000.0, 0.0, tax_year=2026, inflation_rate=0.03, user_state="TX")
    later = tax_indexing.household_take_home_pay(150_000.0 * 1.03 ** 10, 0.0, tax_year=2036, inflation_rate=0.03, user_state="TX")

    assert later["effective_tax_rate"] == pytest.approx(base["effective_tax_rate"], abs=1e-4)
    assert later["total_tax"] == pytest.approx(base["total_tax"] * 1.03 ** 10, rel=1e-4)


def test_wa_millionaire_tax_applies_from_2028_in_projections():
    """F-ENG-5: the projection passes the tax year, so the WA 2028 rule switches on in 2028."""
    y2027 = tax_indexing.household_take_home_pay(3_000_000.0, 0.0, tax_year=2027, inflation_rate=0.0, user_state="WA")
    y2028 = tax_indexing.household_take_home_pay(3_000_000.0, 0.0, tax_year=2028, inflation_rate=0.0, user_state="WA")
    assert y2027["state_tax"] == 0.0
    assert y2028["state_tax"] > 0.0


def test_lp_call_schedule_starts_in_the_given_year(monkeypatch):
    import services.private_markets_service as pms

    monkeypatch.setattr(pms, "get_lp_commitments", lambda family_id=0: [{"unfunded_commitment": 300_000.0, "expected_call_horizon_years": 3}])
    assert pms.get_lp_call_schedule(family_id=42, start_year=2030) == {2030: 100_000.0, 2031: 100_000.0, 2032: 100_000.0}


def test_forecast_cache_key_changes_with_the_projection_year(monkeypatch):
    def _key_in(year):
        class _Fixed(date):
            @classmethod
            def today(cls):
                return date(year, 6, 1)

        monkeypatch.setattr(forecast_cache, "date", _Fixed)
        return forecast_cache.make_cache_key(0, "test", {})

    assert _key_in(2026) == _key_in(2026)
    assert _key_in(2026) != _key_in(2027)


def test_portfolio_weights_come_from_the_whole_household_allocation_once():
    """F-ENG-3: $1M taxable cash plus a $1M 401k in US equity is 50/50, with nothing counted twice."""
    snapshot = {"detailed_asset_allocation": {"totals": {"us_equity": 1_000_000.0, "cash_liquid": 1_000_000.0}}}
    weights = resolve_portfolio_weights(snapshot)
    assert weights["us_equity"] == 0.5
    assert weights["cash"] == 0.5
    assert weights["intl_equity"] == 0.0 and weights["bonds"] == 0.0
    assert weights["source"] == "holdings"


def test_portfolio_weights_without_holdings_data_are_labelled_assumed():
    assert resolve_portfolio_weights({})["source"] == "assumed"


def test_monte_carlo_bands_are_reported_in_the_schedule_dollars():
    """F-ENG-4: in future-dollars view the Monte Carlo bands are in future dollars, matching the plan lines."""
    real = _precomputed({"us_equity": 0.6, "bonds": 0.4})
    nominal = _precomputed({"us_equity": 0.6, "bonds": 0.4})
    for i, row in enumerate(nominal["scenario_schedules"]["scen_baseline"]):
        price_index = 1.025 ** i
        row["liquid_assets"] *= price_index
        row["net_cash_flow"] *= price_index
        row["to_todays_dollars"] = 1.0 / price_index

    r_res, n_res = _mc(real), _mc(nominal)
    last = len(r_res["percentiles_timeline"]) - 1
    assert n_res["percentiles_timeline"][last]["p50"] == pytest.approx(r_res["percentiles_timeline"][last]["p50"] * 1.025 ** last, rel=1e-6)
    assert n_res["median_terminal_wealth"] == pytest.approx(r_res["median_terminal_wealth"] * 1.025 ** last, rel=1e-6)


def test_waterfall_passes_each_projection_year_and_inflation_to_the_tax_engine(monkeypatch):
    """F-ENG-5: the waterfall taxes each year under that year's (indexed) law."""
    seen = []
    real_fn = tax_indexing.household_take_home_pay

    def _spy(*args, **kwargs):
        seen.append((kwargs["tax_year"], kwargs["inflation_rate"]))
        return real_fn(*args, **kwargs)

    monkeypatch.setattr(tax_indexing, "household_take_home_pay", _spy)
    _simulate("nominal", start_year=2027)
    assert seen[:3] == [(2027, 0.03), (2028, 0.03), (2029, 0.03)]


def test_roth_bracket_fill_ceiling_is_indexed_to_the_conversion_year():
    """Auditor M1: a 2036 fill-to-22% conversion uses the 2036 bracket, not the 2026 one."""
    from forecast.event_amounts import EventIndexer
    from forecast.scenarios import ROTH_AUTO_BRACKETS, process_roth_or_72t_event

    ev = {"roth_strategy_preset": "fill_22", "primary_birth_year": 1975, "name": "Roth"}
    retire_after, _, _ = process_roth_or_72t_event(
        ev, "Roth", 61, 10_000_000.0, 0.0, 0.0, [], year=2036, price_index=1.03 ** 10, inflation_rate=0.03,
        indexer=EventIndexer(start_year=2026, inflation_rate=0.03, education_inflation_rate=0.05),
    )
    converted = 10_000_000.0 - retire_after
    assert converted == pytest.approx(ROTH_AUTO_BRACKETS["fill_22"]["ceiling"] * 1.03 ** 10, rel=1e-6)


def test_event_without_a_year_fires_in_the_first_projection_year():
    """Auditor M3: an undated one-time event happens at the start of the plan, whatever the calendar year."""
    ev = {"id": "e1", "category": "capital_outflow", "name": "One-off", "amount": 50_000.0}
    sched = _simulate("nominal", start_year=2031, events=[ev])["schedule"]
    hits = [row["year"] for row in sched if any("One-off" in e for e in row["events_occurred"])]
    assert hits == [2031]


def test_additional_medicare_threshold_is_not_indexed():
    """The $250k Additional Medicare threshold is fixed in statute, so later years pay more of it."""
    from services import tax_engine

    later = tax_indexing.household_take_home_pay(500_000.0, 0.0, tax_year=2040, inflation_rate=0.03, user_state="TX")
    expected = tax_engine.calculate_medicare_tax(500_000.0, is_mfj=True)["total_medicare"]
    assert later["medicare_tax"] == pytest.approx(expected, abs=0.01)


def _spread_sim(liquid, cash_flow, home_equity, years=56):
    scen = {"id": "scen_baseline", "name": "Plan", "inflation_rate": 0.025,
            "portfolio_weights": {"us_equity": 0.6, "intl_equity": 0.2, "bonds": 0.2}}
    return {
        "success": True, "active_scenario_id": "scen_baseline", "scenarios": [scen],
        "scorecard": [{"id": "scen_baseline", "retirement_readiness": {"primary_planned_year": 2035}}],
        "scenario_schedules": {"scen_baseline": [
            {"year": 2026 + i, "age_primary": 45 + i, "liquid_assets": liquid if i == 0 else 0.0,
             "retirement_assets": 0.0, "real_estate_net": home_equity, "company_equity": 0.0,
             "net_cash_flow": cash_flow, "to_todays_dollars": 1.0}
            for i in range(years)
        ]},
    }


def test_funded_plan_has_return_spread():
    res = monte_carlo.run_monte_carlo_simulation(family_id=0, trials=200, seed=3, precomputed_sim=_spread_sim(4_000_000, -60_000, 1_000_000), sandbox=False)
    assert res["p10_terminal_wealth"] < res["median_terminal_wealth"] < res["p90_terminal_wealth"]
    assert res["success_rate_age_85"] > 50.0


def test_unfunded_plan_reports_failure_and_terminal_wealth_is_the_non_liquid_floor():
    """Every path depletes, so terminal wealth is only the (deterministic) home equity: p10 = median = p90 is the truthful result."""
    res = monte_carlo.run_monte_carlo_simulation(family_id=0, trials=200, seed=3, precomputed_sim=_spread_sim(3_000_000, -360_000, 1_000_000), sandbox=False)
    assert res["success_rate_age_100"] < 5.0
    assert res["p10_terminal_wealth"] == res["median_terminal_wealth"] == res["p90_terminal_wealth"] == 1_000_000.0
    early = res["percentiles_timeline"][1]
    assert early["p10"] < early["p90"]  # returns are sampled while the portfolio still exists
