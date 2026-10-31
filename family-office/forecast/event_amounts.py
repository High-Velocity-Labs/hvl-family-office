"""
forecast/event_amounts.py: The one place a life-event amount becomes a nominal dollar amount.

Amounts a user enters on an event are in today's dollars and grow with inflation, unless the
event's `amount_basis` is "fixed" (a signed contract, loan payment or pledge applied exactly as
entered). Education events grow at their own rate. The simulation runs in nominal dollars, so
every event amount read by the waterfall goes through `scale_event_amount` exactly once, in the
year it is applied; a multi-year event is re-indexed each year it applies.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet

AMOUNT_BASIS_TODAYS = "todays_dollars"
AMOUNT_BASIS_FIXED = "fixed"
AMOUNT_BASES = (AMOUNT_BASIS_TODAYS, AMOUNT_BASIS_FIXED)

# Contractual by nature: applied as entered unless the user explicitly marks them today's dollars.
FIXED_BY_DEFAULT_CATEGORIES: FrozenSet[str] = frozenset({
    "refinance", "debt_payoff",
    "pe_capital_call", "capital_call", "j_curve",
    "roth_conversion",
    "marital_settlement",
})

EDUCATION_CATEGORIES: FrozenSet[str] = frozenset({"college", "grad_school", "education"})


@dataclass(frozen=True)
class EventIndexer:
    """Price and tuition indices relative to the projection's first year."""

    start_year: int
    inflation_rate: float
    education_inflation_rate: float

    def price(self, year: int) -> float:
        return (1.0 + self.inflation_rate) ** (year - self.start_year)

    def education(self, year: int) -> float:
        return (1.0 + self.education_inflation_rate) ** (year - self.start_year)


def default_amount_basis(category: str) -> str:
    """The basis an event of this category has when the user has not chosen one."""
    return AMOUNT_BASIS_FIXED if category in FIXED_BY_DEFAULT_CATEGORIES else AMOUNT_BASIS_TODAYS


def resolve_amount_basis(raw: Any, category: str) -> str:
    """Validates a stored `amount_basis`; anything but the two known values is the category default."""
    return raw if raw in AMOUNT_BASES else default_amount_basis(category)


def scale_event_amount(ev: Dict[str, Any], amount: float, year: int, indexer: EventIndexer) -> float:
    """Nominal amount for `amount` (as the user entered it on `ev`) when applied in `year`."""
    category = str(ev.get("category") or "")
    if resolve_amount_basis(ev.get("amount_basis"), category) == AMOUNT_BASIS_FIXED:
        return amount
    index = indexer.education(year) if category in EDUCATION_CATEGORIES else indexer.price(year)
    return amount * index
