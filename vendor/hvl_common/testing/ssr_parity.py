"""
High Velocity Labs SSR Hydration, Placeholder, and Dollar-for-Dollar Parity Auditor.

Provides standardized testing utilities across High Velocity Labs web applications
(finances, ff, highvelocitylabs) to prevent UI layout judder, number pop-ins,
missing comma formatting, and unhydrated client shells.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional, Set, List, Dict, Any


class KPIElementExtractor(HTMLParser):
    """HTML parser that extracts text and attributes from KPI/stat value elements, footer totals, and metric badges."""

    TARGET_CLASSES = {"kpi-value", "hero-kpi", "stat-value", "kpi-num", "metric-value"}
    TARGET_ID_SUFFIXES = ("-total", "-limit", "-headroom", "-balance", "-assets", "-savings", "-coverage", "-cashflow", "-shielded")
    TARGET_ID_PREFIXES = ("stat-", "kpi-", "badge-max-")

    def __init__(self):
        super().__init__()
        self.kpis: List[Dict[str, Any]] = []
        self._current_kpi: Optional[Dict[str, Any]] = None
        self._depth = 0
        self._in_tfoot = False

    def handle_starttag(self, tag, attrs):
        if tag == "tfoot":
            self._in_tfoot = True

        attr_dict = dict(attrs)
        classes = set(attr_dict.get("class", "").split())
        elem_id = attr_dict.get("id", "")

        is_target = bool(classes & self.TARGET_CLASSES)
        if not is_target and elem_id:
            if any(elem_id.endswith(sfx) for sfx in self.TARGET_ID_SUFFIXES):
                is_target = True
            elif any(elem_id.startswith(pfx) for pfx in self.TARGET_ID_PREFIXES):
                is_target = True
            elif self._in_tfoot and tag == "td":
                is_target = True

        if is_target and not self._current_kpi:
            self._current_kpi = {
                "tag": tag,
                "id": elem_id or "unnamed",
                "classes": list(classes),
                "text_parts": [],
            }
            self._depth = 1
        elif self._current_kpi:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag == "tfoot":
            self._in_tfoot = False

        if self._current_kpi:
            self._depth -= 1
            if self._depth == 0:
                self._current_kpi["text"] = "".join(self._current_kpi["text_parts"]).strip()
                self.kpis.append(self._current_kpi)
                self._current_kpi = None

    def handle_data(self, data):
        if self._current_kpi:
            self._current_kpi["text_parts"].append(data)


class SSRParityAuditor:
    """
    Automated auditor for Server-Side Rendered (SSR) HTML and Fragment hydration.
    Enforces HVL invariants for zero-CLS, zero-popin, and format consistency.
    """

    UNHYDRATED_COMMENT_PATTERNS = [
        re.compile(r"<!--\s*(?:Dynamically\s+)?Populated\s+(?:dynamically\s+)?via\s+JS\b", re.IGNORECASE),
        re.compile(r"<!--\s*(?:Dynamically\s+)?Populated\s+by\s+JS\b", re.IGNORECASE),
        re.compile(r"<!--\s*Loaded\s+via\s+JS\b", re.IGNORECASE),
        re.compile(r"<!--\s*Rendered\s+dynamically\s+via\s+JS\b", re.IGNORECASE),
    ]

    UNFORMATTED_CURRENCY_PATTERN = re.compile(r"\$([0-9]{4,})(?:\.[0-9]{2})?\b")

    @classmethod
    def extract_kpis(cls, html: str) -> List[Dict[str, Any]]:
        """Extracts all KPI and metric elements from rendered HTML."""
        parser = KPIElementExtractor()
        parser.feed(html)
        return parser.kpis

    @classmethod
    def clean_number(cls, val: Any) -> float:
        """
        Parses clean float from currency strings like '$995,511', '$1.85M', '$240k', or '$2,733.00'.
        """
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).replace("$", "").replace(",", "").strip()
        if not s or s == "--":
            return 0.0
        if s.endswith("M") or s.endswith("m"):
            return float(s[:-1]) * 1_000_000
        if s.endswith("k") or s.endswith("K"):
            return float(s[:-1]) * 1_000
        if s.endswith("B") or s.endswith("b"):
            return float(s[:-1]) * 1_000_000_000
        return float(s)

    @classmethod
    def assert_no_bare_kpi_dashes(
        cls,
        html: str,
        context_name: str = "",
        allowed_empty_ids: Optional[Set[str]] = None,
    ) -> None:
        """
        Asserts that primary KPI elements in rendered HTML do not contain bare '--'.
        """
        allowed = {k.lower() for k in (allowed_empty_ids or set())}
        kpis = cls.extract_kpis(html)
        failing = []

        for k in kpis:
            txt = k["text"]
            elem_id = k["id"].lower()
            if txt == "--":
                if any(allow in elem_id for allow in allowed):
                    continue
                failing.append(f"#{k['id']} ({'.'.join(k['classes'])}) = '{txt}'")

        assert not failing, (
            f"SSR fragment '{context_name}' rendered unhydrated '--' KPI elements:\n"
            + "\n".join(f"  - {f}" for f in failing)
        )

    @classmethod
    def assert_no_unhydrated_comments(cls, html: str, context_name: str = "") -> None:
        """
        Verifies that rendered HTML does not leave behind placeholder comments like
        '<!-- Populated via JS -->' indicating missing server-side pre-rendering.
        """
        matches = []
        for pat in cls.UNHYDRATED_COMMENT_PATTERNS:
            found = pat.findall(html)
            if found:
                matches.extend(found)

        assert not matches, (
            f"Rendered SSR HTML '{context_name}' contains unhydrated placeholder comments: {matches}. "
            f"Content must be pre-rendered on the server via SSR."
        )

    @classmethod
    def assert_no_unhydrated_tables(
        cls,
        html: str,
        context_name: str = "",
        allowed_empty_ids: Optional[Set[str]] = None,
    ) -> None:
        """
        Asserts that any <tbody> element with an id is pre-rendered with <tr> table rows
        on the server rather than remaining an empty shell or comment placeholder.
        """
        allowed = {k.lower() for k in (allowed_empty_ids or set())}
        tbody_pattern = re.compile(r'<tbody\s+[^>]*id=["\']([^"\']+)["\'][^>]*>(.*?)</tbody>', re.DOTALL | re.IGNORECASE)
        empty_tbodies = []
        for m in tbody_pattern.finditer(html):
            tbody_id = m.group(1)
            content = m.group(2).strip()
            if tbody_id.lower() in allowed:
                continue
            no_comments = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL).strip()
            if not no_comments or '<tr' not in no_comments.lower():
                empty_tbodies.append(tbody_id)

        assert not empty_tbodies, (
            f"SSR fragment '{context_name}' contains unhydrated empty <tbody> elements without <tr> rows: {empty_tbodies}. "
            f"Table rows must be pre-rendered on the server via Jinja SSR."
        )

    @classmethod
    def assert_number_formatting(cls, html: str, context_name: str = "") -> None:
        """
        Detects unformatted 4+ digit currency figures like '$2733' or '$2733.00' that should
        have comma grouping like '$2,733' or '$2,733.00' to prevent font/DOM layout shift.
        """
        unformatted = cls.UNFORMATTED_CURRENCY_PATTERN.findall(html)
        assert not unformatted, (
            f"Rendered SSR HTML '{context_name}' contains unformatted currency numbers missing commas: {unformatted}. "
            f"Use localized comma formatting (e.g. $2,733.00 instead of $2733.00)."
        )

    @classmethod
    def assert_dollar_parity(
        cls,
        val1: Any,
        val2: Any,
        tolerance: float = 1.0,
        label: str = "Metric",
    ) -> None:
        """
        Verifies that an SSR value matches an API or model value within the given tolerance.
        """
        num1 = cls.clean_number(val1)
        num2 = cls.clean_number(val2)
        diff = abs(num1 - num2)
        assert diff <= tolerance, (
            f"{label} parity mismatch: SSR ({num1}) does not match expected ({num2}) within tolerance {tolerance} "
            f"(diff: {diff})"
        )

    @classmethod
    def scan_templates_for_bare_kpi_dashes(
        cls,
        templates_dir: Path,
        ignored_files: Optional[Set[str]] = None,
    ) -> List[str]:
        """
        Scans a directory of HTML templates for static '<div class="kpi-value">--</div>'
        without Jinja expressions.
        """
        ignored = ignored_files or set()
        bare_pattern = re.compile(
            r'<[a-z0-9]+[^>]*class="[^"]*(?:kpi-value|hero-kpi|stat-value)[^"]*"[^>]*>\s*--\s*</[a-z0-9]+>',
            re.IGNORECASE,
        )
        violations = []

        for fpath in templates_dir.rglob("*.html"):
            if fpath.name in ignored:
                continue
            content = fpath.read_text(encoding="utf-8", errors="ignore")
            # If the tag contains Jinja delimiters inside the text, it's dynamic
            matches = bare_pattern.findall(content)
            if matches:
                violations.append(f"{fpath.name}: {matches}")

        return violations
