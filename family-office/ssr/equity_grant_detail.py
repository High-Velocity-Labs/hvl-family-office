"""
SSR view-model for the equity grant inspection card. Every figure comes from the equity engine's per-grant result
(`equity.models.Grant.calculate_at_price`), including the tax on already-owned shares; nothing is computed in JS.
"""

from __future__ import annotations

from typing import Any

from ssr.formatting import fmt_currency

NOT_SET = "--"


def _money(grant: dict, key: str, decimals: int = 0) -> str:
    value = grant.get(key)
    return fmt_currency(float(value), decimals) if value is not None else NOT_SET


def build_ssr_grant_detail(snapshot: dict, grant_id: str) -> dict[str, Any]:
    """Returns the card view-model for `grant_id`, or `{}` when the snapshot has no such grant."""
    grants = (snapshot.get("company_equity") or {}).get("grants") or []
    grant = next((g for g in grants if str(g.get("grant_id")) == str(grant_id)), None)
    if grant is None:
        return {}

    gtype = str(grant.get("grant_type") or "").lower()
    is_rsu, is_iso = gtype == "rsu", gtype == "iso"
    owned = float(grant.get("owned_shares") or 0.0)
    stock_tax = grant.get("stock_tax") or {}
    basis_total = grant.get("owned_cost_basis")
    owned_gross = grant.get("owned_gross_value")
    has_owned = owned > 0 and owned_gross is not None and basis_total is not None
    owned_gain = max(0.0, float(owned_gross) - float(basis_total)) if has_owned else None
    unvested = float(grant.get("unvested_options") or 0.0)
    type_label = (
        "Restricted Stock Unit (RSU)" if is_rsu
        else "Incentive Stock Option (ISO)" if is_iso
        else "Non-Qualified Stock Option (NSO)"
    )

    rows = [
        {"label": "COMPANY", "value": grant.get("company_name") or NOT_SET},
        {"label": "GRANT TYPE", "badge": "badge-green" if is_iso else "badge-blue", "value": type_label},
        {"label": "STRIKE PRICE", "value": "$0.00 (RSU)" if is_rsu else _money(grant, "strike_price", 2)},
        {"label": "VESTED UNITS", "value": f"{float(grant.get('unexercised_options') or 0):,.0f}"},
        {"label": "UNVESTED UNITS", "value": f"{unvested:,.0f}",
         "note": "(Excluded from Net Worth until Vested)" if unvested > 0 else ""},
        {"label": "STRIKE CASH REQUIRED", "value": "$0" if is_rsu else _money(grant, "strike_cost")},
        {"label": "TAXABLE SPREAD", "value": _money(grant, "spread")},
        {"label": "EST. TAX LIABILITY (LTCG)" if is_iso else "ORDINARY TAX LIABILITY",
         "value": _money(grant, "total_tax_drag"), "tone": "red"},
        {"label": "VESTED UNITS NET VALUE", "value": _money(grant, "net_option_value")},
        {"label": "OWNED / EXERCISED SHARES", "value": f"{owned:,.0f} shares" if owned > 0 else "0 shares"},
        {"label": "OWNED SHARES COST BASIS",
         "value": f"{fmt_currency(float(basis_total) / owned, 2)}/sh ({fmt_currency(float(basis_total), 0)} total)"
         if has_owned else NOT_SET},
        {"label": "OWNED SHARES MARKET VALUE", "value": _money(grant, "owned_gross_value") if owned > 0 else NOT_SET},
        {"label": "UNREALIZED CAPITAL GAINS",
         "value": fmt_currency(owned_gain, 0) if has_owned else NOT_SET,
         "tone": "green" if (owned_gain or 0) > 0 else ""},
        {"label": "EST. TAX ON OWNED SHARES",
         "value": fmt_currency(float(stock_tax["total_tax"]), 0) if (owned > 0 and "total_tax" in stock_tax)
         else NOT_SET,
         "tone": "red"},
        {"label": "OWNED SHARES NET VALUE", "tone": "green",
         "value": _money(grant, "net_owned_value") if owned > 0 else NOT_SET},
        {"label": "COMBINED TRUE NET VALUE", "value": _money(grant, "true_net_value"), "tone": "green", "large": True},
        {"label": "VESTING STATUS", "value": grant.get("vesting_completion") or NOT_SET},
    ]
    return {
        "grant_id": grant.get("grant_id"),
        "title": f"Grant Inspection: {grant.get('nickname') or 'Grant'} ({grant.get('grant_date') or NOT_SET})",
        "is_iso": is_iso,
        "rows": rows,
    }
