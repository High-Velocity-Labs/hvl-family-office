"""Tax Engine: Federal and Washington State Tax Modeling."""

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional

from services import statutory_limits
from services.federal_capital_gains import NIIT_RATE, long_term_gain_tax, niit_on_gain
from services.tax_calculations import (
    STATE_TAX_PROFILES,
    calculate_state_tax_for_state,
    compare_state_tax_arbitrage,
)


# 2026 Federal Tax Brackets (Rev. Proc. 2025-32) for Married Filing Jointly (MFJ)
FED_BRACKETS_MFJ_2026: List[Tuple[float, float, float]] = [
    (0.0, 24800.0, 0.10),
    (24800.0, 100800.0, 0.12),
    (100800.0, 211400.0, 0.22),
    (211400.0, 403550.0, 0.24),
    (403550.0, 512450.0, 0.32),
    (512450.0, 768700.0, 0.35),
    (768700.0, float("inf"), 0.37),
]

# 2026 Federal Tax Brackets (Rev. Proc. 2025-32) for Head of Household (HOH) - Single Parents
FED_BRACKETS_HOH_2026: List[Tuple[float, float, float]] = [
    (0.0, 17700.0, 0.10),
    (17700.0, 67450.0, 0.12),
    (67450.0, 105700.0, 0.22),
    (105700.0, 201750.0, 0.24),
    (201750.0, 256200.0, 0.32),
    (256200.0, 640600.0, 0.35),
    (640600.0, float("inf"), 0.37),
]

# 2026 Federal Tax Brackets (Rev. Proc. 2025-32) for Single Filers
FED_BRACKETS_SINGLE_2026: List[Tuple[float, float, float]] = [
    (0.0, 12400.0, 0.10),
    (12400.0, 50400.0, 0.12),
    (50400.0, 105700.0, 0.22),
    (105700.0, 201775.0, 0.24),
    (201775.0, 256225.0, 0.32),
    (256225.0, 640600.0, 0.35),
    (640600.0, float("inf"), 0.37),
]

# 2026 Federal Tax Brackets (Rev. Proc. 2025-32) for Married Filing Separately (MFS): MFJ halved
FED_BRACKETS_MFS_2026: List[Tuple[float, float, float]] = [
    (0.0, 12400.0, 0.10),
    (12400.0, 50400.0, 0.12),
    (50400.0, 105700.0, 0.22),
    (105700.0, 201775.0, 0.24),
    (201775.0, 256225.0, 0.32),
    (256225.0, 384350.0, 0.35),
    (384350.0, float("inf"), 0.37),
]

# Federal Long-Term Capital Gains Brackets (MFJ 2026)
FED_LTCG_BRACKETS_MFJ_2026: List[Tuple[float, float, float]] = [
    (0.0, 98900.0, 0.00),
    (98900.0, 613700.0, 0.15),
    (613700.0, float("inf"), 0.20),
]

# Standard Deductions (2026)
STANDARD_DEDUCTION_MFJ_2026 = 32200.0
STANDARD_DEDUCTION_HOH_2026 = 24150.0
STANDARD_DEDUCTION_SINGLE_2026 = 16100.0
STANDARD_DEDUCTION_MFS_2026 = 16100.0


def get_standard_deduction(filing_status: str = "MFJ", seniors_65_plus: int = 0, tax_year: int = 2026) -> float:
    """Returns the IRS standard deduction (MFJ, MFS, HOH or Single) plus the extra amount per person aged 65+."""
    fs = (filing_status or "MFJ").strip().upper()
    base = {
        "HOH": STANDARD_DEDUCTION_HOH_2026, "SINGLE": STANDARD_DEDUCTION_SINGLE_2026,
        "MFS": STANDARD_DEDUCTION_MFS_2026,
    }.get(fs, STANDARD_DEDUCTION_MFJ_2026)
    married = fs not in ("HOH", "SINGLE")
    return base + statutory_limits.additional_standard_deduction_65(tax_year, married, seniors_65_plus)


def get_total_deduction(
    filing_status: str = "MFJ", seniors_65_plus: int = 0, magi: float = 0.0, tax_year: int = 2026,
) -> float:
    """Standard deduction (with the age-65+ extra) plus the OBBBA senior deduction at `magi`."""
    senior = statutory_limits.senior_deduction(tax_year, filing_status, seniors_65_plus, magi)
    return get_standard_deduction(filing_status, seniors_65_plus, tax_year) + senior


def get_federal_brackets(filing_status: str = "MFJ") -> List[Tuple[float, float, float]]:
    """Returns progressive federal brackets for MFJ, MFS, HOH (single parent), or Single."""
    fs = (filing_status or "MFJ").strip().upper()
    return {"HOH": FED_BRACKETS_HOH_2026, "SINGLE": FED_BRACKETS_SINGLE_2026, "MFS": FED_BRACKETS_MFS_2026}.get(
        fs, FED_BRACKETS_MFJ_2026
    )


# FICA / Medicare Parameters
FICA_SS_WAGE_BASE_2026 = 184500.0   # Social Security wage cap
FICA_SS_RATE = 0.062                 # 6.2%
MEDICARE_BASE_RATE = 0.0145          # 1.45%
ADDITIONAL_MEDICARE_RATE = 0.009     # 0.9%
ADDITIONAL_MEDICARE_THRESHOLD_MFJ = statutory_limits.ADDITIONAL_MEDICARE_THRESHOLDS["MFJ"]

# Net Investment Income Tax (NIIT)
NIIT_THRESHOLD_MFJ = statutory_limits.NIIT_MAGI_THRESHOLDS["MFJ"]

# Washington State Parameters
WA_CAP_GAINS_RATE = 0.07             # 7% excise tax on long-term capital gains
WA_CAP_GAINS_EXEMPTION_2025 = 278000.0  # Tax year 2025; DOR has published no 2026 figure, none is guessed
WA_CAP_GAINS_SURCHARGE_RATE = 0.029  # 2.9% surcharge on taxable gains > $1M (top marginal rate 9.9%)
WA_CAP_GAINS_SURCHARGE_THRESHOLD = 1000000.0  # Threshold above exemption
WA_MILLIONAIRE_TAX_RATE = 0.099      # 9.9% tax on Washington taxable income > $1M (SB 6346)
WA_MILLIONAIRE_TAX_THRESHOLD = 1000000.0


def calculate_wa_capital_gains_tax(gain: float) -> float:
    """
    Calculates WA State Capital Gains excise tax (RCW 82.87):
    - Exempt up to the $278,000 standard deduction (tax year 2025, the latest DOR figure)
    - 7.0% on taxable long-term capital gains up to $1,000,000 above exemption
    - 9.9% (7.0% base + 2.9% surcharge) on taxable long-term capital gains exceeding $1,000,000
    """
    if gain <= WA_CAP_GAINS_EXEMPTION_2025:
        return 0.0
    taxable_gain = gain - WA_CAP_GAINS_EXEMPTION_2025
    if taxable_gain <= WA_CAP_GAINS_SURCHARGE_THRESHOLD:
        return taxable_gain * WA_CAP_GAINS_RATE
    base_tax = WA_CAP_GAINS_SURCHARGE_THRESHOLD * WA_CAP_GAINS_RATE
    surcharged_tax = (taxable_gain - WA_CAP_GAINS_SURCHARGE_THRESHOLD) * (WA_CAP_GAINS_RATE + WA_CAP_GAINS_SURCHARGE_RATE)
    return base_tax + surcharged_tax


@dataclass
class TaxProfile:
    filing_status: str = "MFJ"
    state: str = ""
    include_wa_millionaire_tax: bool = False
    prior_year_total_tax: float = 0.0
    w2_base_salary: float = 0.0
    w2_bonus: float = 0.0
    pre_tax_401k: float = 0.0
    pre_tax_hsa: float = 0.0


def calculate_federal_ordinary_tax(taxable_income: float, brackets: List[Tuple[float, float, float]] = FED_BRACKETS_MFJ_2026) -> float:
    """Calculates progressive federal ordinary income tax from tax brackets."""
    if taxable_income <= 0:
        return 0.0
    total_tax = 0.0
    for lower, upper, rate in brackets:
        if taxable_income > lower:
            taxable_chunk = min(taxable_income, upper) - lower
            total_tax += taxable_chunk * rate
        else:
            break
    return total_tax


def calculate_medicare_tax(
    wages_or_spread: float, prior_wages: float = 0.0, is_mfj: bool = True, filing_status: Optional[str] = None,
) -> Dict[str, float]:
    """
    Calculates Base Medicare (1.45%) and Additional Medicare (0.9%) on supplemental or total wages.
    The Additional Medicare threshold is $250k MFJ, $200k single/HOH and $125k MFS; `filing_status` overrides `is_mfj`.
    """
    base_tax = wages_or_spread * MEDICARE_BASE_RATE
    status = (filing_status or ("MFJ" if is_mfj else "SINGLE")).strip().upper()
    threshold = statutory_limits.ADDITIONAL_MEDICARE_THRESHOLDS.get(status, ADDITIONAL_MEDICARE_THRESHOLD_MFJ)

    total_wages = prior_wages + wages_or_spread
    if total_wages <= threshold:
        addl_tax = 0.0
    elif prior_wages >= threshold:
        addl_tax = wages_or_spread * ADDITIONAL_MEDICARE_RATE
    else:
        addl_tax = (total_wages - threshold) * ADDITIONAL_MEDICARE_RATE

    return {
        "base_medicare": base_tax,
        "additional_medicare": addl_tax,
        "total_medicare": base_tax + addl_tax,
    }


def calculate_household_take_home_pay(
    gross_salary: float,
    user_state: str = "",
    filing_status: str = "MFJ",
    has_spouse: bool = True,
    spouse_gross_salary: float = 0.0,
    tax_year: Optional[int] = None,
    seniors_65_plus: int = 0,
) -> Dict[str, float]:
    """
    Computes realistic post-tax take-home pay and tax haircut for household earned income.
    Includes:
    - Progressive Federal Ordinary Income Tax (with standard deduction)
    - Employee FICA Social Security (6.2% up to annual wage cap per earner)
    - Medicare Base (1.45%) + Additional Medicare (0.9% above threshold)
    - State Income Tax (WA millionaire's tax, CA, NY, etc.)
    """
    if gross_salary <= 0 and spouse_gross_salary <= 0:
        return {
            "gross_compensation": 0.0,
            "federal_tax": 0.0,
            "fica_tax": 0.0,
            "medicare_tax": 0.0,
            "state_tax": 0.0,
            "total_tax": 0.0,
            "effective_tax_rate": 0.0,
            "net_take_home": 0.0,
        }

    total_gross = gross_salary + spouse_gross_salary
    is_mfj = (filing_status or "MFJ").strip().upper() == "MFJ"
    brackets = get_federal_brackets(filing_status)
    std_ded = get_total_deduction(filing_status, seniors_65_plus, total_gross, tax_year or 2026)

    # 1. Federal Ordinary Income Tax
    taxable_ordinary = max(0.0, total_gross - std_ded)
    fed_tax = calculate_federal_ordinary_tax(taxable_ordinary, brackets)

    # 2. FICA Social Security Tax (6.2% per worker up to wage base)
    fica_primary = min(gross_salary, FICA_SS_WAGE_BASE_2026) * FICA_SS_RATE if gross_salary > 0 else 0.0
    fica_spouse = min(spouse_gross_salary, FICA_SS_WAGE_BASE_2026) * FICA_SS_RATE if (has_spouse and spouse_gross_salary > 0) else 0.0
    fica_total = fica_primary + fica_spouse

    # 3. Medicare Tax (1.45% base + 0.9% additional above MFJ $250k, Single/HOH $200k or MFS $125k)
    medicare_info = calculate_medicare_tax(total_gross, prior_wages=0.0, filing_status=filing_status or "MFJ")
    medicare_total = medicare_info.get("total_medicare", 0.0)

    # 4. State Income Tax
    effective_state = user_state
    if user_state == "WA" and tax_year is not None and tax_year >= 2028:
        effective_state = "WA_2028"
    state_info = calculate_state_tax_for_state(effective_state, total_gross, capital_gains=0.0, is_mfj=is_mfj, tax_year=tax_year)
    state_tax = state_info.get("ordinary_income_tax", 0.0)

    total_tax = fed_tax + fica_total + medicare_total + state_tax
    net_take_home = max(0.0, total_gross - total_tax)
    eff_rate = total_tax / total_gross if total_gross > 0 else 0.0

    return {
        "gross_compensation": round(total_gross, 2),
        "federal_tax": round(fed_tax, 2),
        "fica_tax": round(fica_total, 2),
        "medicare_tax": round(medicare_total, 2),
        "state_tax": round(state_tax, 2),
        "total_tax": round(total_tax, 2),
        "effective_tax_rate": round(eff_rate, 4),
        "net_take_home": round(net_take_home, 2),
    }


def calculate_nso_exercise_tax(
    spread: float,
    prior_ordinary_income: float = 0.0,
    include_wa_millionaire_tax: bool = False,
    is_mfj: bool = True,
    tax_year: Optional[int] = None,
    filing_status: Optional[str] = None,
    seniors_65_plus: int = 0,
) -> Dict[str, float]:
    """
    Calculates exact ordinary income tax, Medicare, and WA state tax on an NSO exercise spread.
    `filing_status` ("MFJ"/"HOH"/"SINGLE") selects the deduction and brackets; without it `is_mfj` picks MFJ or Single.
    An NSO spread is treated as W-2 ordinary wages in the year of exercise.
    WA SB 6346 (9.9% tax on Washington taxable income > $1M) is effective for tax years 2028+.
    If tax_year is provided and < 2028, WA millionaire tax is omitted unless explicitly forced
    without a pre-2028 tax_year.
    """
    if spread <= 0:
        return {
            "spread": 0.0,
            "federal_income_tax": 0.0,
            "medicare_tax": 0.0,
            "wa_state_tax": 0.0,
            "total_tax": 0.0,
            "effective_rate": 0.0,
            "marginal_rate": 0.0,
        }

    # Federal income tax delta: tax(prior + spread) - tax(prior)
    status = (filing_status or ("MFJ" if is_mfj else "SINGLE")).strip().upper()
    year = tax_year or 2026
    ded_without = get_total_deduction(status, seniors_65_plus, prior_ordinary_income, year)
    ded_with = get_total_deduction(status, seniors_65_plus, prior_ordinary_income + spread, year)
    brackets = get_federal_brackets(status)
    tax_without = calculate_federal_ordinary_tax(max(0.0, prior_ordinary_income - ded_without), brackets)
    tax_with = calculate_federal_ordinary_tax(max(0.0, prior_ordinary_income + spread - ded_with), brackets)
    fed_tax = tax_with - tax_without

    # Medicare
    med_info = calculate_medicare_tax(spread, prior_wages=prior_ordinary_income, filing_status=status)
    med_tax = med_info["total_medicare"]

    # Washington State Tax (SB 6346: 9.9% on income > $1M effective 2028+)
    apply_wa = include_wa_millionaire_tax and (tax_year is None or tax_year >= 2028)
    wa_tax = 0.0
    if apply_wa:
        total_wa_income = prior_ordinary_income + spread
        if total_wa_income > WA_MILLIONAIRE_TAX_THRESHOLD:
            taxable_wa_spread = min(spread, total_wa_income - WA_MILLIONAIRE_TAX_THRESHOLD)
            wa_tax = taxable_wa_spread * WA_MILLIONAIRE_TAX_RATE

    total_tax = fed_tax + med_tax + wa_tax
    effective_rate = total_tax / spread if spread > 0 else 0.0

    # Marginal rate at top bracket
    top_fed = 0.37
    top_med = MEDICARE_BASE_RATE + ADDITIONAL_MEDICARE_RATE # 2.35%
    top_wa = WA_MILLIONAIRE_TAX_RATE if apply_wa else 0.0
    marginal_rate = top_fed + top_med + top_wa

    return {
        "spread": spread,
        "federal_income_tax": fed_tax,
        "medicare_tax": med_tax,
        "wa_state_tax": wa_tax,
        "total_tax": total_tax,
        "effective_rate": effective_rate,
        "marginal_rate": marginal_rate,
    }


def calculate_stock_sale_tax(
    sale_proceeds: float,
    cost_basis: float,
    holding_period_days: int = 366,
    other_income: float = 0.0,
    is_mfj: bool = True,
    filing_status: Optional[str] = None,
    seniors_65_plus: int = 0,
    tax_year: Optional[int] = None,
    state: str = "",
) -> Dict[str, float]:
    """
    Calculates Capital Gains Tax on already-exercised shares when sold.
    `other_income` is the household's other ordinary income (AGI before the gain). Long-term gain is taxed at
    0/15/20% stacked on top of ordinary taxable income; short-term gain is ordinary income at the progressive
    brackets. NIIT is 3.8% of the gain above the MAGI threshold. `filing_status` ("MFJ"/"MFS"/"HOH"/"SINGLE")
    overrides `is_mfj`. `state` is the household's state: only "WA" owes the WA capital-gains excise (7% above the
    exemption, 9.9% above $1M); other states' capital-gains tax is the caller's (`state_capital_gains_tax`).
    """
    gain = sale_proceeds - cost_basis
    if gain <= 0:
        return {
            "gain": gain,
            "federal_capital_gains_tax": 0.0,
            "niit_tax": 0.0,
            "wa_capital_gains_tax": 0.0,
            "total_tax": 0.0,
            "effective_rate": 0.0,
        }

    status = (filing_status or ("MFJ" if is_mfj else "SINGLE")).strip().upper()
    year = tax_year or 2026
    magi = other_income + gain
    deduction = get_total_deduction(status, seniors_65_plus, magi, year)
    ordinary_taxable = max(0.0, other_income - deduction)
    niit_tax = niit_on_gain(gain, magi, status)

    if holding_period_days > 365:
        gain_taxable = max(0.0, magi - deduction) - ordinary_taxable
        fed_tax = long_term_gain_tax(gain_taxable, ordinary_taxable, status)
        wa_cg_tax = calculate_wa_capital_gains_tax(gain) if str(state or "").strip().upper() == "WA" else 0.0
    else:
        brackets = get_federal_brackets(status)
        fed_tax = calculate_federal_ordinary_tax(max(0.0, magi - deduction), brackets) - calculate_federal_ordinary_tax(
            ordinary_taxable, brackets
        )
        wa_cg_tax = 0.0
    total_tax = fed_tax + niit_tax + wa_cg_tax

    return {
        "gain": gain,
        "federal_capital_gains_tax": fed_tax,
        "niit_tax": niit_tax,
        "wa_capital_gains_tax": wa_cg_tax,
        "total_tax": total_tax,
        "effective_rate": total_tax / gain,
    }


# IRC § 6654(d)(1)(C): the prior-year safe harbor is 110% of prior-year tax only when prior-year
# AGI exceeds this threshold; otherwise it is 100%.
SAFE_HARBOR_AGI_THRESHOLD = 150000.0
SAFE_HARBOR_AGI_THRESHOLD_MFS = 75000.0
SAFE_HARBOR_HIGH_AGI_MULTIPLIER = 1.10


def safe_harbor_prior_year_multiplier(prior_year_agi: Optional[float], filing_status: str = "MFJ") -> float:
    """Prior-year safe-harbor multiplier: 1.10 above the AGI threshold ($75k MFS), else 1.00.

    An unknown prior-year AGI (None) returns 1.10, the conservative (higher) target.
    """
    if prior_year_agi is None:
        return SAFE_HARBOR_HIGH_AGI_MULTIPLIER
    is_mfs = (filing_status or "").strip().upper() == "MFS"
    threshold = SAFE_HARBOR_AGI_THRESHOLD_MFS if is_mfs else SAFE_HARBOR_AGI_THRESHOLD
    return SAFE_HARBOR_HIGH_AGI_MULTIPLIER if float(prior_year_agi) > threshold else 1.00


def calculate_withholding_safe_harbor(
    current_year_projected_tax: float,
    prior_year_total_tax: float,
    current_ytd_withheld: float,
    remaining_paychecks: int = 6,
    is_high_earner: bool = True,
    prior_year_agi: Optional[float] = None,
    filing_status: str = "MFJ",
) -> Dict[str, float]:
    """
    Computes IRS Safe Harbor targets (Form 2210) to avoid penalties:
    Safe Harbor = min(90% of current year tax, 110% of prior year tax if prior-year AGI > $150k, else 100%).
    When `prior_year_agi` is given it decides the multiplier; otherwise `is_high_earner` does.
    Determines exact extra per-paycheck withholding for Form W-4 Step 4(c).
    """
    if prior_year_agi is not None:
        multiplier = safe_harbor_prior_year_multiplier(prior_year_agi, filing_status)
    else:
        multiplier = SAFE_HARBOR_HIGH_AGI_MULTIPLIER if is_high_earner else 1.00
    safe_harbor_prior = (prior_year_total_tax * multiplier) if prior_year_total_tax > 0 else None
    safe_harbor_current = (current_year_projected_tax * 0.90) if current_year_projected_tax > 0 else None

    if safe_harbor_prior is not None and safe_harbor_current is not None:
        target_withholding = min(safe_harbor_prior, safe_harbor_current)
    elif safe_harbor_prior is not None:
        target_withholding = safe_harbor_prior
    elif safe_harbor_current is not None:
        target_withholding = safe_harbor_current
    else:
        target_withholding = 0.0

    shortfall = max(0.0, target_withholding - current_ytd_withheld)
    extra_per_paycheck = shortfall / remaining_paychecks if remaining_paychecks > 0 else shortfall

    return {
        "safe_harbor_target": target_withholding,
        "current_ytd_withheld": current_ytd_withheld,
        "projected_year_end_tax": current_year_projected_tax,
        "shortfall_to_safe_harbor": shortfall,
        "recommended_extra_per_paycheck": extra_per_paycheck,
        "remaining_paychecks": remaining_paychecks,
        "prior_year_multiplier": multiplier,
    }


__all__ = [
    "FED_BRACKETS_MFJ_2026", "FED_BRACKETS_MFS_2026", "STANDARD_DEDUCTION_MFS_2026", "get_total_deduction",
    "FED_BRACKETS_HOH_2026", "FED_BRACKETS_SINGLE_2026",
    "FED_LTCG_BRACKETS_MFJ_2026", "STANDARD_DEDUCTION_MFJ_2026", "STANDARD_DEDUCTION_HOH_2026",
    "STANDARD_DEDUCTION_SINGLE_2026", "get_standard_deduction", "get_federal_brackets",
    "FICA_SS_WAGE_BASE_2026", "FICA_SS_RATE", "MEDICARE_BASE_RATE", "ADDITIONAL_MEDICARE_RATE",
    "ADDITIONAL_MEDICARE_THRESHOLD_MFJ", "NIIT_RATE", "NIIT_THRESHOLD_MFJ", "WA_CAP_GAINS_RATE",
    "WA_CAP_GAINS_EXEMPTION_2025", "WA_CAP_GAINS_SURCHARGE_RATE", "WA_CAP_GAINS_SURCHARGE_THRESHOLD",
    "calculate_wa_capital_gains_tax", "WA_MILLIONAIRE_TAX_RATE", "WA_MILLIONAIRE_TAX_THRESHOLD",
    "STATE_TAX_PROFILES", "TaxProfile", "calculate_federal_ordinary_tax", "calculate_medicare_tax",
    "calculate_household_take_home_pay", "calculate_nso_exercise_tax", "calculate_stock_sale_tax",
    "calculate_withholding_safe_harbor", "safe_harbor_prior_year_multiplier",
    "calculate_state_tax_for_state", "compare_state_tax_arbitrage",
]

