"""
db/account_roles.py: Manual accounts and account role mapping repository.
Handles first-class manual accounts (`manual_*`), their roles, and role inspection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
import secrets
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, func, select

import config
from db.models import AccountRole, MonarchAccount, MonarchHolding
from db.session import get_orm_session, resolve_db_path
import security

logger = logging.getLogger(__name__)


def get_account_role(
    family_id: int = 0,
    account_id: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieves account role configuration for a specific account."""
    if not family_id or not account_id:
        return None
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return None
    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(AccountRole).where(
                AccountRole.family_id == family_id,
                AccountRole.monarch_account_id == str(account_id).strip(),
            )
            r = session.scalars(stmt).first()
            return r.to_dict() if r is not None else None
    except Exception as e:
        logger.warning("Error fetching account role for family %s: %s", family_id, e)
        return None


def get_account_roles(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all account roles configured for family_id."""
    if not family_id:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []
    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(AccountRole).where(AccountRole.family_id == family_id)
            return [r.to_dict() for r in session.scalars(stmt).all()]
    except Exception as e:
        logger.warning("Error fetching account roles for family %s: %s", family_id, e)
        return []


def upsert_manual_account(
    family_id: int = 0,
    account_id: Optional[str] = None,
    display_name: str = "",
    balance: float = 0.0,
    role: str = "cash_liquid",
    institution_name: str = "Manual Entry",
    beneficiary_user_id: Optional[int] = None,
    include_in_net_worth: bool = True,
    minimum_payment: float = 0.0,
    interest_rate: float = 0.0,
    db_path: Optional[Union[str, Path]] = None,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates or updates a first-class manual account (`manual_<id>`) and its confirmed `AccountRole`."""
    from db.balance_history import (
        ROLE_TO_ACCOUNT_TYPE_MAP as _ROLE_TO_ACCOUNT_TYPE_MAP,
        load_balance_history_map as _load_balance_history_map,
        normalize_date_str as _normalize_date_str,
        rebuild_historical_net_worth_from_snapshots,
        save_balance_history_map as _save_balance_history_map,
    )
    from monarch.categorizer import ROLE_ALIASES

    if not family_id or family_id <= 0:
        raise ValueError("Valid family_id > 0 is required to upsert a manual account.")

    raw_id = (account_id or "").strip()
    clean_id = (raw_id if raw_id.startswith("manual_") else f"manual_{raw_id}") if raw_id else f"manual_{secrets.token_hex(4)}"

    norm_role = ROLE_ALIASES.get(str(role or "cash_liquid").strip(), str(role or "cash_liquid").strip())
    acc_type, subtype = _ROLE_TO_ACCOUNT_TYPE_MAP.get(norm_role, ("other_asset", "other"))

    eff_balance = float(balance or 0.0)
    if norm_role in ("mortgages", "credit_cards") and eff_balance > 0:
        eff_balance = -abs(eff_balance)

    clean_name = (display_name or "Manual Account").strip()
    clean_inst = (institution_name or "Manual Entry").strip()
    inc_nw = 1 if include_in_net_worth else 0
    snap_date = _normalize_date_str(as_of_date) or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    path = resolve_db_path(db_path, family_id=family_id)
    security.init_db(path)

    history_map = _load_balance_history_map(family_id=family_id, db_path=path)
    acc_hist = history_map.get(clean_id, {})
    latest_recorded_date = max(acc_hist.keys()) if acc_hist else None
    is_latest_snapshot = (latest_recorded_date is None) or (snap_date >= latest_recorded_date)

    with get_orm_session(path, family_id=family_id, commit=True) as session:
        existing = session.get(MonarchAccount, (family_id, clean_id))
        if existing is not None and not is_latest_snapshot:
            active_current_balance = float(
                existing.current_balance_enc
                if existing.current_balance_enc is not None
                else acc_hist.get(latest_recorded_date, eff_balance)
            )
        else:
            active_current_balance = eff_balance

        payload: Dict[str, Any] = {
            "id": clean_id,
            "displayName": clean_name,
            "currentBalance": active_current_balance,
            "type": {"name": acc_type, "display": acc_type.replace("_", " ").title()},
            "subtype": {"name": subtype, "display": subtype.replace("_", " ").title()},
            "institution": {"name": clean_inst},
            "credential": {"displayName": clean_inst},
            "isManual": True,
            "includeInNetWorth": bool(include_in_net_worth),
            "includeBalanceInNetWorth": bool(include_in_net_worth),
            "isHidden": False,
            "provider": "manual",
            "source_label": "Manual",
            "role": norm_role,
            "minimumPayment": float(minimum_payment or 0.0),
            "interestRate": float(interest_rate or 0.0),
            "as_of_date": snap_date,
        }

        if existing is not None:
            existing.display_name_enc = clean_name
            if is_latest_snapshot:
                existing.current_balance_enc = eff_balance
            existing.account_type = acc_type
            existing.subtype = subtype
            existing.institution_name_enc = clean_inst
            existing.is_manual = 1
            existing.include_in_net_worth = inc_nw
            existing.is_hidden = 0
            existing.payload_enc = payload
        else:
            current_count = int(
                session.scalar(
                    select(func.count()).select_from(MonarchAccount).where(MonarchAccount.family_id == family_id)
                )
                or 0
            )
            if current_count >= config.MAX_HOUSEHOLD_ACCOUNTS:
                raise ValueError(f"Maximum of {config.MAX_HOUSEHOLD_ACCOUNTS} accounts per household reached.")
            session.add(
                MonarchAccount(
                    family_id=family_id,
                    account_id=clean_id,
                    display_name_enc=clean_name,
                    current_balance_enc=active_current_balance,
                    account_type=acc_type,
                    subtype=subtype,
                    institution_name_enc=clean_inst,
                    is_manual=1,
                    include_in_net_worth=inc_nw,
                    is_hidden=0,
                    payload_enc=payload,
                )
            )

        role_row = session.scalars(
            select(AccountRole).where(
                AccountRole.family_id == family_id,
                AccountRole.monarch_account_id == clean_id,
            )
        ).first()
        is_hidden_fo = 1 if norm_role in ("company_equity_nso", "tax_liability", "hidden_from_family_office") else 0
        if role_row is not None:
            role_row.role = norm_role
            role_row.beneficiary_user_id = beneficiary_user_id
            role_row.is_user_confirmed = 1
            role_row.is_hidden_from_family_office = is_hidden_fo
        else:
            session.add(
                AccountRole(
                    family_id=family_id,
                    monarch_account_id=clean_id,
                    role=norm_role,
                    beneficiary_user_id=beneficiary_user_id,
                    is_user_confirmed=1,
                    is_hidden_from_family_office=is_hidden_fo,
                )
            )

    try:
        history_map.setdefault(clean_id, {})[snap_date] = eff_balance
        _save_balance_history_map(family_id=family_id, history_map=history_map, db_path=path)
        rebuild_historical_net_worth_from_snapshots(family_id=family_id, db_path=path)
    except Exception as exc:
        logger.debug("Balance history update skipped on upsert_manual_account for family %s: %s", family_id, exc)

    return payload


def delete_manual_account(
    family_id: int = 0,
    account_id: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Deletes a manual account (`manual_*`) and its associated holdings, role mapping, and balance history."""
    from db.balance_history import (
        load_balance_history_map as _load_balance_history_map,
        rebuild_historical_net_worth_from_snapshots,
        save_balance_history_map as _save_balance_history_map,
    )

    clean_id = (account_id or "").strip()
    if not family_id or family_id <= 0 or not clean_id.startswith("manual_"):
        return False

    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return False

    with get_orm_session(path, family_id=family_id, commit=True) as session:
        res = session.execute(
            delete(MonarchAccount).where(
                MonarchAccount.family_id == family_id,
                MonarchAccount.account_id == clean_id,
            )
        )
        session.execute(
            delete(MonarchHolding).where(
                MonarchHolding.family_id == family_id,
                MonarchHolding.account_id == clean_id,
            )
        )
        session.execute(
            delete(AccountRole).where(
                AccountRole.family_id == family_id,
                AccountRole.monarch_account_id == clean_id,
            )
        )
        deleted = bool((res.rowcount or 0) > 0)

    if deleted:
        try:
            history_map = _load_balance_history_map(family_id=family_id, db_path=path)
            if clean_id in history_map:
                history_map.pop(clean_id, None)
                _save_balance_history_map(family_id=family_id, history_map=history_map, db_path=path)
            rebuild_historical_net_worth_from_snapshots(family_id=family_id, db_path=path)
        except Exception:
            pass
    return deleted
