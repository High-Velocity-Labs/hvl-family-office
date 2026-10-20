"""
Canonical SSR numeric, currency, and percentage formatting helpers for High Velocity Labs UI.
"""

from __future__ import annotations

import math
from typing import Any


def fmt_currency(val: Any, decimals: int = 0) -> str:
    """Format numeric value as US currency (e.g., '$1,234' or '$1,234.56', '--' on None/invalid)."""
    if val is None or isinstance(val, bool):
        return "--"
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return "--"
        sign = "-" if v < 0 else ""
        abs_v = abs(v)
        if decimals <= 0:
            return f"{sign}${abs_v:,.0f}"
        return f"{sign}${abs_v:,.{decimals}f}"
    except (ValueError, TypeError):
        return "--"


def fmt_short_currency(val: Any) -> str:
    """Format numeric value as compact US currency ('$1.5M', '$45k', or '$12.34', '--' on None/invalid)."""
    if val is None or isinstance(val, bool):
        return "--"
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return "--"
        abs_v = abs(v)
        sign = "-" if v < 0 else ""
        if abs_v >= 1_000_000:
            return f"{sign}${abs_v / 1_000_000:.1f}M"
        if abs_v >= 1_000:
            return f"{sign}${abs_v / 1_000:.0f}k"
        return fmt_currency(v, 2)
    except (ValueError, TypeError):
        return "--"


def fmt_pct(val: Any, decimals: int = 1) -> str:
    """Format numeric percentage value (e.g. 12.5 -> '12.5%', '--' on None/invalid)."""
    if val is None or isinstance(val, bool):
        return "--"
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return "--"
        return f"{v:.{decimals}f}%"
    except (ValueError, TypeError):
        return "--"


__all__ = ["fmt_currency", "fmt_short_currency", "fmt_pct"]
