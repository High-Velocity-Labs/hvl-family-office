"""
SSR formatting helpers and private investments data loader.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

from hvl_common.ui import fmt_currency, fmt_short_currency, fmt_pct
import security
import monarch_service

logger = logging.getLogger(__name__)


def get_private_investments_data(family_id: int) -> Dict[str, Any]:
    """Pulls private investments directly from Monarch Money accounts using preloaded categorization context."""
    try:
        import db
        from routes.helpers import DB_PATH
        accounts = db.accounts.list_accounts(family_id=family_id, db_path=DB_PATH) or []
        roles_cache, family_comps = monarch_service.load_family_categorization_context(family_id)
        priv_accounts = [
            a
            for a in accounts
            if isinstance(a, dict)
            and monarch_service.categorize_account(
                a, family_id=family_id, roles_cache=roles_cache, family_comps=family_comps
            )
            == "private_investments"
            and not monarch_service.is_account_hidden_from_family_office(
                str(a.get("id") or ""), "private_investments", family_id=family_id, roles_cache=roles_cache
            )
        ]

        items = []
        for acc in priv_accounts:
            acc_name = (acc.get("displayName") or acc.get("name") or "").strip()
            if not acc_name:
                continue
            bal = float(acc.get("currentBalance") or acc.get("current_balance") or acc.get("balance") or 0.0)
            name_lower = acc_name.lower()
            if "fund" in name_lower or "lbo" in name_lower or "buyout" in name_lower:
                category = "Private Equity / Buyout Fund"
            elif "angel" in name_lower or "syndicate" in name_lower or "spv" in name_lower:
                category = "Angel Syndicate / SPV"
            elif "real estate" in name_lower or "property" in name_lower:
                category = "Private Real Estate / Debt"
            else:
                category = "Venture Capital / Startup"

            inst = (
                (acc.get("credential") or {}).get("displayName")
                or (acc.get("institution") or {}).get("name")
                or ""
            ).strip()
            if not inst:
                inst = "Direct Holding / Manual" if acc.get("isManual") else "Synchronized Investment"

            items.append({
                "account_id": str(acc.get("id")),
                "name": acc_name,
                "current_value": round(bal, 2),
                "total_invested": round(bal, 2),
                "category": category,
                "institution": inst,
                "is_manual": bool(acc.get("isManual", False)),
            })

        items.sort(key=lambda x: x["current_value"], reverse=True)
        total_value = sum(x["current_value"] for x in items)

        for x in items:
            x["percentage"] = round((x["current_value"] / total_value * 100), 2) if total_value > 0 else 0.0

        return {
            "items": items,
            "total_value": round(total_value, 2),
            "total_invested": round(total_value, 2),
            "total_uncalled": 0.0,
            "total_unrealized_gain": 0.0,
            "holdings_count": len(items),
        }
    except Exception as e:
        logger.error("Error retrieving private investments: %s", e)
        return {
            "items": [],
            "total_invested": 0.0,
            "total_value": 0.0,
            "total_uncalled": 0.0,
            "total_unrealized_gain": 0.0,
            "error": str(e),
        }
