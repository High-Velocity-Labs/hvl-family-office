"""
forecast/pension.py: Defined-benefit pension income for the waterfall.
Pure math. An entered pension is the annual benefit in today's dollars: a pension already in payment pays that amount
now; one that starts later pays it in the start year's dollars (grown by inflation to that year). After the start the
benefit grows by its own COLA, which can be below inflation. Survivor_pct is the share of the benefit the other adult
keeps after the annuitant dies; the waterfall carries no deaths (survival is a probability), so it pays the full
benefit and `survivor_pct` only applies where a caller passes `survivor=True`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from forecast import tax_indexing
from services import tax_engine
from services.tax_calculations import state_ordinary_income_tax


@dataclass(frozen=True)
class Pension:
    """One adult's pension: first-year annual amount (today's dollars), start age, COLA, survivor share (decimals)."""
    annual_amount: float
    start_age: int
    cola: float = 0.0
    survivor_pct: float = 0.0

    def __post_init__(self) -> None:
        if self.annual_amount < 0:
            raise ValueError("pension amount must not be negative")
        if not 40 <= self.start_age <= 100:
            raise ValueError("pension start age must be between 40 and 100")
        if not 0.0 <= self.cola <= 0.20:
            raise ValueError("pension COLA must be between 0% and 20%")
        if not 0.0 <= self.survivor_pct <= 1.0:
            raise ValueError("pension survivor share must be between 0% and 100%")


def pensions_from_inputs(raw: Dict[str, Dict[str, float]]) -> Dict[str, Pension]:
    """Pension per person from the stored inputs (`db.engine_inputs.get_pension_inputs`)."""
    return {
        person: Pension(
            annual_amount=float(v["annual_amount"]), start_age=int(v["start_age"]),
            cola=float(v.get("cola", 0.0)), survivor_pct=float(v.get("survivor_pct", 0.0)),
        )
        for person, v in raw.items()
    }


def pension_income(
    pension: Pension, age: int, years_from_now: int, inflation_rate: float, survivor: bool = False,
) -> float:
    """Nominal pension paid in the year `years_from_now` (0 = the plan's first year) when the annuitant is `age`."""
    if age < pension.start_age or pension.annual_amount <= 0:
        return 0.0
    years_until_start = max(0, pension.start_age - (age - years_from_now))
    years_paying = years_from_now - years_until_start
    amount = pension.annual_amount * (1.0 + inflation_rate) ** years_until_start * (1.0 + pension.cola) ** years_paying
    return amount * pension.survivor_pct if survivor else amount


def household_pension_income(
    pensions: Dict[str, Pension], age_primary: int, age_spouse: int, has_spouse: bool,
    years_from_now: int, inflation_rate: float,
) -> float:
    """Both adults' nominal pension income for the year (a spouse's pension counts only if the household has one)."""
    total = 0.0
    if "primary" in pensions:
        total += pension_income(pensions["primary"], age_primary, years_from_now, inflation_rate)
    if has_spouse and "spouse" in pensions:
        total += pension_income(pensions["spouse"], age_spouse, years_from_now, inflation_rate)
    return total


def pension_tax(
    pension_gross: float, other_ordinary_income: float, tax_year: int, inflation_rate: float,
    user_state: str, filing_status: str, seniors_65_plus: int,
) -> float:
    """
    Federal and state income tax caused by `pension_gross` stacked on the year's other ordinary income (nominal
    dollars; thresholds are indexed like the rest of the plan). No FICA applies to a pension. Social Security and
    pre-tax withdrawals are not taxed in the waterfall, so the pension gets the whole standard deduction.
    """
    if pension_gross <= 0:
        return 0.0
    idx = tax_indexing.threshold_index(tax_year, inflation_rate)
    base, added = other_ordinary_income / idx, pension_gross / idx
    status = (filing_status or "MFJ").strip().upper()
    brackets = tax_engine.get_federal_brackets(status)
    deduction = lambda magi: tax_engine.get_total_deduction(status, seniors_65_plus, magi, tax_year)  # noqa: E731
    federal = tax_engine.calculate_federal_ordinary_tax(
        max(0.0, base + added - deduction(base + added)), brackets,
    ) - tax_engine.calculate_federal_ordinary_tax(max(0.0, base - deduction(base)), brackets)
    state = state_ordinary_income_tax("" if user_state == "WA" else user_state, base, added, tax_year=tax_year)
    return max(0.0, federal + state) * idx

