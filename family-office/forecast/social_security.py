"""
forecast/social_security.py: Primary insurance amount (PIA) from a person's own earnings.
Pure math: an AIME approximation from capped salary and the base-year bend points. Claim-age reductions live in
waterfall_withdrawals.py next to the cash-flow code that applies them.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from forecast.benefit_constants import (
    SS_BEND_POINTS_2026,
    SS_CAREER_START_AGE,
    SS_COMPUTATION_YEARS,
    SS_PIA_RATES,
    SS_SPOUSAL_SHARE_OF_PIA,
    SS_WAGE_BASE_2026,
)


def pia_monthly_from_aime(aime_monthly: float) -> float:
    """Applies the 90/32/15 bend-point formula to a monthly AIME."""
    low, high = SS_BEND_POINTS_2026
    r1, r2, r3 = SS_PIA_RATES
    aime = max(0.0, aime_monthly)
    return r1 * min(aime, low) + r2 * max(0.0, min(aime, high) - low) + r3 * max(0.0, aime - high)


def career_years(retirement_age: int) -> int:
    """Years of covered earnings, counted from age 22 to retirement, capped at the 35 SSA averages over."""
    return max(0, min(SS_COMPUTATION_YEARS, int(retirement_age) - SS_CAREER_START_AGE))


def annual_pia_from_earnings(annual_earnings: float, retirement_age: int) -> float:
    """
    Annual PIA (today's dollars, benefit at full retirement age) for a steady earner.
    Earnings are today's salary and bonus capped at the wage base, held flat in real terms for the career years;
    the remaining years of the 35-year averaging window count as zero.
    """
    capped = min(max(0.0, annual_earnings), SS_WAGE_BASE_2026)
    aime = capped / 12.0 * career_years(retirement_age) / SS_COMPUTATION_YEARS
    return pia_monthly_from_aime(aime) * 12.0


def resolve_annual_pia(annual_earnings: float, retirement_age: int, override: Optional[float]) -> float:
    """A user-entered PIA (from the person's SSA statement) wins over the earnings approximation."""
    if override is not None:
        return max(0.0, float(override))
    return annual_pia_from_earnings(annual_earnings, retirement_age)


def household_pias(ctx: Any, primary_retirement_age: int, spouse_retirement_age: int) -> Tuple[float, float]:
    """Each adult's annual PIA: the entered benefit, else the estimate from current earnings (0 with neither)."""
    return (
        resolve_annual_pia(ctx.primary_earned_income, primary_retirement_age, ctx.ss_pia_overrides.get("primary")),
        resolve_annual_pia(ctx.spouse_earned_income, spouse_retirement_age, ctx.ss_pia_overrides.get("spouse")),
    )


def adults_without_social_security(ctx: Any, primary_retirement_age: int, spouse_retirement_age: int) -> List[str]:
    """
    "primary"/"spouse" for each adult the forecast pays no Social Security: no entered benefit and no earnings to
    estimate from. A spouse with no record of their own still draws the spousal benefit on the primary's PIA.
    """
    primary_pia, spouse_pia = household_pias(ctx, primary_retirement_age, spouse_retirement_age)
    gaps: List[str] = []
    if ctx.ss_pia_overrides.get("primary") is None and primary_pia <= 0:
        gaps.append("primary")
    if ctx.has_spouse and ctx.ss_pia_overrides.get("spouse") is None and spouse_pia <= 0:
        if SS_SPOUSAL_SHARE_OF_PIA * primary_pia <= 0:
            gaps.append("spouse")
    return gaps
