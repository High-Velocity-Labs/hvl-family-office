"""
Equity database repository queries for companies, 409A FMV history, and grants.
Uses SQLAlchemy 2.0 ORM (`EquityCompany`, `EquityGrantRecord`, `FmvHistoryRecord`) with
`lazy="selectin"` relationship loading and transparent `TypeDecorator` encryption.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select

from db.models import EquityCompany, EquityGrantRecord, FmvHistoryRecord
from db.session import get_orm_session
from equity.models import (
    CURRENT_409A_PRICE,
    EquityGrant,
    get_db_path,
    get_default_equity_grants,
)


def get_company_name(family_id: int = 0, company_id: Optional[int] = None) -> str:
    """Returns the company name for a specific company or the primary company for the family."""
    db_path = get_db_path()
    if db_path.exists() and family_id:
        try:
            with get_orm_session(db_path, family_id=family_id) as session:
                stmt = select(EquityCompany).where(
                    EquityCompany.family_id == family_id
                )
                if company_id:
                    stmt = stmt.where(EquityCompany.company_id == int(company_id))
                else:
                    stmt = stmt.order_by(EquityCompany.company_id.asc()).limit(1)
                comp = session.scalars(stmt).first()
                if comp and comp.company_name:
                    return str(comp.company_name)
        except Exception:
            pass
    return "Company"


def get_primary_company_name(family_id: int = 0) -> str:
    return get_company_name(family_id=family_id, company_id=None)


def get_company_409a_price(
    family_id: int = 0, company_id: Optional[int] = None
) -> float:
    """Returns the latest equity share price for a specific company or primary company."""
    db_path = get_db_path()
    if db_path.exists() and family_id:
        try:
            with get_orm_session(db_path, family_id=family_id) as session:
                stmt = select(EquityCompany).where(
                    EquityCompany.family_id == family_id
                )
                if company_id:
                    stmt = stmt.where(EquityCompany.company_id == int(company_id))
                else:
                    stmt = stmt.order_by(EquityCompany.company_id.asc()).limit(1)
                comp = session.scalars(stmt).first()
                if comp and comp.current_fmv is not None and float(comp.current_fmv) > 0:
                    return float(comp.current_fmv)
                return 0.0
        except Exception:
            pass
    return 0.0 if family_id else CURRENT_409A_PRICE


def get_current_409a_price(family_id: int = 0) -> float:
    return get_company_409a_price(family_id=family_id, company_id=None)


def load_equity_companies_summary(family_id: int = 0) -> List[Dict[str, Any]]:
    """Returns all equity companies and their grant totals for a family via `selectin` ORM loading."""
    companies: List[Dict[str, Any]] = []
    db_path = get_db_path()
    if not db_path.exists() or not family_id:
        return companies
    try:
        with get_orm_session(db_path, family_id=family_id) as session:
            stmt = (
                select(EquityCompany)
                .where(EquityCompany.family_id == family_id)
                .order_by(EquityCompany.company_id.asc())
            )
            for comp in session.scalars(stmt).all():
                grants_summary: List[Dict[str, Any]] = []
                total_vested_options = 0.0
                total_unvested_options = 0.0
                total_exercised_shares = 0.0
                total_granted = 0.0
                grant_types_set = set()

                for gr in comp.grants:
                    if gr.family_id != family_id:
                        continue
                    strike = float(gr.strike_price or 0.0)
                    granted = float(gr.shares_granted or 0.0)
                    vested = float(gr.shares_vested or 0.0)
                    unvested = float(gr.shares_unvested or 0.0)
                    exercised = float(gr.shares_exercised or 0.0)
                    gtype = str(gr.grant_type or "NSO").upper()
                    grant_types_set.add(gtype)
                    total_granted += granted
                    total_vested_options += vested
                    total_unvested_options += unvested
                    total_exercised_shares += exercised
                    grants_summary.append(
                        {
                            "grant_id": gr.grant_id,
                            "label": gr.grant_label,
                            "grant_type": gtype,
                            "strike_price": strike,
                            "shares_granted": granted,
                            "shares_vested": vested,
                            "shares_unvested": unvested,
                            "shares_exercised": exercised,
                        }
                    )

                companies.append(
                    {
                        "company_id": comp.company_id,
                        "company_name": comp.company_name or "Company",
                        "ticker_or_private": comp.ticker_or_private or "private",
                        "current_fmv": float(comp.current_fmv or 0.0),
                        "fmv_date": str(comp.fmv_date or ""),
                        "grant_types": (
                            sorted(list(grant_types_set)) if grant_types_set else ["NSO"]
                        ),
                        "grants_count": len(grants_summary),
                        "total_vested_options": total_vested_options,
                        "total_unvested_options": total_unvested_options,
                        "total_exercised_shares": total_exercised_shares,
                        "total_granted": total_granted,
                        "grants": grants_summary,
                    }
                )
    except Exception as e:
        print(f"Error loading equity companies summary: {e}")
    return companies


def get_historical_equity_fmv(
    current_price: Optional[float] = None,
    family_id: int = 0,
    company_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Returns the historical 409A Fair Market Value timeline and forward projections
    for the specified company or family's primary equity company.
    """
    records: List[Dict[str, Any]] = []
    db_path = get_db_path()
    if db_path.exists():
        try:
            with get_orm_session(db_path, family_id=family_id) as session:
                if company_id:
                    target_cid: Optional[int] = int(company_id)
                else:
                    primary_comp = session.scalars(
                        select(EquityCompany)
                        .where(EquityCompany.family_id == family_id)
                        .order_by(EquityCompany.company_id.asc())
                        .limit(1)
                    ).first()
                    target_cid = primary_comp.company_id if primary_comp else None

                if target_cid is not None:
                    rows = session.scalars(
                        select(FmvHistoryRecord)
                        .where(FmvHistoryRecord.company_id == target_cid)
                        .order_by(FmvHistoryRecord.valuation_date.asc())
                    ).all()
                    if rows:
                        non_proj_indices = [
                            idx for idx, r in enumerate(rows) if not r.is_projected
                        ]
                        last_actual_idx = (
                            non_proj_indices[-1] if non_proj_indices else -1
                        )
                        for idx, r in enumerate(rows):
                            d_str = str(r.valuation_date).split("T")[0]
                            p = (
                                float(r.share_price)
                                if r.share_price is not None
                                else 0.0
                            )
                            is_proj = bool(r.is_projected)
                            if idx == last_actual_idx and current_price is not None:
                                p = current_price

                            records.append(
                                {
                                    "date": d_str,
                                    "price": round(p, 2),
                                    "percentage_increase": None,
                                    "gross_value": None,
                                    "net_value": None,
                                    "is_projected": is_proj,
                                    "notes": r.notes or "",
                                }
                            )

                        if records and not any(
                            rec.get("is_projected") for rec in records
                        ):
                            last_p = (
                                current_price
                                if current_price is not None
                                else records[-1]["price"]
                            )
                            for yr_offset in range(1, 4):
                                records.append(
                                    {
                                        "date": f"{2026 + yr_offset}-12-31",
                                        "price": round(last_p * (1.105**yr_offset), 2),
                                        "percentage_increase": 10.5,
                                        "gross_value": None,
                                        "net_value": None,
                                        "is_projected": True,
                                        "notes": "Forward 409A estimate (+10.5%/yr)",
                                    }
                                )
                        return records
                elif family_id:
                    return []
        except Exception:
            pass

    base = current_price if current_price is not None else (0.0 if family_id else CURRENT_409A_PRICE)
    if base <= 0:
        return []
    return [
        {
            "date": "2026-12-31",
            "price": base,
            "percentage_increase": 0.0,
            "is_projected": False,
        },
        {
            "date": "2027-12-31",
            "price": round(base * 1.08, 2),
            "percentage_increase": 8.0,
            "is_projected": True,
        },
        {
            "date": "2028-12-31",
            "price": round(base * (1.08**2), 2),
            "percentage_increase": 8.0,
            "is_projected": True,
        },
    ]


def load_equity_grants_from_db(family_id: int = 0) -> List[EquityGrant]:
    """Loads grants from SQLite `equity_grants` table via SQLAlchemy 2.0 ORM, scoped by `family_id`."""
    db_path = get_db_path()
    if db_path.exists() and family_id:
        try:
            with get_orm_session(db_path, family_id=family_id) as session:
                rows = session.scalars(
                    select(EquityGrantRecord)
                    .where(EquityGrantRecord.family_id == family_id)
                    .order_by(EquityGrantRecord.grant_id.asc())
                ).all()
                if rows:
                    grants: List[EquityGrant] = []
                    for r in rows:
                        gtype = str(r.grant_type or "nso").lower()
                        strike = (
                            0.0
                            if gtype == "rsu"
                            else float(r.strike_price or 0.0)
                        )
                        granted = float(r.shares_granted or 0.0)
                        vested = float(r.shares_vested or 0.0)
                        unvested = float(r.shares_unvested or 0.0)
                        exercised = float(r.shares_exercised or 0.0)
                        basis = float(r.cost_basis or 0.0)
                        comp_name = (
                            r.company.company_name
                            if r.company and r.company.company_name
                            else "Company"
                        )
                        grants.append(
                            EquityGrant(
                                grant_id=str(r.grant_id),
                                nickname=r.grant_label,
                                grant_date=r.grant_date or "",
                                grant_type=gtype,
                                strike_price=strike,
                                total_granted=granted,
                                sold_quantity=max(
                                    0.0, granted - vested - unvested - exercised
                                ),
                                owned_exercised=exercised,
                                unexercised_vested=vested,
                                unvested=unvested,
                                historical_cost_basis=basis,
                                fully_vested_date=r.fully_vested_date or "",
                                company_id=r.company_id or 0,
                                company_name=comp_name,
                            )
                        )
                    return grants
        except Exception:
            pass
    return get_default_equity_grants()
