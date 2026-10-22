"""
forecast/context.py: Pre-fetched Household Simulation Context.
Pre-fetches profile, users, compensation, equity pools, and education reserves ONCE per request,
completely decoupling mathematical simulation loops from database I/O and cryptographic decryption.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HouseholdContext:
    """Pre-fetched household parameters, tax status, equity state, and educational reserves."""
    family_id: int = 0
    user_state: str = "WA"
    filing_status: str = "MFJ"
    primary_earned_income: float = 0.0
    spouse_earned_income: float = 0.0
    has_spouse: bool = True
    company_fmvs: Dict[int, float] = field(default_factory=dict)
    current_share_price: float = 0.0
    owned_shares_count: float = 0.0
    options_pools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    options_aliases: Dict[str, str] = field(default_factory=dict)
    grants: list = field(default_factory=list)
    init_options_spread: float = 0.0
    init_nso_retention: float = 0.60
    edu_reserves: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tuition_ledger: Dict[int, Dict[int, float]] = field(default_factory=dict)
    tuition_ledger_loaded: bool = False


def _get_active_db_path() -> Path:
    try:
        from forecast.storage import get_db_path
        return get_db_path()
    except Exception:
        try:
            from routes.helpers import get_current_db_path
            return get_current_db_path()
        except Exception:
            from config import get_global_db_path
            return get_global_db_path()


def build_household_context(family_id: int = 0, children_edu: Optional[list] = None) -> HouseholdContext:
    """
    Constructs a HouseholdContext by executing database queries and cryptographic decryptions once.
    Returns safe generic defaults when family_id <= 0.
    """
    if not family_id or family_id <= 0:
        return HouseholdContext(family_id=0, tuition_ledger_loaded=True)

    import db
    import equity_engine
    import tax_engine
    from db.session import resolve_db_path
    from .storage import load_children_edu_reserves

    db_path = resolve_db_path(_get_active_db_path(), family_id=family_id)
    companies_summary = db.store.get_equity_companies_summary(family_id=family_id, db_path=db_path)
    company_fmvs: Dict[int, float] = {
        int(c["company_id"]): float(c.get("current_fmv") or 0.0)
        for c in companies_summary if c.get("company_id")
    }

    current_share_price = equity_engine.get_current_409a_price(family_id=family_id)
    grants = db.store.get_equity_grants(family_id=family_id, db_path=db_path)
    owned_shares_count = sum(g.owned_exercised for g in grants)

    options_pools: Dict[str, Dict[str, Any]] = {}
    options_aliases: Dict[str, str] = {}
    for g in grants:
        gid = str(g.grant_id)
        is_rsu = str(getattr(g, "grant_type", "nso")).lower() == "rsu"
        strike = 0.0 if is_rsu else float(g.strike_price or 0.0)
        p_data = {
            "options": g.unexercised_vested,
            "strike": strike,
            "active": g.unexercised_vested > 0,
            "grant_id": gid,
            "grant_type": "rsu" if is_rsu else "nso",
            "company_id": getattr(g, "company_id", 0) or 0,
        }
        options_pools[gid] = p_data
        options_aliases[gid] = gid
        options_aliases[g.nickname] = gid
        for part in g.nickname.replace("(", " ").replace(")", " ").split():
            if "-" in part or part.startswith("G"):
                options_aliases[part] = gid

    user_state = "WA"
    filing_status = "MFJ"
    primary_earned_income = 0.0
    spouse_earned_income = 0.0
    has_spouse = True

    if db_path.exists() and family_id:
        try:
            from db.household import get_household_profile, get_household_members
            from db.compensation import get_latest_compensation

            hp = get_household_profile(family_id=family_id, db_path=db_path)
            if hp:
                user_state = str(hp.get("state") or "WA")
                filing_status = str(hp.get("filing_status") or "MFJ")

            members = get_household_members(family_id=family_id, db_path=db_path)
            p_uid = None
            s_uid = None
            for m in members:
                if m.get("relationship") == "primary":
                    p_uid = m.get("user_id")
                elif m.get("relationship") == "spouse":
                    s_uid = m.get("user_id")
            has_spouse = (s_uid is not None)

            if p_uid:
                crow = get_latest_compensation(family_id=family_id, user_id=p_uid, db_path=db_path)
                if crow:
                    b = float(crow.get("salary") or 0.0)
                    bn = float(crow.get("bonus") or 0.0)
                    if b > 0 or bn > 0:
                        primary_earned_income = b + bn
            if s_uid:
                crow = get_latest_compensation(family_id=family_id, user_id=s_uid, db_path=db_path)
                if crow:
                    b = float(crow.get("salary") or 0.0)
                    bn = float(crow.get("bonus") or 0.0)
                    spouse_earned_income = b + bn
        except Exception as e:
            logger.warning("Error fetching compensation records in forecast context: %s", e)

    init_options_spread = sum(
        max(0.0, (current_share_price - p["strike"]) * p["options"])
        for p in options_pools.values()
    )
    if init_options_spread > 0:
        init_tax_calc = tax_engine.calculate_nso_exercise_tax(
            spread=init_options_spread,
            prior_ordinary_income=primary_earned_income + spouse_earned_income,
            include_wa_millionaire_tax=(user_state == "WA"),
            is_mfj=(filing_status == "MFJ"),
        )
        init_nso_retention = max(0.50, min(1.0, 1.0 - init_tax_calc.get("effective_rate", 0.40)))
    else:
        init_nso_retention = 0.60

    if children_edu is None:
        children_edu = load_children_edu_reserves(family_id=family_id)
    edu_reserves: Dict[str, Dict[str, Any]] = {}
    for c in children_edu:
        cid = str(c["user_id"])
        edu_reserves[cid] = {
            "name": c["name"],
            "first_name": c["first_name"],
            "balance": float(c["current_529_balance"]),
            "college_start": c["college_start"],
        }

    tuition_ledger = db.store.get_tuition_ledger(family_id=family_id, db_path=db_path)

    return HouseholdContext(
        family_id=family_id,
        user_state=user_state,
        filing_status=filing_status,
        primary_earned_income=primary_earned_income,
        spouse_earned_income=spouse_earned_income,
        has_spouse=has_spouse,
        company_fmvs=company_fmvs,
        current_share_price=current_share_price,
        owned_shares_count=owned_shares_count,
        options_pools=options_pools,
        options_aliases=options_aliases,
        grants=grants,
        init_options_spread=init_options_spread,
        init_nso_retention=init_nso_retention,
        edu_reserves=edu_reserves,
        tuition_ledger=tuition_ledger,
        tuition_ledger_loaded=True,
    )

