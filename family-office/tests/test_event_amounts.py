"""F-ENG-13: life-event amounts are today's dollars unless the event is a fixed contract."""

from __future__ import annotations

import pytest

from forecast import engine as forecast_engine
from forecast import event_amounts
from forecast.event_amounts import (
    EventIndexer,
    default_amount_basis,
    resolve_amount_basis,
    scale_event_amount,
)
from forecast.tuition_levels import COLLEGE, K12, PREK, classify_tuition_level
from plan_kwargs import run_simulation

INFLATION = 0.03
EDU_INFLATION = 0.05


def _simulate(events, view_mode="nominal", **kwargs):
    params = dict(
        events=events, liquid_start=20_000_000.0, retirement_start=0.0, real_estate_start=0.0,
        mortgage_start=0.0, other_start=0.0, family_id=0, view_mode=view_mode,
        annual_spending=0.0, inflation_rate=INFLATION, education_inflation_rate=EDU_INFLATION,
        primary_retirement_age=150, spouse_retirement_age=150, start_year=2026,
    )
    params.update(kwargs)
    return run_simulation(**params)["schedule"]


def _house(**extra):
    return {"id": "evt_house", "name": "House", "category": "real_estate", "year": 2036,
            "purchase_price": 1_000_000.0, "mortgage_term": "all_cash", **extra}


def _event_outflow(schedule, year):
    return next(r for r in schedule if r["year"] == year)["yearly_outflow"]


def test_house_purchase_grows_with_inflation_to_the_purchase_year():
    nominal = _simulate([_house()], "nominal")
    real = _simulate([_house()], "real")
    cash_outlay = 1_000_000.0 * 1.03 ** 10 * 1.02  # price plus 2% closing friction
    assert _event_outflow(nominal, 2036) == pytest.approx(cash_outlay, rel=1e-6)
    assert _event_outflow(real, 2036) == pytest.approx(1_000_000.0 * 1.02, rel=1e-6)


def test_fixed_event_costs_exactly_what_was_entered():
    nominal = _simulate([_house(amount_basis="fixed")], "nominal")
    assert _event_outflow(nominal, 2036) == pytest.approx(1_000_000.0 * 1.02, rel=1e-6)


def test_recurring_annual_event_is_indexed_every_year_it_applies():
    travel = {"id": "evt_travel", "name": "Travel", "category": "lifestyle", "year": 2030, "end_year": 2034,
              "annual_amount": 50_000.0}
    schedule = _simulate([travel])
    for year in range(2030, 2035):
        assert _event_outflow(schedule, year) == pytest.approx(50_000.0 * 1.03 ** (year - 2026), rel=1e-6)
    assert _event_outflow(schedule, 2035) == 0.0


def test_tuition_grows_at_the_education_rate_not_general_inflation():
    college = {"id": "evt_college", "name": "College", "category": "college", "year": 2036,
               "annual_amount": 80_000.0, "use_529_reserves": False}
    schedule = _simulate([college])
    assert _event_outflow(schedule, 2036) == pytest.approx(80_000.0 * 1.05 ** 10, rel=1e-6)


def test_education_rate_is_a_scenario_field_with_a_default():
    from forecast.capital_market_assumptions import DEFAULT_EDUCATION_INFLATION_RATE
    assert DEFAULT_EDUCATION_INFLATION_RATE == 0.05
    from forecast.hierarchy import INHERITABLE_ASSUMPTION_KEYS
    assert "education_inflation_rate" in INHERITABLE_ASSUMPTION_KEYS


@pytest.mark.parametrize("category", ["refinance", "debt_payoff", "pe_capital_call", "capital_call", "j_curve",
                                       "roth_conversion", "marital_settlement"])
def test_contractual_categories_default_to_fixed(category):
    assert default_amount_basis(category) == "fixed"
    indexer = EventIndexer(2026, INFLATION, EDU_INFLATION)
    assert scale_event_amount({"category": category}, 100.0, 2036, indexer) == 100.0
    todays = scale_event_amount({"category": category, "amount_basis": "todays_dollars"}, 100.0, 2036, indexer)
    assert todays == pytest.approx(100.0 * 1.03 ** 10)


def test_capital_call_is_fixed_by_default_and_indexed_when_marked_todays_dollars():
    call = {"id": "evt_pe", "name": "Fund", "category": "pe_capital_call", "year": 2036, "end_year": 2036,
            "annual_call": 100_000.0, "include_harvest": False}
    assert _event_outflow(_simulate([call]), 2036) == pytest.approx(100_000.0)
    indexed = _simulate([{**call, "amount_basis": "todays_dollars"}])
    assert _event_outflow(indexed, 2036) == pytest.approx(100_000.0 * 1.03 ** 10, rel=1e-6)


@pytest.mark.parametrize("bad", ["bogus", "", None, True, 3, ["fixed"]])
def test_invalid_amount_basis_is_treated_as_the_category_default(bad):
    assert resolve_amount_basis(bad, "lifestyle") == "todays_dollars"
    assert resolve_amount_basis(bad, "debt_payoff") == "fixed"
    indexer = EventIndexer(2026, INFLATION, EDU_INFLATION)
    assert scale_event_amount({"category": "lifestyle", "amount_basis": bad}, 100.0, 2036, indexer) == pytest.approx(100.0 * 1.03 ** 10)


def test_save_event_validates_amount_basis(monkeypatch):
    from services import scenario_overlay_service as svc

    class _Engine:
        def __init__(self):
            self.state = {"events": []}
        def load_scenario_state(self, family_id):
            return self.state
        def save_scenario_state(self, state, family_id):
            self.state = state

    class _Cache:
        def invalidate_family_cache(self, family_id):
            pass

    engine = _Engine()
    base = {"id": "evt_x", "name": "X", "category": "lifestyle", "amount": 10.0}
    assert svc.save_scenario_event(1, {**base, "amount_basis": "fixed"}, engine=engine, cache=_Cache())[0]
    assert engine.state["events"][0]["amount_basis"] == "fixed"
    assert svc.save_scenario_event(1, {**base, "amount_basis": "nonsense"}, engine=engine, cache=_Cache())[0]
    assert engine.state["events"][0]["amount_basis"] == "todays_dollars"


def test_every_event_amount_is_scaled_exactly_once(monkeypatch):
    calls = []
    real = event_amounts.scale_event_amount

    def spy(ev, amount, year, indexer):
        calls.append((ev["id"], year, amount))
        return real(ev, amount, year, indexer)

    monkeypatch.setattr(event_amounts, "scale_event_amount", spy)
    events = [
        {"id": "evt_gift", "name": "Gift", "category": "gifting", "year": 2030, "end_year": 2032, "annual_amount": 10_000.0},
        {"id": "evt_win", "name": "Windfall", "category": "capital_inflow", "year": 2031, "amount": 20_000.0},
    ]
    schedule = _simulate(events)
    assert sorted(calls) == [
        ("evt_gift", 2030, 10_000.0), ("evt_gift", 2031, 10_000.0), ("evt_gift", 2032, 10_000.0),
        ("evt_win", 2031, 20_000.0),
    ]
    assert _event_outflow(schedule, 2031) == pytest.approx(10_000.0 * 1.03 ** 5, rel=1e-6)


def test_home_loan_is_sized_at_the_purchase_year_price_and_carry_keeps_growing():
    house = _house(mortgage_term="30_fixed", down_payment_pct=0.20, interest_rate=0.06, annual_ongoing_carrying_cost=10_000.0)
    schedule = _simulate([house])
    loan = 800_000.0 * 1.03 ** 10
    monthly_rate = 0.06 / 12.0
    service = loan * (monthly_rate * (1 + monthly_rate) ** 360) / ((1 + monthly_rate) ** 360 - 1) * 12.0
    assert _event_outflow(schedule, 2037) == pytest.approx(service + 10_000.0 * 1.03 ** 11, rel=1e-6)


# Tuition-ledger rows are classified pre-K / K-12 / college so the K-12 529 cap only applies to K-12.
def test_classify_by_label_then_age():
    assert classify_tuition_level("UC Berkeley (Junior) Projected in-state tuition", 19) == COLLEGE
    assert classify_tuition_level("Elite Private University (College Freshman)", 18) == COLLEGE
    assert classify_tuition_level("Tribeca Montessori (Pre-K 3) Pre-K 3 nursery school", 3) == PREK
    assert classify_tuition_level("Tribeca Early Childhood (Nursery)", 2) == PREK
    assert classify_tuition_level("NYC Independent School (Kindergarten)", 5) == K12
    assert classify_tuition_level("SF Private High School (11th)", 16) == K12
    # Label says nothing: age decides.
    assert classify_tuition_level("", 3) == PREK
    assert classify_tuition_level("", 12) == K12
    assert classify_tuition_level("", 19) == COLLEGE


def test_k12_records_exclude_college_and_prek_rows(demo_jones_universe):
    recs = forecast_engine.load_children_k12_tuition(family_id=1)
    names = {r["first_name"] for r in recs}
    assert "Maya" not in names  # college only
    assert all(r["level"] in ("k12", "prek") for r in recs)
    ethan = next(r for r in recs if r["first_name"] == "Ethan")
    assert ethan["k12_end"] <= 2027  # 12th grade; college years 2028+ are not K-12


def test_college_event_comes_from_ledger_not_default(demo_jones_universe):
    edu = {c["first_name"]: c for c in forecast_engine.load_children_edu_reserves(family_id=1)}
    assert edu["Ethan"]["college_from_ledger"] is True
    assert edu["Ethan"]["college_start"] == 2028
    assert edu["Ethan"]["college_end"] == 2031
    events = forecast_engine.get_default_event_catalog(family_id=1)
    col = next(e for e in events if e["id"] == "evt_college_ethan")
    assert col["sync_with_ledger"] is True
    assert (col["year"], col["end_year"]) == (2028, 2031)
    k12 = next(e for e in events if e["id"] == "evt_k12_ethan")
    assert k12["use_529_k12_election"] is True and k12["end_year"] < col["year"]


def test_prek_events_skip_529_k12_election():
    from forecast.presets_family_edu import build_education_events

    kids = [{
        "user_id": 9, "name": "Leo Chen", "first_name": "Leo", "level": "prek", "event_id": "evt_prek_leo",
        "k12_start": 2026, "k12_end": 2028, "annual_amount": 30000.0,
    }]
    evs = build_education_events(family_id=0, children_k12=kids, children_edu=[], as_of_year=2026)
    prek = next(e for e in evs if e["id"] == "evt_prek_leo")
    assert prek["use_529_k12_election"] is False
