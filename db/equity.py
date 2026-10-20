"""
Repository for Equity entities (`equity_companies`, `equity_grants`, `fmv_history` tables).
Uses SQLAlchemy 2.0 ORM (`EquityCompany`, `EquityGrantRecord`, `FmvHistoryRecord`) with transparent
`TypeDecorator` column encryption and automatic `after_commit` cache invalidation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import delete, func, select

import config
from db.models import EquityCompany, EquityGrantRecord, FmvHistoryRecord
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def get_or_create_primary_company(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Tuple[int, str, float, str]:
    """
    Fetches the primary company record or creates a default one if none exists.
    Returns `(company_id, company_name, current_fmv, fmv_date)`.
    """
    if not family_id:
        return 0, "Company", 0.0, ""

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        comp = session.scalars(
            select(EquityCompany).where(EquityCompany.family_id == family_id).order_by(EquityCompany.company_id.asc()).limit(1)
        ).first()
        if comp is not None:
            return comp.company_id, comp.company_name or "Company", float(comp.current_fmv or 0.0), comp.fmv_date or ""

        new_comp = EquityCompany(
            family_id=family_id,
            company_name="Primary Equity",
            current_fmv=100.0,
            fmv_date="2026-01-01",
        )
        session.add(new_comp)
        session.flush()
        return new_comp.company_id, "Primary Equity", 100.0, "2026-01-01"


def create_company(
    family_id: int = 0,
    company_name: str = "",
    current_fmv: float = 10.0,
    fmv_date: str = "2026-01-01",
    ticker_or_private: str = "private",
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Creates a new equity company and initial FMV record."""
    if not family_id or not company_name:
        return 0

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        existing_comps = session.scalars(
            select(EquityCompany).where(EquityCompany.family_id == family_id)
        ).all()
        clean_name = company_name.strip().lower()
        matched = next((c for c in existing_comps if (c.company_name or "").strip().lower() == clean_name), None)
        if matched is not None:
            matched.current_fmv = float(current_fmv)
            matched.fmv_date = fmv_date
            if ticker_or_private:
                matched.ticker_or_private = ticker_or_private
            session.flush()
            return matched.company_id

        max_companies = int(getattr(config, "MAX_EQUITY_COMPANIES", 20))
        if len(existing_comps) >= max_companies:
            raise ValueError(f"Maximum of {max_companies} equity companies per household reached.")

        comp = EquityCompany(
            family_id=family_id,
            company_name=company_name,
            ticker_or_private=ticker_or_private or "private",
            current_fmv=float(current_fmv),
            fmv_date=fmv_date,
        )
        session.add(comp)
        session.flush()
        cid = comp.company_id
        session.add(FmvHistoryRecord(company_id=cid, valuation_date=fmv_date, share_price=float(current_fmv), is_projected=0, notes="Initial 409A Valuation"))
        return cid


def record_fmv_valuation(
    family_id: int = 0,
    price: float = 0.0,
    valuation_date: str = "",
    notes: str = "409A Valuation",
    company_id: Optional[Union[int, str]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Tuple[int, str]:
    """Updates company FMV and upserts an `fmv_history` entry. Returns `(company_id, company_name)`."""
    if not family_id or price <= 0:
        return 0, "Company"

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        comp: Optional[EquityCompany] = None
        if company_id and str(company_id).isdigit():
            comp = session.scalars(
                select(EquityCompany).where(
                    EquityCompany.family_id == family_id,
                    EquityCompany.company_id == int(company_id),
                )
            ).first()

        if comp is None:
            comp = session.scalars(
                select(EquityCompany)
                .where(EquityCompany.family_id == family_id)
                .order_by(EquityCompany.company_id.asc())
                .limit(1)
            ).first()

        if comp is None:
            comp = EquityCompany(
                family_id=family_id,
                company_name="Primary Equity",
                current_fmv=float(price),
                fmv_date=valuation_date,
            )
            session.add(comp)
            session.flush()
        else:
            comp.current_fmv = float(price)
            comp.fmv_date = valuation_date

        cid = comp.company_id
        cname = comp.company_name or "Company"

        existing_fmv = session.scalars(
            select(FmvHistoryRecord).where(
                FmvHistoryRecord.company_id == cid,
                FmvHistoryRecord.valuation_date == valuation_date,
            )
        ).first()

        if existing_fmv is not None:
            existing_fmv.share_price = float(price)
            existing_fmv.notes = notes
        else:
            max_fmv = int(getattr(config, "MAX_FMV_RECORDS_PER_COMPANY", 200))
            fmv_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(FmvHistoryRecord)
                    .where(FmvHistoryRecord.company_id == cid)
                )
                or 0
            )
            if fmv_count >= max_fmv:
                raise ValueError(
                    f"Maximum of {max_fmv} FMV history records per company reached."
                )

            session.add(
                FmvHistoryRecord(
                    company_id=cid,
                    valuation_date=valuation_date,
                    share_price=float(price),
                    notes=notes,
                )
            )
        return cid, cname


add_fmv_record = record_fmv_valuation


def insert_grant(
    family_id: int = 0,
    company_id: int = 0,
    grant_label: str = "",
    grant_type: str = "nso",
    strike_price: float = 0.0,
    shares_granted: float = 0.0,
    shares_vested: float = 0.0,
    shares_unvested: float = 0.0,
    grant_date: str = "",
    fully_vested_date: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Inserts a new equity grant with transparent `TypeDecorator` column encryption."""
    if not family_id or not grant_label:
        return 0

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        max_grants = int(getattr(config, "MAX_EQUITY_GRANTS", 200))
        grant_count = int(
            session.scalar(
                select(func.count())
                .select_from(EquityGrantRecord)
                .where(EquityGrantRecord.family_id == family_id)
            )
            or 0
        )
        if grant_count >= max_grants:
            raise ValueError(
                f"Maximum of {max_grants} equity grants per household reached."
            )

        grant = EquityGrantRecord(
            company_id=company_id,
            family_id=family_id,
            grant_label=grant_label,
            grant_type=grant_type.lower(),
            strike_price=float(strike_price or 0.0),
            shares_granted=float(shares_granted or 0.0),
            shares_vested=float(shares_vested or 0.0),
            shares_unvested=float(shares_unvested or 0.0),
            grant_date=grant_date,
            fully_vested_date=fully_vested_date,
        )
        session.add(grant)
        session.flush()
        return grant.grant_id


def update_grant(
    family_id: int = 0,
    grant_id_or_label: Union[int, str] = "",
    grant_label: str = "",
    grant_type: str = "nso",
    company_id: Optional[int] = None,
    strike_price: float = 0.0,
    shares_granted: float = 0.0,
    shares_vested: float = 0.0,
    shares_unvested: float = 0.0,
    shares_exercised: float = 0.0,
    cost_basis: float = 0.0,
    grant_date: str = "",
    fully_vested_date: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Updates an existing equity grant."""
    if not family_id or not grant_id_or_label:
        return False

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        is_int_id = str(grant_id_or_label).isdigit()
        cond = (EquityGrantRecord.grant_id == int(grant_id_or_label)) if is_int_id else (EquityGrantRecord.grant_label == str(grant_id_or_label))
        grants = session.scalars(select(EquityGrantRecord).where(EquityGrantRecord.family_id == family_id, cond)).all()
        for g in grants:
            g.grant_label = grant_label
            g.grant_type = grant_type
            if is_int_id and company_id:
                g.company_id = int(company_id)
            g.strike_price = float(strike_price or 0.0)
            g.shares_granted = float(shares_granted or 0.0)
            g.shares_vested = float(shares_vested or 0.0)
            g.shares_unvested = float(shares_unvested or 0.0)
            g.shares_exercised = float(shares_exercised or 0.0)
            g.cost_basis = float(cost_basis or 0.0)
            g.grant_date = grant_date
            g.fully_vested_date = fully_vested_date
    return True


def delete_grant(
    family_id: int = 0,
    grant_id_or_label: Union[int, str] = "",
    db_path: Optional[Union[str, Path]] = None,
) -> bool:
    """Deletes an equity grant by ID or nickname, scoped to `family_id`."""
    if not family_id or not grant_id_or_label:
        return False

    with get_orm_session(db_path, family_id=family_id, commit=True) as session:
        cond = (EquityGrantRecord.grant_id == int(grant_id_or_label)) if str(grant_id_or_label).isdigit() else (EquityGrantRecord.grant_label == str(grant_id_or_label))
        res = session.execute(delete(EquityGrantRecord).where(EquityGrantRecord.family_id == family_id, cond))
        return bool((res.rowcount or 0) > 0)


def list_unexercised_grants(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Returns decrypted list of equity grants with unexercised shares for event modeling."""
    if not family_id:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []
    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(EquityGrantRecord).where(
                EquityGrantRecord.family_id == family_id
            ).order_by(EquityGrantRecord.grant_id.asc())
            results = []
            for g in session.scalars(stmt).all():
                vested = float(g.shares_vested or 0.0)
                exercised = float(g.shares_exercised or 0.0)
                strike = float(g.strike_price or 0.0)
                gtype = str(g.grant_type or "NSO").upper()
                if gtype == "RSU":
                    strike = 0.0
                unexercised = max(0.0, vested - exercised)
                if unexercised > 0:
                    results.append({
                        "grant_id": g.grant_id,
                        "label": g.grant_label or f"Grant {g.grant_id}",
                        "unexercised": unexercised,
                        "strike": strike,
                        "grant_type": gtype,
                    })
            return results
    except Exception as e:
        logger.warning("Error listing grants for family %s: %s", family_id, e)
        return []


def get_primary_company_name(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
    default: str = "Primary Equity",
) -> str:
    """Returns the primary equity company name for family_id, or default."""
    if not family_id:
        return default
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return default
    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(EquityCompany).where(EquityCompany.family_id == family_id).order_by(EquityCompany.company_id.asc()).limit(1)
            comp = session.scalars(stmt).first()
            if comp and comp.company_name:
                return str(comp.company_name)
    except Exception:
        pass
    return default


def get_family_company_names(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> List[str]:
    """Returns lowercased names and ticker symbols of registered equity companies for this family."""
    if not family_id:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []
    try:
        with get_orm_session(path, family_id=family_id) as session:
            stmt = select(EquityCompany).where(EquityCompany.family_id == family_id)
            names = []
            for c in session.scalars(stmt).all():
                cname = (c.company_name or "").strip().lower()
                if cname:
                    names.append(cname)
                ticker = (c.ticker_or_private or "").strip().lower()
                if ticker and ticker != "private":
                    names.append(ticker)
            return names
    except Exception as e:
        logger.warning("Error fetching equity companies for family %s: %s", family_id, e)
        return []

