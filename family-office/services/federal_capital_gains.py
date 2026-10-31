"""Federal long-term capital gains rate bands and net investment income tax (pure math)."""

from __future__ import annotations

from services import statutory_limits

LTCG_ZERO_RATE = 0.00
LTCG_MID_RATE = 0.15
LTCG_TOP_RATE = 0.20
NIIT_RATE = 0.038


def long_term_gain_tax(gain: float, ordinary_taxable: float, filing_status: str) -> float:
    """Tax on `gain` taxed as long-term gain, stacked on top of `ordinary_taxable` income (0/15/20% bands)."""
    if gain <= 0:
        return 0.0
    zero_top, mid_top = statutory_limits.LTCG_BAND_TOPS_2026[(filing_status or "MFJ").strip().upper()]
    start = max(0.0, ordinary_taxable)
    end = start + gain
    in_zero = max(0.0, min(end, zero_top) - start)
    in_mid = max(0.0, min(end, mid_top) - max(start, zero_top))
    in_top = max(0.0, end - max(start, mid_top))
    return in_zero * LTCG_ZERO_RATE + in_mid * LTCG_MID_RATE + in_top * LTCG_TOP_RATE


def niit_on_gain(gain: float, magi: float, filing_status: str) -> float:
    """3.8% on the lesser of the gain or MAGI above the filing-status threshold."""
    threshold = statutory_limits.NIIT_MAGI_THRESHOLDS[(filing_status or "MFJ").strip().upper()]
    return NIIT_RATE * max(0.0, min(gain, magi - threshold))
