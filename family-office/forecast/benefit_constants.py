"""
forecast/benefit_constants.py: Statutory figures the forecast uses for Social Security and ACA poverty lines.
One place for the constants; the benefit math lives in social_security.py and scenarios.py.
"""

from __future__ import annotations

from services.tax_engine import FICA_SS_WAGE_BASE_2026

# SSA PIA formula for the plan base year (ssa.gov/oact/COLA/piaformula.html):
# 90% / 32% / 15% of AIME across these monthly bend points.
SS_WAGE_BASE_2026 = FICA_SS_WAGE_BASE_2026
SS_BEND_POINTS_2026 = (1_286.0, 7_749.0)
SS_PIA_RATES = (0.90, 0.32, 0.15)
SS_COMPUTATION_YEARS = 35
SS_CAREER_START_AGE = 22
SS_SPOUSAL_SHARE_OF_PIA = 0.50

# HHS poverty guideline behind the base-year ACA credit (the two-person figure matches statutory_limits),
# 48 contiguous states: first person plus each additional. Source: the HHS poverty guidelines for the base year
# (Federal Register, January; https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines): $15,650 + $5,500 per extra person.
ACA_FPL_FIRST_PERSON = 15_650.0
ACA_FPL_PER_ADDITIONAL_PERSON = 5_500.0

# IRC 170(b)(1): public charity / DAF gifts as a share of AGI, and the carryforward window.
CHARITABLE_CASH_AGI_LIMIT = 0.60
CHARITABLE_PROPERTY_AGI_LIMIT = 0.30
CHARITABLE_CARRYFORWARD_YEARS = 5


def aca_poverty_line(household_size: int) -> float:
    """The poverty line (today's dollars) for a household of `household_size` people."""
    if household_size < 1:
        raise ValueError("household_size must be at least 1")
    return ACA_FPL_FIRST_PERSON + ACA_FPL_PER_ADDITIONAL_PERSON * (household_size - 1)
