"""Federal tax engine: MFS/HOH, age-65 deductions, LTCG stacking + NIIT, safe harbor, filing-status profile."""

import pytest

from services import statutory_limits as sl
from services import tax_engine as te


def test_mfs_brackets_are_half_of_mfj_and_deduction_is_single():
    for (lo, hi, rate), (mlo, mhi, mrate) in zip(te.get_federal_brackets("MFS")[:-1], te.FED_BRACKETS_MFJ_2026[:-1]):
        assert (hi, rate) == (mhi / 2, mrate)
    assert te.get_federal_brackets("mfs")[-1][0] == 384350.0
    assert te.get_standard_deduction("MFS") == 16100.0
    assert te.calculate_federal_ordinary_tax(100000 - 16100, te.get_federal_brackets("MFS")) > te.calculate_federal_ordinary_tax(
        200000 - 32200, te.get_federal_brackets("MFJ")
    ) / 2 - 1


def test_hoh_present_and_distinct():
    assert te.get_standard_deduction("HOH") == 24150.0
    assert te.get_federal_brackets("HOH")[0][1] == 17700.0


def test_age_65_additional_standard_deduction():
    assert te.get_standard_deduction("SINGLE", 1) == 16100.0 + 2050.0
    assert te.get_standard_deduction("HOH", 1) == 24150.0 + 2050.0
    assert te.get_standard_deduction("MFJ", 2) == 32200.0 + 2 * 1650.0
    assert te.get_standard_deduction("MFS", 1) == 16100.0 + 1650.0
    assert te.get_standard_deduction("MFJ", 0) == 32200.0


def test_senior_deduction_amount_phaseout_and_years():
    assert sl.senior_deduction(2026, "SINGLE", 1, 75000) == 6000.0
    assert sl.senior_deduction(2026, "SINGLE", 1, 85000) == 6000.0 - 600.0
    assert sl.senior_deduction(2026, "SINGLE", 1, 175000) == 0.0
    assert sl.senior_deduction(2026, "MFJ", 2, 150000) == 12000.0
    assert sl.senior_deduction(2026, "MFJ", 2, 200000) == 12000.0 - 3000.0
    assert sl.senior_deduction(2026, "MFS", 1, 10000) == 0.0
    assert sl.senior_deduction(2029, "SINGLE", 1, 10000) == 0.0
    assert sl.senior_deduction(2025, "SINGLE", 1, 10000) == 6000.0


def test_senior_deduction_reaches_the_tax_math():
    base = te.calculate_household_take_home_pay(100000.0, filing_status="SINGLE", has_spouse=False)
    senior = te.calculate_household_take_home_pay(100000.0, filing_status="SINGLE", has_spouse=False, seniors_65_plus=1)
    extra = 2050.0 + 6000.0 - 0.06 * 25000.0
    brk = te.FED_BRACKETS_SINGLE_2026
    expected_drop = te.calculate_federal_ordinary_tax(100000 - 16100, brk) - te.calculate_federal_ordinary_tax(
        100000 - 16100 - extra, brk
    )
    assert base["federal_tax"] - senior["federal_tax"] == pytest.approx(expected_drop, abs=0.01)
    nso0 = te.calculate_nso_exercise_tax(10000.0, 70000.0, filing_status="SINGLE")
    nso1 = te.calculate_nso_exercise_tax(10000.0, 70000.0, filing_status="SINGLE", seniors_65_plus=1)
    assert nso1["federal_income_tax"] < nso0["federal_income_tax"]


def test_ltcg_zero_band_and_stacking_on_ordinary_income():
    low = te.calculate_stock_sale_tax(30000.0, 0.0, other_income=16100.0, filing_status="SINGLE")
    assert low["federal_capital_gains_tax"] == 0.0 and low["niit_tax"] == 0.0
    # Stacked: ordinary taxable 40,000 (single), gain 20,000 -> 9,450 at 0%, 10,550 at 15%
    stacked = te.calculate_stock_sale_tax(20000.0, 0.0, other_income=56100.0, filing_status="SINGLE")
    assert stacked["federal_capital_gains_tax"] == pytest.approx(10550.0 * 0.15)
    top = te.calculate_stock_sale_tax(1_000_000.0, 0.0, other_income=1_000_000.0, filing_status="SINGLE")
    assert top["federal_capital_gains_tax"] == pytest.approx(1_000_000.0 * 0.20)


def test_ltcg_spans_all_three_bands():
    res = te.calculate_stock_sale_tax(700000.0, 0.0, other_income=32200.0, filing_status="MFJ")
    assert res["federal_capital_gains_tax"] == pytest.approx((613700 - 98900) * 0.15 + (700000 - 613700) * 0.20)


def test_niit_threshold_by_status():
    for status, threshold in (("SINGLE", 200000.0), ("MFJ", 250000.0), ("MFS", 125000.0), ("HOH", 200000.0)):
        below = te.calculate_stock_sale_tax(50000.0, 0.0, other_income=threshold - 50000.0, filing_status=status)
        assert below["niit_tax"] == 0.0
        straddle = te.calculate_stock_sale_tax(50000.0, 0.0, other_income=threshold - 20000.0, filing_status=status)
        assert straddle["niit_tax"] == pytest.approx(30000.0 * 0.038)
    assert te.calculate_stock_sale_tax(10000.0, 0.0, other_income=400000.0, is_mfj=True)["niit_tax"] == pytest.approx(380.0)


def test_short_term_gain_is_ordinary_income():
    st = te.calculate_stock_sale_tax(10000.0, 0.0, holding_period_days=100, other_income=116100.0, filing_status="SINGLE")
    brk = te.FED_BRACKETS_SINGLE_2026
    assert st["federal_capital_gains_tax"] == pytest.approx(
        te.calculate_federal_ordinary_tax(110000.0, brk) - te.calculate_federal_ordinary_tax(100000.0, brk)
    )
    assert st["wa_capital_gains_tax"] == 0.0


def test_safe_harbor_multiplier_by_prior_agi():
    assert te.calculate_withholding_safe_harbor(0.0, 10000.0, 0.0, prior_year_agi=140000.0)["safe_harbor_target"] == 10000.0
    assert te.calculate_withholding_safe_harbor(0.0, 10000.0, 0.0, prior_year_agi=160000.0)["safe_harbor_target"] == pytest.approx(11000.0)
    assert te.calculate_withholding_safe_harbor(0.0, 10000.0, 0.0, prior_year_agi=80000.0, filing_status="MFS")["safe_harbor_target"] == pytest.approx(11000.0)
    capped = te.calculate_withholding_safe_harbor(40000.0, 100000.0, 0.0, prior_year_agi=500000.0)
    assert capped["safe_harbor_target"] == pytest.approx(36000.0)


def test_compensation_safe_harbor_uses_current_year_estimate():
    from ssr import compensation_ssr as cs

    history = [{"year": 2025, "user_id": 1, "salary": 150000.0, "bonus": 50000.0}]
    est = cs._current_year_federal_tax_estimate(history, history, "MFJ")
    assert est == pytest.approx(te.calculate_federal_ordinary_tax(200000 - 32200))
    half = cs._current_year_federal_tax_estimate(history + [{"year": 2025, "user_id": 2, "salary": 200000.0}], history, "MFJ")
    assert 0 < half < te.calculate_federal_ordinary_tax(400000 - 32200)
    assert cs._current_year_federal_tax_estimate([], [], "MFJ") == 0.0


def test_filing_status_options_and_route_validation():
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "templates/components/settings/_tax_profile.html").read_text()
    for value in ("MFJ", "SINGLE", "MFS", "HOH"):
        assert f'<option value="{value}"' in html
    route = (Path(__file__).resolve().parent.parent / "routes/settings.py").read_text()
    assert '("MFJ", "SINGLE", "MFS", "HOH")' in route


# --- F-ENG-17 follow-ups: state-gated WA excise, filing status in sales, MFS Medicare -----------------------------------

def test_wa_excise_is_charged_only_to_a_wa_household_inside_the_engine():
    wa = te.calculate_stock_sale_tax(2_278_000.0, 0.0, state="WA")
    assert wa["wa_capital_gains_tax"] == pytest.approx(169_000.0)
    assert wa["total_tax"] == pytest.approx(
        wa["federal_capital_gains_tax"] + wa["niit_tax"] + wa["wa_capital_gains_tax"]
    )
    for state in ("TX", "CA", "", None):
        other = te.calculate_stock_sale_tax(2_278_000.0, 0.0, state=state)
        assert other["wa_capital_gains_tax"] == 0.0
        assert other["total_tax"] == pytest.approx(wa["total_tax"] - 169_000.0)


def test_mfs_additional_medicare_threshold_is_125k():
    assert sl.ADDITIONAL_MEDICARE_THRESHOLDS == {"MFJ": 250_000.0, "SINGLE": 200_000.0, "HOH": 200_000.0, "MFS": 125_000.0}
    mfs = te.calculate_medicare_tax(150_000.0, filing_status="MFS")
    assert mfs["additional_medicare"] == pytest.approx(25_000.0 * 0.009)
    assert te.calculate_medicare_tax(150_000.0, filing_status="SINGLE")["additional_medicare"] == 0.0
    assert te.calculate_medicare_tax(150_000.0, filing_status="HOH")["additional_medicare"] == 0.0
    assert te.calculate_medicare_tax(260_000.0, filing_status="MFJ")["additional_medicare"] == pytest.approx(90.0)
    # prior wages already past the MFS threshold: every added dollar owes the 0.9%
    assert te.calculate_medicare_tax(10_000.0, prior_wages=130_000.0, filing_status="MFS")["additional_medicare"] == pytest.approx(90.0)
    # the NSO path uses the filing status, not just the MFJ flag
    nso = te.calculate_nso_exercise_tax(50_000.0, 100_000.0, filing_status="MFS")
    assert nso["medicare_tax"] == pytest.approx(50_000.0 * 0.0145 + 25_000.0 * 0.009)
    assert te.calculate_household_take_home_pay(150_000.0, filing_status="MFS", has_spouse=False)["medicare_tax"] == pytest.approx(
        150_000.0 * 0.0145 + 25_000.0 * 0.009, abs=0.01
    )


def test_hoh_and_mfs_sales_stack_on_other_income_not_from_zero():
    kw = dict(sale_proceeds=100_000.0, cost_basis=0.0)
    for status, zero_top in (("HOH", 66_200.0), ("MFS", 49_450.0), ("SINGLE", 49_450.0)):
        std = te.get_standard_deduction(status)
        stacked = te.calculate_stock_sale_tax(other_income=std + zero_top, filing_status=status, **kw)
        assert stacked["federal_capital_gains_tax"] == pytest.approx(100_000.0 * 0.15)
        fresh = te.calculate_stock_sale_tax(other_income=0.0, filing_status=status, **kw)
        assert fresh["federal_capital_gains_tax"] < stacked["federal_capital_gains_tax"]
    # the old is_mfj flag alone meant Single, which is wrong for HOH
    hoh = te.calculate_stock_sale_tax(other_income=60_000.0, filing_status="HOH", **kw)
    single = te.calculate_stock_sale_tax(other_income=60_000.0, is_mfj=False, **kw)
    assert hoh["federal_capital_gains_tax"] < single["federal_capital_gains_tax"]


def test_indexed_sale_deflates_other_income_and_keeps_niit_threshold_nominal():
    from forecast import tax_indexing as ti
    # 2026 is the base year: no indexing, same as the engine
    base = ti.stock_sale_tax(100_000.0, 0.0, 2026, 0.03, other_income=300_000.0, filing_status="SINGLE", state="")
    direct = te.calculate_stock_sale_tax(100_000.0, 0.0, other_income=300_000.0, filing_status="SINGLE", tax_year=2026)
    assert base["total_tax"] == pytest.approx(direct["total_tax"])
    # in 2036 the same nominal income is lower in today's dollars (cheaper LTCG band), but NIIT is fixed in statute
    later = ti.stock_sale_tax(100_000.0, 0.0, 2036, 0.03, other_income=300_000.0, filing_status="SINGLE", state="")
    assert later["niit_tax"] == pytest.approx(100_000.0 * 0.038)  # all 100k is over the fixed $200k threshold
    assert later["federal_capital_gains_tax"] < base["federal_capital_gains_tax"] or later["federal_capital_gains_tax"] == base["federal_capital_gains_tax"]


def test_2026_amt_and_ltcg_constants_match_rev_proc_2025_32():
    assert sl.AMT_EXEMPTION_2026 == {"MFJ": 140_200.0, "SINGLE": 90_100.0, "HOH": 90_100.0, "MFS": 70_100.0}
    assert sl.AMT_PHASEOUT_START_2026 == {"MFJ": 1_000_000.0, "SINGLE": 500_000.0, "HOH": 500_000.0, "MFS": 500_000.0}
    assert sl.AMT_UPPER_RATE_THRESHOLD_2026 == {"MFJ": 244_500.0, "SINGLE": 244_500.0, "HOH": 244_500.0, "MFS": 122_250.0}
    assert sl.AMT_PHASEOUT_RATE == 0.50
    # complete phase-out amounts published in § 3.10: exemption / 50% above the threshold
    for status, complete in (("MFJ", 1_280_400.0), ("SINGLE", 680_200.0), ("MFS", 640_200.0)):
        assert sl.AMT_PHASEOUT_START_2026[status] + sl.AMT_EXEMPTION_2026[status] / sl.AMT_PHASEOUT_RATE == complete
    assert sl.LTCG_BAND_TOPS_2026["MFS"] == (49_450.0, 306_850.0)
