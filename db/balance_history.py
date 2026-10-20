"""
db/balance_history.py: Per-Account Dated Balance History, Carry-Forward / Linear Interpolation
Net Worth Timeline Builder, and CSV Import / Export Repository.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select

from db.balance_history_csv import (
    ROLE_TO_ACCOUNT_TYPE_MAP,
    export_balances_csv,
    infer_role_from_account_name,
    normalize_date_str,
    parse_and_import_balance_csv,
    parse_currency_float,
)
from db.models import AccountRole, MonarchAccount
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def load_roles_map_for_path(family_id: int, path: Path) -> Dict[str, tuple[str, bool]]:
    """Loads `{monarch_account_id: (normalized_role, is_hidden_from_fo)}` directly from `path`."""
    from monarch.categorizer import ROLE_ALIASES

    roles_cache: Dict[str, tuple[str, bool]] = {}
    if not family_id or not path.exists():
        return roles_cache
    try:
        with get_orm_session(path, family_id=family_id) as session:
            for r in session.scalars(select(AccountRole).where(AccountRole.family_id == family_id)).all():
                if aid := str(r.monarch_account_id or "").strip():
                    raw_r = str(r.role or "").strip()
                    roles_cache[aid] = (ROLE_ALIASES.get(raw_r, raw_r), bool(r.is_hidden_from_family_office or 0))
    except Exception:
        pass
    return roles_cache


def load_balance_history_map(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, float]]:
    """Loads `{account_id: {"YYYY-MM-DD": float_balance}}` from `family_encrypted_store`."""
    if not family_id or family_id <= 0:
        return {}
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return {}
    import security
    raw = security.db_load_encrypted(path, "account_balance_history", family_id=family_id)
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Dict[str, float]] = {}
    for acc_id, dates_dict in raw.items():
        if isinstance(dates_dict, dict):
            norm_dates = {
                nd: round(fv, 2)
                for d_str, bal_val in dates_dict.items()
                if (nd := normalize_date_str(d_str)) and (fv := parse_currency_float(bal_val)) is not None
            }
            if norm_dates:
                cleaned[str(acc_id)] = dict(sorted(norm_dates.items()))
    return cleaned


def save_balance_history_map(
    family_id: int = 0,
    history_map: Optional[Dict[str, Dict[str, float]]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Persists `{account_id: {"YYYY-MM-DD": float_balance}}` into `family_encrypted_store`."""
    if not family_id or family_id <= 0:
        return
    path = resolve_db_path(db_path, family_id=family_id)
    import security
    security.init_db(path)
    clean_out: Dict[str, Dict[str, float]] = {}
    for acc_id, dates_dict in (history_map or {}).items():
        if isinstance(dates_dict, dict) and dates_dict:
            clean_out[str(acc_id)] = {
                str(k): round(float(v), 2)
                for k, v in sorted(dates_dict.items())
                if k and v is not None
            }
    security.db_save_encrypted(path, "account_balance_history", "balance_history", clean_out, family_id=family_id)
    try:
        from db import store as db_store
        db_store.invalidate_family(family_id, db_path=path)
    except Exception:
        pass


def record_account_balance_snapshots(
    family_id: int = 0,
    snapshots: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Records one or more dated account balance snapshots. Matches existing accounts by `account_id`
    or case-insensitive `displayName`, or creates a new manual account (`manual_<hex>`) if no match exists.
    """
    from db import accounts as db_accounts

    if not family_id or family_id <= 0:
        return {"success": False, "recorded_count": 0, "accounts_affected": 0, "years_covered": [], "historical_net_worth": []}

    path = resolve_db_path(db_path, family_id=family_id)
    import security
    security.init_db(path)

    existing_accounts = db_accounts.list_accounts(family_id=family_id, db_path=path)
    roles_cache = load_roles_map_for_path(family_id, path)

    by_id: Dict[str, Dict[str, Any]] = {str(a["id"]): a for a in existing_accounts if a.get("id")}
    by_name_lower: Dict[str, Dict[str, Any]] = {
        str(a.get("displayName") or a.get("name") or "").strip().lower(): a
        for a in existing_accounts if (a.get("displayName") or a.get("name"))
    }

    history_map = load_balance_history_map(family_id=family_id, db_path=path)
    recorded_count = 0
    affected_accounts: set[str] = set()

    for item in snapshots or []:
        if not isinstance(item, dict):
            continue
        snap_date = normalize_date_str(item.get("date") or item.get("as_of_date"))
        if not snap_date:
            continue
        raw_bal = item.get("balance") if item.get("balance") is not None else item.get("amount", item.get("value"))
        bal = parse_currency_float(raw_bal)
        if bal is None:
            continue

        raw_acc_id = str(item.get("account_id") or item.get("id") or "").strip()
        raw_name = str(item.get("account_name") or item.get("name") or item.get("displayName") or "").strip()
        raw_role = str(item.get("role") or item.get("type") or "").strip()
        raw_inst = str(item.get("institution") or "").strip()
        inc_nw_raw = item.get("include_in_net_worth", item.get("includeInNetWorth", True))
        inc_nw_bool = inc_nw_raw.strip().lower() not in ("false", "0", "no", "n") if isinstance(inc_nw_raw, str) else bool(inc_nw_raw)

        target_acc: Optional[Dict[str, Any]] = None
        if raw_acc_id:
            for candidate_id in (raw_acc_id, f"manual_{raw_acc_id}", f"sfin_{raw_acc_id}"):
                if candidate_id in by_id:
                    target_acc = by_id[candidate_id]
                    break
        if target_acc is None and raw_name and raw_name.lower() in by_name_lower:
            target_acc = by_name_lower[raw_name.lower()]

        if target_acc is None:
            inferred_role = infer_role_from_account_name(raw_name or raw_acc_id, raw_role=raw_role, balance=bal)
            created_acc = db_accounts.upsert_manual_account(
                family_id=family_id,
                account_id=raw_acc_id if raw_acc_id.startswith("manual_") else None,
                display_name=raw_name or raw_acc_id or "Manual Account",
                balance=bal,
                role=inferred_role,
                institution_name=raw_inst or "Manual Entry",
                include_in_net_worth=inc_nw_bool,
                db_path=path,
                as_of_date=snap_date,
            )
            acc_id = str(created_acc["id"])
            by_id[acc_id] = created_acc
            by_name_lower[str(created_acc.get("displayName") or "").strip().lower()] = created_acc
            roles_cache[acc_id] = (inferred_role, inferred_role in ("company_equity_nso", "tax_liability", "hidden_from_family_office"))
            eff_bal = -abs(bal) if (inferred_role in ("mortgages", "credit_cards") and bal > 0) else bal
            history_map.setdefault(acc_id, {})[snap_date] = round(eff_bal, 2)
            recorded_count += 1
            affected_accounts.add(acc_id)
            continue

        acc_id = str(target_acc["id"])
        acc_role = roles_cache.get(acc_id, (str(target_acc.get("role") or ""), False))[0] or infer_role_from_account_name(
            str(target_acc.get("displayName") or target_acc.get("name") or ""), raw_role=raw_role, balance=bal
        )
        eff_bal = -abs(bal) if (acc_role in ("mortgages", "credit_cards") and bal > 0) else bal
        history_map.setdefault(acc_id, {})[snap_date] = round(eff_bal, 2)
        recorded_count += 1
        affected_accounts.add(acc_id)

    if affected_accounts:
        with get_orm_session(path, family_id=family_id, commit=True) as session:
            for acc_id in affected_accounts:
                acc_dates = history_map.get(acc_id) or {}
                if not acc_dates:
                    continue
                latest_d = max(acc_dates.keys())
                latest_bal = float(acc_dates[latest_d])
                row = session.get(MonarchAccount, (family_id, acc_id))
                if row is not None:
                    row.current_balance_enc = latest_bal
                    payload = dict(row.payload_enc) if isinstance(row.payload_enc, dict) else {}
                    payload.update({"currentBalance": latest_bal, "displayBalance": latest_bal, "balance": latest_bal, "as_of_date": latest_d})
                    row.payload_enc = payload

        save_balance_history_map(family_id=family_id, history_map=history_map, db_path=path)

    nw_series = rebuild_historical_net_worth_from_snapshots(family_id=family_id, db_path=path)
    years_covered = sorted(
        {int(d[:4]) for acc_d in history_map.values() for d in acc_d.keys() if len(d) >= 4 and d[:4].isdigit()}
        | {int(row["year"]) for row in nw_series if isinstance(row, dict) and row.get("year")}
    )
    return {
        "success": True,
        "recorded_count": recorded_count,
        "accounts_affected": len(affected_accounts),
        "years_covered": years_covered,
        "historical_net_worth": nw_series,
    }


def get_account_balance_history(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns a sorted list of historical balance snapshot entries across all household accounts."""
    from db import accounts as db_accounts
    from monarch.categorizer import categorize_account

    if not family_id or family_id <= 0:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    accounts = db_accounts.list_accounts(family_id=family_id, db_path=path)
    roles_cache = load_roles_map_for_path(family_id, path)
    history_map = load_balance_history_map(family_id=family_id, db_path=path)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    acc_meta: Dict[str, Dict[str, Any]] = {}
    for acc in accounts:
        aid = str(acc.get("id") or "")
        if not aid:
            continue
        raw_prov = str(acc.get("provider") or "").lower()
        prov = "manual" if (aid.startswith("manual_") or raw_prov == "manual") else ("simplefin" if (aid.startswith("sfin_") or raw_prov == "simplefin") else "monarch")
        src_label = "Manual" if prov == "manual" else ("SimpleFIN" if prov == "simplefin" else "Monarch Money")

        inst_obj, cred_obj = acc.get("institution"), acc.get("credential")
        inst_name = (
            (inst_obj.get("name") if isinstance(inst_obj, dict) else str(inst_obj or ""))
            or (cred_obj.get("displayName") if isinstance(cred_obj, dict) else "")
            or "Manual Entry"
        ).strip()
        role_str = roles_cache.get(aid, ("", False))[0] or str(acc.get("role") or "") or categorize_account(acc, family_id=family_id, roles_cache=roles_cache, family_comps=[])
        inc_nw = bool(acc.get("includeInNetWorth", True) and acc.get("includeBalanceInNetWorth", True))
        name_str = str(acc.get("displayName") or acc.get("name") or aid).strip()

        acc_meta[aid] = {
            "account_id": aid, "account_name": name_str, "name": name_str,
            "provider": prov, "source_label": src_label, "role": role_str,
            "institution": inst_name, "include_in_net_worth": inc_nw,
            "current_balance": float(acc.get("currentBalance", acc.get("balance", 0.0)) or 0.0),
            "as_of_date": str(acc.get("as_of_date") or today_str),
        }

    entries: List[Dict[str, Any]] = []
    seen_acc_ids: set[str] = set()

    for aid, dates_dict in history_map.items():
        if not isinstance(dates_dict, dict):
            continue
        meta = acc_meta.get(aid, {
            "account_id": aid, "account_name": aid, "name": aid,
            "provider": "manual" if aid.startswith("manual_") else ("simplefin" if aid.startswith("sfin_") else "monarch"),
            "source_label": "Manual" if aid.startswith("manual_") else ("SimpleFIN" if aid.startswith("sfin_") else "Monarch Money"),
            "role": "cash_liquid", "institution": "Manual Entry", "include_in_net_worth": True,
        })
        seen_acc_ids.add(aid)
        for d_str, bal_val in dates_dict.items():
            entries.append({
                "account_id": aid, "account_name": meta["account_name"], "name": meta["account_name"],
                "provider": meta["provider"], "source_label": meta["source_label"], "role": meta["role"],
                "institution": meta["institution"], "date": str(d_str), "as_of_date": str(d_str),
                "balance": round(float(bal_val), 2), "include_in_net_worth": meta["include_in_net_worth"],
            })

    for aid, meta in acc_meta.items():
        if aid not in seen_acc_ids:
            entries.append({
                "account_id": aid, "account_name": meta["account_name"], "name": meta["account_name"],
                "provider": meta["provider"], "source_label": meta["source_label"], "role": meta["role"],
                "institution": meta["institution"], "date": meta["as_of_date"], "as_of_date": meta["as_of_date"],
                "balance": round(meta["current_balance"], 2), "include_in_net_worth": meta["include_in_net_worth"],
            })

    entries.sort(key=lambda x: (x["date"], x["account_name"].lower()), reverse=True)
    return entries


def delete_account_balance_snapshot(
    family_id: int = 0,
    account_id: str = "",
    date_str: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Deletes a specific `(account_id, date_str)` snapshot for corrections and refreshes `"historical_net_worth"`."""
    if not family_id or family_id <= 0 or not account_id or not date_str:
        return False
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return False

    clean_id = str(account_id).strip()
    norm_date = normalize_date_str(date_str) or str(date_str).strip()
    history_map = load_balance_history_map(family_id=family_id, db_path=path)
    acc_dates = history_map.get(clean_id)
    if not isinstance(acc_dates, dict):
        return False

    removed = False
    for candidate_key in (norm_date, str(date_str).strip()):
        if candidate_key in acc_dates:
            acc_dates.pop(candidate_key, None)
            removed = True
            break
    if not removed:
        return False

    if acc_dates:
        latest_d = max(acc_dates.keys())
        latest_bal = float(acc_dates[latest_d])
        try:
            with get_orm_session(path, family_id=family_id, commit=True) as session:
                row = session.get(MonarchAccount, (family_id, clean_id))
                if row is not None:
                    row.current_balance_enc = latest_bal
                    payload = dict(row.payload_enc) if isinstance(row.payload_enc, dict) else {}
                    payload.update({"currentBalance": latest_bal, "displayBalance": latest_bal, "balance": latest_bal, "as_of_date": latest_d})
                    row.payload_enc = payload
        except Exception:
            pass
    else:
        history_map.pop(clean_id, None)

    save_balance_history_map(family_id=family_id, history_map=history_map, db_path=path)
    rebuild_historical_net_worth_from_snapshots(family_id=family_id, db_path=path)
    return True


from db.balance_history_helpers import (
    _load_snapshot_eval_context,
    _sum_buckets_at_date,
    build_dated_net_worth_series,
    interpolate_account_balance_at_date,
    rebuild_historical_net_worth_from_snapshots,
)

__all__ = [
    "ROLE_TO_ACCOUNT_TYPE_MAP",
    "normalize_date_str",
    "parse_currency_float",
    "load_balance_history_map",
    "save_balance_history_map",
    "interpolate_account_balance_at_date",
    "infer_role_from_account_name",
    "load_roles_map_for_path",
    "record_account_balance_snapshots",
    "get_account_balance_history",
    "delete_account_balance_snapshot",
    "_load_snapshot_eval_context",
    "_sum_buckets_at_date",
    "rebuild_historical_net_worth_from_snapshots",
    "build_dated_net_worth_series",
    "parse_and_import_balance_csv",
    "export_balances_csv",
]
