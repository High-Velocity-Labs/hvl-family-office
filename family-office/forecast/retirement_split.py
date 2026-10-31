"""
forecast/retirement_split.py: Share of the retirement balance that is pre-tax (traditional) rather than Roth.
Pure math over the balance sheet's retirement accounts. A household with no Roth account on file is treated as all
pre-tax, not as an assumed 80/20 mix.
"""

from __future__ import annotations

from typing import Any, Dict, List

ALL_PRETAX = 1.0


def pretax_share(retirement_accounts: List[Dict[str, Any]]) -> float:
    """Balance-weighted pre-tax share; accounts whose name or type says Roth count as Roth."""
    total = roth = 0.0
    for acc in retirement_accounts:
        bal = abs(float(acc.get("balance") or acc.get("currentBalance") or acc.get("current_balance") or 0.0))
        label = " ".join(str(acc.get(k) or "") for k in ("name", "displayName", "type", "subtype")).lower()
        total += bal
        roth += bal if "roth" in label else 0.0
    return ALL_PRETAX if total <= 0 else 1.0 - roth / total
