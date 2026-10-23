"""Tax Engine: Federal and Washington State Tax Modeling."""

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional

from tax_engine_helpers import (
    STATE_TAX_PROFILES,
    calculate_state_tax_for_state,
    compare_state_tax_arbitrage,
)


# 2026 Projected Federal Tax Brackets for Married Filing Jointly (MFJ)
FED_BRACKETS_MFJ_2026: List[Tuple[float, float, float]] = [
    (0.0, 24800.0, 0.10),
    (24800.0, 100800.0, 0.12),
    (100800.0, 211400.0, 0.22),
    (211400.0, 403550.0, 0.24),
    (403550.0, 512450.0, 0.32),
    (512450.0, 768700.0, 0.35),
    (768700.0, float("inf"), 0.37),
]

# 2026 Projected Federal Tax Brackets for Head of Household (HOH) - Single Parents
FED_BRACKETS_HOH_2026: List[Tuple[float, float, float]] = [
    (0.0, 17700.0, 0.10),
    (17700.0, 67450.0, 0.12),
    (67450.0, 105700.0, 0.22),
    (105700.0, 201750.0, 0.24),
    (201750.0, 256200.0, 0.32),
    (256200.0, 640600.0, 0.35),
    (640600.0, float("inf"), 0.37),
]

# 2026 Projected Federal Tax Brackets for Single Filers
FED_BRACKETS_SINGLE_2026: List[Tuple[float, float, float]] = [
    (0.0, 12400.0, 0.10),
    (12400.0, 50400.0, 0.12),
    (50400.0, 105700.0, 0.22),
    (105700.0, 201775.0, 0.24),
    (201775.0, 256225.0, 0.32),
    (256225.0, 640600.0, 0.35),
    (640600.0, float("inf"), 0.37),
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


def get_standard_deduction(filing_status: str = "MFJ") -> float:
    """Returns IRS standard deduction for MFJ, HOH (single parent), or Single."""
    fs = (filing_status or "MFJ").strip().upper()
    if fs == "HOH":
        return STANDARD_DEDUCTION_HOH_2026
    elif fs == "SINGLE":
        return STANDARD_DEDUCTION_SINGLE_2026
    return STANDARD_DEDUCTION_MFJ_2026


def get_federal_brackets(filing_status: str = "MFJ") -> List[Tuple[float, float, float]]:
    """Returns progressive federal brackets for MFJ, HOH (single parent), or Single."""
    fs = (filing_status or "MFJ").strip().upper()
    if fs == "HOH":
        return FED_BRACKETS_HOH_2026
    elif fs == "SINGLE":
        return FED_BRACKETS_SINGLE_2026
    return FED_BRACKETS_MFJ_2026

# FICA / Medicare Parameters
FICA_SS_WAGE_BASE_2026 = 184500.0   # Social Security wage cap
FICA_SS_RATE = 0.062                 # 6.2%
MEDICARE_BASE_RATE = 0.0145          # 1.45%
ADDITIONAL_MEDICARE_RATE = 0.009     # 0.9%
ADDITIONAL_MEDICARE_THRESHOLD_MFJ = 250000.0

# Net Investment Income Tax (NIIT)
NIIT_RATE = 0.038                    # 3.8%
NIIT_THRESHOLD_MFJ = 250000.0

# Washington State Parameters
WA_CAP_GAINS_RATE = 0.07             # 7% excise tax on long-term capital gains
WA_CAP_GAINS_EXEMPTION_2026 = 278000.0 # Indexed standard deduction (~$278k)
WA_CAP_GAINS_SURCHARGE_RATE = 0.029  # 2.9% surcharge on taxable gains > $1M (top marginal rate 9.9%)
WA_CAP_GAINS_SURCHARGE_THRESHOLD = 1000000.0  # Threshold above exemption
WA_MILLIONAIRE_TAX_RATE = 0.099      # 9.9% tax on Washington taxable income > $1M (SB 6346)
WA_MILLIONAIRE_TAX_THRESHOLD = 1000000.0


def calculate_wa_capital_gains_tax(gain: float) -> float:
    """
    Calculates WA State Capital Gains excise tax (RCW 82.87):
    - Exempt up to $278,000 standard deduction
    - 7.0% on taxable long-term capital gains up to $1,000,000 above exemption
    - 9.9% (7.0% base + 2.9% surcharge) on taxable long-term capital gains exceeding $1,000,000
    """
    if gain <= WA_CAP_GAINS_EXEMPTION_2026:
        return 0.0
    taxable_gain = gain - WA_CAP_GAINS_EXEMPTION_2026
    if taxable_gain <= WA_CAP_GAINS_SURCHARGE_THRESHOLD:
        return taxable_gain * WA_CAP_GAINS_RATE
    base_tax = WA_CAP_GAINS_SURCHARGE_THRESHOLD * WA_CAP_GAINS_RATE
    surcharged_tax = (taxable_gain - WA_CAP_GAINS_SURCHARGE_THRESHOLD) * (WA_CAP_GAINS_RATE + WA_CAP_GAINS_SURCHARGE_RATE)
    return base_tax + surcharged_tax


@dataclass
class TaxProfile:
    filing_status: str = "MFJ"
    state: str = "WA"
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


def calculate_medicare_tax(wages_or_spread: float, prior_wages: float = 0.0, is_mfj: bool = True) -> Dict[str, float]:
    """Calculates Base Medicare (1.45%) and Additional Medicare (0.9%) on supplemental or total wages."""
    base_tax = wages_or_spread * MEDICARE_BASE_RATE
    threshold = ADDITIONAL_MEDICARE_THRESHOLD_MFJ if is_mfj else 200000.0

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
    user_state: str = "WA",
    filing_status: str = "MFJ",
    has_spouse: bool = True,
    spouse_gross_salary: float = 0.0,
    tax_year: Optional[int] = None,
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
    std_ded = get_standard_deduction(filing_status)

    # 1. Federal Ordinary Income Tax
    taxable_ordinary = max(0.0, total_gross - std_ded)
    fed_tax = calculate_federal_ordinary_tax(taxable_ordinary, brackets)

    # 2. FICA Social Security Tax (6.2% per worker up to wage base)
    fica_primary = min(gross_salary, FICA_SS_WAGE_BASE_2026) * FICA_SS_RATE if gross_salary > 0 else 0.0
    fica_spouse = min(spouse_gross_salary, FICA_SS_WAGE_BASE_2026) * FICA_SS_RATE if (has_spouse and spouse_gross_salary > 0) else 0.0
    fica_total = fica_primary + fica_spouse

    # 3. Medicare Tax (1.45% base + 0.9% additional above MFJ $250k or Single $200k)
    medicare_info = calculate_medicare_tax(total_gross, prior_wages=0.0, is_mfj=is_mfj)
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
) -> Dict[str, float]:
    """
    Calculates exact ordinary income tax, Medicare, and WA state tax on an NSO exercise spread.
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
    std_ded = STANDARD_DEDUCTION_MFJ_2026 if is_mfj else STANDARD_DEDUCTION_SINGLE_2026
    brackets = FED_BRACKETS_MFJ_2026 if is_mfj else FED_BRACKETS_SINGLE_2026
    tax_without = calculate_federal_ordinary_tax(max(0.0, prior_ordinary_income - std_ded), brackets)
    tax_with = calculate_federal_ordinary_tax(max(0.0, prior_ordinary_income + spread - std_ded), brackets)
    fed_tax = tax_with - tax_without

    # Medicare
    med_info = calculate_medicare_tax(spread, prior_wages=prior_ordinary_income, is_mfj=is_mfj)
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
    is_mfj: bool = True
) -> Dict[str, float]:
    """
    Calculates Capital Gains Tax on already-exercised shares when sold.
    Includes Federal LTCG (up to 20%), NIIT (3.8%), and WA Capital Gains Tax (7% above exemption, 9.9% above $1M).
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

    is_long_term = holding_period_days > 365

    if is_long_term:
        # Federal LTCG: 20% on high income
        fed_ltcg_rate = 0.20
        fed_tax = gain * fed_ltcg_rate

        # NIIT: 3.8% on net investment income if MAGI > $250k
        niit_tax = gain * NIIT_RATE

        # Washington Capital Gains Tax: 7% on gains up to $1M above exemption, 9.9% above $1M
        wa_cg_tax = calculate_wa_capital_gains_tax(gain)

        total_tax = fed_tax + niit_tax + wa_cg_tax
    else:
        # Short-term is ordinary income
        fed_tax = gain * 0.37
        niit_tax = gain * NIIT_RATE
        wa_cg_tax = 0.0
        total_tax = fed_tax + niit_tax

    return {
        "gain": gain,
        "federal_capital_gains_tax": fed_tax,
        "niit_tax": niit_tax,
        "wa_capital_gains_tax": wa_cg_tax,
        "total_tax": total_tax,
        "effective_rate": total_tax / gain if gain > 0 else 0.0,
    }


def calculate_withholding_safe_harbor(
    current_year_projected_tax: float,
    prior_year_total_tax: float,
    current_ytd_withheld: float,
    remaining_paychecks: int = 6,
    is_high_earner: bool = True
) -> Dict[str, float]:
    """
    Computes IRS Safe Harbor targets (Form 2210) to avoid penalties:
    Safe Harbor = min(90% of current year tax, 110% of prior year tax for AGI > $150k).
    Determines exact extra per-paycheck withholding for Form W-4 Step 4(c).
    """
    multiplier = 1.10 if is_high_earner else 1.00
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
    }


__all__ = [
    "FED_BRACKETS_MFJ_2026", "FED_BRACKETS_HOH_2026", "FED_BRACKETS_SINGLE_2026",
    "FED_LTCG_BRACKETS_MFJ_2026", "STANDARD_DEDUCTION_MFJ_2026", "STANDARD_DEDUCTION_HOH_2026",
    "STANDARD_DEDUCTION_SINGLE_2026", "get_standard_deduction", "get_federal_brackets",
    "FICA_SS_WAGE_BASE_2026", "FICA_SS_RATE", "MEDICARE_BASE_RATE", "ADDITIONAL_MEDICARE_RATE",
    "ADDITIONAL_MEDICARE_THRESHOLD_MFJ", "NIIT_RATE", "NIIT_THRESHOLD_MFJ", "WA_CAP_GAINS_RATE",
    "WA_CAP_GAINS_EXEMPTION_2026", "WA_CAP_GAINS_SURCHARGE_RATE", "WA_CAP_GAINS_SURCHARGE_THRESHOLD",
    "calculate_wa_capital_gains_tax", "WA_MILLIONAIRE_TAX_RATE", "WA_MILLIONAIRE_TAX_THRESHOLD",
    "STATE_TAX_PROFILES", "TaxProfile", "calculate_federal_ordinary_tax", "calculate_medicare_tax",
    "calculate_household_take_home_pay", "calculate_nso_exercise_tax", "calculate_stock_sale_tax",
    "calculate_withholding_safe_harbor", "calculate_state_tax_for_state", "compare_state_tax_arbitrage",
]

