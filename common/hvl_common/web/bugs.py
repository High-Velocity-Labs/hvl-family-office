"""
Shared HVL Bug Report PII & Monetary Anonymization Primitives.
Provides deterministic token redaction, email scrubbing, and isomorphic numeric scaling.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from hvl_common.security.sanitize import sanitize_text

NON_MONETARY_KEYS: frozenset[str] = frozenset({
    "id", "family_id", "household_id", "user_id", "bug_id", "age", "retirement_age",
    "year", "years", "month", "count", "account_count", "total_count", "rate",
    "pct", "percent", "percentage", "percentile", "trials", "status", "role",
    "universe", "filing_status", "state", "tier", "version", "app_version",
    "client_version", "git_sha", "support_access_enabled", "is_demo", "is_sandbox",
    "active", "enabled",
})

GENERIC_WORDS: frozenset[str] = frozenset({
    "cash", "stock", "trust", "plan", "the", "family", "bank", "roth", "ira",
    "401k", "loan", "card", "fund", "savings", "checking", "none", "null",
    "true", "false", "holding", "equity", "vested", "unvested", "total",
})

_NON_MONETARY_SUFFIXES: tuple[str, ...] = (
    "_id", "_count", "_year", "_age", "_rate", "_pct", "_percent",
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

_DOLLAR_RE = re.compile(
    r"([+-])?\$\s*([+-])?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|\d+(?:\.[0-9]+)?)(?:\s*([kKmMbB])\b)?"
)


def anonymize_structure(
    obj: Any,
    scale_factor: float,
    token_map: dict[str, str],
    active_key: str = "",
) -> Any:
    """Recursively replaces sensitive tokens and scales monetary values in nested data."""
    if isinstance(obj, str):
        val = obj
        for phrase, token in sorted(token_map.items(), key=lambda x: len(x[0]), reverse=True):
            if len(phrase) >= 3:
                val = re.sub(re.escape(phrase), token, val, flags=re.IGNORECASE)
        return val
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        key_low = active_key.lower()
        if key_low in NON_MONETARY_KEYS or key_low.endswith(_NON_MONETARY_SUFFIXES):
            return obj
        return round(float(obj) * scale_factor, 2)
    if isinstance(obj, dict):
        return {
            k: anonymize_structure(v, scale_factor, token_map, active_key=str(k))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [
            anonymize_structure(item, scale_factor, token_map, active_key=active_key)
            for item in obj
        ]
    return obj


def scrub_explanatory_text(
    text: str,
    token_map: dict[str, str],
    scale_factor: float,
    max_length: int = 500,
    sanitize_fn: Callable[[str], str] | None = None,
) -> str:
    """Sanitizes user description, redacts known tokens and emails, and scales dollar amounts."""
    raw_clipped = str(text or "").strip()[:max_length]
    if sanitize_fn is not None:
        cleaned = sanitize_fn(raw_clipped)
    else:
        cleaned = sanitize_text(
            raw_clipped, max_length=max_length, field_name="description"
        )
    if not cleaned:
        return ""

    for phrase, token in sorted(token_map.items(), key=lambda x: len(x[0]), reverse=True):
        if len(phrase) >= 3:
            cleaned = re.sub(re.escape(phrase), token, cleaned, flags=re.IGNORECASE)

    cleaned = _EMAIL_RE.sub("[redacted-email]", cleaned)

    def _scale_dollar(m: re.Match) -> str:
        sign = m.group(1) or m.group(2) or ""
        try:
            val = float(m.group(3).replace(",", ""))
        except ValueError:
            return m.group(0)
        suf = (m.group(4) or "").lower()
        val *= (
            1000.0 if suf == "k"
            else (1000000.0 if suf == "m" else (1000000000.0 if suf == "b" else 1.0))
        )
        scaled = val * scale_factor
        return (
            f"{sign}${scaled:,.0f} (scaled)"
            if scaled >= 10
            else f"{sign}${scaled:,.2f} (scaled)"
        )

    return _DOLLAR_RE.sub(_scale_dollar, cleaned)
