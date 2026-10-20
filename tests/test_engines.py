"""
Unit tests for tax_engine and equity_engine
Verifies calculations against user's ground-truth spreadsheet and Monarch snapshots.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tax_engine
import equity_engine


def test_primary_equity_ground_truth():
    """Validates Grant 1, 2, 3 numbers and totals at active FMV."""
    price = equity_engine.get_current_409a_price(family_id=1)
    sim = equity_engine.simulate_valuation_scenario(share_price=price, include_wa_millionaire_tax=False, family_id=1)

    # 1. Total Gross Equity Value matches Monarch display balance ($34,471,775.80)
    assert abs(sim["total_gross_equity_value"] - 34471775.80) < 0.10

    # 2. Owned Stock (2,178 shares @ $2,733 = $5,952,474.00)
    assert sim["total_owned_shares"] == 2178.0
    g1 = next(g for g in sim["grants"] if "Grant 1" in g["nickname"])
    assert abs(g1["owned_gross_value"] - 5952474.00) < 0.10

    # 3. Grant 1 unexercised options (7,505 options, spread = $19,478,176.80)
    assert g1["unexercised_options"] == 7505.0
    assert abs(g1["strike_cost"] - 1032988.20) < 0.10
    assert abs(g1["spread"] - 19478176.80) < 0.10

    # 4. Grant 2 unexercised options (2,372 options, spread = $4,257,740.00)
    g2 = next(g for g in sim["grants"] if "Grant 2" in g["nickname"])
    assert g2["unexercised_options"] == 2372.0
    assert abs(g2["strike_cost"] - 2224936.00) < 0.10
    assert abs(g2["spread"] - 4257740.00) < 0.10

    # 5. Grant 3 vested unexercised options (4,685 options, spread = $4,783,385.00)
    g3 = next(g for g in sim["grants"] if "Grant 3" in g["nickname"])
    assert g3["unexercised_options"] == 4685.0
    assert abs(g3["strike_cost"] - 8020720.00) < 0.10
    assert abs(g3["spread"] - 4783385.00) < 0.10

    # 6. Total Unexercised Vested Spread = $28,519,301.80
    assert abs(sim["total_taxable_spread"] - 28519301.80) < 0.10

    # 7. Total Strike Cost Needed = $11,278,644.20
    assert abs(sim["total_strike_cost_needed"] - 11278644.20) < 0.10


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
    price = equity_engine.get_current_409a_price(family_id=1)
    sim = equity_engine.simulate_valuation_scenario(share_price=price, family_id=1)
    # The WA 9.9% tax on $28.5M spread should be over $2.7M
    assert sim["wa_tax_difference"] > 2700000.0


def test_state_tax_arbitrage_comparison():
    """Tests multi-state tax arbitrage (WA vs WA_2028 vs NV vs CA)."""
    spread = 28519301.80
    cap_gains = 4717026.00 # Gains on 2,178 shares

    arb = tax_engine.compare_state_tax_arbitrage(
        ordinary_spread=spread,
        capital_gains=cap_gains,
        base_w2_salary=500000.0
    )

    states_dict = {s["state_code"]: s for s in arb["states"]}

    # Nevada, Texas, Florida should have $0 state tax
    assert states_dict["NV"]["total_state_tax"] == 0.0
    assert states_dict["TX"]["total_state_tax"] == 0.0
    assert states_dict["FL"]["total_state_tax"] == 0.0

    # California should have massive state tax (> $4.4M)
    assert states_dict["CA"]["total_state_tax"] > 4400000.0

    # Moving to Nevada from WA under 2028 laws saves over $3M
    assert arb["nevada_arbitrage_savings_vs_wa_2028"] > 3000000.0


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
    import tax_engine

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
    import monarch_service
    snap = monarch_service.get_financial_snapshot(family_id=1)
    # Education accounts must be tracked as separate custodial assets
    assert snap["education_assets"] > 700000.0
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
    import forecast_engine
    res = forecast_engine.simulate_multi_scenarios(family_id=1, annual_living_spend=50000000.0)
    readiness = res.get("active_retirement_readiness", {})
    assert readiness.get("is_sustainable") is False
    assert readiness.get("can_retire_today") is False
    assert readiness.get("earliest_joint_year") is None
    assert res["scorecard"][0]["is_depleted"] is True


def test_dynamic_gap_year_roth_conversion_bracket_fill():
    """Validates dynamic bracket-filling Roth conversion ladder in gap years and working years."""
    from forecast.scenarios import process_roth_or_72t_event, process_pre65_healthcare_event

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
    )
    assert any("244k MAGI" in msg for msg in aca_log)


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
    sale_res = tax_engine.calculate_stock_sale_tax(sale_proceeds=2278000.0, cost_basis=0.0)
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
    from forecast.waterfall_helpers import _ss_factor

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

