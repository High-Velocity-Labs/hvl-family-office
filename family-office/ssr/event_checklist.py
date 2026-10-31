"""
View-model for the scenario-plan modal's event checklist (accordion of catalog events grouped by category).
The browser sends the draft (checked ids, parent plan, search text, open groups); every label, badge class,
icon, inheritance badge and count is decided here, so the client only swaps the returned fragment.
"""

from __future__ import annotations

from typing import Any, Iterable

# (key, title, sprite icon, color, categories); the final "other" group collects every unlisted category.
EVENT_GROUPS: tuple[dict[str, Any], ...] = (
    {"key": "education", "title": "Education & College Tuition", "icon": "evt-college", "color": "#0284C7",
     "categories": ("education", "college", "grad_school", "superfund_529")},
    {"key": "equity", "title": "Company Equity, Career & Private Markets", "icon": "evt-equity", "color": "#059669",
     "categories": ("company_equity", "equity", "sabbatical", "income_change", "pe_capital_call")},
    {"key": "real_estate", "title": "Real Estate, Relocation & Mortgages", "icon": "evt-real-estate",
     "color": "#D97706",
     "categories": ("real_estate", "home_renovation", "home_sale", "refinance", "debt_payoff", "state_relocation")},
    {"key": "gifting", "title": "Tax Strategy, Gifting & Philanthropy (DAF)", "icon": "evt-gifting", "color": "#1D4ED8",
     "categories": ("gifting", "gifting_throughline", "philanthropy_daf", "child_home_gift", "roth_conversion")},
    {"key": "eldercare", "title": "Family Care, LTC & Eldercare", "icon": "evt-eldercare", "color": "#0D9488",
     "categories": ("eldercare", "parent_care", "new_child", "medical_expense", "ltc_insurance", "pre65_healthcare")},
    {"key": "lifestyle", "title": "Lifestyle, Milestones & Travel Surges", "icon": "evt-travel", "color": "#C06C26",
     "categories": ("lifestyle", "travel_surge", "wedding", "vehicle_purchase")},
    {"key": "capital_outflow", "title": "Capital Outflows & Settlements", "icon": "evt-capital-outflow",
     "color": "#C75D6E", "categories": ("capital_outflow", "withdrawal", "angel_investment", "marital_settlement")},
    {"key": "capital_inflow", "title": "Capital Inflows & Income Streams", "icon": "evt-capital-inflow",
     "color": "#059669",
     "categories": ("capital_inflow", "custom_spike", "windfall", "rental_income", "deferred_comp")},
    {"key": "other", "title": "Other Financial Events", "icon": "evt-other", "color": "#64748B",
     "categories": ("other",)},
)
_KNOWN_CATEGORIES = frozenset(c for g in EVENT_GROUPS if g["key"] != "other" for c in g["categories"])

CATEGORY_LABELS = {
    "college": "College Education", "grad_school": "Graduate / Professional School",
    "superfund_529": "529 Superfunding", "company_equity": "Company Equity", "equity": "Company Equity",
    "pe_capital_call": "Private Equity / VC (J-Curve)", "real_estate": "Real Estate",
    "home_renovation": "Home Renovation / Remodel", "home_sale": "Home Sale / Downsize",
    "state_relocation": "State Tax Relocation", "sabbatical": "Sabbatical / Career Pivot",
    "income_change": "Career / Income Pivot", "philanthropy_daf": "Charitable / DAF",
    "roth_conversion": "Roth Conversion Ladder", "wedding": "Wedding / Celebration",
    "child_home_gift": "First-Home Down Payment Gift", "new_child": "New Child / Childcare",
    "vehicle_purchase": "Vehicle Purchase", "angel_investment": "Angel / Venture Investment",
    "marital_settlement": "Marital Settlement / Split", "rental_income": "Rental Income Stream",
    "deferred_comp": "Deferred Comp / Pension", "medical_expense": "Major Medical Expense",
    "ltc_insurance": "Long-Term Care (LTC) Policy", "pre65_healthcare": "Pre-65 Healthcare / ACA Bridge",
    "lifestyle": "Lifestyle & Travel", "travel_surge": "Lifestyle & Travel", "education": "K-12 Education",
    "eldercare": "Elderly Parent Care", "parent_care": "Elderly Parent Care", "gifting": "Family Gifting",
    "gifting_throughline": "Family Gifting", "debt_payoff": "Debt Payoff", "refinance": "Mortgage Refinance",
    "capital_outflow": "Capital Outflow / Milestone", "withdrawal": "Capital Outflow / Withdrawal",
    "capital_inflow": "Capital Inflow / Windfall", "custom_spike": "Capital Inflow / Windfall",
    "windfall": "Capital Inflow / Windfall",
}

_BADGE_CLASSES = (
    ("badge-blue", ("college", "education", "grad_school", "superfund_529")),
    ("badge-orange", ("real_estate", "home_renovation", "home_sale")),
    ("badge-pink", ("lifestyle", "travel_surge", "wedding")),
    ("badge-green", ("debt_payoff", "refinance", "state_relocation", "company_equity", "equity", "pe_capital_call",
                     "capital_inflow", "custom_spike", "windfall", "rental_income", "deferred_comp")),
    ("badge-teal", ("eldercare", "parent_care", "new_child", "medical_expense", "ltc_insurance", "pre65_healthcare")),
    ("badge-purple", ("gifting", "gifting_throughline", "philanthropy_daf", "child_home_gift", "sabbatical",
                      "income_change", "roth_conversion")),
    ("badge-red", ("capital_outflow", "withdrawal", "vehicle_purchase", "angel_investment", "marital_settlement")),
)

# Event category (or catalog icon key) -> sprite id in /common/icons.svg
CATEGORY_ICONS = {
    "company_equity": "evt-equity", "equity": "evt-equity", "lifestyle": "evt-travel", "travel_surge": "evt-travel",
    "real_estate": "evt-real-estate", "debt_payoff": "evt-debt", "refinance": "evt-refi", "education": "evt-k12",
    "college": "evt-college", "gifting": "evt-gifting", "gifting_throughline": "evt-gifting",
    "eldercare": "evt-eldercare", "parent_care": "evt-eldercare", "capital_outflow": "evt-capital-outflow",
    "withdrawal": "evt-capital-outflow", "capital_inflow": "evt-capital-inflow", "custom_spike": "evt-capital-inflow",
    "windfall": "evt-capital-inflow", "other": "evt-other", "vacation_home": "evt-vacation-home",
    "home_sale": "evt-home-sale", "home_renovation": "evt-renovation", "child_home_gift": "evt-house-key",
    "solar_energy": "evt-solar", "wedding": "evt-wedding", "new_child": "evt-baby", "grad_school": "evt-grad-school",
    "medical_expense": "evt-medical", "vehicle_purchase": "evt-car", "yacht_vessel": "evt-yacht",
    "major_purchase": "evt-art", "sabbatical": "evt-briefcase", "income_change": "evt-briefcase",
    "angel_investment": "evt-rocket", "asset_sale": "evt-business-sale", "inheritance": "evt-inheritance",
    "rental_income": "evt-rental-income", "deferred_comp": "evt-pension", "philanthropy_daf": "evt-philanthropy",
    "charitable": "evt-philanthropy", "tax_legal": "evt-tax-legal", "state_relocation": "evt-relocation",
    "roth_conversion": "evt-roth-ladder", "superfund_529": "evt-529-superfund", "pe_capital_call": "evt-j-curve",
    "ltc_insurance": "evt-ltc-shield", "pre65_healthcare": "evt-ltc-shield", "marital_settlement": "evt-asset-split",
    "evt-gift": "evt-gifting", "evt-tuition": "evt-college", "evt-charity": "evt-philanthropy",
    "evt-sabbatical": "evt-briefcase", "evt-529": "evt-529-superfund", "evt-capital-call": "evt-j-curve",
    "evt-lifestyle": "evt-travel",
}


def category_label(cat: str | None) -> str:
    if not cat:
        return "Event"
    return CATEGORY_LABELS.get(cat) or str(cat).replace("_", " ").title()


def category_badge_class(cat: str | None) -> str:
    return next((cls for cls, cats in _BADGE_CLASSES if cat in cats), "badge-blue")


def event_icon_id(event: dict[str, Any]) -> str:
    """Sprite id for an event: its own icon key when known, else its category's icon."""
    key = event.get("icon")
    if isinstance(key, str):
        if key in CATEGORY_ICONS:
            return CATEGORY_ICONS[key]
        if key.startswith("evt-") and key[4:] and "<" not in key:
            return key
    return CATEGORY_ICONS.get(str(event.get("category") or "other"), "evt-other")


def _in_group(group: dict[str, Any], category: str | None) -> bool:
    if group["key"] == "other":
        return category not in _KNOWN_CATEGORIES
    return category in group["categories"]


def _timing(event: dict[str, Any]) -> str:
    year, end = event.get("year"), event.get("end_year")
    return f"{year}" if (not end or year == end) else f"{year}–{end}"


def _inheritance(has_parent: bool, checked: bool, in_parent: bool) -> str:
    if not has_parent:
        return ""
    if in_parent:
        return "inherited" if checked else "excluded"
    return "override" if checked else ""


def build_event_checklist(
    *,
    events: Iterable[dict[str, Any]],
    selected_ids: set[str],
    parent: dict[str, Any] | None,
    overlay_on_baseline: bool,
    query: str,
    open_keys: set[str] | None,
) -> dict[str, Any]:
    """Returns {groups, total, parent_name}. `open_keys=None` opens the groups holding a checked event."""
    catalog = [e for e in events if isinstance(e, dict) and e.get("id")]
    parent_ids: set[str] = set()
    if parent:
        raw = parent.get("raw_event_ids")
        parent_ids = set(raw if (overlay_on_baseline and isinstance(raw, list)) else parent.get("event_ids") or [])
    q = (query or "").lower().strip()
    groups, total = [], 0
    for group in EVENT_GROUPS:
        members = [e for e in catalog if _in_group(group, e.get("category"))]
        if q:
            members = [
                e for e in members
                if q in str(e.get("name") or "").lower() or q in str(e.get("description") or "").lower()
                or q in category_label(e.get("category")).lower()
            ]
        if not members:
            continue
        rows = []
        for e in members:
            checked = e["id"] in selected_ids
            cat = e.get("category")
            rows.append({
                "id": e["id"], "name": e.get("name") or "", "description": e.get("description") or "",
                "checked": checked, "timing": _timing(e), "category_label": category_label(cat),
                "badge_class": category_badge_class(cat), "icon": event_icon_id(e),
                "inheritance": _inheritance(bool(parent), checked, e["id"] in parent_ids),
                "ledger": (("synced" if e.get("sync_with_ledger") else "speculative")
                           if cat in ("college", "education") else ""),
            })
        active = sum(1 for r in rows if r["checked"])
        if q:
            is_open = True
        elif open_keys is None:
            is_open = any(e["id"] in selected_ids for e in catalog if _in_group(group, e.get("category")))
        else:
            is_open = group["key"] in open_keys
        total += len(rows)
        groups.append({**group, "rows": rows, "active": active, "open": is_open})
    return {"groups": groups, "total": total, "catalog_empty": not catalog, "query": q,
            "parent_name": (parent or {}).get("name") or ""}
