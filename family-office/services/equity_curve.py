"""
Equity valuation sensitivity curve: the equity engine run at a ladder of share prices around a base price.
All tax math comes from `simulate_valuation_scenario`; the browser only plots the returned series.
"""

from __future__ import annotations

from typing import Any

from services.equity_engine import simulate_valuation_scenario

SAMPLE_MULTIPLES = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)


def build_valuation_curve(
    family_id: int, base_price: float, include_wa_tax: bool, company_id: int | None = None,
) -> dict[str, Any]:
    """Returns parallel series (one point per sampled price) for gross value, net value, tax drag and strike cost."""
    if base_price <= 0:
        raise ValueError("A positive base share price is required to build a valuation curve.")
    prices = [round(base_price * m) for m in SAMPLE_MULTIPLES]
    series: dict[str, list[float]] = {"gross": [], "net": [], "tax": [], "strike": [], "unvested_net": []}
    for price in prices:
        sim = simulate_valuation_scenario(
            share_price=float(price), include_wa_millionaire_tax=include_wa_tax,
            family_id=family_id, company_id=company_id,
        )
        series["gross"].append(round(sim["company_nominal_gross_equity_value"]))
        series["net"].append(round(sim["company_true_net_post_tax_value"]))
        series["tax"].append(round(sim["company_tax_drag"]))
        series["strike"].append(round(sim["company_strike_cost_needed"]))
        series["unvested_net"].append(round(sim["unvested_net_value"]))
    return {"prices": prices, **series}
