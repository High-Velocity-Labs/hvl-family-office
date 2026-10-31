"""
db/philanthropy.py: Normalized SQLAlchemy 2.0 ORM repository for charitable donations and annual budgets.
Operates on `PhilanthropyDonation` and `PhilanthropyBudget` with transparent `TypeDecorator` encryption
and automatic `after_commit` cache invalidation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, func, select

import config
from db.models import PhilanthropyBudget, PhilanthropyDonation
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def get_philanthropy_payload(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Reconstructs the philanthropy ledger payload from `philanthropy_donations`
    and `philanthropy_budgets`.
    """
    if not family_id:
        return {}
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return {}

    try:
        with get_orm_session(path, family_id=family_id) as session:
            b_rows = session.scalars(
                select(PhilanthropyBudget).where(PhilanthropyBudget.family_id == family_id).order_by(PhilanthropyBudget.tax_year.asc())
            ).all()
            d_rows = session.scalars(
                select(PhilanthropyDonation).where(PhilanthropyDonation.family_id == family_id)
                .order_by(PhilanthropyDonation.tax_year.desc(), PhilanthropyDonation.donation_id.asc())
            ).all()
            if not b_rows and not d_rows:
                return {}

            budgets_by_year: Dict[str, float] = {}
            default_budget: Optional[float] = None
            meta_dict: Dict[str, Any] = {}
            for br in b_rows:
                yr = int(br.tax_year)
                raw_val = br.budget_amount_enc or ""
                if yr == -1:
                    try:
                        loaded_meta = json.loads(raw_val)
                        if isinstance(loaded_meta, dict):
                            meta_dict = loaded_meta
                    except Exception:
                        meta_dict = {}
                elif yr == 0:
                    try:
                        default_budget = float(raw_val or 0.0)
                    except (ValueError, TypeError):
                        default_budget = 0.0
                else:
                    try:
                        budgets_by_year[str(yr)] = float(raw_val or 0.0)
                    except (ValueError, TypeError):
                        budgets_by_year[str(yr)] = 0.0

            donations_list_by_year: Dict[str, List[Dict[str, Any]]] = {}
            for dr in d_rows:
                yr_str = str(dr.tax_year)
                item: Dict[str, Any] = dict(dr.payload_enc) if isinstance(dr.payload_enc, dict) else {}
                item["date"] = str(dr.donation_date or item.get("date") or f"{yr_str}-12-15")
                if dr.organization_enc:
                    item["organization"] = str(dr.organization_enc)
                item["amount"] = float(dr.amount_enc or 0.0)
                if dr.description_enc:
                    item["description"] = str(dr.description_enc)
                donations_list_by_year.setdefault(yr_str, []).append(item)

            year_totals_override = meta_dict.get("year_totals") or {}
            all_years = sorted(
                set(
                    list(budgets_by_year.keys())
                    + list(donations_list_by_year.keys())
                    + list(year_totals_override.keys())
                ),
                reverse=True,
            )

            donations_by_year: Dict[str, Dict[str, Any]] = {}
            for yr_str in all_years:
                d_list = donations_list_by_year.get(yr_str, [])
                calc_tot = round(
                    sum(float(d.get("amount", 0.0) or 0.0) for d in d_list), 2
                )
                if d_list:
                    yr_tot = calc_tot
                elif yr_str in year_totals_override:
                    yr_tot = float(year_totals_override[yr_str] or 0.0)
                else:
                    yr_tot = calc_tot

                y_entry: Dict[str, Any] = {
                    "total": round(yr_tot, 2),
                    "donations": d_list,
                }
                if yr_str in budgets_by_year:
                    y_entry["budget"] = round(budgets_by_year[yr_str], 2)
                donations_by_year[yr_str] = y_entry

            calc_lifetime = round(
                sum(float(v.get("total", 0.0) or 0.0) for v in donations_by_year.values()),
                2,
            )
            stored_lifetime = float(meta_dict.get("total_lifetime_charity") or 0.0)
            total_lifetime = calc_lifetime if calc_lifetime > 0 else stored_lifetime
            if stored_lifetime > calc_lifetime and not d_rows:
                total_lifetime = stored_lifetime

            lifetime_history = list(meta_dict.get("lifetime_history") or [])
            for entry in lifetime_history:
                if not isinstance(entry, dict):
                    continue
                eyr = str(entry.get("year", ""))
                if eyr in donations_by_year and donations_by_year[eyr]["donations"]:
                    entry["total"] = donations_by_year[eyr]["total"]
                    entry["grant_count"] = len(donations_by_year[eyr]["donations"])
                if eyr in budgets_by_year:
                    entry["budget"] = budgets_by_year[eyr]

            out: Dict[str, Any] = {
                "total_lifetime_charity": round(total_lifetime, 2),
                "lifetime_history": lifetime_history,
                "donations_by_year": donations_by_year,
                "annual_budgets": budgets_by_year,
                "budgets_by_year": budgets_by_year,
            }
            if default_budget is not None:
                out["default_annual_budget"] = default_budget
            elif budgets_by_year:
                latest_b_yr = max(budgets_by_year.keys())
                out["default_annual_budget"] = budgets_by_year[latest_b_yr]
            return out
    except Exception as e:
        logger.warning(
            "Error reading philanthropy tables for family %s: %s", family_id, e
        )
        return {}


def save_philanthropy_payload(
    family_id: int = 0,
    payload: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Atomically writes a philanthropy payload into `philanthropy_budgets` and `philanthropy_donations`."""
    if not family_id or not isinstance(payload, dict):
        return

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        session.execute(
            delete(PhilanthropyBudget).where(PhilanthropyBudget.family_id == family_id)
        )
        session.execute(
            delete(PhilanthropyDonation).where(
                PhilanthropyDonation.family_id == family_id
            )
        )

        budget_rows: Dict[int, PhilanthropyBudget] = {}
        if payload.get("default_annual_budget") is not None:
            budget_rows[0] = PhilanthropyBudget(
                family_id=family_id, tax_year=0,
                budget_amount_enc=str(float(payload["default_annual_budget"] or 0.0)),
            )

        raw_budgets = dict(payload.get("annual_budgets") or payload.get("budgets_by_year") or {})
        donations_map = payload.get("donations_by_year") or {}
        year_totals: Dict[str, float] = {}

        for yr_str, y_val in donations_map.items():
            if isinstance(y_val, dict):
                if y_val.get("budget") is not None and str(yr_str) not in raw_budgets:
                    raw_budgets[str(yr_str)] = float(y_val["budget"] or 0.0)
                if y_val.get("total") is not None:
                    year_totals[str(yr_str)] = float(y_val["total"] or 0.0)

        meta_blob = {
            "total_lifetime_charity": float(payload.get("total_lifetime_charity") or 0.0),
            "lifetime_history": payload.get("lifetime_history") or [],
            "year_totals": year_totals,
        }
        budget_rows[-1] = PhilanthropyBudget(family_id=family_id, tax_year=-1, budget_amount_enc=json.dumps(meta_blob, default=str))

        for yr_str, b_amt in raw_budgets.items():
            if str(yr_str).isdigit():
                budget_rows[int(yr_str)] = PhilanthropyBudget(family_id=family_id, tax_year=int(yr_str), budget_amount_enc=str(float(b_amt or 0.0)))

        session.add_all(budget_rows.values())

        donation_rows: List[PhilanthropyDonation] = []
        for yr_str, y_val in donations_map.items():
            if not str(yr_str).isdigit():
                continue
            yr_int = int(yr_str)
            items = y_val.get("donations", []) if isinstance(y_val, dict) else (y_val if isinstance(y_val, list) else [])
            for d in items:
                if isinstance(d, dict):
                    donation_rows.append(PhilanthropyDonation(
                        family_id=family_id, tax_year=yr_int,
                        donation_date=str(d.get("date") or f"{yr_str}-12-15"),
                        organization_enc=str(d.get("organization") or ""),
                        amount_enc=float(d.get("amount", 0.0) or 0.0),
                        description_enc=str(d.get("description") or ""),
                        payload_enc=d,
                    ))
        if donation_rows:
            session.add_all(donation_rows)


def set_year_budget(
    family_id: int = 0,
    tax_year: int = 0,
    budget_amount: float = 0.0,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """Atomically upserts a single year's budget in `philanthropy_budgets`."""
    if not family_id or not tax_year:
        return

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        existing = session.get(PhilanthropyBudget, (family_id, int(tax_year)))
        if existing is None and int(tax_year) > 0:
            max_years = int(getattr(config, "MAX_PHILANTHROPY_YEARS", 50))
            current_count = int(session.scalar(
                select(func.count()).select_from(PhilanthropyBudget).where(
                    PhilanthropyBudget.family_id == family_id, PhilanthropyBudget.tax_year > 0
                )
            ) or 0)
            if current_count >= max_years:
                raise ValueError(f"Maximum of {max_years} philanthropy budget years per household reached.")

        session.merge(PhilanthropyBudget(family_id=family_id, tax_year=int(tax_year), budget_amount_enc=str(float(budget_amount))))


upsert_budget = set_year_budget


def add_donation(
    family_id: int = 0,
    tax_year: int = 0,
    donation: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Atomically inserts a single donation row into `philanthropy_donations`."""
    if not family_id or not tax_year or not isinstance(donation, dict):
        return 0

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        max_donations = int(getattr(config, "MAX_PHILANTHROPY_DONATIONS", 1000))
        current_count = int(session.scalar(
            select(func.count()).select_from(PhilanthropyDonation).where(PhilanthropyDonation.family_id == family_id)
        ) or 0)
        if current_count >= max_donations:
            raise ValueError(f"Maximum of {max_donations} charitable donations per household reached.")

        row = PhilanthropyDonation(
            family_id=family_id, tax_year=int(tax_year),
            donation_date=str(donation.get("date") or f"{tax_year}-12-15"),
            organization_enc=str(donation.get("organization") or ""),
            amount_enc=float(donation.get("amount", 0.0) or 0.0),
            description_enc=str(donation.get("description") or ""),
            payload_enc=donation,
        )
        session.add(row)
        session.flush()
        return int(row.donation_id or 0)


def update_donation_by_index(
    family_id: int = 0,
    tax_year: int = 0,
    index: int = 0,
    donation: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Atomically updates the N-th donation row for `(family_id, tax_year)`."""
    if (
        not family_id
        or not tax_year
        or not isinstance(donation, dict)
        or index is None
        or index < 0
    ):
        return None

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        rows = session.scalars(
            select(PhilanthropyDonation)
            .where(
                PhilanthropyDonation.family_id == family_id,
                PhilanthropyDonation.tax_year == int(tax_year),
            )
            .order_by(PhilanthropyDonation.donation_id.asc())
        ).all()
        if index >= len(rows):
            return None
        target = rows[index]
        target.donation_date = str(donation.get("date") or f"{tax_year}-12-15")
        target.organization_enc = str(donation.get("organization") or "")
        target.amount_enc = float(donation.get("amount", 0.0) or 0.0)
        target.description_enc = str(donation.get("description") or "")
        target.payload_enc = donation
        return dict(donation)


def delete_donation_by_index(
    family_id: int = 0,
    tax_year: int = 0,
    index: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Atomically deletes the N-th donation row for `(family_id, tax_year)` and returns its decrypted dict."""
    if not family_id or not tax_year or index is None or index < 0:
        return None

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        rows = session.scalars(
            select(PhilanthropyDonation)
            .where(
                PhilanthropyDonation.family_id == family_id,
                PhilanthropyDonation.tax_year == int(tax_year),
            )
            .order_by(PhilanthropyDonation.donation_id.asc())
        ).all()
        if index >= len(rows):
            return None
        target = rows[index]
        removed: Dict[str, Any] = (
            dict(target.payload_enc) if isinstance(target.payload_enc, dict) else {}
        )
        if "organization" not in removed and target.organization_enc:
            removed["organization"] = str(target.organization_enc)
        if "amount" not in removed and target.amount_enc:
            removed["amount"] = float(target.amount_enc or 0.0)
        session.delete(target)
        return removed
