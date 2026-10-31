"""
State and equity tax: one state-rate source, NSO/RSU state tax, the ISO regular-tax and AMT model, equity income after a
move, no state-specific defaults for other households, and a household-derived state for every equity tax figure.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app  # noqa: F401  (imports the package graph in application order)
from equity import iso_amt, simulator
from equity.models import EquityGrant
from forecast import presets, waterfall_equity
from forecast.waterfall_events import process_year_events
from services import residence_state, tax_calculations as tc
from services.advisor import context as advisor_context
from services.advisor import tools_core


def _grant(gtype: str, strike: float = 10.0, vested: float = 10000.0, unvested: float = 0.0) -> EquityGrant:
    return EquityGrant(
        grant_id=f"g_{gtype}", nickname=gtype, grant_date="2024-01-01", grant_type=gtype,
        strike_price=strike, total_granted=vested + unvested, sold_quantity=0.0, owned_exercised=0.0,
        unexercised_vested=vested, unvested=unvested, company_id=1, company_name="Co",
    )


# --- 1. one source of truth for state rates -------------------------------------------------------------------------

def test_equity_path_reads_state_rates_from_tax_calculations():
    assert waterfall_equity.STATE_INCOME_TAX_RATES == tc.state_income_tax_rates()
    assert not hasattr(waterfall_equity, "_UNPROFILED_STATE_TOP_RATES")
    assert tc.state_income_tax_rates()["MA"] == pytest.approx(0.09)  # 5% plus the 4% surtax
    assert tc.state_income_tax_rates()["WA"] == 0.0


def test_nso_event_taxes_the_ca_household_with_the_profile_rate_and_a_nv_household_nothing():
    def run(state: str) -> float:
        pools = {"G1": {"options": 1000.0, "strike": 10.0, "active": True, "nickname": "G1"}}
        inflow = waterfall_equity.process_company_equity_event(
            ev={"year": 2027, "action": "cashless_repurchase"}, share_price=1010.0, options_pools=pools,
            primary_earned_income=300000.0, spouse_earned_income=0.0, liquid_bal=0.0, yearly_event_inflow=0.0,
            events_occurred=[], year=2027, effective_user_state=state, filing_status="MFJ",
        )[1]
        return inflow

    spread = 1_000_000.0
    state_tax = tc.state_ordinary_income_tax("CA", 300000.0, spread, tax_year=2027)
    assert state_tax == pytest.approx(spread * 0.133)
    assert run("NV") - run("CA") == pytest.approx(state_tax)
    assert run("") == pytest.approx(run("NV"))  # an unset state is no state tax, not another state's rules


# --- 2. NSO and RSU state tax -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("gtype", ["nso", "rsu"])
def test_vest_and_spread_take_the_households_state_income_tax(gtype):
    grant = _grant(gtype)
    res = grant.calculate_at_price(100.0, False, 200000.0, state="CA")
    spread = res["spread"]
    base = grant.calculate_at_price(100.0, False, 200000.0, state="NV")
    assert res["option_tax"]["state_tax"] == pytest.approx(tc.state_ordinary_income_tax("CA", 200000.0, spread))
    assert res["total_tax_drag"] - base["total_tax_drag"] == pytest.approx(res["option_tax"]["state_tax"])
    assert base["option_tax"]["state_tax"] == 0.0


@pytest.mark.parametrize("gtype", ["nso", "rsu"])
def test_wa_compensation_pays_the_millionaire_tax_over_1m_never_the_capital_gains_rate(gtype):
    grant = _grant(gtype, vested=20000.0)
    on = grant.calculate_at_price(110.0, True, 500000.0, state="WA")
    off = grant.calculate_at_price(110.0, False, 500000.0, state="WA")
    spread = on["spread"]
    taxable_over_1m = 500000.0 + spread - 1_000_000.0
    assert on["option_tax"]["state_tax"] == pytest.approx(taxable_over_1m * 0.099)
    assert off["option_tax"]["state_tax"] == 0.0  # no WA wage tax before SB 6346


def test_non_wa_household_never_pays_wa_rates_even_with_the_wa_toggle_on():
    grant = _grant("nso", vested=20000.0)
    tx = grant.calculate_at_price(110.0, True, 500000.0, state="TX")
    assert tx["option_tax"]["state_tax"] == 0.0
    sim = simulator.simulate_valuation_scenario(
        share_price=110.0, include_wa_millionaire_tax=True, prior_w2_income=500000.0,
        grants=[_grant("nso", vested=20000.0, unvested=20000.0)], state="TX",
    )
    assert sim["wa_tax_difference"] == 0.0
    assert sim["unvested_net_value"] == pytest.approx(2_000_000.0 * (1 - 0.3935))


def test_unvested_value_uses_the_wage_tax_not_the_wa_capital_gains_rate():
    # 10,000 unvested at spread 100 = $1M; over $1M only the part above the threshold bears the WA wage tax.
    grants = [_grant("nso", strike=0.0, vested=0.0, unvested=20000.0)]
    off = simulator.simulate_valuation_scenario(
        share_price=100.0, prior_w2_income=500000.0, grants=grants, state="WA",
    )
    assert off["unvested_net_value"] == pytest.approx(2_000_000.0 * (1 - 0.3935))  # old code took 7% here
    on = simulator.simulate_valuation_scenario(
        share_price=100.0, include_wa_millionaire_tax=True, prior_w2_income=500000.0, grants=grants, state="WA",
    )
    assert on["unvested_net_value"] == pytest.approx(2_000_000.0 * (1 - 0.3935) - 1_500_000.0 * 0.099)


def test_owned_stock_sale_takes_wa_excise_only_for_a_wa_household():
    grant = _grant("nso", vested=0.0)
    grant.owned_exercised, grant.historical_cost_basis = 10000.0, 10.0
    wa = grant.calculate_at_price(110.0, False, 500000.0, state="WA")["stock_tax"]
    tx = grant.calculate_at_price(110.0, False, 500000.0, state="TX")["stock_tax"]
    ca = grant.calculate_at_price(110.0, False, 500000.0, state="CA")["stock_tax"]
    gain = 1_000_000.0
    assert tx["wa_capital_gains_tax"] == 0.0 and tx["state_capital_gains_tax"] == 0.0
    assert wa["state_capital_gains_tax"] == pytest.approx(tc.state_capital_gains_tax("WA", gain))
    assert wa["state_capital_gains_tax"] > 0
    assert ca["state_capital_gains_tax"] == pytest.approx(gain * 0.133)
    assert wa["total_tax"] - tx["total_tax"] == pytest.approx(wa["state_capital_gains_tax"])


def _exercise_tool(monkeypatch, state: str, grant_type: str = "nso", **kwargs):
    monkeypatch.setattr(tools_core, "_resolve_tool_family_id", lambda family_id=0: 1)
    monkeypatch.setattr(
        tools_core, "get_cash_flow_summary", lambda family_id=0: {"tax_filing_status": "MFJ", "state_residence": state},
    )
    monkeypatch.setattr(tools_core.equity_engine, "get_company_409a_price", lambda family_id=0, company_id=None: 100.0)
    return tools_core.estimate_equity_exercise_tax(
        family_id=1, shares_to_exercise=20000.0, strike_price=0.0 if grant_type == "rsu" else 50.0, share_price=100.0,
        grant_type=grant_type, **kwargs,
    )


def test_advisor_exercise_estimate_applies_wa_only_to_wa_households(monkeypatch):
    nv = _exercise_tool(monkeypatch, "NV", include_wa_millionaire_tax=True, tax_year=2028)
    assert nv["wa_state_tax"] == 0.0 and nv["state_income_tax"] == 0.0 and nv["wa_sb6346_tax_if_exercised_2028_plus"] == 0.0
    wa = _exercise_tool(monkeypatch, "WA", include_wa_millionaire_tax=True, tax_year=2028)
    assert wa["wa_state_tax"] > 0 and wa["total_tax_liability"] > nv["total_tax_liability"]
    ca = _exercise_tool(monkeypatch, "CA")
    assert ca["state_income_tax"] == pytest.approx(ca["gross_spread"] * 0.133)
    assert ca["wa_state_tax"] == 0.0
    rsu = _exercise_tool(monkeypatch, "CA", grant_type="rsu")
    assert rsu["gross_spread"] == 2_000_000.0 and rsu["total_strike_cost"] == 0.0
    assert rsu["state_income_tax"] == pytest.approx(2_000_000.0 * 0.133)


def test_advisor_stock_sale_estimate_has_no_wa_tax_for_a_tx_household(monkeypatch):
    res = _exercise_tool(monkeypatch, "TX", grant_type="common")
    assert res["wa_capital_gains_tax"] == 0.0 and res["state_capital_gains_tax"] == 0.0


# --- 3. ISO regular tax and AMT ---------------------------------------------------------------------------------------

def test_amt_exemption_phases_out_at_50_percent_over_the_2026_thresholds():
    assert iso_amt.amt_exemption(1_000_000.0, "MFJ") == 140_200.0
    assert iso_amt.amt_exemption(1_100_000.0, "MFJ") == pytest.approx(90_200.0)
    assert iso_amt.amt_exemption(2_000_000.0, "MFJ") == 0.0
    assert iso_amt.amt_exemption(600_000.0, "SINGLE") == pytest.approx(40_100.0)


def test_tentative_minimum_tax_uses_26_and_28_percent_bands():
    # (500,000 - 140,200) = 359,800: 26% of the first 244,500 and 28% of the rest
    assert iso_amt.tentative_minimum_tax(500_000.0, "MFJ") == pytest.approx(244_500 * 0.26 + 115_300 * 0.28)


def test_iso_exercise_amt_is_tmt_over_regular_tax_and_becomes_a_credit():
    res = iso_amt.iso_exercise_amt(300_000.0, 200_000.0, "MFJ")
    assert res["amt"] == pytest.approx(res["tentative_minimum_tax"] - res["regular_tax"])
    assert res["amt"] > 0
    assert res["amt_credit_carryforward"] == res["amt"]
    low = iso_amt.iso_exercise_amt(10_000.0, 100_000.0, "MFJ")
    assert low["amt"] == 0.0 and low["amt_credit_carryforward"] == 0.0  # regular tax already exceeds the TMT
    assert iso_amt.iso_exercise_amt(0.0, 500_000.0)["amt"] == 0.0


def test_iso_regular_income_by_disposition():
    # strike 10, FMV at exercise 50
    assert iso_amt.iso_regular_income(100, 10, 50, 80, "hold") == {"ordinary_income": 0.0, "capital_gain": 0.0}
    assert iso_amt.iso_regular_income(100, 10, 50, 80, "qualifying") == {"ordinary_income": 0.0, "capital_gain": 7000.0}
    # disqualifying: lesser of spread at exercise (40) and gain (70) is ordinary, the rest capital gain
    assert iso_amt.iso_regular_income(100, 10, 50, 80, "disqualifying") == {
        "ordinary_income": 4000.0, "capital_gain": 3000.0,
    }
    # sold below the exercise FMV: ordinary income is only the gain actually realized
    assert iso_amt.iso_regular_income(100, 10, 50, 30, "disqualifying") == {
        "ordinary_income": 2000.0, "capital_gain": 0.0,
    }
    with pytest.raises(ValueError):
        iso_amt.iso_regular_income(100, 10, 50, 80, "whenever")


def test_iso_hold_owes_no_regular_tax_only_amt_and_a_disqualifying_sale_erases_the_preference():
    grant = _grant("iso", strike=10.0, vested=20000.0)
    held = grant.calculate_at_price(100.0, state="CA", iso_disposition="hold", prior_income=500_000.0)["option_tax"]
    assert held["regular_tax"] == 0.0 and held["state_tax"] == 0.0
    assert held["amt_preference"] == 1_800_000.0 and held["amt_exercise_tax"] > 0
    assert held["total_tax"] == held["amt_exercise_tax"]
    assert held["amt_credit_carryforward"] == held["amt_exercise_tax"]
    dq = grant.calculate_at_price(100.0, state="CA", iso_disposition="disqualifying", prior_income=500_000.0)["option_tax"]
    assert dq["amt_preference"] == 0.0 and dq["amt_exercise_tax"] == 0.0
    # all-ordinary disqualifying sale: federal ordinary tax and CA ordinary tax, no Medicare, no NIIT
    assert dq["medicare_tax"] == 0.0
    assert dq["state_tax"] == pytest.approx(tc.state_ordinary_income_tax("CA", 500000.0, 1_800_000.0))
    qual = grant.calculate_at_price(100.0, state="CA", iso_disposition="qualifying", prior_income=500_000.0)["option_tax"]
    # the gain stacks on $500k of income less the $32,200 deduction: 15% to the $613,700 band top, 20% above
    assert qual["federal_tax"] == pytest.approx(145_900.0 * 0.15 + (1_800_000.0 - 145_900.0) * 0.20)
    assert qual["state_tax"] == pytest.approx(1_800_000.0 * 0.133)
    assert dq["total_tax"] > qual["total_tax"]


# --- 4. equity income after a move ------------------------------------------------------------------------------------

def _year_events(events, year, user_state, override=None):
    pools = {"G1": {"options": 1000.0, "strike": 10.0, "active": True, "nickname": "G1"}}
    out = process_year_events(
        events=events, year=year, liquid_bal=0.0, retire_bal=0.0, re_bal=0.0, mortgage_bal=0.0, other_bal=0.0,
        share_price=1010.0, options_pools=pools, edu_reserves={}, primary_earned_income=300000.0,
        spouse_earned_income=0.0, earned_income_multiplier=1.0, active_tax_state_override=override,
        active_state_tax_delta_rate=0.0, mortgage_annual_service=0.0, is_working=True, age_primary=45,
        context=SimpleNamespace(options_aliases=None), family_id=0, user_state=user_state, start_year=2027,
    )
    return out[0], out[10]  # liquid balance, active state override


def test_equity_after_a_move_is_taxed_by_the_new_state_on_the_event_date():
    sale = {"id": "s", "category": "company_equity", "year": 2028, "end_year": 2028, "action": "cashless_repurchase"}
    move = {"id": "m", "category": "state_relocation", "year": 2027, "origin_state": "CA", "target_state": "NV"}
    before_move, _ = _year_events([sale], 2028, "CA")
    liquid_after_move, state_after = _year_events([sale], 2028, "CA", override="NV")
    assert state_after == "NV"
    spread = 1_000_000.0
    assert liquid_after_move - before_move == pytest.approx(tc.state_ordinary_income_tax("CA", 300000.0, spread))
    # the move event itself switches the state in its own year, before equity events in that year are taxed
    same_year_sale = {**sale, "year": 2027, "end_year": 2027}
    liquid_same_year, state_same_year = _year_events([same_year_sale, move], 2027, "CA")
    assert state_same_year == "NV"
    assert liquid_same_year == pytest.approx(liquid_after_move - 35000.0)


# --- 5. no WA-centric defaults ----------------------------------------------------------------------------------------

def test_default_arbitrage_comparison_starts_from_the_home_state_and_leaves_wa_out_for_others():
    tx = tc.compare_state_tax_arbitrage(1_000_000.0, home_state="TX")
    codes = [s["state_code"] for s in tx["states"]]
    assert codes[0] == "TX" and "WA" not in codes and "WA_2028" not in codes
    assert tx["nevada_arbitrage_savings_vs_wa_2028"] == 0.0 and tx["california_penalty_vs_wa"] == 0.0
    assert all(s["savings_vs_wa_2028"] == 0.0 for s in tx["states"])
    wa = tc.compare_state_tax_arbitrage(3_000_000.0, home_state="WA")
    wa_codes = [s["state_code"] for s in wa["states"]]
    assert wa_codes[:3] == ["WA", "WA_2028", "NV"]
    assert wa["nevada_arbitrage_savings_vs_wa_2028"] > 0


def test_advisor_prompts_use_the_households_state():
    assert "WA" not in advisor_context._state_comparison_prompt({"state": "TX"})
    assert advisor_context._state_comparison_prompt({"state": "TX"}).startswith("Compare our 5-year tax")
    assert "TX" in advisor_context._state_comparison_prompt({"state": "TX"})
    unset = advisor_context._state_comparison_prompt({"state": ""})
    assert "WA" not in unset and "NV" not in unset
    assert advisor_context._home_state_name({"state": "CO"}) == "Colorado"
    assert advisor_context._home_state_name({}) == "our state"
    prompt = advisor_context._format_fiduciary_system_prompt({"state": "TX", "family_name": "T"})
    assert "SB 6346" not in prompt
    assert "Not set" in advisor_context._format_fiduciary_system_prompt({"state": "", "family_name": "T"})


@pytest.mark.parametrize(
    ("home", "origin", "target", "savings"),
    [("TX", "TX", "NV", 0.0), ("WA", "WA", "NV", 0.0), ("NV", "NV", "TX", 0.0), ("CA", "CA", "NV", 0.133)],
)
def test_relocation_preset_moves_away_from_the_households_own_state(monkeypatch, home, origin, target, savings):
    monkeypatch.setattr(presets, "household_state", lambda family_id=0: home)
    ev = next(e for e in presets.get_default_event_catalog(family_id=0) if e["id"] == "evt_state_relocation")
    assert (ev["origin_state"], ev["target_state"]) == (origin, target)
    assert ev["state_tax_savings_rate"] == pytest.approx(savings)
    assert f"{origin} \u2192 {target}" in ev["name"]


def test_relocation_preset_for_an_unset_household_claims_no_origin_or_savings(monkeypatch):
    monkeypatch.setattr(presets, "household_state", lambda family_id=0: residence_state.UNSET)
    ev = next(e for e in presets.get_default_event_catalog(family_id=0) if e["id"] == "evt_state_relocation")
    assert ev["origin_state"] == "" and ev["state_tax_savings_rate"] == 0.0 and "CA" not in ev["name"]


# --- 6. the state always comes from the household ---------------------------------------------------------------------

def test_equity_drag_takes_the_state_from_the_household_when_no_state_is_passed(monkeypatch):
    seen = []
    monkeypatch.setattr(simulator, "household_state", lambda family_id=0: seen.append(family_id) or "CA")
    grants = [_grant("nso", vested=1000.0)]
    implicit = simulator.simulate_valuation_scenario(share_price=100.0, grants=grants)
    explicit = simulator.simulate_valuation_scenario(share_price=100.0, grants=grants, state="CA")
    nv = simulator.simulate_valuation_scenario(share_price=100.0, grants=grants, state="NV")
    assert seen == [0]  # id 0 resolves to the current request's household, never to "no state"
    assert implicit["total_tax_drag"] == explicit["total_tax_drag"]
    assert implicit["total_tax_drag"] - nv["total_tax_drag"] == pytest.approx(
        tc.state_ordinary_income_tax("CA", 500000.0, implicit["total_taxable_spread"]),
    )
    assert implicit["total_tax_drag"] > nv["total_tax_drag"] > 0


def test_household_state_resolves_the_current_household_when_no_id_is_given(monkeypatch):
    from services import household_tax_state

    monkeypatch.setattr("services.request_context.get_current_family_id", lambda: 5)
    monkeypatch.setattr("db.families.get_household_profile", lambda family_id=0, db_path=None: {"state": "co"})
    assert household_tax_state.household_state(0) == "CO"
    monkeypatch.setattr("db.families.get_household_profile", lambda family_id=0, db_path=None: {"state": "ND"})
    assert household_tax_state.household_state(3) == residence_state.UNSET  # a state the engines do not model
    monkeypatch.setattr("services.request_context.get_current_family_id", lambda: 0)
    assert household_tax_state.household_state(0) == residence_state.UNSET


# --- F-ENG-17 follow-ups: the sale producer owns the WA gate; filing status and income reach every sale ----------------

def test_stock_sale_for_state_charges_wa_excise_once_and_other_states_their_own_rate():
    from equity.state_tax import stock_sale_tax_for_state

    wa = stock_sale_tax_for_state(2_278_000.0, 0.0, 0.0, "WA", 2027)
    assert wa["wa_capital_gains_tax"] == pytest.approx(169_000.0) == pytest.approx(wa["state_capital_gains_tax"])
    ca = stock_sale_tax_for_state(2_278_000.0, 0.0, 0.0, "CA", 2027)
    assert ca["wa_capital_gains_tax"] == 0.0 and ca["state_capital_gains_tax"] == pytest.approx(2_278_000.0 * 0.133)
    tx = stock_sale_tax_for_state(2_278_000.0, 0.0, 0.0, "TX", 2027)
    assert tx["state_capital_gains_tax"] == 0.0
    # same federal part everywhere; only the state part differs
    assert wa["total_tax"] - wa["state_capital_gains_tax"] == pytest.approx(tx["total_tax"])


def test_stock_sale_for_state_uses_filing_status_and_other_income():
    from equity.state_tax import stock_sale_tax_for_state

    hoh = stock_sale_tax_for_state(100_000.0, 0.0, 60_000.0, "TX", 2027, "HOH")
    single = stock_sale_tax_for_state(100_000.0, 0.0, 60_000.0, "TX", 2027, "SINGLE")
    assert hoh["federal_capital_gains_tax"] == pytest.approx((100_000.0 - (66_200.0 - 35_850.0)) * 0.15)
    assert single["federal_capital_gains_tax"] == pytest.approx((100_000.0 - (49_450.0 - 43_900.0)) * 0.15)
    poor = stock_sale_tax_for_state(100_000.0, 0.0, 0.0, "TX", 2027, "HOH")
    assert poor["federal_capital_gains_tax"] < hoh["federal_capital_gains_tax"]


def test_held_share_sale_event_passes_income_and_status_and_has_no_wa_workaround():
    def net(state: str, status: str, earned: float, **ev) -> float:
        lots = {"G1": {"options": 0.0, "strike": 10.0, "active": False, "nickname": "G1"}}
        return waterfall_equity.process_company_equity_event(
            ev={"year": 2027, "action": "sell_held_shares", "options_quantity": 30_000.0, "cost_basis_per_share": 10.0, **ev},
            share_price=110.0, options_pools=lots, primary_earned_income=earned, spouse_earned_income=0.0,
            liquid_bal=0.0, yearly_event_inflow=0.0, events_occurred=[], year=2027, owned_shares_count=30_000.0,
            effective_user_state=state, filing_status=status,
        )[1]

    # 100k gain: low earned income lets HOH use the 0% band, high earned income does not
    assert net("TX", "HOH", 20_000.0) > net("TX", "HOH", 300_000.0)
    assert net("TX", "HOH", 90_000.0) > net("TX", "SINGLE", 90_000.0)
    # WA excise only for WA households; a WA household that opts out of WA tax pays none
    assert net("TX", "MFJ", 500_000.0) == net("", "MFJ", 500_000.0)
    assert net("WA", "MFJ", 500_000.0, exempt_wa_tax=True) == pytest.approx(net("TX", "MFJ", 500_000.0))
    wa_excise = tc.state_capital_gains_tax("WA", 3_000_000.0, 2027)
    assert net("TX", "MFJ", 500_000.0) - net("WA", "MFJ", 500_000.0, include_wa_tax=True) == pytest.approx(wa_excise)
    # the excise applies to WA residents before 2028 without the wage-tax toggle (in force since 2022)
    assert net("TX", "MFJ", 500_000.0) - net("WA", "MFJ", 500_000.0) == pytest.approx(wa_excise)


def test_iso_gain_stacks_on_income_by_filing_status():
    grant = _grant("iso", strike=10.0, vested=1000.0)
    low = grant.calculate_at_price(110.0, state="TX", iso_disposition="qualifying", prior_income=20_000.0,
                                   filing_status="HOH")["option_tax"]
    high = grant.calculate_at_price(110.0, state="TX", iso_disposition="qualifying", prior_income=700_000.0,
                                    filing_status="HOH")["option_tax"]
    assert low["federal_tax"] < high["federal_tax"] == pytest.approx(100_000.0 * 0.20)
    assert low["medicare_tax"] == 0.0  # under the NIIT threshold
    assert high["medicare_tax"] == pytest.approx(100_000.0 * 0.038)


def test_advisor_sale_estimate_uses_household_income_and_status(monkeypatch):
    res = _exercise_tool(monkeypatch, "TX", grant_type="common")
    assert res["federal_ltcg_tax"] >= 0.0
