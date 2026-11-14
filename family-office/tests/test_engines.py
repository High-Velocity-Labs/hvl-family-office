"""
Unit tests for tax_engine and equity_engine
Verifies calculations against user's ground-truth spreadsheet and Monarch snapshots.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from household_factory import HOUSEHOLD_FAMILY_ID
from services import tax_engine
from services import equity_engine
import inspect
from datetime import date

import numpy as np

import routes  # noqa: F401  (resolves the advisor import cycle first)
from account_sync.categorizer_rules import is_coverdell_name, suggest_account_role_and_beneficiary
from forecast import engine as forecast_engine
from forecast import hierarchy
from forecast.monte_carlo_kernel import _execute_monte_carlo_kernel
from forecast.presets import build_annual_savings_presets
from plan_kwargs import run_simulation
from forecast.waterfall_equity import STATE_INCOME_TAX_RATES
from services import statutory_limits
from services.advisor import context as advisor_context
from services.advisor import tools_chief_of_staff
from services.person_name import first_name
from services.tax_calculations import STATE_TAX_PROFILES, calculate_state_tax_for_state


def test_primary_equity_ground_truth():
    """Validates Grant 1, 2, 3 numbers and totals at active FMV."""
    price = equity_engine.get_current_409a_price(family_id=HOUSEHOLD_FAMILY_ID)
    sim = equity_engine.simulate_valuation_scenario(share_price=price, include_wa_millionaire_tax=False, family_id=HOUSEHOLD_FAMILY_ID)

    # 1. Total Gross Equity Value of the synthetic fixture (owned stock plus vested spread)
    assert abs(sim["total_gross_equity_value"] - 6850000.00) < 0.10

    # 2. Owned Stock (2,000 shares @ $500 = $1,000,000.00)
    assert sim["total_owned_shares"] == 2000.0
    g1 = next(g for g in sim["grants"] if "Grant 1" in g["nickname"])
    assert abs(g1["owned_gross_value"] - 1000000.00) < 0.10

    # 3. Grant 1 unexercised options (7,000 options, spread = $3,430,000.00)
    assert g1["unexercised_options"] == 7000.0
    assert abs(g1["strike_cost"] - 70000.00) < 0.10
    assert abs(g1["spread"] - 3430000.00) < 0.10

    # 4. Grant 2 unexercised options (2,000 options, spread = $900,000.00)
    g2 = next(g for g in sim["grants"] if "Grant 2" in g["nickname"])
    assert g2["unexercised_options"] == 2000.0
    assert abs(g2["strike_cost"] - 100000.00) < 0.10
    assert abs(g2["spread"] - 900000.00) < 0.10

    # 5. Grant 3 vested unexercised options (4,000 options, spread = $1,520,000.00)
    g3 = next(g for g in sim["grants"] if "Grant 3" in g["nickname"])
    assert g3["unexercised_options"] == 4000.0
    assert abs(g3["strike_cost"] - 480000.00) < 0.10
    assert abs(g3["spread"] - 1520000.00) < 0.10

    # 6. Total Unexercised Vested Spread = $5,850,000.00
    assert abs(sim["total_taxable_spread"] - 5850000.00) < 0.10

    # 7. Total Strike Cost Needed = $650,000.00
    assert abs(sim["total_strike_cost_needed"] - 650000.00) < 0.10


def test_federal_tax_and_medicare():
    """Tests ordinary income tax and Medicare on NSO spread."""
    # Top marginal rate should be 37% Fed + 1.45% Med + 0.9% Addl Med = 39.35%
    tax_info = tax_engine.calculate_nso_exercise_tax(
        spread=10000000.0,
        prior_ordinary_income=500000.0,
        include_wa_millionaire_tax=False
    )
    assert tax_info["marginal_rate"] == 0.3935
    # Effective rate on $10M above $500k base income should be within 0.01 of 39.35%
    assert abs(tax_info["effective_rate"] - 0.3935) < 0.01


def test_wa_millionaire_tax_penalty():
    """Tests the dollar impact of Washington State's 9.9% tax on equity."""
    price = equity_engine.get_current_409a_price(family_id=HOUSEHOLD_FAMILY_ID)
    sim = equity_engine.simulate_valuation_scenario(share_price=price, family_id=HOUSEHOLD_FAMILY_ID)
    # The WA 9.9% tax on the $5.85M spread (above the exemption) is $568,260
    assert sim["wa_tax_difference"] == 568260.0


def test_state_tax_arbitrage_comparison():
    """Tests multi-state tax arbitrage (WA vs WA_2028 vs NV vs CA)."""
    spread = 5850000.00
    cap_gains = 980000.00 # Gains on 2,000 shares

    arb = tax_engine.compare_state_tax_arbitrage(
        ordinary_spread=spread,
        capital_gains=cap_gains,
        base_w2_salary=500000.0,
        home_state="WA",
    )

    states_dict = {s["state_code"]: s for s in arb["states"]}

    # Nevada, Texas, Florida should have $0 state tax
    assert states_dict["NV"]["total_state_tax"] == 0.0
    assert states_dict["TX"]["total_state_tax"] == 0.0
    assert states_dict["FL"]["total_state_tax"] == 0.0

    # California should have a large state tax (> $970k on this spread)
    assert states_dict["CA"]["total_state_tax"] > 970000.0

    # Moving to Nevada from WA under 2028 laws saves over $500k
    assert arb["nevada_arbitrage_savings_vs_wa_2028"] > 500000.0


def test_safe_harbor_optimizer():
    """Tests IRS Safe Harbor 110% prior-year calculation."""
    res = tax_engine.calculate_withholding_safe_harbor(
        current_year_projected_tax=400000.0,
        prior_year_total_tax=250000.0,
        current_ytd_withheld=200000.0,
        remaining_paychecks=5
    )
    # Safe harbor is min(90% of 400k = 360k, 110% of 250k = 275k) = 275,000
    assert res["safe_harbor_target"] == 275000.0
    # Shortfall = 275k - 200k = 75,000
    assert res["shortfall_to_safe_harbor"] == 75000.0
    # Extra per paycheck = 75k / 5 = 15,000
    assert res["recommended_extra_per_paycheck"] == 15000.0


def test_single_parent_hoh_tax():
    """Verifies that single-parent households have correct HOH standard deductions and tax brackets."""
    from services import tax_engine

    hoh_deduction = tax_engine.get_standard_deduction("HOH")
    assert hoh_deduction == 24150.0
    single_deduction = tax_engine.get_standard_deduction("SINGLE")
    assert single_deduction == 16100.0
    mfj_deduction = tax_engine.get_standard_deduction("MFJ")
    assert mfj_deduction == 32200.0

    hoh_brackets = tax_engine.get_federal_brackets("HOH")
    assert len(hoh_brackets) == 7
    # First bracket for HOH is 10% from $0 to $17,700
    assert hoh_brackets[0] == (0.0, 17700.0, 0.10)


def test_monarch_education_exclusion_and_vanguard_positions():
    """Verifies that education accounts are excluded from parent net worth and Vanguard positions extracted."""
    import account_sync
    snap = account_sync.get_financial_snapshot(family_id=HOUSEHOLD_FAMILY_ID)
    # Education accounts must be tracked as separate custodial assets
    assert snap["education_assets"] == 220000.0
    # Parent true net worth must not include education assets
    assert snap["categories"]["education_529"]["label"].startswith("Education")
    # Vanguard & 401k accounts must be present with positions
    vanguard_positions = snap["vanguard_and_401k_positions"]
    assert len(vanguard_positions) >= 5
    # Must contain 401k and Joint Vanguard
    names = [a["account_name"] for a in vanguard_positions]
    assert any("401(k)" in n for n in names)
    assert any("brokerage" in n.lower() or "vanguard" in n.lower() for n in names)


def test_forecast_engine_depletion_under_extreme_spend():
    """Verifies that unsustainable annual spend (e.g. $50M/yr) correctly flags depletion and disallows retirement."""
    from forecast import engine as forecast_engine
    res = forecast_engine.simulate_multi_scenarios(family_id=1, annual_living_spend=50000000.0)
    readiness = res.get("active_retirement_readiness", {})
    assert readiness.get("is_sustainable") is False
    assert readiness.get("can_retire_today") is False
    assert readiness.get("earliest_joint_year") is None
    assert res["scorecard"][0]["is_depleted"] is True


def test_dynamic_gap_year_roth_conversion_bracket_fill():
    """Validates dynamic bracket-filling Roth conversion ladder in gap years and working years."""
    from forecast.event_amounts import EventIndexer
    from forecast.scenarios import process_roth_or_72t_event, process_pre65_healthcare_event

    indexer = EventIndexer(start_year=2026, inflation_rate=0.0, education_inflation_rate=0.0)

    # 1. auto_bracket_24 converts $0 when working with income above the ceiling ($500k > $424,600)
    ev_24 = {
        "category": "roth_conversion",
        "name": "Auto-Fill 24% Bracket",
        "roth_strategy_preset": "auto_bracket_24",
    }
    events_log = []
    r_bal, l_bal, outflow = process_roth_or_72t_event(
        ev=ev_24,
        name=ev_24["name"],
        age_primary=62,
        retire_bal=1_000_000.0,
        liquid_bal=300_000.0,
        yearly_event_outflow=0.0,
        events_occurred=events_log,
        is_working=True,
        primary_earned_income=500_000.0,
        spouse_earned_income=0.0,
        earned_income_multiplier=1.0,
        indexer=indexer,
    )
    assert r_bal == 1_000_000.0
    assert l_bal == 300_000.0
    assert outflow == 0.0
    assert any("$0 converted" in msg for msg in events_log)

    # 2. auto_bracket_22 in gap year (is_working=False, liquid_bal=$500k -> $10k taxable yield)
    # Headroom = $243,600 - $10,000 = $233,600
    ev_22 = {
        "category": "roth_conversion",
        "name": "Auto-Fill 22% Bracket",
        "roth_strategy_preset": "auto_bracket_22",
    }
    events_log_22 = []
    r_bal2, l_bal2, outflow2 = process_roth_or_72t_event(
        ev=ev_22,
        name=ev_22["name"],
        age_primary=63,
        retire_bal=1_000_000.0,
        liquid_bal=500_000.0,
        yearly_event_outflow=0.0,
        events_occurred=events_log_22,
        is_working=False,
        primary_earned_income=0.0,
        spouse_earned_income=0.0,
        earned_income_multiplier=1.0,
        indexer=indexer,
    )
    expected_headroom = 243600.0 - 10000.0
    expected_tax = expected_headroom * 0.22
    assert abs(r_bal2 - (1_000_000.0 - expected_headroom)) < 0.01
    assert abs(l_bal2 - (500_000.0 + expected_headroom - expected_tax)) < 0.01
    assert abs(outflow2 - expected_tax) < 0.01
    assert any("Auto-filled 22% bracket" in msg for msg in events_log_22)

    # 3. Stops automatically once RMD age is reached (age_primary >= 73)
    events_log_rmd = []
    r_bal_rmd, l_bal_rmd, outflow_rmd = process_roth_or_72t_event(
        ev=ev_22,
        name=ev_22["name"],
        age_primary=73,
        retire_bal=1_000_000.0,
        liquid_bal=500_000.0,
        yearly_event_outflow=0.0,
        events_occurred=events_log_rmd,
        is_working=False,
        indexer=indexer,
    )
    assert r_bal_rmd == 1_000_000.0
    assert l_bal_rmd == 500_000.0
    assert outflow_rmd == 0.0
    assert len(events_log_rmd) == 0

    # 4. Pre-65 healthcare event estimates dynamic bracket fill for ACA MAGI
    aca_ev = {"category": "healthcare_bridge", "name": "ACA Bridge", "annual_premium": 24000.0}
    aca_log = []
    process_pre65_healthcare_event(
        ev=aca_ev,
        year=2028,
        age_primary=62,
        liquid_bal=500_000.0,
        is_working=False,
        primary_earned_income=0.0,
        spouse_earned_income=0.0,
        earned_income_multiplier=1.0,
        yearly_event_outflow=0.0,
        events_occurred=aca_log,
        events=[{"category": "roth_conversion", "roth_strategy_preset": "auto_bracket_22", "year": 2027, "end_year": 2034}],
        indexer=indexer,
    )
    assert any("244k MAGI" in msg and "no ACA credit" in msg for msg in aca_log)  # above 400% of the poverty line


def test_2026_statutory_tax_figures_and_fica_wage_base():
    """Validates 2026 IRS Rev. Proc. 2025-32 / OBBBA statutory brackets and standard deductions."""
    assert tax_engine.STANDARD_DEDUCTION_MFJ_2026 == 32200.0
    assert tax_engine.STANDARD_DEDUCTION_HOH_2026 == 24150.0
    assert tax_engine.STANDARD_DEDUCTION_SINGLE_2026 == 16100.0
    assert tax_engine.FICA_SS_WAGE_BASE_2026 == 184500.0

    # Progressive brackets
    mfj = tax_engine.FED_BRACKETS_MFJ_2026
    assert mfj[0] == (0.0, 24800.0, 0.10)
    assert mfj[1] == (24800.0, 100800.0, 0.12)
    assert mfj[2] == (100800.0, 211400.0, 0.22)
    assert mfj[3] == (211400.0, 403550.0, 0.24)
    assert mfj[4] == (403550.0, 512450.0, 0.32)
    assert mfj[5] == (512450.0, 768700.0, 0.35)
    assert mfj[6] == (768700.0, float("inf"), 0.37)

    single = tax_engine.FED_BRACKETS_SINGLE_2026
    assert single[0] == (0.0, 12400.0, 0.10)
    assert single[1] == (12400.0, 50400.0, 0.12)
    assert single[2] == (50400.0, 105700.0, 0.22)
    assert single[3] == (105700.0, 201775.0, 0.24)
    assert single[4] == (201775.0, 256225.0, 0.32)
    assert single[5] == (256225.0, 640600.0, 0.35)
    assert single[6] == (640600.0, float("inf"), 0.37)

    ltcg_mfj = tax_engine.FED_LTCG_BRACKETS_MFJ_2026
    assert ltcg_mfj[0] == (0.0, 98900.0, 0.00)
    assert ltcg_mfj[1] == (98900.0, 613700.0, 0.15)
    assert ltcg_mfj[2] == (613700.0, float("inf"), 0.20)


def test_wa_capital_gains_tiered_surcharge_and_year_gate():
    """Validates WA capital gains 7% + 2.9% tiered surcharge (> $1M taxable) and SB 6346 year gate (< 2028)."""
    # 1. Under exemption ($278k) -> $0 tax
    assert tax_engine.calculate_wa_capital_gains_tax(278000.0) == 0.0

    # 2. $500k above exemption ($778k total gain) -> 7% on $500k = $35,000
    assert abs(tax_engine.calculate_wa_capital_gains_tax(778000.0) - 35000.0) < 0.01

    # 3. Exactly $1M above exemption ($1,278,000 total gain) -> 7% on $1M = $70,000
    assert abs(tax_engine.calculate_wa_capital_gains_tax(1278000.0) - 70000.0) < 0.01

    # 4. $2M above exemption ($2,278,000 total gain) -> $70,000 + (1,000,000 * 0.099) = $169,000
    assert abs(tax_engine.calculate_wa_capital_gains_tax(2278000.0) - 169000.0) < 0.01

    # Stock sale tax uses tiered surcharge
    sale_res = tax_engine.calculate_stock_sale_tax(sale_proceeds=2278000.0, cost_basis=0.0, state="WA")
    assert abs(sale_res["wa_capital_gains_tax"] - 169000.0) < 0.01

    # WA SB 6346 Year Gate: 2026 has no WA millionaire tax; 2028+ applies 9.9%
    tax_2026 = tax_engine.calculate_nso_exercise_tax(
        spread=2000000.0,
        prior_ordinary_income=500000.0,
        include_wa_millionaire_tax=True,
        tax_year=2026,
    )
    assert tax_2026["wa_state_tax"] == 0.0

    tax_2028 = tax_engine.calculate_nso_exercise_tax(
        spread=2000000.0,
        prior_ordinary_income=500000.0,
        include_wa_millionaire_tax=True,
        tax_year=2028,
    )
    assert tax_2028["wa_state_tax"] > 0.0
    # Prior $500k + spread $2M = $2.5M. Taxable above $1M = $1.5M. Spread portion = $1.5M * 9.9% = $148,500
    assert abs(tax_2028["wa_state_tax"] - 148500.0) < 0.01

    # Direct forced call without tax_year applies millionaire tax
    tax_forced = tax_engine.calculate_nso_exercise_tax(
        spread=2000000.0,
        prior_ordinary_income=500000.0,
        include_wa_millionaire_tax=True,
        tax_year=None,
    )
    assert abs(tax_forced["wa_state_tax"] - 148500.0) < 0.01


def test_social_security_statutory_early_claiming_reduction():
    """Validates SSA statutory reduction: 5/9 of 1%/mo for first 36 mo, 5/12 of 1%/mo beyond 36 mo."""
    from forecast.waterfall_withdrawals import _ss_factor

    assert _ss_factor(67) == 1.0
    assert _ss_factor(66) == 0.933333
    assert _ss_factor(65) == 0.866667
    assert _ss_factor(64) == 0.80
    assert _ss_factor(63) == 0.75
    assert _ss_factor(62) == 0.70
    assert _ss_factor(70) == 1.24


def test_historical_2025_sp500_return_and_default_inflation_rate():
    """Validates Damodaran 2025 S&P 500 total return (17.78%) and consistent default inflation (2.5%)."""
    from forecast.historical_cohorts import HISTORICAL_MARKET_ROWS
    row_2025 = next(r for r in HISTORICAL_MARKET_ROWS if r[0] == 2025)
    assert row_2025[1] == 0.1778

    from db.schemas import HouseholdProfileSchema
    assert HouseholdProfileSchema().inflation_rate == 0.025
    assert HouseholdProfileSchema.from_dict({}).inflation_rate == 0.025


if __name__ == "__main__":
    test_primary_equity_ground_truth()
    test_federal_tax_and_medicare()
    test_wa_millionaire_tax_penalty()
    test_state_tax_arbitrage_comparison()
    test_safe_harbor_optimizer()
    test_dynamic_gap_year_roth_conversion_bracket_fill()
    test_monarch_education_exclusion_and_vanguard_positions()
    test_forecast_engine_depletion_under_extreme_spend()
    print("All tax, equity, retirement, and holdings tests passed with 100% precision!")



def test_aca_applicable_percentage_bands_and_cliff():
    """2026 applicable percentages rise across each band, and above 400% of the poverty line there is no credit."""
    from services.statutory_limits import aca_applicable_percentage

    assert aca_applicable_percentage(1.0) == pytest.approx(0.0210)
    assert aca_applicable_percentage(1.75) == pytest.approx((0.0419 + 0.0660) / 2)
    assert aca_applicable_percentage(4.0) == pytest.approx(0.0996)
    assert aca_applicable_percentage(4.01) is None


_RELOCATION = {
    "id": "evt_reloc", "name": "Move to TX", "category": "state_relocation", "year": 2028, "end_year": 2028,
    "origin_state": "CA", "target_state": "TX", "amount": 35000.0,
}


def _run_reloc(events, retired):
    return run_simulation(
        events=events, liquid_start=10_000_000.0, retirement_start=0.0, real_estate_start=0.0,
        mortgage_start=0.0, other_start=0.0, equity_annual_growth=0.0,
        primary_birth_year=1950 if retired else 1985, spouse_birth_year=1950 if retired else 1985,
        primary_retirement_age=60, spouse_retirement_age=60,
        annual_spending=400_000.0, annual_savings=0.0, inflation_rate=0.0,
        view_mode="nominal", family_id=0,
    )["schedule"]


def test_retiree_relocation_costs_only_the_move():
    base = _run_reloc([], retired=True)
    moved = _run_reloc([_RELOCATION], retired=True)
    row_b = next(r for r in base if r["year"] == 2029)
    row_m = next(r for r in moved if r["year"] == 2029)
    # Spending is after-tax for a household with no wages, so moving can only cost the moving expense.
    assert row_m["liquid_assets"] <= row_b["liquid_assets"]


def test_nso_tax_honors_head_of_household():
    kw = dict(spread=200_000.0, prior_ordinary_income=150_000.0, tax_year=2026)
    hoh = tax_engine.calculate_nso_exercise_tax(is_mfj=False, filing_status="HOH", **kw)
    single = tax_engine.calculate_nso_exercise_tax(is_mfj=False, **kw)
    mfj = tax_engine.calculate_nso_exercise_tax(is_mfj=True, **kw)
    assert hoh["federal_income_tax"] < single["federal_income_tax"]
    assert mfj["federal_income_tax"] < hoh["federal_income_tax"]
    brackets = tax_engine.get_federal_brackets("HOH")
    std = tax_engine.get_standard_deduction("HOH")
    expected = (
        tax_engine.calculate_federal_ordinary_tax(350_000.0 - std, brackets)
        - tax_engine.calculate_federal_ordinary_tax(150_000.0 - std, brackets)
    )
    assert abs(hoh["federal_income_tax"] - expected) < 1.0


def test_savings_preset_reads_the_statutory_limit_and_hides_a_duplicate_baseline():
    limit = statutory_limits.section_415c_limit(date.today().year)
    presets = build_annual_savings_presets(baseline_savings=limit)
    tax_adv = next(p for p in presets if p["source"] == "tax_advantaged")
    assert tax_adv["savings"] == limit
    assert not any(p["source"] == "baseline" for p in presets)
    # Any other baseline value still appears as its own preset.
    assert any(p["source"] == "baseline" for p in build_annual_savings_presets(baseline_savings=limit + 20_000.0))


def _ctx_state(state):
    return {"family_name": "Test", "family_id": 1, "state": state, "filing_status": "MFJ", "equity": {}, "net_worth_snapshot": {}}


def test_washington_nso_guidance_only_for_washington_households():
    wa = advisor_context._format_fiduciary_system_prompt(_ctx_state("WA"))
    ca = advisor_context._format_fiduciary_system_prompt(_ctx_state("CA"))
    ny = advisor_context._format_fiduciary_system_prompt(_ctx_state(""))
    assert "SB 6346" in wa
    assert "SB 6346" not in ca and "Millionaire" not in ca
    assert "SB 6346" not in ny
    assert "Cash-Cover vs. Sell-to-Cover" in ca


def test_cash_flow_detail_does_not_expose_an_rmd_field():
    assert "rmd_amount" not in inspect.getsource(tools_chief_of_staff)


def test_safe_harbor_multiplier_depends_on_prior_agi():
    mult = tax_engine.safe_harbor_prior_year_multiplier
    assert mult(150_000.0) == 1.00
    assert mult(150_001.0) == 1.10
    assert mult(75_001.0, "MFS") == 1.10
    assert mult(75_000.0, "MFS") == 1.00
    assert mult(None) == 1.10  # unknown AGI: the conservative target
    low = tax_engine.calculate_withholding_safe_harbor(0.0, 20_000.0, 0.0, prior_year_agi=140_000.0)
    high = tax_engine.calculate_withholding_safe_harbor(0.0, 20_000.0, 0.0, prior_year_agi=400_000.0)
    assert low["safe_harbor_target"] == 20_000.0
    assert high["safe_harbor_target"] == 22_000.0


def test_coverdell_matches_but_530a_does_not():
    for name in ("Coverdell ESA - Sam", "Sam ESA", "Sam § 530 account", "Section 530 plan"):
        assert is_coverdell_name(name), name
    for name in ("Sam 530A Trump Account", "Trump account", "Section 530A"):
        assert not is_coverdell_name(name), name
    role, _ = suggest_account_role_and_beneficiary({"displayName": "Sam 530A Account"}, [])
    assert role not in ("education_529", "education_530a")
    role, _ = suggest_account_role_and_beneficiary({"displayName": "Sam Coverdell ESA"}, [])
    assert role == "education_530a"


def test_state_rates_share_one_source():
    assert STATE_INCOME_TAX_RATES["CA"] == STATE_TAX_PROFILES["CA"]["ordinary_rate"] == 0.133
    assert STATE_INCOME_TAX_RATES["ID"] == 0.053 and STATE_INCOME_TAX_RATES["UT"] == 0.045
    assert STATE_INCOME_TAX_RATES["WA"] == 0.0
    for code, prof in STATE_TAX_PROFILES.items():
        if code.startswith("WA"):
            continue
        assert STATE_INCOME_TAX_RATES[code] >= prof["ordinary_rate"]


def test_college_funding_status_is_computed_not_hardcoded():
    from ssr.planning_cards import _funding_status

    tiers = [{"four_year_total": 100_000}, {"four_year_total": 400_000}]
    kid = {"current_529_balance": 150_000.0, "projected_529_balance": 150_000.0, "years_remaining": 0.0}
    short = _funding_status(tiers, [kid], use_projected=False)
    assert short["has_data"] and not short["all_funded"] and short["min_pct"] == 38
    rich = _funding_status(tiers, [dict(kid, current_529_balance=500_000.0)], use_projected=False)
    assert rich["all_funded"] and rich["text"] == "100% Fully Funded"
    assert _funding_status(tiers, [], use_projected=False)["has_data"] is False


def test_ohio_profile_is_flat_2_75_percent():
    prof = STATE_TAX_PROFILES["OH"]
    assert prof["ordinary_rate"] == 0.0275 and prof["cap_gains_rate"] == 0.0275
    assert {"name", "property_tax_rate", "sales_tax_rate", "coli_index", "notes"} <= set(prof)
    res = calculate_state_tax_for_state("OH", 400_000.0, 100_000.0)
    assert res["state_code"] == "OH"
    assert abs(res["total_state_tax"] - 500_000.0 * 0.0275) < 0.01


def _sim_r3(events=(), **kw):
    params = dict(
        events=list(events), liquid_start=0.0, retirement_start=0.0, real_estate_start=0.0,
        mortgage_start=0.0, other_start=0.0, family_id=0, view_mode="nominal", start_year=2026,
        annual_spending=0.0, inflation_rate=0.0, equity_annual_growth=0.0,
        blended_liquid_growth=0.0, blended_retire_growth=0.0, growth_real_estate=0.0,
        primary_birth_year=1980, spouse_birth_year=1980, primary_retirement_age=150, spouse_retirement_age=150,
    )
    params.update(kw)
    return run_simulation(**params)


# 1. A child plan with a stored empty event_ids inherits every parent event.
def test_child_with_empty_event_ids_inherits_parent_events():
    scens = [
        {"id": "scen_baseline", "name": "Baseline", "event_ids": ["e1", "e2"]},
        {"id": "scen_child", "name": "Child", "parent_id": "scen_baseline", "event_ids": []},
    ]
    child = next(s for s in hierarchy.resolve_scenario_hierarchy(scens) if s["id"] == "scen_child")
    assert child["event_ids"] == ["e1", "e2"]
    assert child["excluded_event_ids"] == []


def test_child_explicit_exclusion_still_removes_parent_event():
    scens = [
        {"id": "scen_baseline", "name": "Baseline", "event_ids": ["e1", "e2"]},
        {"id": "scen_child", "name": "Child", "parent_id": "scen_baseline", "event_ids": [], "excluded_event_ids": ["e2"], "added_event_ids": []},
    ]
    child = next(s for s in hierarchy.resolve_scenario_hierarchy(scens) if s["id"] == "scen_child")
    assert child["event_ids"] == ["e1"]


# 2. A scenario's own ss_claim_age wins over the parent's per-person claim age.
def test_scenario_ss_claim_age_overrides_inherited_primary_claim_age():
    scens = [
        {"id": "scen_baseline", "name": "Baseline", "event_ids": [], "primary_ss_claim_age": 67, "spouse_ss_claim_age": 67},
        {"id": "scen_child", "name": "Child", "parent_id": "scen_baseline", "ss_claim_age": 70},
    ]
    child = next(s for s in hierarchy.resolve_scenario_hierarchy(scens) if s["id"] == "scen_child")
    assert child["primary_ss_claim_age"] == 70
    assert child["spouse_ss_claim_age"] == 70
    assert child["overrides"]["primary_ss_claim_age"] == 70


# 3. A debt payoff larger than liquid assets is funded from retirement accounts, not created from nothing.
def test_debt_payoff_beyond_liquid_draws_retirement_accounts():
    payoff = {"id": "evt_pay", "name": "Pay off mortgage", "category": "debt_payoff", "year": 2027, "amount": 242_000.0,
              "amount_basis": "fixed"}
    base = _sim_r3(liquid_start=44_000.0, retirement_start=500_000.0, real_estate_start=600_000.0, mortgage_start=242_000.0)["schedule"]
    paid = _sim_r3([payoff], liquid_start=44_000.0, retirement_start=500_000.0, real_estate_start=600_000.0, mortgage_start=242_000.0)["schedule"]
    row_b = next(r for r in base if r["year"] == 2027)
    row_p = next(r for r in paid if r["year"] == 2027)
    # Net worth is unchanged by repaying debt with assets (mortgage service itself is the only difference).
    assert abs(row_p["total_net_worth"] - row_b["total_net_worth"]) < 60_000.0
    assert row_p["liquid_assets"] + row_p["retirement_assets"] < row_b["liquid_assets"] + row_b["retirement_assets"] - 150_000.0


# 4. The projection runs to the primary earner's age 100.
def test_projection_runs_through_age_100():
    sched = _sim_r3(primary_birth_year=1990)["schedule"]
    assert sched[-1]["age_primary"] == 100
    assert sched[0]["age_primary"] == 36


def test_mc_success_rate_is_none_for_ages_never_reached():
    n = 20
    res = _execute_monte_carlo_kernel(
        trials=50, seed=1, num_years=n, years=[2026 + i for i in range(n)], ages_primary=[50 + i for i in range(n)],
        initial_liquid=1_000_000.0, initial_re=0.0, initial_equity=0.0, initial_total_nw=1_000_000.0,
        yearly_net_cf=[0.0] * n, yearly_re_equity=[0.0] * n, yearly_comp_equity=[0.0] * n, yearly_non_liquid=[0.0] * n,
        mu_real=0.03, drift=0.02, sigma_port=0.1, inflation_rate=0.02, planned_ret_yr=2030,
        port_stats={"w_us": 0.6, "w_intl": 0.2, "w_bonds": 0.2, "w_cash": 0.0}, active_id="s", scenario_name="S",
    )
    assert res["success_rate_age_85"] is None and res["success_rate_age_90"] is None and res["success_rate_age_100"] is None


# 5. Company equity does not make a trial solvent.
def test_mc_trial_with_only_company_equity_is_not_solvent():
    n = 46
    res = _execute_monte_carlo_kernel(
        trials=50, seed=1, num_years=n, years=[2026 + i for i in range(n)], ages_primary=[55 + i for i in range(n)],
        initial_liquid=100_000.0, initial_re=0.0, initial_equity=5_000_000.0, initial_total_nw=5_100_000.0,
        yearly_net_cf=[-50_000.0] * n, yearly_re_equity=[0.0] * n, yearly_comp_equity=[5_000_000.0] * n,
        yearly_non_liquid=[5_000_000.0] * n,
        mu_real=0.0, drift=0.0, sigma_port=0.0, inflation_rate=0.0, planned_ret_yr=2030,
        port_stats={"w_us": 0.6, "w_intl": 0.2, "w_bonds": 0.2, "w_cash": 0.0}, active_id="s", scenario_name="S",
    )
    assert res["success_rate_age_85"] == 0.0 and res["success_rate_age_100"] == 0.0
    assert all(not st["survived"] for st in res["stress_tests"].values())


# 6. Stated annual savings are saved in full while the household is working.
def test_annual_savings_are_not_scaled_by_take_home_ratio():
    from forecast.context import HouseholdContext
    ctx = HouseholdContext(user_state="TX", primary_earned_income=300_000.0, has_spouse=False)
    sched = _sim_r3(
        primary_birth_year=1990, primary_retirement_age=65, spouse_retirement_age=65,
        annual_spending=100_000.0, annual_savings=40_000.0, context=ctx,
    )["schedule"]
    assert sched[0]["salary_savings"] == 40_000.0


# 8. Honorifics and suffixes are not first names.
def test_first_name_skips_honorifics_and_suffixes():
    assert first_name("Dr. Sarah Jones, MD", "User") == "Sarah"
    assert first_name("Mr. Robert Chen Jr.", "User") == "Robert"
    assert first_name("Priya Natarajan", "User") == "Priya"
    assert first_name("Dr.", "User") == "User"
    assert first_name("", "User") == "User"


# 10. A primary-residence purchase ends the old mortgage.
def test_buy_primary_sells_old_home_and_pays_off_old_mortgage():
    buy = {"id": "evt_buy", "name": "Buy primary", "category": "real_estate", "re_action": "buy_primary", "year": 2027,
           "purchase_price": 1_000_000.0, "down_payment_pct": 0.5, "amount_basis": "fixed", "annual_ongoing_carrying_cost": 0.0}
    common = dict(liquid_start=2_000_000.0, real_estate_start=800_000.0, mortgage_start=400_000.0, mortgage_annual_service=30_000.0)
    sched = _sim_r3([buy], **common)["schedule"]
    row = next(r for r in sched if r["year"] == 2027)
    # Old $400k loan is gone; only the new $500k loan remains.
    assert 480_000.0 <= row["mortgage_balance"] <= 500_000.0
    later = next(r for r in sched if r["year"] == 2030)
    assert later["mortgage_balance"] <= 500_000.0
    keep = _sim_r3([{**buy, "re_action": "buy_vacation"}], **common)["schedule"]
    assert next(r for r in keep if r["year"] == 2027)["mortgage_balance"] > 850_000.0


# 7. The IPS section is read from the stored household assumptions, not a nonexistent profile key.
def test_ssr_holdings_reads_stored_investment_policy(monkeypatch):
    from ssr import holdings

    class _Path:
        def exists(self):
            return True

    monkeypatch.setattr(holdings, "DB_PATH", _Path())
    sections = {"investment_policy": {"anchor_preset": "glidepath_60_40", "drift_tolerance": 0.1}}
    monkeypatch.setattr(
        holdings.db.household_assumptions, "get_dict_section",
        lambda family_id=0, section_key="", db_path=None: dict(sections.get(section_key) or {}),
    )
    assert holdings.read_stored_investment_policy(7) == {"anchor_preset": "glidepath_60_40", "drift_tolerance": 0.1}
    assert holdings.read_stored_investment_policy(0) == {}


# 9. LP NAV outside synced accounts counts toward private investments in the allocation.
def test_allocation_includes_manual_lp_nav(monkeypatch):
    from account_sync import allocation
    from services import private_markets_service as pms

    monkeypatch.setattr(pms, "get_lp_commitments", lambda family_id=0: [
        {"id": "a", "account_id": "", "current_nav": 300_000.0},
        {"id": "b", "account_id": "acc1", "current_nav": 999_000.0},
    ])
    assert allocation._manual_lp_nav(5, {"acc1"}) == 300_000.0
    assert allocation._manual_lp_nav(0, set()) == 0.0
    monkeypatch.setattr(pms, "get_lp_commitments", lambda family_id=0: [{"id": "a", "account_id": "", "current_nav": 300_000.0}])
    out = allocation.get_detailed_asset_allocation([], {}, categories={"private_investments": {"total": 100_000.0}},
                                                   family_id=5, roles_cache={}, family_comps=[])
    assert out["totals"]["private_investments"] == 400_000.0


# 11. Form 3921 only for ISO exercises.
def test_form_3921_only_for_iso_exercises(monkeypatch):
    from types import SimpleNamespace
    from services import tax_checklist_service as tcs

    def grant(kind, exercised, company):
        return SimpleNamespace(grant_type=kind, shares_exercised=exercised, company=SimpleNamespace(company_name=company))

    grants = [grant("nso", 100.0, "NsoCo"), grant("rsu", 0.0, "RsuCo"), grant("iso", 0.0, "IsoUnexercised"), grant("iso", 50.0, "IsoCo")]

    class _Sess:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def scalars(self, stmt): return SimpleNamespace(all=lambda: grants)

    monkeypatch.setattr(tcs, "get_orm_session", lambda *a, **k: _Sess())
    items = tcs._derive_equity_phil_lp_items(None, 1, 2026)
    ids = [i["id"] for i in items if i["id"].startswith("equity_3921")]
    assert ids == ["equity_3921_isoco"]


def test_lp_commitments_read_the_database_of_the_request_universe(monkeypatch):
    """The LP book lives in the household DB of the session's universe, not of the process-wide APP_UNIVERSE."""
    import config
    from flask import session
    from services import private_markets_service as pms
    from services import request_context
    from wsgi import app as flask_app

    seen = []

    def _load(db_path, table, family_id=0):
        seen.append(Path(db_path))
        return [{"id": "lp_1", "fund_name": "Alpha", "current_nav": 10.0, "total_commitment": 20.0}]

    monkeypatch.setattr(pms.security, "db_load_encrypted", _load)
    with flask_app.test_request_context("/"):
        session.update(authenticated=True, family_id=1, user_family_id=1, universe="public", is_demo=False)
        assert request_context.get_current_universe() == "public"
        expected = request_context.get_current_db_path(family_id=1)
        pms.get_lp_commitments(family_id=1)
    assert seen == [expected]
    assert expected != config.get_family_db_path(1)
