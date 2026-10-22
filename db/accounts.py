"""
db/accounts.py: Normalized SQLAlchemy 2.0 ORM repository for Monarch Money accounts and holdings.
Operates on `MonarchAccount` and `MonarchHolding` models with transparent `TypeDecorator` encryption.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, select, text

from db.models import AccountRole, MonarchAccount, MonarchHolding
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def list_accounts(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns decrypted list of Monarch account dicts for a family from `monarch_accounts`."""
    if not family_id:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(MonarchAccount).where(MonarchAccount.family_id == family_id).order_by(text("rowid ASC"))
            return [r.to_dict() for r in session.scalars(stmt).all()]
    except Exception as e:
        logger.warning("Error reading monarch_accounts for family %s: %s", family_id, e)
        return []


def replace_accounts(
    family_id: int = 0,
    accounts: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[Union[str, Path]] = None,
    provider: Optional[str] = None,
    as_of_date: Optional[str] = None,
) -> None:
    """Atomically replaces `monarch_accounts` rows for a family (optionally scoped by provider: 'monarch' or 'simplefin')."""
    if not family_id:
        return

    from datetime import datetime, timezone
    from sqlalchemy import func
    import config

    norm_provider = str(provider or "").strip().lower() or None
    path = resolve_db_path(db_path, family_id=family_id)

    with get_orm_session(path, family_id=family_id, commit=True) as session:
        del_stmt = delete(MonarchAccount).where(MonarchAccount.family_id == family_id)
        if norm_provider == "simplefin":
            del_stmt = del_stmt.where(MonarchAccount.account_id.like("sfin_%"))
        elif norm_provider == "manual":
            del_stmt = del_stmt.where(MonarchAccount.account_id.like("manual_%"))
        elif norm_provider == "monarch":
            del_stmt = del_stmt.where(~MonarchAccount.account_id.like("sfin_%"), ~MonarchAccount.account_id.like("manual_%"))
        session.execute(del_stmt)

        remaining_count = int(
            session.scalar(select(func.count()).select_from(MonarchAccount).where(MonarchAccount.family_id == family_id)) or 0
        )
        max_to_insert = max(0, config.MAX_HOUSEHOLD_ACCOUNTS - remaining_count)

        by_id: Dict[str, MonarchAccount] = {}
        for idx, acc in enumerate(accounts or []):
            if len(by_id) >= max_to_insert:
                break
            if not isinstance(acc, dict):
                continue
            acc_id = str(acc.get("id") or f"acc_{idx}")
            display_name = str(acc.get("displayName") or acc.get("name") or "")
            bal = float(acc.get("currentBalance", acc.get("displayBalance", acc.get("balance", 0.0))) or 0.0)
            acc_type_obj = acc.get("type")
            acc_type = str(acc_type_obj.get("name") if isinstance(acc_type_obj, dict) else (acc_type_obj or ""))
            sub_obj = acc.get("subtype")
            subtype = str(sub_obj.get("name") if isinstance(sub_obj, dict) else (sub_obj or ""))
            inst_obj, cred_obj = acc.get("institution"), acc.get("credential")
            inst_name = str(
                inst_obj.get("name")
                if isinstance(inst_obj, dict)
                else (inst_obj or (cred_obj.get("displayName") if isinstance(cred_obj, dict) else "") or "")
            )
            is_manual = 1 if (acc.get("isManual") or acc_id.startswith("manual_")) else 0
            inc_nw = 1 if acc.get("includeInNetWorth", True) and acc.get("includeBalanceInNetWorth", True) else 0
            is_hidden = 1 if acc.get("isHidden", False) else 0

            payload = dict(acc)
            raw_prov = str(payload.get("provider") or "").lower()
            if norm_provider == "manual" or acc_id.startswith("manual_") or raw_prov == "manual":
                inferred_prov, inferred_label = "manual", "Manual"
            elif norm_provider == "simplefin" or acc_id.startswith("sfin_") or raw_prov == "simplefin":
                inferred_prov, inferred_label = "simplefin", "SimpleFIN"
            else:
                inferred_prov, inferred_label = "monarch", "Monarch Money"
            payload.setdefault("provider", inferred_prov)
            payload.setdefault("source_label", inferred_label)

            by_id[acc_id] = MonarchAccount(
                family_id=family_id,
                account_id=acc_id,
                display_name_enc=display_name,
                current_balance_enc=bal,
                account_type=acc_type,
                subtype=subtype,
                institution_name_enc=inst_name,
                is_manual=is_manual,
                include_in_net_worth=inc_nw,
                is_hidden=is_hidden,
                payload_enc=payload,
            )
        if by_id:
            session.add_all(by_id.values())

    try:
        snap_date = _normalize_date_str(as_of_date) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        history_map = _load_balance_history_map(family_id=family_id, db_path=path)
        changed = False
        if not by_id and norm_provider == "simplefin":
            for k in [aid for aid in list(history_map.keys()) if str(aid).startswith("sfin_")]:
                history_map.pop(k, None)
                changed = True
        for acc_id, acc_row in by_id.items():
            history_map.setdefault(acc_id, {})[snap_date] = float(acc_row.current_balance_enc or 0.0)
            changed = True
        if changed:
            _save_balance_history_map(family_id=family_id, history_map=history_map, db_path=path)
            rebuild_historical_net_worth_from_snapshots(family_id=family_id, db_path=path)
    except Exception as exc:
        logger.debug("Balance history snapshot skipped on replace_accounts for family %s: %s", family_id, exc)


def toggle_account_net_worth(
    family_id: int = 0,
    account_id: str = "",
    include: bool = True,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[str]:
    """
    Atomically updates a single account row's `include_in_net_worth` flag in `monarch_accounts`.
    Returns the account's `displayName` if found and updated, or `None` if not found.
    """
    if not family_id or not account_id:
        return None
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return None

    with get_orm_session(path, family_id=family_id, commit=True) as session:
        row = session.get(MonarchAccount, (family_id, str(account_id)))
        if not row:
            return None

        display_name = row.display_name_enc or str(account_id)
        payload: Dict[str, Any] = dict(row.payload_enc) if isinstance(row.payload_enc, dict) else {}
        payload["includeInNetWorth"] = bool(include)
        payload["includeBalanceInNetWorth"] = bool(include)
        row.include_in_net_worth = 1 if include else 0
        row.payload_enc = payload
        return str(display_name)


def get_holdings_by_account(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Returns `{account_id: [holding_dict, ...]}` for a family from `monarch_holdings`."""
    if not family_id:
        return {}
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return {}

    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(MonarchHolding).where(MonarchHolding.family_id == family_id).order_by(MonarchHolding.holding_id.asc())
            out: Dict[str, List[Dict[str, Any]]] = {}
            for r in session.scalars(stmt).all():
                if isinstance(r.payload_enc, dict) and r.payload_enc:
                    out.setdefault(str(r.account_id), []).append(dict(r.payload_enc))
            return out
    except Exception as e:
        logger.warning("Error reading monarch_holdings for family %s: %s", family_id, e)
        return {}


def replace_holdings(
    family_id: int = 0,
    holdings_by_account: Optional[Union[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]] = None,
    db_path: Optional[Union[str, Path]] = None,
    provider: Optional[str] = None,
    holdings: Optional[Union[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]] = None,
) -> None:
    """Atomically replaces `monarch_holdings` rows for a family (optionally scoped by provider: 'monarch' or 'simplefin')."""
    if not family_id:
        return

    from sqlalchemy import func
    import config

    norm_provider = str(provider or "").strip().lower() or None
    source_holdings = holdings_by_account if holdings_by_account is not None else holdings
    normalized_by_acc: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(source_holdings, dict):
        normalized_by_acc = source_holdings
    elif isinstance(source_holdings, list):
        for item in source_holdings:
            if isinstance(item, dict):
                normalized_by_acc.setdefault(str(item.get("account_id") or "default"), []).append(item)

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        del_stmt = delete(MonarchHolding).where(MonarchHolding.family_id == family_id)
        if norm_provider == "simplefin":
            del_stmt = del_stmt.where(MonarchHolding.account_id.like("sfin_%"))
        elif norm_provider == "manual":
            del_stmt = del_stmt.where(MonarchHolding.account_id.like("manual_%"))
        elif norm_provider == "monarch":
            del_stmt = del_stmt.where(~MonarchHolding.account_id.like("sfin_%"), ~MonarchHolding.account_id.like("manual_%"))
        session.execute(del_stmt)

        remaining_count = int(
            session.scalar(select(func.count()).select_from(MonarchHolding).where(MonarchHolding.family_id == family_id)) or 0
        )

        new_rows: List[MonarchHolding] = []
        for acc_id, nodes in normalized_by_acc.items():
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                sec = node.get("security") if isinstance(node.get("security"), dict) else {}
                ticker_val = str(sec.get("ticker") or node.get("ticker") or "")
                sec_name_val = str(sec.get("name") or node.get("name") or node.get("security_name") or "")
                tot_val = float(node.get("totalValue", node.get("total_value", 0.0)) or 0.0)
                qty_val = float(node.get("quantity", 0.0) or 0.0)
                norm_node = dict(node)
                norm_node.setdefault("totalValue", tot_val)
                norm_node.setdefault("total_value", tot_val)
                norm_node.setdefault("name", sec_name_val)
                norm_node.setdefault("security_name", sec_name_val)
                norm_node.setdefault("ticker", ticker_val)
                if qty_val > 0:
                    norm_node.setdefault("quantity", qty_val)
                new_rows.append(
                    MonarchHolding(
                        family_id=family_id,
                        account_id=str(acc_id),
                        ticker_enc=ticker_val,
                        security_name_enc=sec_name_val,
                        quantity_enc=qty_val,
                        total_value_enc=tot_val,
                        basis_enc=float(node.get("basis", 0.0) or 0.0),
                        payload_enc=norm_node,
                    )
                )
        if remaining_count + len(new_rows) > config.MAX_HOUSEHOLD_HOLDINGS:
            raise ValueError(f"Maximum of {config.MAX_HOUSEHOLD_HOLDINGS} holdings per household reached.")
        if new_rows:
            session.add_all(new_rows)


from db.balance_history import (
    ROLE_TO_ACCOUNT_TYPE_MAP as _ROLE_TO_ACCOUNT_TYPE_MAP,
    build_dated_net_worth_series,
    delete_account_balance_snapshot,
    export_balances_csv,
    get_account_balance_history,
    infer_role_from_account_name as _infer_role_from_account_name,
    interpolate_account_balance_at_date as _interpolate_account_balance_at_date,
    load_balance_history_map as _load_balance_history_map,
    load_roles_map_for_path as _load_roles_map_for_path,
    normalize_date_str as _normalize_date_str,
    parse_and_import_balance_csv,
    parse_currency_float as _parse_currency_float,
    rebuild_historical_net_worth_from_snapshots,
    record_account_balance_snapshots,
    save_balance_history_map as _save_balance_history_map,
)


from db.account_roles import (
    delete_manual_account,
    get_account_role,
    get_account_roles,
    upsert_manual_account,
)

save_accounts = replace_accounts
save_holdings = replace_holdings




