"""
Incentive stock option (ISO) taxes: the regular-tax path for each disposition and the AMT at exercise.

Regular tax: nothing is owed when an ISO is exercised. A qualifying disposition (held 2 years from grant and
1 year from exercise) is all long-term capital gain; a disqualifying one makes the lesser of the spread at
exercise and the actual gain ordinary income, and the rest capital gain.

AMT: the spread at exercise is an AMT preference when the shares are still held at year end. This is a simple
estimate (AMTI = ordinary income + preference, no other adjustments), not a full Form 6251:
the tentative minimum tax uses the 26%/28% rates, the exemption and its phase-out, and AMT paid becomes a
minimum-tax credit carried forward against later regular tax (the recovery year is not modeled).
"""

from __future__ import annotations

from typing import Dict

from services import statutory_limits, tax_engine

# Tax year 2026 AMT figures live in services/statutory_limits.py (IRS Rev. Proc. 2025-32).
AMT_LOWER_RATE = 0.26
AMT_UPPER_RATE = 0.28

DISPOSITIONS = ("qualifying", "disqualifying", "hold")


def _status(filing_status: str) -> str:
    status = str(filing_status or "MFJ").strip().upper()
    return status if status in statutory_limits.AMT_EXEMPTION_2026 else "MFJ"


def amt_exemption(amti: float, filing_status: str = "MFJ") -> float:
    """The 2026 AMT exemption after its 50% phase-out above the filing-status threshold."""
    status = _status(filing_status)
    reduction = statutory_limits.AMT_PHASEOUT_RATE * max(0.0, amti - statutory_limits.AMT_PHASEOUT_START_2026[status])
    return max(0.0, statutory_limits.AMT_EXEMPTION_2026[status] - reduction)


def tentative_minimum_tax(amti: float, filing_status: str = "MFJ") -> float:
    """26% up to the 2026 threshold and 28% above it, on AMTI less the phased-out exemption."""
    status = _status(filing_status)
    base = max(0.0, amti - amt_exemption(amti, status))
    threshold = statutory_limits.AMT_UPPER_RATE_THRESHOLD_2026[status]
    return min(base, threshold) * AMT_LOWER_RATE + max(0.0, base - threshold) * AMT_UPPER_RATE


def iso_exercise_amt(preference: float, prior_ordinary_income: float, filing_status: str = "MFJ") -> Dict[str, float]:
    """
    AMT owed for exercising and holding ISOs with `preference` of bargain element, stacked on
    `prior_ordinary_income`. AMT is the tentative minimum tax over regular tax on that income; what is paid
    is the minimum-tax credit carried forward (`amt_credit_carryforward`).
    """
    status = _status(filing_status)
    if preference <= 0:
        return {"amt_preference": 0.0, "tentative_minimum_tax": 0.0, "regular_tax": 0.0, "amt": 0.0,
                "amt_credit_carryforward": 0.0}
    std_ded = tax_engine.get_standard_deduction(status)
    regular = tax_engine.calculate_federal_ordinary_tax(
        max(0.0, prior_ordinary_income - std_ded), tax_engine.get_federal_brackets(status),
    )
    tmt = tentative_minimum_tax(prior_ordinary_income + preference, status)
    amt = max(0.0, tmt - regular)
    return {
        "amt_preference": preference, "tentative_minimum_tax": tmt, "regular_tax": regular,
        "amt": amt, "amt_credit_carryforward": amt,
    }


def iso_regular_income(
    options: float, strike: float, exercise_fmv: float, sale_price: float, disposition: str,
) -> Dict[str, float]:
    """
    Splits an ISO disposition into ordinary income and capital gain, in dollars. `hold` (exercised, not sold)
    has no regular tax at all; a qualifying sale is all capital gain; a disqualifying sale is ordinary income on
    the lesser of the spread at exercise and the gain, with any gain above that as capital gain.
    """
    if disposition not in DISPOSITIONS:
        raise ValueError(f"ISO disposition must be one of {DISPOSITIONS}, got {disposition!r}")
    if disposition == "hold":
        return {"ordinary_income": 0.0, "capital_gain": 0.0}
    gain = max(0.0, sale_price - strike) * options
    if disposition == "qualifying":
        return {"ordinary_income": 0.0, "capital_gain": gain}
    ordinary = min(max(0.0, exercise_fmv - strike) * options, gain)
    return {"ordinary_income": ordinary, "capital_gain": gain - ordinary}


def amt_credit_recovery(
    carryforward: float, ordinary_income: float, filing_status: str = "MFJ", tax_year: int = 2026,
) -> Dict[str, float]:
    """
    Minimum-tax credit used in a year with `ordinary_income` and no ISO preference: the lesser of the carryforward
    and the amount regular tax exceeds the tentative minimum tax (zero when AMT still applies). Returns the credit
    used and the carryforward left.
    """
    status = _status(filing_status)
    std_ded = tax_engine.get_standard_deduction(status, 0, tax_year)
    regular = tax_engine.calculate_federal_ordinary_tax(
        max(0.0, ordinary_income - std_ded), tax_engine.get_federal_brackets(status),
    )
    room = max(0.0, regular - tentative_minimum_tax(ordinary_income, status))
    used = min(max(0.0, carryforward), room)
    return {"credit_used": used, "carryforward_left": max(0.0, carryforward) - used, "regular_tax": regular}


def amt_credit_recovery_years(
    carryforward: float, ordinary_income: float, filing_status: str = "MFJ", tax_year: int = 2026,
    max_years: int = 30,
) -> int:
    """Years to recover the whole credit at a steady `ordinary_income`; 0 for no credit, -1 if it is never recovered."""
    left, years = max(0.0, carryforward), 0
    while left > 0.005:
        step = amt_credit_recovery(left, ordinary_income, filing_status, tax_year)
        if step["credit_used"] <= 0 or years >= max_years:
            return -1
        left, years = step["carryforward_left"], years + 1
    return years
