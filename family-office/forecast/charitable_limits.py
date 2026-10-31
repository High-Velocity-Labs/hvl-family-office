"""
forecast/charitable_limits.py: AGI caps and carryforwards for gifts to public charities and donor-advised funds.
Pure math (IRC 170(b)(1)): cash is deductible up to 60% of AGI and long-term appreciated property up to 30%, with
the two together capped at 60%. Excess carries forward 5 years, oldest first, after the current year's gifts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from forecast.benefit_constants import (
    CHARITABLE_CARRYFORWARD_YEARS,
    CHARITABLE_CASH_AGI_LIMIT,
    CHARITABLE_PROPERTY_AGI_LIMIT,
)
from forecast.investment_income import DEFAULT_TAXABLE_YIELD_RATE

CASH = "cash"
PROPERTY = "property"
# (year given, kind, remaining amount)
Carryforward = Tuple[int, str, float]


@dataclass
class CharitableGivingState:
    """Gifts over the AGI caps waiting to be deducted, and the marginal rate the last DAF event set for them."""
    carryforwards: List[Carryforward] = field(default_factory=list)
    deduction_rate: float = 0.0


def agi_proxy(
    earned_income: float, taxable_balance: float, prior_year_taxable_withdrawals: float,
    current_year_taxable_income: float = 0.0, taxable_yield_rate: float = DEFAULT_TAXABLE_YIELD_RATE,
) -> float:
    """
    AGI estimate for the cap: wages, yield on the taxable balance, this year's other known taxable income (pension),
    and last year's taxable withdrawals. This year's own withdrawals depend on the gifts being capped (the draw
    covers them), so they cannot enter without a cycle; last year's draw stands in for them.
    """
    return (
        max(0.0, earned_income) + max(0.0, taxable_balance) * taxable_yield_rate
        + max(0.0, current_year_taxable_income) + max(0.0, prior_year_taxable_withdrawals)
    )


def _use(
    kind: str, current: float, year: int, carry: List[Carryforward], cap: float,
) -> Tuple[float, List[Carryforward]]:
    """Deducts `kind` gifts up to `cap`: current-year gift first, then unexpired carryforwards oldest first."""
    room = max(0.0, cap)
    used_now = min(current, room)
    room -= used_now
    deducted = used_now
    remaining: List[Carryforward] = []
    for given, k, amt in sorted(carry):
        if k != kind:
            remaining.append((given, k, amt))
            continue
        take = min(amt, room)
        room -= take
        deducted += take
        if amt - take > 0:
            remaining.append((given, k, amt - take))
    if current - used_now > 0:
        remaining.append((year, kind, current - used_now))
    return deducted, remaining


def apply_agi_limits(
    agi: float, cash_gift: float, property_gift: float, year: int, carryforwards: List[Carryforward],
) -> Tuple[float, List[Carryforward]]:
    """Returns (deductible amount this year, carryforwards to the next year). Gifts older than 5 years expire."""
    agi = max(0.0, agi)
    live = [c for c in carryforwards if year - c[0] <= CHARITABLE_CARRYFORWARD_YEARS]
    cash_deducted, after_cash = _use(CASH, max(0.0, cash_gift), year, live, CHARITABLE_CASH_AGI_LIMIT * agi)
    prop_cap = min(CHARITABLE_PROPERTY_AGI_LIMIT * agi, CHARITABLE_CASH_AGI_LIMIT * agi - cash_deducted)
    prop_deducted, after_prop = _use(PROPERTY, max(0.0, property_gift), year, after_cash, prop_cap)
    return cash_deducted + prop_deducted, after_prop
