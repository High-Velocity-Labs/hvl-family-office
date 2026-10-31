"""
forecast/investment_income.py: The household's taxable investment income, for the ACA MAGI and the charitable AGI.
Pure math. A household with tax transcripts on file has real 1099 dividend and interest income; its yield on the
starting taxable balance replaces the flat 2% proxy. Without transcripts the proxy stands, and the plan says so by
returning None rather than a number.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Yield on the taxable balance counted toward MAGI/AGI when the household has no investment income on file.
DEFAULT_TAXABLE_YIELD_RATE = 0.02

_INCOME_KEYS = ("ordinary_dividends", "qualified_dividends", "interest_income")


def _totals_income(totals: Dict[str, Any]) -> Optional[float]:
    """Dividends plus interest from one transcript totals dict; None when it reports neither."""
    if not any(k in totals for k in _INCOME_KEYS):
        return None
    dividends = float(totals.get("ordinary_dividends") or totals.get("qualified_dividends") or 0.0)
    return dividends + float(totals.get("interest_income") or 0.0)


def known_investment_income(payload: Dict[str, Any]) -> Optional[float]:
    """
    Annual taxable dividends and interest in the latest tax year on file, or None when no year reports them.
    A year's full transcript wins; otherwise its household summary, otherwise the sum of the adults' summaries.
    """
    year_keys = [str(y) for key in ("transcripts_by_year", "historical_summary") for y in (payload.get(key) or {})]
    year_keys += [str(y) for adult in (payload.get("transcripts_by_adult") or {}).values() for y in adult]
    years = sorted({int(y) for y in year_keys if y.isdigit()}, reverse=True)
    for year in years:
        full = (payload.get("transcripts_by_year") or {}).get(str(year)) or {}
        income = _totals_income(full.get("totals", full) if isinstance(full.get("totals"), dict) else full)
        if income is None:
            income = _totals_income((payload.get("historical_summary") or {}).get(str(year)) or {})
        if income is None:
            adults = [a.get(str(year)) or {} for a in (payload.get("transcripts_by_adult") or {}).values()]
            parts = [_totals_income(a) for a in adults]
            income = sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None
        if income is not None:
            return income
    return None


def taxable_yield_rate(known_income: Optional[float], taxable_balance: float) -> float:
    """Yield on the taxable balance: the household's actual income over its balance, else the 2% proxy."""
    if known_income is None or taxable_balance <= 0:
        return DEFAULT_TAXABLE_YIELD_RATE
    return max(0.0, known_income) / taxable_balance
