"""
View-model for the Master Event Catalog modal list: filter by category group and search text, and decide every label,
badge class, icon, timing and plan-usage badge here so the browser only swaps the returned fragment.
"""

from __future__ import annotations

from typing import Any, Iterable

from ssr.event_checklist import category_badge_class, category_label, event_icon_id

# Catalog filter value -> categories it covers. "other" is every category not listed under any group below.
CATALOG_FILTER_GROUPS: dict[str, tuple[str, ...]] = {
    "education": ("education", "college", "grad_school", "superfund_529"),
    "company_equity": ("company_equity", "equity", "sabbatical", "income_change", "roth_conversion"),
    "real_estate": ("real_estate", "home_renovation", "home_sale", "refinance", "debt_payoff", "state_relocation"),
    "gifting": ("gifting", "gifting_throughline", "philanthropy_daf", "child_home_gift", "superfund_529"),
    "eldercare": ("eldercare", "parent_care", "ltc_insurance", "pre65_healthcare", "new_child", "medical_expense"),
    "lifestyle": ("lifestyle", "travel_surge", "wedding", "vehicle_purchase"),
    "capital_outflow": ("capital_outflow", "withdrawal", "angel_investment", "pe_capital_call", "marital_settlement"),
    "capital_inflow": ("capital_inflow", "custom_spike", "windfall", "rental_income", "deferred_comp"),
}
_KNOWN_CATEGORIES = frozenset(c for cats in CATALOG_FILTER_GROUPS.values() for c in cats)


def _matches_category(category: str | None, selected: str) -> bool:
    if selected in ("", "ALL"):
        return True
    if selected == "other":
        return category not in _KNOWN_CATEGORIES
    if selected in CATALOG_FILTER_GROUPS:
        return category in CATALOG_FILTER_GROUPS[selected]
    return category == selected


def _timing(event: dict[str, Any]) -> str:
    year, end = event.get("year"), event.get("end_year")
    return f"{year}" if (not end or year == end) else f"{year}–{end}"


def build_event_catalog(
    *, events: Iterable[dict[str, Any]], scenarios: Iterable[dict[str, Any]], query: str, category: str
) -> dict[str, Any]:
    """Returns {rows, total} for the events matching `category` and the search `query`."""
    q = (query or "").lower().strip()
    plans = [s for s in scenarios if isinstance(s, dict)]
    rows = []
    for e in events:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        cat = e.get("category")
        if not _matches_category(cat, category):
            continue
        label = category_label(cat)
        if q and not any(q in str(text or "").lower() for text in (e.get("name"), e.get("description"), label)):
            continue
        using = [s.get("name") or s.get("id") for s in plans if e["id"] in (s.get("event_ids") or [])]
        rows.append({
            "id": e["id"], "name": e.get("name") or "", "description": e.get("description") or "",
            "timing": _timing(e), "category_label": label, "badge_class": category_badge_class(cat),
            "icon": event_icon_id(e), "plan_count": len(using), "plan_names": ", ".join(using),
        })
    return {"rows": rows, "total": len(rows)}
