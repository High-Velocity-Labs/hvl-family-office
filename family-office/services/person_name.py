"""Given-name extraction from a full display name (honorifics and suffixes are not names)."""

from __future__ import annotations

_HONORIFICS = frozenset({
    "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "professor", "sir", "dame", "rev", "fr", "hon",
    "judge", "capt", "col", "gen", "lt", "maj", "sgt",
})
_SUFFIXES = frozenset({
    "jr", "sr", "ii", "iii", "iv", "v", "md", "phd", "esq", "dds", "dvm", "do", "cpa", "cfa", "rn", "mba", "jd",
})


def _norm(token: str) -> str:
    return token.strip().strip(",;").rstrip(".").lower()


def first_name(full_name: str, default: str) -> str:
    """First given name of `full_name`, skipping leading honorifics ("Dr. Sarah Jones, MD" -> "Sarah").

    Returns `default` when no name token remains (empty input or only honorifics/suffixes).
    """
    for token in (full_name or "").replace(",", " ").split():
        if _norm(token) not in _HONORIFICS and _norm(token) not in _SUFFIXES:
            return token.strip(",;")
    return default
