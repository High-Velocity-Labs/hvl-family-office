"""
forecast/tax_indexing.py: Projects the statutory tax tables onto future plan years.

services/tax_engine.py encodes one tax year (STATUTORY_BASE_YEAR) of brackets, deductions and
wage bases. The plan indexes those thresholds by its inflation rate for later years. Because the
tax functions are piecewise-linear in income, that equals computing tax on the year's nominal
amounts expressed in base-year dollars and scaling the dollar results back up. Year-gated rules
(e.g. the WA 2028 millionaire tax) still see the real projection year.

Exceptions: the Additional Medicare and NIIT thresholds are fixed in statute, so those are recomputed on
the nominal amounts. Other thresholds the engine treats as fixed dollar amounts (the WA $1M
capital-gains and SB 6346 thresholds) are indexed here like the brackets; that is an
approximation, as is indexing the FICA wage base by prices rather than wages.
"""

from __future__ import annotations
from typing import Any, Dict, Optional

from services import tax_engine
from services.federal_capital_gains import niit_on_gain

STATUTORY_BASE_YEAR = 2026


def threshold_index(tax_year: int, inflation_rate: float) -> float:
    """How much the base-year tax thresholds have grown by `tax_year`."""
    return (1.0 + float(inflation_rate)) ** max(0, int(tax_year) - STATUTORY_BASE_YEAR)


def _scale_money(result: Dict[str, Any], idx: float) -> Dict[str, Any]:
    return {
        k: (v * idx if isinstance(v, (int, float)) and not isinstance(v, bool) and not k.endswith("rate") else v)
        for k, v in result.items()
    }


def _with_unindexed_medicare(result: Dict[str, Any], medicare_key: str, medicare_tax: float, net_key: Optional[str]) -> Dict[str, Any]:
    delta = medicare_tax - float(result.get(medicare_key, 0.0))
    result[medicare_key] = round(medicare_tax, 2)
    result["total_tax"] = round(float(result["total_tax"]) + delta, 2)
    if net_key:
        result[net_key] = round(max(0.0, float(result[net_key]) - delta), 2)
    return result


def household_take_home_pay(
    gross_salary: float, spouse_gross_salary: float, tax_year: int, inflation_rate: float, **kwargs: Any,
) -> Dict[str, Any]:
    idx = threshold_index(tax_year, inflation_rate)
    calc = tax_engine.calculate_household_take_home_pay(
        gross_salary=gross_salary / idx, spouse_gross_salary=spouse_gross_salary / idx, tax_year=tax_year, **kwargs,
    )
    out = _scale_money(calc, idx)
    total_gross = gross_salary + spouse_gross_salary
    if total_gross <= 0:
        return out
    status = str(kwargs.get("filing_status") or "MFJ")
    medicare = tax_engine.calculate_medicare_tax(total_gross, prior_wages=0.0, filing_status=status)["total_medicare"]
    out = _with_unindexed_medicare(out, "medicare_tax", medicare, "net_take_home")
    out["effective_tax_rate"] = round(out["total_tax"] / total_gross, 4)
    return out


def nso_exercise_tax(
    spread: float, prior_ordinary_income: float, tax_year: int, inflation_rate: float, **kwargs: Any,
) -> Dict[str, Any]:
    idx = threshold_index(tax_year, inflation_rate)
    calc = tax_engine.calculate_nso_exercise_tax(
        spread=spread / idx, prior_ordinary_income=prior_ordinary_income / idx, tax_year=tax_year, **kwargs,
    )
    out = _scale_money(calc, idx)
    if spread <= 0:
        return out
    medicare = tax_engine.calculate_medicare_tax(
        spread, prior_wages=prior_ordinary_income,
        filing_status=kwargs.get("filing_status") or ("MFJ" if kwargs.get("is_mfj", True) else "SINGLE"),
    )["total_medicare"]
    out = _with_unindexed_medicare(out, "medicare_tax", medicare, None)
    out["effective_rate"] = out["total_tax"] / spread
    return out


def stock_sale_tax(
    sale_proceeds: float, cost_basis: float, tax_year: int, inflation_rate: float, other_income: float = 0.0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Sale tax in nominal dollars; proceeds, basis and the year's other income are deflated to base-year thresholds."""
    idx = threshold_index(tax_year, inflation_rate)
    calc = tax_engine.calculate_stock_sale_tax(
        sale_proceeds=sale_proceeds / idx, cost_basis=cost_basis / idx, other_income=other_income / idx,
        tax_year=tax_year, **kwargs,
    )
    out = _scale_money(calc, idx)
    gain = float(out.get("gain", 0.0))
    if gain <= 0:
        return out
    # The NIIT thresholds are fixed in statute, so the NIIT is recomputed on the nominal amounts.
    status = str(kwargs.get("filing_status") or ("MFJ" if kwargs.get("is_mfj", True) else "SINGLE")).strip().upper()
    niit = niit_on_gain(gain, other_income + gain, status)
    out["total_tax"] = out["total_tax"] + niit - out["niit_tax"]
    out["niit_tax"] = niit
    out["effective_rate"] = out["total_tax"] / gain
    return out
