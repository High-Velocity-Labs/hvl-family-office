"""Forecast benefit engines: Social Security from earnings, ACA household size and per-adult coverage,
charitable AGI limits, and event-loan amortization."""

from __future__ import annotations

import pytest

from forecast import charitable_limits, mortgage_amortization as amort, social_security as ss
from forecast.benefit_constants import SS_WAGE_BASE_2026, aca_poverty_line
from forecast.context import HouseholdContext
from forecast.event_amounts import EventIndexer
from forecast.household_roster import HouseholdRoster
from forecast.scenarios import process_pre65_healthcare_event
from plan_kwargs import run_simulation
from forecast.waterfall_withdrawals import compute_social_security, process_real_estate_event


# ---- Social Security ----------------------------------------------------------------------------------------------

def test_ssa_2026_constants():
    assert SS_WAGE_BASE_2026 == 184_500.0
    assert ss.SS_BEND_POINTS_2026 == (1_286.0, 7_749.0)


def test_pia_formula_bend_points():
    assert ss.pia_monthly_from_aime(1_000.0) == pytest.approx(900.0)
    assert ss.pia_monthly_from_aime(5_000.0) == pytest.approx(0.9 * 1_286 + 0.32 * (5_000 - 1_286))
    top = 0.9 * 1_286 + 0.32 * (7_749 - 1_286) + 0.15 * (15_375 - 7_749)
    assert ss.pia_monthly_from_aime(15_375.0) == pytest.approx(top)


def test_pia_caps_earnings_at_wage_base_and_scales_with_career_length():
    full = ss.annual_pia_from_earnings(184_500.0, 65)
    assert ss.annual_pia_from_earnings(900_000.0, 65) == pytest.approx(full)
    assert full == pytest.approx(12 * (0.9 * 1_286 + 0.32 * (7_749 - 1_286) + 0.15 * (15_375 - 7_749)))
    assert ss.career_years(65) == 35 and ss.career_years(50) == 28 and ss.career_years(20) == 0
    assert ss.annual_pia_from_earnings(100_000.0, 50) < ss.annual_pia_from_earnings(100_000.0, 65)
    assert ss.annual_pia_from_earnings(0.0, 65) == 0.0


def test_user_entered_pia_overrides_earnings():
    assert ss.resolve_annual_pia(200_000.0, 65, 30_000.0) == 30_000.0
    assert ss.resolve_annual_pia(200_000.0, 65, 0.0) == 0.0
    assert ss.resolve_annual_pia(200_000.0, 65, None) == ss.annual_pia_from_earnings(200_000.0, 65)


def test_claim_age_reduction_and_delayed_credits_apply_to_own_pia():
    kw = dict(age_spouse=70, has_spouse=False, spouse_ss_claim_age=67, primary_pia=40_000.0, spouse_pia=0.0)
    assert compute_social_security(age_primary=62, primary_ss_claim_age=62, **kw)[0] == pytest.approx(28_000.0)
    assert compute_social_security(age_primary=67, primary_ss_claim_age=67, **kw)[0] == pytest.approx(40_000.0)
    assert compute_social_security(age_primary=70, primary_ss_claim_age=70, **kw)[0] == pytest.approx(49_600.0)
    assert compute_social_security(age_primary=61, primary_ss_claim_age=62, **kw)[0] == 0.0


def test_spouse_gets_own_benefit_plus_excess_spousal_once_primary_claims():
    base = dict(has_spouse=True, primary_ss_claim_age=67, spouse_ss_claim_age=67, primary_pia=40_000.0)
    # No own record: 50% of the primary's PIA, but only after the primary claims.
    assert compute_social_security(age_primary=67, age_spouse=67, spouse_pia=0.0, **base)[1] == pytest.approx(20_000.0)
    assert compute_social_security(age_primary=66, age_spouse=67, spouse_pia=0.0, **base)[1] == 0.0
    # Own PIA of 15k: own benefit plus the 5k excess.
    assert compute_social_security(age_primary=67, age_spouse=67, spouse_pia=15_000.0, **base)[1] == pytest.approx(20_000.0)
    # Own PIA above half the primary's: no spousal top-up.
    assert compute_social_security(age_primary=67, age_spouse=67, spouse_pia=25_000.0, **base)[1] == pytest.approx(25_000.0)
    # Spousal portion is reduced for claiming at 62 (35% cut) and gets no delayed credits after 67.
    early = {**base, "spouse_ss_claim_age": 62}
    assert compute_social_security(age_primary=67, age_spouse=62, spouse_pia=0.0, **early)[1] == pytest.approx(20_000.0 * 0.65)
    late = {**base, "spouse_ss_claim_age": 70}
    assert compute_social_security(age_primary=70, age_spouse=70, spouse_pia=0.0, **late)[1] == pytest.approx(20_000.0)


def _first_ss(ctx, **kw):
    sched = run_simulation(
        events=[], liquid_start=0.0, retirement_start=0.0, real_estate_start=0.0, mortgage_start=0.0, other_start=0.0,
        family_id=0, view_mode="nominal", start_year=2026, annual_spending=0.0, inflation_rate=0.0,
        equity_annual_growth=0.0, blended_liquid_growth=0.0, blended_retire_growth=0.0, growth_real_estate=0.0,
        primary_birth_year=1959, spouse_birth_year=1959, primary_retirement_age=65, spouse_retirement_age=65,
        primary_ss_claim_age=67, spouse_ss_claim_age=67, context=ctx, **kw,
    )["schedule"]
    return sched[0]["social_security"]


def test_simulation_pays_social_security_from_each_persons_earnings_not_a_fixed_figure():
    low = HouseholdContext(user_state="TX", primary_earned_income=60_000.0, spouse_earned_income=0.0)
    high = HouseholdContext(user_state="TX", primary_earned_income=250_000.0, spouse_earned_income=0.0)
    low_ss, high_ss = _first_ss(low), _first_ss(high)
    assert low_ss != 74_700.0 and high_ss != 74_700.0
    assert high_ss > low_ss > 0
    primary_pia = ss.annual_pia_from_earnings(60_000.0, 65)
    assert low_ss == pytest.approx(primary_pia * 1.5, abs=1.0)  # own benefit + 50% spousal, both at FRA


def test_simulation_uses_entered_pia_override():
    ctx = HouseholdContext(user_state="TX", primary_earned_income=0.0, has_spouse=False, ss_pia_overrides={"primary": 36_000.0})
    assert _first_ss(ctx) == pytest.approx(36_000.0, abs=1.0)
    assert _first_ss(HouseholdContext(user_state="TX", primary_earned_income=0.0, has_spouse=False)) == 0.0


def test_ss_overrides_round_trip_through_household_profile(tmp_path, monkeypatch):
    import json
    from db import benefit_inputs as bi

    store = {"assumptions_json": "{}"}
    monkeypatch.setattr(bi, "get_household_profile", lambda **_: dict(store))
    monkeypatch.setattr(bi, "update_household_assumptions_key",
                        lambda family_id, section_key, section_value, db_path=None: store.update(
                            assumptions_json=json.dumps({**json.loads(store["assumptions_json"]), section_key: section_value})))
    assert bi.get_social_security_pia_overrides(family_id=1) == {}
    bi.set_social_security_pia_override(1, "primary", 41_000.0)
    bi.set_social_security_pia_override(1, "spouse", 12_000.0)
    assert bi.get_social_security_pia_overrides(family_id=1) == {"primary": 41_000.0, "spouse": 12_000.0}
    bi.set_social_security_pia_override(1, "spouse", None)
    assert bi.get_social_security_pia_overrides(family_id=1) == {"primary": 41_000.0}
    with pytest.raises(ValueError):
        bi.set_social_security_pia_override(1, "child", 1.0)
    with pytest.raises(ValueError):
        bi.set_social_security_pia_override(1, "primary", -1.0)


# ---- ACA ----------------------------------------------------------------------------------------------------------

def _aca(year, age_primary, roster, premium=30_000.0, earned=0.0):
    log: list[str] = []
    ev = {"category": "pre65_healthcare", "name": "ACA", "annual_premium": premium, "amount_basis": "fixed"}
    indexer = EventIndexer(start_year=2026, inflation_rate=0.0, education_inflation_rate=0.0)
    _, outflow = process_pre65_healthcare_event(
        ev=ev, year=year, age_primary=age_primary, liquid_bal=1_000_000.0, is_working=earned > 0,
        primary_earned_income=earned, spouse_earned_income=0.0, earned_income_multiplier=1.0,
        yearly_event_outflow=0.0, events_occurred=log, indexer=indexer, roster=roster,
    )
    return outflow, log


def test_poverty_line_grows_with_household_size():
    assert aca_poverty_line(2) == 21_150.0
    assert aca_poverty_line(1) == 15_650.0
    assert aca_poverty_line(4) == 32_150.0
    with pytest.raises(ValueError):
        aca_poverty_line(0)


def test_roster_counts_adults_and_dependents_by_year():
    roster = HouseholdRoster(spouse_birth_year=1976, dependent_birth_years=(2010, 2015))
    assert roster.household_size(2026) == 4
    assert roster.household_size(2034) == 3  # the 2010 child is past 23
    assert HouseholdRoster().household_size(2026) == 1


def test_larger_household_gets_a_larger_aca_subsidy():
    # Household income about 3x the two-person line: more dependents lower the ratio and the required contribution.
    magi_earned = 60_000.0
    small, _ = _aca(2030, 60, HouseholdRoster(spouse_birth_year=1970), earned=magi_earned)
    large, _ = _aca(2030, 60, HouseholdRoster(spouse_birth_year=1970, dependent_birth_years=(2015, 2017, 2019)), earned=magi_earned)
    assert large < small


def test_bridge_covers_each_adult_until_their_own_65():
    # Primary turns 65 in 2039 while the spouse (born 1976) is 63: the bridge continues for the spouse alone.
    roster = HouseholdRoster(spouse_birth_year=1976)
    # Income far above 400% of the poverty line, so the household pays the gross premium.
    both, _ = _aca(2030, 56, roster, premium=24_000.0, earned=900_000.0)
    spouse_only, log = _aca(2039, 65, roster, premium=24_000.0, earned=900_000.0)
    assert spouse_only > 0 and log, "bridge must continue for the under-65 spouse"
    assert both == pytest.approx(24_000.0) and spouse_only == pytest.approx(12_000.0)
    none_left, empty_log = _aca(2041, 67, roster)
    assert none_left == 0.0 and empty_log == []


def test_unsubsidized_premium_also_shrinks_per_covered_adult():
    roster = HouseholdRoster(spouse_birth_year=1976)
    ev = {"category": "pre65_healthcare", "annual_premium": 24_000.0, "aca_subsidy_mode": "cobra", "amount_basis": "fixed"}
    indexer = EventIndexer(start_year=2026, inflation_rate=0.0, education_inflation_rate=0.0)
    _, out = process_pre65_healthcare_event(
        ev=ev, year=2040, age_primary=66, liquid_bal=0.0, is_working=False, primary_earned_income=0.0,
        spouse_earned_income=0.0, earned_income_multiplier=1.0, yearly_event_outflow=0.0, events_occurred=[],
        indexer=indexer, roster=roster,
    )
    assert out == pytest.approx(12_000.0)


# ---- Charitable AGI limits ----------------------------------------------------------------------------------------

def test_cash_gift_capped_at_60_percent_of_agi_with_carryforward():
    ded, carry = charitable_limits.apply_agi_limits(500_000.0, 400_000.0, 0.0, 2026, [])
    assert ded == pytest.approx(300_000.0)
    assert carry == [(2026, "cash", pytest.approx(100_000.0))]


def test_appreciated_property_capped_at_30_percent_and_combined_at_60():
    ded, carry = charitable_limits.apply_agi_limits(500_000.0, 0.0, 400_000.0, 2026, [])
    assert ded == pytest.approx(150_000.0)
    assert carry == [(2026, "property", pytest.approx(250_000.0))]
    ded, _ = charitable_limits.apply_agi_limits(500_000.0, 250_000.0, 400_000.0, 2026, [])
    assert ded == pytest.approx(250_000.0 + 50_000.0)  # cash uses 250k of the 300k combined room; property gets 50k


def test_carryforward_used_next_year_oldest_first_and_expires_after_five_years():
    ded, carry = charitable_limits.apply_agi_limits(500_000.0, 0.0, 0.0, 2027, [(2026, "cash", 100_000.0)])
    assert ded == pytest.approx(100_000.0) and carry == []
    ded, carry = charitable_limits.apply_agi_limits(500_000.0, 0.0, 0.0, 2032, [(2026, "cash", 100_000.0)])
    assert ded == 0.0 and carry == []  # sixth year after the gift
    ded, carry = charitable_limits.apply_agi_limits(100_000.0, 20_000.0, 0.0, 2028, [(2026, "cash", 100_000.0)])
    assert ded == pytest.approx(60_000.0)  # current gift first, then the carryforward up to the cap
    assert carry == [(2026, "cash", pytest.approx(60_000.0))]


def test_zero_agi_deducts_nothing_and_carries_the_gift():
    ded, carry = charitable_limits.apply_agi_limits(0.0, 10_000.0, 0.0, 2026, [])
    assert ded == 0.0 and carry == [(2026, "cash", 10_000.0)]


# ---- Event-loan amortization --------------------------------------------------------------------------------------

def test_amortization_matches_closed_form_and_pays_off():
    bal, rate, n = 800_000.0, 0.06, 360
    pmt = amort.monthly_payment(bal, rate, n)
    b = bal
    for _ in range(12):
        b = b * (1 + rate / 12) - pmt
    assert amort.balance_after(bal, rate, n, 12) == pytest.approx(b)
    assert amort.balance_after(bal, rate, n, 360) == 0.0
    total = sum(amort.principal_paid_in_year(bal, rate, n, y) for y in range(1, 31))
    assert total == pytest.approx(bal)
    # Early years are mostly interest, so principal grows over the life of the loan.
    assert amort.principal_paid_in_year(bal, rate, n, 1) < amort.principal_paid_in_year(bal, rate, n, 20)
    assert amort.principal_paid_in_year(bal, rate, n, 1) < 0.40 * pmt * 12  # the old fixed 40% share overstated year 1


def test_real_estate_event_pays_down_principal_from_rate_and_balance():
    ev = {"id": "evt_re", "name": "Buy", "category": "real_estate", "re_action": "buy", "purchase_price": 1_000_000.0,
          "down_payment_pct": 0.2, "interest_rate": 0.065, "mortgage_term": "30_fixed", "amount_basis": "fixed",
          "annual_ongoing_carrying_cost": 1_000.0}
    indexer = EventIndexer(start_year=2026, inflation_rate=0.0, education_inflation_rate=0.0)
    out = process_real_estate_event(
        ev=ev, year=2027, ev_start=2026, cat="real_estate", name="Buy", liquid_bal=0.0, re_bal=1_000_000.0,
        mortgage_bal=800_000.0, yearly_event_inflow=0.0, yearly_event_outflow=0.0, events_occurred=[], indexer=indexer,
    )
    new_bal = out[2]
    assert 800_000.0 - new_bal == pytest.approx(amort.principal_paid_in_year(800_000.0, 0.065, 360, 1))
    assert out[4] - 1_000.0 == pytest.approx(amort.monthly_payment(800_000.0, 0.065, 360) * 12.0)


# ---- Social Security: no silent $0 ---------------------------------------------------------------------------------

def test_adults_with_neither_earnings_nor_entered_benefit_are_named():
    gaps = ss.adults_without_social_security
    assert gaps(HouseholdContext(primary_earned_income=0.0, spouse_earned_income=0.0), 65, 65) == ["primary", "spouse"]
    assert gaps(HouseholdContext(primary_earned_income=0.0, has_spouse=False), 65, 65) == ["primary"]
    assert gaps(HouseholdContext(ss_pia_overrides={"primary": 40_000.0, "spouse": 0.0}), 65, 65) == []
    assert gaps(HouseholdContext(primary_earned_income=90_000.0, spouse_earned_income=0.0), 65, 65) == []
    # a spouse with no record of their own still draws the spousal benefit on the primary's PIA
    assert gaps(HouseholdContext(ss_pia_overrides={"primary": 40_000.0}), 65, 65) == []
    # with a zero primary PIA there is no spousal benefit either, so the spouse is named too
    assert gaps(HouseholdContext(ss_pia_overrides={"primary": 0.0}), 65, 65) == ["spouse"]


def test_notice_renders_on_the_forecast_assumptions_card_only_when_a_gap_exists():
    from flask import render_template_string

    from app import app

    tpl = '{% include "components/scenarios/plan_card_assumptions.html" %}'
    gap = {"social_security_gaps": [{"person": "primary", "name": "Robert"}, {"person": "spouse", "name": "Karen"}]}
    with app.test_request_context():
        shown = render_template_string(tpl, ssr_scenarios=gap, render_override_tag=lambda _k: '')
        hidden = render_template_string(
            tpl, ssr_scenarios={"social_security_gaps": []}, render_override_tag=lambda _k: '')
    assert "Social Security not included — enter your benefit in Settings" in shown
    assert "Robert and Karen" in shown and 'data-action="open-settings"' in shown
    assert "notice-social-security-missing" not in hidden


def test_settings_saves_monthly_benefit_as_annual_pia_and_clears_it():
    from db.benefit_inputs import get_social_security_pia_overrides
    from services.request_context import DB_PATH
    from tests.test_api_endpoints import get_authenticated_client

    client = get_authenticated_client()
    state = client.get("/api/settings/assumptions").get_json()["assumptions"]["state"] or "TX"
    resp = client.post("/api/settings/assumptions", json={"state": state, "ss_primary_monthly": 3200, "ss_spouse_monthly": 900})
    assert resp.status_code == 200, resp.get_json()
    with client.session_transaction() as sess:
        family_id = sess.get("family_id") or 1
    assert get_social_security_pia_overrides(family_id=family_id, db_path=DB_PATH) == {
        "primary": 3200 * 12.0, "spouse": 900 * 12.0}
    assert client.post("/api/settings/assumptions", json={"state": state, "ss_spouse_monthly": None}).status_code == 200
    assert get_social_security_pia_overrides(family_id=family_id, db_path=DB_PATH) == {"primary": 3200 * 12.0}
    assert client.post("/api/settings/assumptions", json={"state": state, "ss_primary_monthly": -5}).status_code == 400
    client.post("/api/settings/assumptions", json={"state": state, "ss_primary_monthly": None})


def test_demo_personas_without_a_salary_are_seeded_with_benefits():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_demo_families as seeds

    miller = seeds._social_security_section(primary_monthly=3700.0, spouse_monthly=2800.0)["social_security"]
    assert miller == {"primary_annual_pia": 44_400.0, "spouse_annual_pia": 33_600.0}
    assert Path(seeds.__file__).read_text().count("**_social_security_section(") == 2  # Miller and Ramirez


# ---- Retention, seniors, roster ------------------------------------------------------------------------------------

def test_initial_option_retention_uses_the_household_state_tax_and_filing_status():
    from forecast.context import initial_nso_retention
    from services.tax_calculations import state_ordinary_income_tax

    ca = initial_nso_retention(1_000_000.0, 300_000.0, "CA", "MFJ")
    tx = initial_nso_retention(1_000_000.0, 300_000.0, "TX", "MFJ")
    assert tx == pytest.approx(initial_nso_retention(1_000_000.0, 300_000.0, "", "MFJ")) and ca < tx
    assert tx - ca == pytest.approx(state_ordinary_income_tax("CA", 300_000.0, 1_000_000.0) / 1_000_000.0, abs=0.01)
    # MFS is taxed on its own brackets and thresholds, not as Single.
    assert initial_nso_retention(1_000_000.0, 100_000.0, "TX", "MFS") != initial_nso_retention(
        1_000_000.0, 100_000.0, "TX", "SINGLE")


def test_seniors_count_follows_each_adults_age():
    from forecast.household_roster import seniors_65_plus

    assert seniors_65_plus(64, 70, True) == 1 and seniors_65_plus(65, 66, True) == 2
    assert seniors_65_plus(70, 70, False) == 1 and seniors_65_plus(60, 60, True) == 0


def test_waterfall_passes_the_senior_count_of_each_year_to_the_take_home_tax(monkeypatch):
    from forecast import tax_indexing

    calls = {}
    real = tax_indexing.household_take_home_pay

    def spy(*args, **kwargs):
        calls[kwargs["tax_year"]] = kwargs["seniors_65_plus"]
        return real(*args, **kwargs)

    monkeypatch.setattr(tax_indexing, "household_take_home_pay", spy)
    ctx = HouseholdContext(user_state="TX", primary_earned_income=200_000.0, spouse_earned_income=100_000.0)
    run_simulation(
        events=[], liquid_start=1e6, retirement_start=0.0, real_estate_start=0.0, mortgage_start=0.0, other_start=0.0,
        family_id=0, view_mode="nominal", start_year=2026, primary_birth_year=1963, spouse_birth_year=1959,
        primary_retirement_age=70, spouse_retirement_age=70, context=ctx,
    )
    assert calls[2026] == 1 and calls[2027] == 1 and calls[2028] == 2  # spouse 65 since 2024, primary from 2028


def test_year_events_hand_the_roster_to_the_healthcare_bridge():
    from forecast.waterfall_events import process_year_events

    def outflow(roster):
        ev = {"id": "h", "category": "pre65_healthcare", "name": "ACA", "year": 2030, "end_year": 2045,
              "annual_premium": 24_000.0, "amount_basis": "fixed", "aca_subsidy_mode": "cobra"}
        return process_year_events(
            events=[ev], year=2040, liquid_bal=0.0, retire_bal=0.0, re_bal=0.0, mortgage_bal=0.0, other_bal=0.0,
            share_price=0.0, options_pools={}, edu_reserves={}, primary_earned_income=0.0, spouse_earned_income=0.0,
            earned_income_multiplier=1.0, active_tax_state_override=None, active_state_tax_delta_rate=0.0,
            mortgage_annual_service=0.0, is_working=False, age_primary=66, context=HouseholdContext(roster=roster),
            family_id=0, start_year=2026,
        )[6]

    # Primary is 66; the spouse (born 1976) is 64, so half the plan premium is still owed.
    assert outflow(HouseholdRoster(spouse_birth_year=1976)) == pytest.approx(12_000.0)
    assert outflow(None) == 0.0


# ---- DAF gifts against the AGI caps --------------------------------------------------------------------------------

def _daf_run(asset_type, include_offset=True, amount=300_000.0):
    ev = {"id": "d", "category": "philanthropy_daf", "name": "DAF", "year": 2026, "end_year": 2026, "amount": amount,
          "annual_amount": amount, "tax_deduction_rate": 0.40, "amount_basis": "fixed", "is_outflow": True,
          "include_tax_offset": include_offset}
    if asset_type:
        ev["asset_type"] = asset_type
    ctx = HouseholdContext(user_state="TX", primary_earned_income=200_000.0, has_spouse=False)
    out = run_simulation(
        events=[ev], liquid_start=0.0, retirement_start=0.0, real_estate_start=0.0, mortgage_start=0.0,
        other_start=0.0, family_id=0, view_mode="nominal", start_year=2026, inflation_rate=0.0,
        primary_birth_year=1980, primary_retirement_age=90, context=ctx, annual_spending=0.0,
        equity_annual_growth=0.0, blended_liquid_growth=0.0, blended_retire_growth=0.0,
    )
    return out["schedule"][:3], out["cash_flow_series"][:3]


def test_daf_deduction_is_capped_by_asset_type_and_carries_forward():
    prop_sched, prop_flow = _daf_run("property")
    _, cash_flow = _daf_run("cash")
    _, default_flow = _daf_run(None)
    prop_saving = 300_000.0 - prop_flow[0]["events_outflow"]
    cash_saving = 300_000.0 - cash_flow[0]["events_outflow"]
    assert prop_saving == pytest.approx(0.40 * 0.30 * 200_000.0, rel=0.05)
    assert cash_saving == pytest.approx(0.40 * 0.60 * 200_000.0, rel=0.05)
    assert default_flow[0]["events_outflow"] == pytest.approx(prop_flow[0]["events_outflow"])  # default is securities
    # The excess is deducted in later years with no new gift: an event inflow, not a lost saving.
    assert prop_flow[1]["event_inflows"] == pytest.approx(0.40 * 0.30 * 200_000.0, rel=0.05)
    assert any("tax deduction offset" in e for e in prop_sched[1]["events_occurred"])


def test_daf_without_tax_offset_claims_no_deduction():
    _, flow = _daf_run("cash", include_offset=False, amount=50_000.0)
    assert flow[0]["events_outflow"] == pytest.approx(50_000.0) and flow[1]["event_inflows"] == 0.0


# ---- The baseline mortgage amortizes -------------------------------------------------------------------------------

def _mortgage_run(balance=300_000.0, service=None, events=None, rate=None):
    ctx = HouseholdContext(user_state="TX", primary_earned_income=0.0, has_spouse=False, mortgage_rate=rate)
    out = run_simulation(
        events=events or [], liquid_start=5e6, retirement_start=0.0, real_estate_start=800_000.0,
        mortgage_start=balance, other_start=0.0, family_id=0, view_mode="nominal", start_year=2026,
        inflation_rate=0.0, primary_birth_year=1980, primary_retirement_age=90, context=ctx, annual_spending=0.0,
        mortgage_annual_service=service, equity_annual_growth=0.0, blended_liquid_growth=0.0,
        blended_retire_growth=0.0, growth_real_estate=0.0,
    )
    return out["schedule"], out["cash_flow_series"]


def test_pay_year_follows_the_closed_form_and_stops_at_payoff():
    pmt = amort.monthly_payment(400_000.0, 0.06, 360)
    bal, paid = amort.pay_year(400_000.0, 0.06, pmt * 12.0)
    assert bal == pytest.approx(amort.balance_after(400_000.0, 0.06, 360, 12)) and paid == pytest.approx(pmt * 12.0)
    last, paid_last = amort.pay_year(5_000.0, 0.06, pmt * 12.0)
    assert last == 0.0 and 5_000.0 < paid_last < 5_100.0
    assert amort.pay_year(0.0, 0.06, 10_000.0) == (0.0, 0.0)
    flat, _ = amort.pay_year(100_000.0, 0.06, 3_000.0)  # below the monthly interest: the balance never grows
    assert flat == pytest.approx(100_000.0)


def test_baseline_rate_is_the_balance_weighted_reported_rate():
    accts = [{"balance": -300_000.0, "interest_rate": 6.0}, {"balance": -100_000.0, "interest_rate": 4.0},
             {"balance": -50_000.0, "interest_rate": 0.0}]
    assert amort.baseline_mortgage_rate(accts) == pytest.approx(0.055)
    assert amort.baseline_mortgage_rate([{"balance": -1.0, "interest_rate": 0.0}]) is None


def test_baseline_mortgage_balance_falls_and_service_stops_at_payoff():
    rate = 0.06
    service = amort.monthly_payment(300_000.0, rate, 180) * 12.0  # a 15-year payoff
    sched, flow = _mortgage_run(service=service, rate=rate)
    balances = [r["mortgage_balance"] for r in sched]
    assert balances[0] == pytest.approx(amort.balance_after(300_000.0, rate, 180, 12), rel=1e-3)
    assert all(a > b for a, b in zip(balances[:14], balances[1:15])) and balances[14] == 0.0
    assert [r["mortgage_debt_service"] for r in flow[:15]] == pytest.approx([service] * 15, rel=1e-6)
    assert all(r["mortgage_debt_service"] == 0.0 for r in flow[15:])


def test_baseline_mortgage_uses_the_default_rate_when_the_balance_sheet_has_none():
    a, _ = _mortgage_run(rate=None, service=30_000.0)
    b, _ = _mortgage_run(rate=amort.DEFAULT_BASELINE_MORTGAGE_RATE, service=30_000.0)
    assert [r["mortgage_balance"] for r in a] == [r["mortgage_balance"] for r in b]


def test_debt_payoff_event_retires_the_baseline_loan_and_its_service():
    payoff = {"id": "p", "category": "debt_payoff", "name": "Payoff", "year": 2030, "end_year": 2030,
              "amount_basis": "fixed", "amount": 1e9}
    sched, flow = _mortgage_run(service=24_000.0, events=[payoff], rate=0.06)
    assert sched[3]["mortgage_balance"] > 0 and flow[3]["mortgage_debt_service"] == pytest.approx(24_000.0)
    assert sched[4]["mortgage_balance"] == 0.0 and flow[4]["mortgage_debt_service"] == 0.0


def test_refinance_restarts_the_baseline_at_the_new_rate_and_term():
    refi = {"id": "r", "category": "refinance", "name": "Refi", "year": 2028, "end_year": 2028, "amount_basis": "fixed",
            "new_interest_rate": 0.04, "new_term_years": 30, "closing_costs": 0.0}
    sched, flow = _mortgage_run(service=30_000.0, events=[refi], rate=0.065)
    before = sched[1]["mortgage_balance"]
    assert flow[2]["mortgage_debt_service"] == pytest.approx(amort.monthly_payment(before, 0.04, 360) * 12.0, rel=1e-6)
    assert sched[2]["mortgage_balance"] == pytest.approx(amort.balance_after(before, 0.04, 360, 12), rel=1e-4)
    assert sched[29]["mortgage_balance"] > 0.0  # the 30-year clock restarted in 2028


def test_event_purchase_loan_is_amortized_separately_from_the_baseline():
    buy = {"id": "b", "category": "real_estate", "re_action": "buy", "name": "Cabin", "year": 2027, "end_year": 2027,
           "purchase_price": 500_000.0, "down_payment_pct": 0.2, "interest_rate": 0.06, "mortgage_term": "30_fixed",
           "amount_basis": "fixed", "annual_ongoing_carrying_cost": 0.0}
    service = amort.monthly_payment(300_000.0, 0.06, 180) * 12.0
    base, _ = _mortgage_run(service=service, rate=0.06)
    sched, flow = _mortgage_run(service=service, events=[buy], rate=0.06)
    assert base[15]["mortgage_balance"] == 0.0
    # The baseline is gone after 15 years; only the cabin loan (400k from 2027) remains.
    assert sched[15]["mortgage_balance"] == pytest.approx(amort.balance_after(400_000.0, 0.06, 360, 12 * 14), rel=1e-3)
    assert sched[15]["mortgage_balance"] > 0
