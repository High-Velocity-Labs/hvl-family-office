"""
A household's state of residence: one of the tax jurisdictions the engines model, or unset.

Unset (`UNSET`, stored as "") means the household has not told us yet. Engines then apply no state
tax and the onboarding wizard asks for it; nothing falls back to a particular state.
"""

from __future__ import annotations

from typing import Mapping

from services.tax_calculations import STATE_TAX_PROFILES

UNSET = ""
SUPPORTED_STATES = frozenset(code for code in STATE_TAX_PROFILES if len(code) == 2)


def normalize(value: object) -> str:
    """The supported two-letter state code for `value`, or UNSET."""
    code = str(value or "").strip().upper()
    return code if code in SUPPORTED_STATES else UNSET


def from_request_headers(headers: Mapping[str, str]) -> str:
    """
    The visitor's state from Cloudflare's visitor location headers (`CF-IPCountry`, `CF-Region-Code`),
    or UNSET when the visitor is outside the US, the headers are absent, or the state is not modeled.
    """
    if str(headers.get("CF-IPCountry") or "").strip().upper() != "US":
        return UNSET
    return normalize(headers.get("CF-Region-Code"))
