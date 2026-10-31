"""
db/data_migration.py: Automatic, idempotent data migration from legacy `family_encrypted_store`
JSON blobs into normalized relational tables (`monarch_accounts`, `monarch_holdings`,
`estate_profiles`, `tax_transcript_records`, `tax_transcript_meta`, `tuition_year_records`,
`forecast_settings`, `forecast_scenarios`, `forecast_events`, `philanthropy_budgets`,
`philanthropy_donations`, `gifts`, `gift_recipients`, `compensation`, `equity_grants`).
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import threading
from hvl_common.db import get_db_connection
import security
from db import accounts, transcripts, philanthropy, scenarios, estate, education, gifting, compensation, equity

logger = logging.getLogger(__name__)

MIGRATED_STORE_KEYS: Tuple[str, ...] = (
    "accounts", "holdings", "estate_profile", "tax_transcripts",
    "private_school_tuition", "scenario_system_state", "scenarios",
    "annual_donations", "family_gifts", "career_compensation", "company_equity_grants",
)

_MIGRATED_DB_PATHS: Set[str] = set()
_MIGRATION_TLS = threading.local()


def is_in_initial_migration() -> bool:
    return bool(getattr(_MIGRATION_TLS, "active", False))


def _table_has_rows_for_family(conn: Any, table_name: str, family_id: int) -> bool:
    """Checks if a relational table already has at least one row for `family_id`."""
    ALLOWED_TABLES = {
        "monarch_accounts", "monarch_holdings", "estate_profiles", "tax_transcript_records",
        "tax_transcript_meta", "tuition_year_records", "forecast_scenarios", "philanthropy_donations",
        "philanthropy_budgets", "gifts", "gift_recipients", "compensation", "equity_grants",
    }
    if table_name not in ALLOWED_TABLES:
        return False
    return conn.execute(f"SELECT 1 FROM {table_name} WHERE family_id = ? LIMIT 1", (family_id,)).fetchone() is not None


def _migrate_single_key(
    path: Path,
    family_id: int,
    key: str,
    data: Any,
    overwrite: bool = False,
    strict: bool = False,
) -> bool:
    """Migrates a single decrypted payload into its normalized relational table(s)."""
    if data is None:
        if strict:
            raise ValueError(f"Cannot save {key!r}: payload is None")
        return True

    handlers = {
        "accounts": ("monarch_accounts", list, lambda: accounts.replace_accounts(family_id=family_id, accounts=data, db_path=path)),
        "holdings": ("monarch_holdings", (dict, list), lambda: accounts.replace_holdings(family_id=family_id, holdings_by_account=data, db_path=path)),
        "estate_profile": ("estate_profiles", dict, lambda: estate.save_estate_profile_row(family_id=family_id, profile=data, db_path=path)),
        "tax_transcripts": ("tax_transcript_records", dict, lambda: transcripts.save_transcripts_payload(family_id=family_id, payload=data, db_path=path)),
        "private_school_tuition": ("tuition_year_records", dict, lambda: education.save_tuition_store_payload(family_id=family_id, payload=data, db_path=path)),
        "scenario_system_state": ("forecast_scenarios", dict, lambda: scenarios.save_scenario_state(family_id=family_id, state=data, db_path=path)),
        "scenarios": ("forecast_scenarios", dict, lambda: scenarios.save_scenario_state(family_id=family_id, state=data, db_path=path)),
        "annual_donations": ("philanthropy_donations", dict, lambda: philanthropy.save_philanthropy_payload(family_id=family_id, payload=data, db_path=path)),
        "family_gifts": ("gift_recipients", dict, lambda: _rel_save_family_gifts(path, family_id, data)),
        "career_compensation": ("compensation", (dict, list), lambda: _rel_save_career_comp(path, family_id, data)),
        "company_equity_grants": ("equity_grants", (dict, list), lambda: _rel_save_equity_grants(path, family_id, data)),
    }
    if key not in handlers:
        return False
    tbl, exp_type, fn = handlers[key]
    if not isinstance(data, exp_type):
        if strict:
            raise TypeError(f"Cannot save {key!r}: expected {exp_type}, got {type(data).__name__}")
        return False

    conn = get_db_connection(path)
    try:
        if overwrite or not _table_has_rows_for_family(conn, tbl, family_id):
            conn.close()
            if fn() is False and strict:
                raise ValueError(f"Cannot save {key!r}: payload shape {type(data).__name__} has no savable content")
        return True
    finally:
        try:
            conn.close()
        except Exception:
            pass


def migrate_encrypted_store_to_relational(db_path: Optional[Union[str, Path]] = None) -> int:
    """
    Idempotently migrates all domain blobs in `family_encrypted_store` into normalized
    relational tables and deletes the migrated keys from `family_encrypted_store`.
    """
    if db_path is None:
        from services.request_context import get_current_db_path
        path = get_current_db_path()
    else:
        path = Path(db_path)

    if not path.exists():
        return 0

    conn = get_db_connection(path, timeout=30.0)
    try:
        has_store = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='family_encrypted_store'").fetchone()
        has_norm = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='monarch_accounts'").fetchone()
        if not has_store or not has_norm:
            return 0

        placeholders = ",".join("?" for _ in MIGRATED_STORE_KEYS)
        rows = conn.execute(
            f"SELECT family_id, key, encrypted_payload FROM family_encrypted_store WHERE key IN ({placeholders})",
            MIGRATED_STORE_KEYS,
        ).fetchall()
        if not rows:
            return 0

        decrypted_items, corrupt_items = [], []
        for r in rows:
            fid, k = int(r["family_id"]), str(r["key"])
            if fid <= 0:
                corrupt_items.append((fid, k))
                continue
            try:
                data = security.decrypt_data(r["encrypted_payload"], key=security.get_family_key(conn, fid))
            except Exception:
                try:
                    data = security.decrypt_data(r["encrypted_payload"])
                except Exception as exc:
                    logger.warning("Skipping undecryptable legacy row (%s, %s): %s", fid, k, exc)
                    continue
            decrypted_items.append((fid, k, data))

        if corrupt_items:
            with conn:
                for fid, k in corrupt_items:
                    conn.execute("DELETE FROM family_encrypted_store WHERE family_id = ? AND key = ?", (fid, k))
    finally:
        conn.close()

    migrated_count = 0
    _MIGRATION_TLS.active = True
    try:
        for fid, k, data in decrypted_items:
            try:
                if _migrate_single_key(path, fid, k, data, overwrite=False):
                    with get_db_connection(path, timeout=30.0) as del_conn:
                        with del_conn:
                            del_conn.execute("DELETE FROM family_encrypted_store WHERE family_id = ? AND key = ?", (fid, k))
                        migrated_count += 1
            except Exception as exc:
                logger.warning("Failed migrating family_encrypted_store (%s, %s): %s", fid, k, exc)
    finally:
        _MIGRATION_TLS.active = False

    return migrated_count


def try_relational_save(
    db_path: Path,
    key: str,
    data: Any,
    family_id: int,
) -> bool:
    """
    Routes writes for normalized domain keys directly to their relational tables
    instead of writing JSON blobs to `family_encrypted_store`.

    Returns False only when the key is not a migrated key (or family_id is 0).
    For migrated keys it returns True on success and RAISES on any failure.
    """
    if key not in MIGRATED_STORE_KEYS or not family_id:
        return False
    conn = get_db_connection(db_path)
    try:
        has_norm = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='monarch_accounts'"
        ).fetchone()
    finally:
        conn.close()
    if not has_norm:
        raise RuntimeError(f"Relational tables missing in {db_path}; cannot save migrated key {key!r}")
    # Errors from the relational write propagate: the caller must never report success
    # for a value that reads (relational-first) would not return.
    return _migrate_single_key(db_path, int(family_id), key, data, overwrite=True, strict=True)


def _gift_rows_from_payload(data: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[Tuple[str, int], Dict[str, Any]]]:
    """Normalizes a gifts payload into recipients by name and gifts by (recipient name, year). No writes."""
    recipients: Dict[str, Dict[str, Any]] = {}
    gifts: Dict[Tuple[str, int], Dict[str, Any]] = {}
    by_lower: Dict[str, str] = {}

    def add_gift(name: str, year: int, amount: float, notes: str) -> None:
        if amount < 0:
            raise ValueError(f"Negative gift amount for {name!r} in {year}")
        prev = gifts.get((name, year))
        gifts[(name, year)] = {"amount": round(amount, 2), "notes": notes or (prev or {}).get("notes", "")}

    for r in data.get("recipients") or []:
        rd = r if isinstance(r, dict) else {}
        nm = str(rd.get("recipient_group_name") or rd.get("recipient_name") or rd.get("name") or "") if rd else str(r or "")
        if not nm:
            continue
        recipients[nm] = {
            "member_count": int(rd.get("member_count", 1) or 1), "relationship": str(rd.get("relationship", "") or ""),
            "notes": str(rd.get("notes", "") or ""),
        }
        by_lower[nm.lower()] = nm
        for g in rd.get("gifts") or rd.get("annual_gifts") or []:
            if isinstance(g, dict) and g.get("year"):
                add_gift(nm, int(g["year"]), float(g.get("amount", 0.0) or 0.0), str(g.get("notes", "") or ""))
    for yr_str, items in (data.get("gifts_by_year") or {}).items():
        if str(yr_str).isdigit() and isinstance(items, list):
            for g in items:
                if isinstance(g, dict) and g.get("recipient"):
                    nm = by_lower.get(str(g["recipient"]).strip().lower()) or str(g["recipient"]).strip()
                    if nm not in recipients:
                        recipients[nm] = {"member_count": 1, "relationship": "", "notes": ""}
                        by_lower[nm.lower()] = nm
                    add_gift(nm, int(yr_str), float(g.get("amount", 0.0) or 0.0), str(g.get("notes", "") or ""))
    return recipients, gifts


def _rel_save_family_gifts(path: Path, family_id: int, data: Any) -> bool:
    """Replaces a household's gift recipients and gifts in ONE transaction: any failure rolls everything back."""
    if not isinstance(data, dict):
        return False
    import config
    from db.models import AnnualGift, GiftRecipient
    from db.session import get_orm_session
    from sqlalchemy import delete

    recipients, gifts = _gift_rows_from_payload(data)
    if len(recipients) > int(getattr(config, "MAX_GIFT_RECIPIENTS", 50)):
        raise ValueError("Maximum gift recipients per household reached.")
    if len(gifts) > int(getattr(config, "MAX_GIFT_RECORDS", 1000)):
        raise ValueError("Maximum gift records per household reached.")
    with get_orm_session(path, family_id=family_id, commit=True) as session:
        session.execute(delete(AnnualGift).where(AnnualGift.family_id == family_id))
        session.execute(delete(GiftRecipient).where(GiftRecipient.family_id == family_id))
        rows: Dict[str, Any] = {}
        for nm, meta in recipients.items():
            rows[nm] = GiftRecipient(
                family_id=family_id, recipient_group_name=nm, member_count=meta["member_count"],
                relationship_type=meta["relationship"], notes=meta["notes"],
            )
            session.add(rows[nm])
        session.flush()
        for (nm, year), g in gifts.items():
            session.add(AnnualGift(
                family_id=family_id, recipient_id=rows[nm].recipient_id, year=year, amount=g["amount"], notes=g["notes"],
            ))
    return True


def _rel_load_family_gifts(path: Path, family_id: int) -> Dict[str, Any]:
    recs = gifting.list_gift_recipients(family_id=family_id, db_path=path)
    gifts_by_rid: Dict[int, list] = {}
    for g in gifting.list_gifts(family_id=family_id, db_path=path):
        gifts_by_rid.setdefault(int(g.get("recipient_id") or 0), []).append(
            {"year": int(g.get("year", 0)), "amount": float(g.get("amount", 0.0) or 0.0), "notes": str(g.get("notes") or "")}
        )
    return {
        "annual_exclusion_limits": {},
        "recipients": [
            {
                "recipient_id": int(r.get("recipient_id") or 0),
                "name": str(r.get("recipient_group_name") or r.get("name") or ""),
                "recipient_name": str(r.get("recipient_group_name") or r.get("name") or ""),
                "member_count": int(r.get("member_count") or 1),
                "relationship": str(r.get("relationship") or ""),
                "notes": str(r.get("notes") or ""),
                "gifts": gifts_by_rid.get(int(r.get("recipient_id") or 0), []),
            }
            for r in recs
        ],
    }


def _rel_save_career_comp(path: Path, family_id: int, data: Any) -> bool:
    """Replaces a household's compensation history in ONE transaction: any failure rolls everything back."""
    items = data.get("history") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return False
    import config
    from db.models import CompensationRecord
    from db.session import get_orm_session
    from sqlalchemy import delete

    wanted: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for h in items:
        if isinstance(h, dict) and h.get("year"):
            company = str(h.get("company") or h.get("employer") or "Primary Employer")
            wanted[(int(h["year"]), company.lower())] = {
                "year": int(h["year"]), "company": company,
                "salary": float(h.get("salary", h.get("base_salary", 0.0)) or 0.0),
                "bonus": float(h.get("bonus", 0.0) or 0.0),
                "source": str(h.get("source") or h.get("notes") or "Manual Entry"),
            }
    if len(wanted) > int(getattr(config, "MAX_COMPENSATION_RECORDS", 200)):
        raise ValueError("Maximum compensation records per household reached.")
    with get_orm_session(path, family_id=family_id, commit=True) as session:
        session.execute(delete(CompensationRecord).where(CompensationRecord.family_id == family_id))
        for w in wanted.values():
            session.add(CompensationRecord(
                family_id=family_id, user_id=None, tax_year=w["year"], employer_name=w["company"],
                base_salary=w["salary"], bonus=w["bonus"], notes=w["source"],
            ))
    return True


def _rel_load_career_comp(path: Path, family_id: int) -> List[Dict[str, Any]]:
    rows = compensation.list_compensation_records(family_id=family_id, db_path=path)
    out: List[Dict[str, Any]] = []
    for r in rows:
        payload = r.get("payload_json")
        if payload:
            try:
                parsed = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(parsed, dict):
                    out.append(parsed)
                    continue
            except Exception:
                pass
        out.append({
            "year": int(r.get("year") or r.get("tax_year") or 0),
            "company": str(r.get("company") or r.get("employer_name") or ""),
            "salary": float(r.get("salary", r.get("base_salary", 0.0)) or 0.0),
            "bonus": float(r.get("bonus", 0.0) or 0.0),
            "notes": str(r.get("notes") or r.get("source") or ""),
        })
    return out


def _rel_save_equity_grants(path: Path, family_id: int, data: Any) -> bool:
    items = data.get("equityGrants") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return False
    from db.models import EquityGrantRecord
    from db.session import get_orm_session
    from sqlalchemy import delete
    cid, _, _, _ = equity.get_or_create_primary_company(family_id=family_id, db_path=path)
    with get_orm_session(path, family_id=family_id, commit=True) as session:
        session.execute(delete(EquityGrantRecord).where(EquityGrantRecord.family_id == family_id))
        for g in items:
            if not isinstance(g, dict):
                continue
            lbl = str(g.get("grant_label") or g.get("nickname") or f"Grant {g.get('grant_id', '')}").strip() or "Grant"
            sched = g.get("vesting_schedule") or g.get("vesting_schedule_json") or "{}"
            session.add(EquityGrantRecord(
                company_id=int(g.get("company_id") or cid or 1), family_id=family_id,
                grant_label=lbl, grant_type=str(g.get("grant_type", "nso")).lower(),
                strike_price=float(g.get("strike_price", 0.0) or 0.0),
                shares_granted=float(g.get("shares_granted", g.get("total_granted", 0.0)) or 0.0),
                shares_vested=float(g.get("shares_vested", g.get("unexercised_vested", 0.0)) or 0.0),
                shares_unvested=float(g.get("shares_unvested", g.get("unvested", 0.0)) or 0.0),
                shares_exercised=float(g.get("shares_exercised", g.get("owned_exercised", 0.0)) or 0.0),
                cost_basis=float(g.get("cost_basis", g.get("historical_cost_basis", 0.0)) or 0.0),
                vesting_schedule_json=json.dumps(sched) if isinstance(sched, dict) else str(sched),
                grant_date=str(g.get("grant_date", "") or ""),
                fully_vested_date=str(g.get("fully_vested_date", "") or ""),
            ))
    return True


def _rel_load_equity_grants(path: Path, family_id: int) -> List[Dict[str, Any]]:
    from db.models import EquityGrantRecord
    from db.session import get_orm_session
    from sqlalchemy import select
    with get_orm_session(path, family_id=family_id) as session:
        records = session.scalars(select(EquityGrantRecord).where(EquityGrantRecord.family_id == family_id).order_by(EquityGrantRecord.grant_id.asc())).all()
        out: List[Dict[str, Any]] = []
        for r in records:
            sched = {}
            if r.vesting_schedule_json:
                try:
                    sched = json.loads(r.vesting_schedule_json)
                except Exception:
                    pass
            out.append({
                "grant_id": r.grant_id, "company_id": r.company_id, "grant_label": r.grant_label,
                "grant_type": r.grant_type, "strike_price": float(r.strike_price or 0.0),
                "shares_granted": float(r.shares_granted or 0.0), "shares_vested": float(r.shares_vested or 0.0),
                "shares_unvested": float(r.shares_unvested or 0.0), "shares_exercised": float(r.shares_exercised or 0.0),
                "cost_basis": float(r.cost_basis or 0.0), "grant_date": r.grant_date or "",
                "fully_vested_date": r.fully_vested_date or "", "vesting_schedule": sched,
                "vesting_schedule_json": r.vesting_schedule_json or "{}",
            })
        return out


def try_relational_load(
    db_path: Path,
    key: str,
    family_id: int,
) -> Tuple[bool, Any]:
    """
    Routes reads for normalized domain keys directly to their relational tables.
    Returns `(handled, result)`. `handled` is False only when the key is not migrated or the
    relational tables do not exist yet (pre-migration DB). Read errors propagate; they are never
    answered from a stale legacy blob.
    """
    if key not in MIGRATED_STORE_KEYS or not family_id or not db_path.exists():
        return (False, None)
    conn = get_db_connection(db_path)
    try:
        has_norm = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='monarch_accounts'"
        ).fetchone()
    finally:
        conn.close()
    if not has_norm:
        return (False, None)

    fid = int(family_id)
    loaders = {
        "accounts": lambda: accounts.list_accounts(family_id=fid, db_path=db_path),
        "holdings": lambda: accounts.get_holdings_by_account(family_id=fid, db_path=db_path),
        "estate_profile": lambda: estate.get_estate_profile_row(family_id=fid, db_path=db_path),
        "tax_transcripts": lambda: transcripts.get_transcripts_payload(family_id=fid, db_path=db_path),
        "private_school_tuition": lambda: education.get_tuition_store_payload(family_id=fid, db_path=db_path),
        "scenario_system_state": lambda: scenarios.get_scenario_state(family_id=fid, db_path=db_path),
        "scenarios": lambda: scenarios.get_scenario_state(family_id=fid, db_path=db_path),
        "annual_donations": lambda: philanthropy.get_philanthropy_payload(family_id=fid, db_path=db_path),
        "family_gifts": lambda: _rel_load_family_gifts(db_path, fid),
        "career_compensation": lambda: _rel_load_career_comp(db_path, fid),
        "company_equity_grants": lambda: _rel_load_equity_grants(db_path, fid),
    }
    return (True, loaders[key]()) if key in loaders else (False, None)
