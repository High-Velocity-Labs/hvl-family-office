"""
SSR view-model builders for Balance Sheet Accounts, Multi-State Tax Arbitrage, and Compensation / Safe Harbor / IRS Transcripts.
"""

from __future__ import annotations
import logging

import db
import monarch_service
import security
from ssr.formatting import fmt_currency, fmt_short_currency

logger = logging.getLogger(__name__)


def _resolve_provider_flags(
    family_id: int = 0,
    monarch_count: int = 0,
    simplefin_count: int = 0,
    is_demo: bool | None = None,
) -> dict[str, bool]:
    """Determines whether Monarch Money and/or SimpleFIN Bridge are configured or active for a household."""
    from routes.helpers import _is_demo_session, get_current_db_path, get_current_universe
    eff_demo = _is_demo_session() if is_demo is None else bool(is_demo)
    has_monarch_creds = False
    has_simplefin_creds = False
    if family_id and family_id > 0 and not eff_demo:
        try:
            target_db = get_current_db_path(family_id=family_id)
            if target_db.exists():
                try:
                    m_creds = security.db_load_encrypted(target_db, "monarch_credentials", family_id=family_id) or {}
                    if isinstance(m_creds, dict) and (m_creds.get("token") or m_creds.get("email")):
                        has_monarch_creds = True
                except Exception:
                    pass
                if not has_monarch_creds and get_current_universe() == "public":
                    sess_file = monarch_service.get_family_session_file(family_id)
                    if sess_file and sess_file.exists():
                        has_monarch_creds = True
                try:
                    s_creds = security.db_load_encrypted(target_db, "simplefin_credentials", family_id=family_id) or {}
                    if isinstance(s_creds, dict) and s_creds.get("access_url"):
                        has_simplefin_creds = True
                except Exception:
                    pass
        except Exception:
            pass

    has_monarch = bool(has_monarch_creds)
    has_simplefin = bool(has_simplefin_creds)
    return {
        "has_monarch": has_monarch,
        "has_simplefin": has_simplefin,
        "has_any_sync_provider": bool(has_monarch or has_simplefin),
    }


def build_ssr_accounts(snapshot: dict, family_id: int = 0, is_demo: bool | None = None) -> dict:
    """Prepares structured SSR data for Accounts & Balance Sheet holdings."""
    if not snapshot:
        flags = _resolve_provider_flags(family_id=family_id, monarch_count=0, simplefin_count=0, is_demo=is_demo)
        return {
            "total_count": 0,
            "monarch_count": 0,
            "simplefin_count": 0,
            "manual_count": 0,
            "categories": [],
            "balance_history": [],
            **flags,
        }
    categories = snapshot.get("categories") or {}
    total_acc_count = sum(len(cat.get("accounts") or []) for cat in categories.values())
    monarch_count = 0
    simplefin_count = 0
    manual_count = 0

    rendered_categories = []
    for cat_key, cat in categories.items():
        acc_list = cat.get("accounts") or []
        if not acc_list:
            continue
        is_excluded = cat_key in ("company_equity_nso", "tax_liability", "hidden_from_family_office")
        tot = float(cat.get("total") or 0.0)
        acc_rows = []
        for a in acc_list:
            aid_str = str(a.get("id") or "")
            raw_prov = str(a.get("provider") or "").lower()
            if aid_str.startswith("sfin_") or raw_prov == "simplefin":
                prov = "simplefin"
                default_src = "SimpleFIN"
                simplefin_count += 1
            elif aid_str.startswith("monarch_") or raw_prov == "monarch":
                prov = "monarch"
                default_src = "Monarch Money"
                monarch_count += 1
            else:
                prov = "manual"
                default_src = "Manual"
                manual_count += 1
            acc_rows.append({
                "id": a.get("id"),
                "name": a.get("name") or a.get("raw_name") or "Account",
                "type": a.get("type") or "Account",
                "provider": prov,
                "source_label": a.get("source_label") or default_src,
                "institution": a.get("institution") or "",
                "balance_raw": float(a.get("balance") or 0.0),
                "balance_str": fmt_currency(float(a.get("balance") or 0.0), 2),
                "balance_color": "var(--status-red)" if float(a.get("balance") or 0.0) < 0 else "var(--text-primary)",
                "is_child_account": bool(a.get("is_child_account")),
                "is_fo_hidden": bool(a.get("is_fo_hidden")),
                "role": a.get("role"),
                "include_in_net_worth": bool(a.get("include_in_net_worth", True)),
            })
        rendered_categories.append({
            "key": cat_key, "label": cat.get("label") or cat_key, "is_excluded": is_excluded,
            "accounts": acc_rows, "total_str": fmt_currency(tot, 2),
            "total_color": "var(--status-red)" if tot < 0 else "var(--text-primary)",
        })

    flags = _resolve_provider_flags(
        family_id=family_id,
        monarch_count=monarch_count,
        simplefin_count=simplefin_count,
        is_demo=is_demo,
    )

    balance_history = []
    if family_id and family_id > 0:
        try:
            from routes.helpers import DB_PATH
            get_hist_fn = getattr(db.accounts, "get_account_balance_history", None)
            if callable(get_hist_fn):
                raw_hist = get_hist_fn(family_id=family_id, db_path=DB_PATH) or []
                for row in raw_hist:
                    if not isinstance(row, dict):
                        continue
                    bal_val = float(row.get("balance") or 0.0)
                    prov_str = str(row.get("provider") or "manual").lower()
                    if prov_str == "simplefin":
                        p_badge = "badge-green"
                        p_label = "SimpleFIN"
                    elif prov_str == "monarch":
                        p_badge = "badge-blue"
                        p_label = "Monarch"
                    else:
                        p_badge = "badge-purple"
                        p_label = "Manual"
                    balance_history.append({
                        **row,
                        "account_id": str(row.get("account_id") or ""),
                        "account_name": str(row.get("account_name") or row.get("name") or "Account"),
                        "date": str(row.get("date") or ""),
                        "balance_raw": bal_val,
                        "balance_str": fmt_currency(bal_val, 2),
                        "balance_color": "var(--status-red)" if bal_val < 0 else "var(--text-primary)",
                        "provider": prov_str,
                        "provider_badge": p_badge,
                        "provider_label": p_label,
                    })
        except Exception as exc:
            logger.debug("Could not load balance_history for SSR: %s", exc)

    sync_age_label = "--"
    sync_is_stale = False
    core_burn_preview = {}
    if family_id and family_id > 0:
        try:
            from datetime import datetime, timezone
            from routes.helpers import DB_PATH
            sync_meta = security.db_load_encrypted(DB_PATH, "last_sync_metadata", family_id=family_id) or {}
            raw_ts = sync_meta.get("timestamp") if isinstance(sync_meta, dict) else None
            if not raw_ts:
                raw_ts = snapshot.get("last_monarch_sync")
            if raw_ts and str(raw_ts).lower() != "never":
                raw_str = str(raw_ts).replace("Z", "+00:00")
                dt = datetime.fromisoformat(raw_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                diff_sec = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
                if diff_sec < 3600:
                    sync_age_label = f"{max(1, int(diff_sec / 60))}m ago"
                elif diff_sec < 86400:
                    sync_age_label = f"{int(diff_sec / 3600)}h ago"
                else:
                    days = int(diff_sec / 86400)
                    sync_age_label = f"{days}d ago"
                    if days >= 7:
                        sync_is_stale = True
        except Exception as exc:
            logger.debug("Could not compute sync freshness: %s", exc)

        try:
            from services.tax_checklist_service import compute_monarch_core_burn_calibration
            from routes.helpers import DB_PATH
            core_burn_preview = compute_monarch_core_burn_calibration(family_id=family_id, db_path=DB_PATH)
        except Exception as exc:
            logger.debug("Could not compute core_burn_preview: %s", exc)

    return {
        "total_count": total_acc_count,
        "monarch_count": monarch_count,
        "simplefin_count": simplefin_count,
        "manual_count": manual_count,
        "categories": rendered_categories,
        "balance_history": balance_history,
        "sync_age_label": sync_age_label,
        "sync_is_stale": sync_is_stale,
        "core_burn_preview": core_burn_preview,
        **flags,
    }


build_accounts_ssr_context = build_ssr_accounts



from ssr.arbitrage_ssr import build_ssr_arbitrage
from ssr.compensation_ssr import build_ssr_compensation

__all__ = [
    "build_ssr_accounts",
    "build_accounts_ssr_context",
    "build_ssr_arbitrage",
    "build_ssr_compensation",
    "_resolve_provider_flags",
]

