"""
State tax on equity compensation, in one place for the grant model, the simulator and the advisor.

Vest income (RSU) and the option spread (NSO) are wages: they take the household's state income tax, never a
capital-gains rate. Washington has no wage tax until SB 6346 (9.9% over $1M, tax years 2028+, treated as
enacted); its 7% / 9.9% excise applies only to sales of stock. An unset state owes no state tax.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from services import tax_engine
from services.tax_calculations import state_capital_gains_tax, state_ordinary_income_tax

FEDERAL_MEDICARE_ORDINARY_RATE = 0.3935  # 37% federal + 2.35% Medicare, the top bracket on wages


def resolve_state(state: Optional[str], include_wa_tax: bool) -> str:
    """
    The state whose rules apply. A given state (even "" for unset) is the household's own. `None` means the
    caller has no household, and then only the explicit Washington what-if toggle stands in for WA.
    """
    if state is None:
        return "WA" if include_wa_tax else ""
    return str(state).strip().upper()


def wa_wage_tax_applies(state: str, include_wa_tax: bool, tax_year: Optional[int] = None) -> bool:
    """Whether the SB 6346 wage tax is on: a WA household with the toggle on, in 2028 or later."""
    return state == "WA" and include_wa_tax and (tax_year is None or tax_year >= 2028)


def compensation_option_tax(
    spread: float, prior_income: float, state: str, include_wa_tax: bool,
    tax_year: Optional[int] = None, filing_status: str = "MFJ",
) -> Dict[str, Any]:
    """Federal, Medicare and state tax on an NSO spread or RSU vest, as the engine's dict plus `state_tax`."""
    tax = dict(tax_engine.calculate_nso_exercise_tax(
        spread=spread, prior_ordinary_income=prior_income,
        include_wa_millionaire_tax=wa_wage_tax_applies(state, include_wa_tax, tax_year),
        filing_status=filing_status, tax_year=tax_year,
    ))
    other_state = state_ordinary_income_tax("" if state == "WA" else state, prior_income, spread, tax_year)
    tax["state_tax"] = float(tax.get("wa_state_tax", 0.0)) + other_state
    tax["total_tax"] = float(tax.get("total_tax", 0.0)) + other_state
    tax["effective_rate"] = tax["total_tax"] / spread if spread > 0 else 0.0
    tax["state_code"] = state
    return tax


def stock_sale_tax_for_state(
    sale_proceeds: float, cost_basis: float, other_income: float, state: str, tax_year: Optional[int] = None,
    filing_status: str = "MFJ",
) -> Dict[str, Any]:
    """Long-term sale tax with the household's own state capital-gains tax (the WA excise only for WA)."""
    sale = dict(tax_engine.calculate_stock_sale_tax(
        sale_proceeds=sale_proceeds, cost_basis=cost_basis, holding_period_days=366, other_income=other_income,
        filing_status=filing_status, tax_year=tax_year, state=state,
    ))
    gain = float(sale.get("gain", 0.0))
    # The engine already charged the WA excise for a WA household; every other state's tax is added here.
    other_state_tax = state_capital_gains_tax("" if state == "WA" else state, gain, tax_year, base_income=other_income)
    state_tax = float(sale.get("wa_capital_gains_tax", 0.0)) + other_state_tax
    sale["total_tax"] = float(sale.get("total_tax", 0.0)) + other_state_tax
    sale["state_capital_gains_tax"] = state_tax
    sale["effective_rate"] = sale["total_tax"] / gain if gain > 0 else 0.0
    return sale


def unvested_net_value(
    spread: float, prior_income: float, state: str, include_wa_tax: bool, tax_year: Optional[int] = None,
) -> float:
    """After-tax value of an unvested spread, taxed as wages at the top federal rate plus the household's state."""
    if spread <= 0:
        return 0.0
    state_tax = state_ordinary_income_tax(
        state, prior_income, spread, tax_year, wa_wage_tax=wa_wage_tax_applies(state, include_wa_tax, tax_year),
    )
    return max(0.0, spread - spread * FEDERAL_MEDICARE_ORDINARY_RATE - state_tax)
