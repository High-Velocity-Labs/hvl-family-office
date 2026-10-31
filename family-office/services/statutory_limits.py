"""
services/statutory_limits.py: Statutory dollar limits that belong to a specific tax year.

One table per limit, keyed by tax year, so a number is never copied into a route, template or
script. A year without a published figure uses the latest published figure at or before it (a
limit only moves when the IRS publishes a new one); a year earlier than the table uses the
earliest entry.

Adding a new year is a one-line edit to the table below.
"""

from __future__ import annotations
from typing import Dict, Optional

# IRC § 2503(b) annual gift tax exclusion per donor per recipient, by tax year (IRS Rev. Proc.).
ANNUAL_GIFT_EXCLUSION_BY_TAX_YEAR: Dict[int, float] = {
    2024: 18_000.0,
    2025: 19_000.0,
    2026: 19_000.0,
}

# IRC § 529(c)(2)(B): a 529 contribution may be treated as made ratably over five years.
SECTION_529_SUPERFUND_YEARS = 5

# IRC § 529(e)(3)(A): yearly 529 distributions for K-12 tuition per beneficiary, by tax year (TCJA 2018, OBBBA 2026).
K12_529_LIMIT_BY_TAX_YEAR: Dict[int, float] = {
    2018: 10_000.0,
    2026: 20_000.0,
}

# IRC § 415(c) annual additions limit (defined-contribution plans, all sources), by tax year (IRS Notice).
SECTION_415C_LIMIT_BY_TAX_YEAR: Dict[int, float] = {
    2025: 70_000.0,
    2026: 72_000.0,
}


def _latest_published(table: Dict[int, float], tax_year: int) -> float:
    published = [y for y in table if y <= int(tax_year)]
    return table[max(published)] if published else table[min(table)]


def annual_gift_exclusion(tax_year: int) -> float:
    """Per-donor annual gift exclusion for `tax_year` (latest published figure if none for that year)."""
    return _latest_published(ANNUAL_GIFT_EXCLUSION_BY_TAX_YEAR, tax_year)


def annual_gift_exclusion_couple(tax_year: int) -> float:
    """Gift-splitting couple's exclusion per recipient for `tax_year`."""
    return 2.0 * annual_gift_exclusion(tax_year)


def k12_529_limit(tax_year: int) -> float:
    """Per-beneficiary yearly limit on 529 distributions for K-12 tuition in `tax_year`."""
    return _latest_published(K12_529_LIMIT_BY_TAX_YEAR, tax_year)


def section_415c_limit(tax_year: int) -> float:
    """Annual additions limit for defined-contribution plans in `tax_year`."""
    return _latest_published(SECTION_415C_LIMIT_BY_TAX_YEAR, tax_year)


def section_529_superfund_limit(tax_year: int) -> float:
    """Per-donor, per-beneficiary 5-year accelerated 529 contribution limit for `tax_year`."""
    return SECTION_529_SUPERFUND_YEARS * annual_gift_exclusion(tax_year)


# ACA premium tax credit for 2026 coverage (Rev. Proc. 2025-25; the enhanced credits ended 2025-12-31).
# The poverty line for 2026 coverage is the 2025 HHS guideline for a household of two.
ACA_FPL_HOUSEHOLD_OF_TWO = 21_150.0
# (band floor, band ceiling) as a multiple of the poverty line -> applicable percentage of MAGI, rising linearly
# across the band. Above 400% of the poverty line there is no credit.
ACA_APPLICABLE_PERCENTAGES = (
    (0.00, 1.33, 0.0210, 0.0210),
    (1.33, 1.50, 0.0314, 0.0419),
    (1.50, 2.00, 0.0419, 0.0660),
    (2.00, 2.50, 0.0660, 0.0844),
    (2.50, 3.00, 0.0844, 0.0996),
    (3.00, 4.00, 0.0996, 0.0996),
)


def aca_applicable_percentage(fpl_ratio: float) -> Optional[float]:
    """Share of MAGI a household pays toward the benchmark plan, or None above 400% of the poverty line (no credit)."""
    for floor, ceiling, pct_floor, pct_ceiling in ACA_APPLICABLE_PERCENTAGES:
        if fpl_ratio <= ceiling:
            span = max(0.0, min(1.0, (fpl_ratio - floor) / (ceiling - floor)))
            return pct_floor + (pct_ceiling - pct_floor) * span
    return None


# IRC § 63(f) additional standard deduction per taxpayer or spouse who is 65+ or blind, by tax year
# (IRS Rev. Proc. 2024-40 for 2025, Rev. Proc. 2025-32 for 2026). Unmarried covers single and head of household;
# married covers MFJ, MFS and surviving spouse.
ADDITIONAL_STD_DEDUCTION_65_UNMARRIED_BY_TAX_YEAR: Dict[int, float] = {2025: 2_000.0, 2026: 2_050.0}
ADDITIONAL_STD_DEDUCTION_65_MARRIED_BY_TAX_YEAR: Dict[int, float] = {2025: 1_600.0, 2026: 1_650.0}

# IRC § 151(d)(5)(B) senior deduction (OBBBA § 70103), per person aged 65+, tax years 2025 through 2028. It phases
# out by 6% of MAGI over the threshold and is not allowed to married-filing-separately filers.
SENIOR_DEDUCTION_AMOUNT = 6_000.0
SENIOR_DEDUCTION_FIRST_YEAR = 2025
SENIOR_DEDUCTION_LAST_YEAR = 2028
SENIOR_DEDUCTION_PHASEOUT_RATE = 0.06
SENIOR_DEDUCTION_PHASEOUT_START_JOINT = 150_000.0
SENIOR_DEDUCTION_PHASEOUT_START_OTHER = 75_000.0

# IRC § 1(h) long-term capital gains rate bands, tax year 2026 (Rev. Proc. 2025-32): taxable income up to the first
# figure is taxed at 0%, up to the second at 15%, above it at 20%. MFS is half of MFJ by statute.
# The MFS pair ($49,450 / $306,850) is verified against Rev. Proc. 2025-32 § 3.03.
LTCG_BAND_TOPS_2026: Dict[str, tuple] = {
    "MFJ": (98_900.0, 613_700.0),
    "SINGLE": (49_450.0, 545_500.0),
    "HOH": (66_200.0, 579_600.0),
    "MFS": (49_450.0, 306_850.0),
}

# IRC § 1411(b) net investment income tax: 3.8% on the lesser of net investment income or MAGI over the threshold
# (statutory, not indexed).
NIIT_MAGI_THRESHOLDS: Dict[str, float] = {"MFJ": 250_000.0, "SINGLE": 200_000.0, "HOH": 200_000.0, "MFS": 125_000.0}


def additional_standard_deduction_65(tax_year: int, married: bool, qualifying_people: int) -> float:
    """Extra standard deduction for `qualifying_people` aged 65+ (latest published figure if none for the year)."""
    married_table = ADDITIONAL_STD_DEDUCTION_65_MARRIED_BY_TAX_YEAR
    table = married_table if married else ADDITIONAL_STD_DEDUCTION_65_UNMARRIED_BY_TAX_YEAR
    return max(0, int(qualifying_people)) * _latest_published(table, tax_year)


def senior_deduction(tax_year: int, filing_status: str, qualifying_people: int, magi: float) -> float:
    """OBBBA $6,000 deduction per person aged 65+, reduced 6% of MAGI over $75k ($150k joint); 0 outside 2025-2028."""
    status = (filing_status or "MFJ").strip().upper()
    if status == "MFS" or not SENIOR_DEDUCTION_FIRST_YEAR <= int(tax_year) <= SENIOR_DEDUCTION_LAST_YEAR:
        return 0.0
    start = SENIOR_DEDUCTION_PHASEOUT_START_JOINT if status == "MFJ" else SENIOR_DEDUCTION_PHASEOUT_START_OTHER
    full = max(0, int(qualifying_people)) * SENIOR_DEDUCTION_AMOUNT
    return max(0.0, full - SENIOR_DEDUCTION_PHASEOUT_RATE * max(0.0, float(magi) - start))


# IRC § 3101(b)(2) / § 3102(f) Additional Medicare Tax (0.9%) wage thresholds. Statutory, not indexed.
ADDITIONAL_MEDICARE_THRESHOLDS: Dict[str, float] = {
    "MFJ": 250_000.0, "SINGLE": 200_000.0, "HOH": 200_000.0, "MFS": 125_000.0,
}

# IRC § 55 alternative minimum tax, tax year 2026. Source: IRS Rev. Proc. 2025-32 § 3.10 (exemption amounts, the
# 28% excess-taxable-income band, and the § 55(d)(2) phase-out thresholds); OBBBA § 70107 made the TCJA exemptions
# permanent and set the phase-out rate to 50%. Unmarried covers single and head of household.
AMT_EXEMPTION_2026: Dict[str, float] = {"MFJ": 140_200.0, "SINGLE": 90_100.0, "HOH": 90_100.0, "MFS": 70_100.0}
AMT_PHASEOUT_START_2026: Dict[str, float] = {
    "MFJ": 1_000_000.0, "SINGLE": 500_000.0, "HOH": 500_000.0, "MFS": 500_000.0,
}
AMT_PHASEOUT_RATE = 0.50
AMT_UPPER_RATE_THRESHOLD_2026: Dict[str, float] = {
    "MFJ": 244_500.0, "SINGLE": 244_500.0, "HOH": 244_500.0, "MFS": 122_250.0,
}
