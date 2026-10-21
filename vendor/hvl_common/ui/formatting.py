"""
Canonical SSR numeric, currency, percentage, and markdown changelog formatting helpers for High Velocity Labs UI.
"""

from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any

_INLINE_MD_RE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")
_SAFE_ROUTE_RE = re.compile(r"^/[a-z0-9_/-]+$")


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


def tokenize_inline_markdown(text: str) -> list[dict[str, str]]:
    """Splits inline markdown text into tokens ('text', 'bold', 'code', 'code_link') for safe SSR without Jinja `| safe`."""
    tokens: list[dict[str, str]] = []
    for part in _INLINE_MD_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            tokens.append({"type": "bold", "text": part[2:-2]})
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            inner = part[1:-1]
            if _SAFE_ROUTE_RE.match(inner):
                tokens.append({"type": "code_link", "text": inner, "href": inner})
            else:
                tokens.append({"type": "code", "text": inner})
        else:
            tokens.append({"type": "text", "text": part})
    return tokens


_tokenize_inline_markdown = tokenize_inline_markdown


def parse_changelog_releases(
    changelog_path: Path | str,
    max_releases: int = 8,
) -> list[dict[str, Any]]:
    """Parses a CHANGELOG.md file into structured release objects for semantic SSR rendering."""
    path_obj = Path(changelog_path)
    if not path_obj.is_file():
        return []
    try:
        raw = path_obj.read_text(encoding="utf-8")
    except Exception:
        return []

    header_re = re.compile(r"^##\s+\[?(v?\d+\.\d+\.\d+[^\]]*)\]?(?:\s*-\s*(\S+))?", re.MULTILINE)
    matches = list(header_re.finditer(raw))
    releases: list[dict[str, Any]] = []

    for idx, match in enumerate(matches[:max_releases]):
        ver_raw = match.group(1).strip()
        version = ver_raw if ver_raw.startswith("v") else f"v{ver_raw}"
        date_str = (match.group(2) or "").strip()
        end_idx = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        body = raw[match.end() : end_idx].strip()

        sections: list[dict[str, Any]] = []
        current_section: dict[str, Any] = {"heading": "", "groups": []}
        current_group: dict[str, Any] | None = None

        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("### "):
                if current_section["heading"] or current_section["groups"]:
                    sections.append(current_section)
                current_section = {"heading": stripped[4:].strip(), "groups": []}
                current_group = None
            elif line.startswith("- "):
                title_clean = stripped[2:].strip().rstrip(":").strip()
                bullet_tokens: list[list[dict[str, str]]] = []
                current_group = {
                    "title": title_clean,
                    "title_tokens": tokenize_inline_markdown(title_clean),
                    "bullets": bullet_tokens,
                    "bullet_tokens": bullet_tokens,
                    "bullet_texts": [],
                }
                current_section["groups"].append(current_group)
            elif line.startswith(("  - ", "    - ")):
                if current_group is None:
                    bullet_tokens = []
                    current_group = {
                        "title": "",
                        "title_tokens": [],
                        "bullets": bullet_tokens,
                        "bullet_tokens": bullet_tokens,
                        "bullet_texts": [],
                    }
                    current_section["groups"].append(current_group)
                bullet_str = stripped[2:].strip()
                current_group["bullet_texts"].append(bullet_str)
                current_group["bullets"].append(tokenize_inline_markdown(bullet_str))
            elif current_group and current_group["bullet_texts"]:
                current_group["bullet_texts"][-1] += " " + stripped
                current_group["bullets"][-1] = tokenize_inline_markdown(current_group["bullet_texts"][-1])

        if current_section["heading"] or current_section["groups"]:
            sections.append(current_section)
        releases.append({"version": version, "date": date_str, "sections": sections})

    return releases


__all__ = [
    "fmt_currency",
    "fmt_short_currency",
    "fmt_pct",
    "tokenize_inline_markdown",
    "_tokenize_inline_markdown",
    "parse_changelog_releases",
]
