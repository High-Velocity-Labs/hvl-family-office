"""Engine inputs: pension, known investment income in MAGI, AMT credit recovery, mortgage term, household prior income."""

from __future__ import annotations

import pytest

from forecast.actuarial import household_survival, unisex_survival
from forecast.charitable_limits import agi_proxy
from forecast.context import HouseholdContext
from forecast.event_amounts import EventIndexer
from forecast.household_roster import HouseholdRoster
from forecast.investment_income import DEFAULT_TAXABLE_YIELD_RATE, known_investment_income, taxable_yield_rate
from forecast.mortgage_amortization import BaselineLoan
from forecast.pension import Pension, household_pension_income, pension_income, pension_tax
from forecast.retirement_split import pretax_share
from forecast.scenarios import process_pre65_healthcare_event
from plan_kwargs import run_simulation
from equity.iso_amt import amt_credit_recovery, amt_credit_recovery_years  # noqa: E402
from services.household_income import household_income_from_records  # noqa: E402


def test_pension_starts_at_start_age_and_grows_by_cola():
    p = Pension(annual_amount=40_000.0, start_age=62, cola=0.02)
    assert pension_income(p, 60, 0, 0.03) == 0.0
    assert pension_income(p, 62, 2, 0.03) == pytest.approx(40_000 * 1.03**2)
    assert pension_income(p, 64, 4, 0.03) == pytest.approx(40_000 * 1.03**2 * 1.02**2)
    assert pension_income(p, 70, 0, 0.03) == pytest.approx(40_000)  # already in payment: the entered amount
    assert pension_income(Pension(40_000.0, 62, 0.0, 0.5), 70, 0, 0.03, survivor=True) == pytest.approx(20_000)


def test_pension_validates_and_spouse_needs_a_spouse():
    for bad in (dict(annual_amount=-1.0, start_age=62), dict(annual_amount=1.0, start_age=20),
                dict(annual_amount=1.0, start_age=62, cola=0.5), dict(annual_amount=1.0, start_age=62, survivor_pct=2)):
        with pytest.raises(ValueError):
            Pension(**bad)
    pensions = {"primary": Pension(10_000.0, 60), "spouse": Pension(5_000.0, 60)}
    assert household_pension_income(pensions, 61, 61, True, 0, 0.0) == 15_000.0
    assert household_pension_income(pensions, 61, 61, False, 0, 0.0) == 10_000.0


def test_pension_tax_is_ordinary_income_with_no_fica():
    assert pension_tax(0.0, 0.0, 2030, 0.025, "TX", "MFJ", 0) == 0.0
    assert pension_tax(30_000.0, 0.0, 2026, 0.0, "TX", "MFJ", 0) == 0.0  # under the standard deduction
    assert 0.0 < pension_tax(100_000.0, 0.0, 2026, 0.0, "TX", "MFJ", 0) < 15_000.0
    assert pension_tax(100_000.0, 0.0, 2026, 0.0, "CA", "MFJ", 0) > pension_tax(100_000.0, 0.0, 2026, 0.0, "TX", "MFJ", 0)


def _run(pensions):
    ctx = HouseholdContext(user_state="TX", has_spouse=False, pensions=pensions)
    return run_simulation(
        [], liquid_start=500_000.0, retirement_start=0.0, real_estate_start=0.0, mortgage_start=0.0, other_start=0.0,
        primary_retirement_age=60, retirement_age=60, annual_spending=60_000.0, inflation_rate=0.0,
        primary_birth_year=1966, start_year=2026, context=ctx, view_mode="nominal",
    )


def test_pension_flows_into_the_waterfall_as_income():
    without, with_pension = _run({}), _run({"primary": Pension(60_000.0, 60)})
    row = with_pension["cash_flow_series"][0]
    assert without["cash_flow_series"][0]["pension_income"] == 0.0
    assert 0.0 < row["pension_income"] <= 60_000.0
    assert row["income_tax_haircut"] == pytest.approx(60_000.0 - row["pension_income"], abs=0.5)
    assert with_pension["schedule"][5]["liquid_assets"] > without["schedule"][5]["liquid_assets"]


def test_known_investment_income_replaces_the_flat_yield_in_aca_magi():
    payload = {"transcripts_by_year": {"2024": {"totals": {"qualified_dividends": 1.0, "interest_income": 1.0}},
                                       "2025": {"totals": {"ordinary_dividends": 70_000.0, "interest_income": 30_000.0}}}}
    assert known_investment_income(payload) == 100_000.0
    assert known_investment_income({}) is None
    assert taxable_yield_rate(None, 1_000_000.0) == DEFAULT_TAXABLE_YIELD_RATE
    assert taxable_yield_rate(100_000.0, 1_000_000.0) == pytest.approx(0.10)

    def magi_premium(rate):
        ev = {"category": "pre65_healthcare", "annual_premium": 30_000.0, "amount_basis": "fixed"}
        _, outflow = process_pre65_healthcare_event(
            ev, 2026, 55, 1_000_000.0, False, 0.0, 0.0, 1.0, 0.0, [], None, 1.0, 0.0,
            indexer=EventIndexer(start_year=2026, inflation_rate=0.0, education_inflation_rate=0.0),
            roster=HouseholdRoster(), taxable_yield_rate=rate,
        )
        return outflow

    assert magi_premium(0.10) > magi_premium(DEFAULT_TAXABLE_YIELD_RATE)


def test_daf_agi_counts_current_year_pension_and_the_known_yield():
    assert agi_proxy(0.0, 1_000_000.0, 0.0) == pytest.approx(20_000.0)
    assert agi_proxy(0.0, 1_000_000.0, 5_000.0, 40_000.0, 0.05) == pytest.approx(95_000.0)


def test_amt_credit_recovers_only_where_regular_tax_exceeds_tmt():
    low = amt_credit_recovery(50_000.0, 40_000.0)  # no AMT at this income: the credit offsets all regular tax
    assert low["credit_used"] == pytest.approx(low["regular_tax"]) and low["carryforward_left"] > 0
    assert amt_credit_recovery(50_000.0, 0.0)["credit_used"] == 0.0  # nothing to offset
    high = amt_credit_recovery(1_000_000.0, 500_000.0)
    assert 0.0 < high["credit_used"] < 1_000_000.0
    assert high["credit_used"] + high["carryforward_left"] == pytest.approx(1_000_000.0)
    assert amt_credit_recovery_years(0.0, 500_000.0) == 0
    assert amt_credit_recovery_years(10_000.0, 500_000.0) >= 1
    assert amt_credit_recovery_years(10_000.0, 40_000.0) > amt_credit_recovery_years(10_000.0, 500_000.0)
    assert amt_credit_recovery_years(10_000.0, 0.0) == -1


def test_baseline_loan_uses_the_entered_term_and_rate():
    short = BaselineLoan(300_000.0, 0.04, 15.0).level_annual_service()
    long = BaselineLoan(300_000.0, 0.04, 30.0).level_annual_service()
    assert short > long
    assert BaselineLoan(300_000.0).level_annual_service() == pytest.approx(
        BaselineLoan(300_000.0, 0.065, 30.0).level_annual_service())
    ctx = HouseholdContext(user_state="TX", has_spouse=False, mortgage_rate=0.04, mortgage_term_years=10.0)
    out = run_simulation(
        [], liquid_start=1_000_000.0, retirement_start=0.0, real_estate_start=500_000.0, mortgage_start=300_000.0,
        other_start=0.0, annual_spending=50_000.0, inflation_rate=0.0, primary_birth_year=1980, start_year=2026,
        context=ctx, view_mode="nominal",
    )
    paid = [r["mortgage_debt_service"] for r in out["cash_flow_series"]]
    assert paid[0] == pytest.approx(BaselineLoan(300_000.0, 0.04, 10.0).level_annual_service(), rel=1e-3)
    assert paid[9] > 0 and paid[10] == 0


def test_mortgage_service_resolves_from_entered_term():
    from forecast.orchestrator_params import resolve_mortgage_service

    snap = {"mortgage_annual_service": 99_999.0, "categories": {"mortgages": {"accounts": []}}}
    assert resolve_mortgage_service(snap, 0.0, {}) == 0.0
    assert resolve_mortgage_service(snap, 300_000.0, {}) == 99_999.0
    assert resolve_mortgage_service(snap, 300_000.0, {"remaining_term_years": 15.0, "annual_rate": 0.04}) == pytest.approx(
        BaselineLoan(300_000.0, 0.04, 15.0).level_annual_service())


def test_household_income_sums_each_earners_latest_year():
    rows = [
        {"user_id": 1, "year": 2024, "salary": 100.0, "bonus": 0.0},
        {"user_id": 1, "year": 2025, "salary": 200.0, "bonus": 50.0},
        {"user_id": 2, "year": 2025, "salary": 150.0, "bonus": 0.0},
    ]
    assert household_income_from_records(rows) == 400.0
    assert household_income_from_records([]) == 0.0


def test_retirement_split_is_all_pretax_unless_roth_is_named():
    assert pretax_share([]) == 1.0
    assert pretax_share([{"name": "Fidelity 401k", "balance": 300.0}, {"name": "Roth IRA", "balance": 100.0}]) == 0.75


def test_survival_is_sex_neutral():
    assert 0.0 < unisex_survival(80) < 1.0
    assert household_survival(80, 80, True) > household_survival(80, 80, False)


def test_settings_saves_pension_and_mortgage_inputs_and_clears_them():
    from db.engine_inputs import get_mortgage_inputs, get_pension_inputs
    from services.request_context import DB_PATH
    from tests.test_api_endpoints import get_authenticated_client

    client = get_authenticated_client()
    state = client.get("/api/settings/assumptions").get_json()["assumptions"]["state"] or "TX"
    with client.session_transaction() as sess:
        family_id = sess.get("family_id") or 1
    body = {"state": state, "pension_primary_annual": 54000, "pension_primary_start_age": 62,
            "pension_primary_cola_pct": 2, "pension_primary_survivor_pct": 50,
            "mortgage_remaining_years": 22, "mortgage_rate_pct": 3.375}
    assert client.post("/api/settings/assumptions", json=body).status_code == 200
    assert get_pension_inputs(family_id=family_id, db_path=DB_PATH)["primary"] == {
        "annual_amount": 54000.0, "start_age": 62.0, "cola": 0.02, "survivor_pct": 0.5}
    assert get_mortgage_inputs(family_id=family_id, db_path=DB_PATH) == {
        "remaining_term_years": 22.0, "annual_rate": pytest.approx(0.03375)}
    assert client.post("/api/settings/assumptions", json={"state": state, "pension_primary_start_age": 10,
                                                          "pension_primary_annual": 1}).status_code == 400
    clear = {"state": state, "pension_primary_annual": None, "mortgage_remaining_years": None, "mortgage_rate_pct": None}
    assert client.post("/api/settings/assumptions", json=clear).status_code == 200
    assert "primary" not in get_pension_inputs(family_id=family_id, db_path=DB_PATH)
    assert get_mortgage_inputs(family_id=family_id, db_path=DB_PATH) == {}
