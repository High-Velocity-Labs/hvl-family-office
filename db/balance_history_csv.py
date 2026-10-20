"""
CSV Import, Export, and Date / Currency Parsing for Balance History.
Extracted from db/balance_history.py for modularity.
"""

from __future__ import annotations

import calendar
import csv
from datetime import date, datetime, timezone
import io
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

ROLE_TO_ACCOUNT_TYPE_MAP: Dict[str, tuple[str, str]] = {
    "cash_liquid": ("depository", "checking"),
    "public_brokerage": ("investment", "brokerage"),
    "retirement": ("investment", "401k"),
    "education_529": ("investment", "529"),
    "education_530a": ("investment", "530a"),
    "real_estate": ("real_estate", "residence"),
    "mortgages": ("loan", "mortgage"),
    "credit_cards": ("credit", "credit_card"),
    "private_investments": ("investment", "private_equity"),
    "donor_advised_fund": ("investment", "daf"),
    "vehicles": ("other_asset", "vehicle"),
    "other_assets": ("other_asset", "other"),
}


def normalize_date_str(raw_date: Any) -> Optional[str]:
    """
    Normalizes flexible date inputs (`YYYY-MM-DD`, `YYYY-MM`, `YYYY`, `MM/DD/YYYY`, ISO timestamps)
    into canonical `YYYY-MM-DD` strings. Returns `None` if empty or unparseable.
    """
    if raw_date is None:
        return None
    if isinstance(raw_date, (datetime, date)):
        return raw_date.strftime("%Y-%m-%d")

    s = str(raw_date).strip()
    if not s:
        return None

    if "T" in s:
        s = s.split("T", 1)[0].strip()
    elif " " in s and re.match(r"^\d{4}-\d{2}-\d{2}\s+", s):
        s = s.split(" ", 1)[0].strip()

    now_utc = datetime.now(timezone.utc)

    if re.match(r"^\d{4}$", s):
        yr = int(s)
        if 1900 <= yr <= 2100:
            return now_utc.strftime("%Y-%m-%d") if yr == now_utc.year else f"{yr:04d}-12-31"
        return None

    m_ym = re.match(r"^(\d{4})[-/](\d{1,2})$", s)
    if m_ym:
        yr, mo = int(m_ym.group(1)), int(m_ym.group(2))
        if 1900 <= yr <= 2100 and 1 <= mo <= 12:
            last_day = calendar.monthrange(yr, mo)[1]
            return f"{yr:04d}-{mo:02d}-{last_day:02d}"
        return None

    m_iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m_iso:
        yr, mo, dy = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if 1900 <= yr <= 2100 and 1 <= mo <= 12:
            max_dy = calendar.monthrange(yr, mo)[1]
            dy = min(max(1, dy), max_dy)
            return f"{yr:04d}-{mo:02d}-{dy:02d}"
        return None

    m_us = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$", s)
    if m_us:
        mo, dy, yr = int(m_us.group(1)), int(m_us.group(2)), int(m_us.group(3))
        if yr < 100:
            yr += 2000 if yr < 70 else 1900
        if 1900 <= yr <= 2100 and 1 <= mo <= 12:
            max_dy = calendar.monthrange(yr, mo)[1]
            dy = min(max(1, dy), max_dy)
            return f"{yr:04d}-{mo:02d}-{dy:02d}"
        return None

    return None


def parse_currency_float(val: Any) -> Optional[float]:
    """Parses currency strings (`$1,250.00`, `($450.25)`, `-1200`) into float, or `None` if blank/invalid."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s.lower() in ("-", "--", "n/a", "null", "none", "nan"):
        return None
    is_paren_neg = s.startswith("(") and s.endswith(")")
    if is_paren_neg:
        s = s[1:-1].strip()
    s = s.replace("$", "").replace(",", "").replace("USD", "").replace("usd", "").strip()
    if not s:
        return None
    try:
        f = float(s)
        return -abs(f) if is_paren_neg else f
    except (ValueError, TypeError):
        return None


def infer_role_from_account_name(name: str, raw_role: str = "", balance: float = 0.0) -> str:
    """Infers a normalized Family Office role from an explicit role string or account name."""
    from monarch.categorizer import ROLE_ALIASES

    clean_role = str(raw_role or "").strip().lower().replace(" ", "_")
    if clean_role in ROLE_ALIASES:
        return ROLE_ALIASES[clean_role]
    if clean_role in ROLE_TO_ACCOUNT_TYPE_MAP:
        return clean_role

    lower = (name or "").lower()
    if "529" in lower or "college" in lower or "education" in lower:
        return "education_529"
    if "530a" in lower or "coverdell" in lower:
        return "education_530a"
    if any(k in lower for k in ("401k", "401(k)", "403b", "403(b)", "ira", "roth", "pension", "retirement")):
        return "retirement"
    if any(k in lower for k in ("mortgage", "home loan", "heloc")):
        return "mortgages"
    if any(k in lower for k in ("residence", "home", "house", "property", "real estate", "condo")):
        return "real_estate"
    if any(k in lower for k in ("credit card", "visa", "mastercard", "amex", "discover", "sapphire")):
        return "credit_cards"
    if any(k in lower for k in ("daf", "donor advised", "charit", "foundation")):
        return "donor_advised_fund"
    if any(k in lower for k in ("private equity", "venture", "angel", "lp", "syndicate")):
        return "private_investments"
    if any(k in lower for k in ("brokerage", "vanguard", "fidelity", "schwab", "investment", "portfolio", "trust", "etf")):
        return "public_brokerage"
    if any(k in lower for k in ("checking", "savings", "cash", "money market", "hysa", "cd", "bank")):
        return "cash_liquid"
    return "credit_cards" if balance < 0 else "cash_liquid"


def parse_and_import_balance_csv(
    family_id: int = 0,
    csv_text: str = "",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Parses uploaded CSV text supporting both Long Format (`Date, Account Name, Balance`)
    and Wide / Pivot Spreadsheet Format (`Date` in col 0, Account Names in col 1..N).
    """
    from db.balance_history import record_account_balance_snapshots

    if not family_id or family_id <= 0:
        return {"success": False, "imported_rows": 0, "imported": 0, "accounts_affected": 0, "accounts_updated": 0, "years_covered": []}

    clean_text = (csv_text or "").lstrip("\ufeff").strip()
    if not clean_text:
        raise ValueError("CSV content is empty.")

    reader = csv.reader(io.StringIO(clean_text))
    rows = [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("CSV must include a header row and at least one data row.")

    headers = rows[0]
    lower_headers = [h.lower().strip() for h in headers]

    def _find_col(candidates: set[str]) -> Optional[int]:
        for idx, h in enumerate(lower_headers):
            if h in candidates:
                return idx
        return None

    date_idx = _find_col({"date", "as of", "as_of", "as_of_date", "as of date", "year", "month", "period", "timestamp"})
    acc_idx = _find_col({"account", "account name", "account_name", "name", "display_name", "displayname"})
    id_idx = _find_col({"account id", "account_id", "id"})
    bal_idx = _find_col({"balance", "amount", "value", "current balance", "current_balance", "ending balance", "net worth"})
    role_idx = _find_col({"role", "type", "account type", "account_type", "category"})
    inst_idx = _find_col({"institution", "institution name", "institution_name", "bank", "organization", "provider"})
    inc_idx = _find_col({"include in net worth", "include_in_net_worth", "includeinnetworth"})

    snapshots_to_record: List[Dict[str, Any]] = []
    if date_idx is not None and bal_idx is not None and (acc_idx is not None or id_idx is not None):
        for r in rows[1:]:
            if date_idx >= len(r) or bal_idx >= len(r):
                continue
            d_str = normalize_date_str(r[date_idx])
            bal_val = parse_currency_float(r[bal_idx])
            if not d_str or bal_val is None:
                continue
            acc_name = r[acc_idx] if (acc_idx is not None and acc_idx < len(r)) else ""
            acc_id = r[id_idx] if (id_idx is not None and id_idx < len(r)) else ""
            if not acc_name and not acc_id:
                continue
            snapshots_to_record.append({
                "account_id": acc_id,
                "account_name": acc_name,
                "date": d_str,
                "balance": bal_val,
                "role": r[role_idx] if (role_idx is not None and role_idx < len(r)) else "",
                "institution": r[inst_idx] if (inst_idx is not None and inst_idx < len(r)) else "",
                "include_in_net_worth": r[inc_idx] if (inc_idx is not None and inc_idx < len(r)) else True,
            })
    else:
        if len(headers) < 2:
            raise ValueError("Unrecognized CSV format. Expected 'Date, Account Name, Balance' or a multi-column date pivot table.")
        for r in rows[1:]:
            if not r:
                continue
            d_str = normalize_date_str(r[0])
            if not d_str:
                continue
            for c_idx in range(1, min(len(headers), len(r))):
                acc_name = headers[c_idx].strip()
                bal_val = parse_currency_float(r[c_idx]) if acc_name else None
                if acc_name and bal_val is not None:
                    snapshots_to_record.append({"account_name": acc_name, "date": d_str, "balance": bal_val})

    if not snapshots_to_record:
        raise ValueError("No valid dated account balance rows found in CSV.")

    rec_res = record_account_balance_snapshots(family_id=family_id, snapshots=snapshots_to_record, db_path=db_path)
    cnt = rec_res.get("recorded_count", 0)
    aff = rec_res.get("accounts_affected", 0)
    return {
        "success": True,
        "imported_rows": cnt,
        "imported": cnt,
        "recorded_count": cnt,
        "accounts_affected": aff,
        "accounts_updated": aff,
        "years_covered": rec_res.get("years_covered", []),
        "historical_net_worth": rec_res.get("historical_net_worth", []),
    }


def export_balances_csv(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> str:
    """Exports all historical balance snapshots as a clean CSV string."""
    from db.balance_history import get_account_balance_history

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["Date", "Account Name", "Provider", "Role", "Institution", "Balance", "Include in Net Worth"])
    if not family_id or family_id <= 0:
        return buf.getvalue()

    for item in get_account_balance_history(family_id=family_id, db_path=db_path):
        writer.writerow([
            item.get("date", ""),
            item.get("account_name", ""),
            item.get("provider", ""),
            item.get("role", ""),
            item.get("institution", ""),
            f"{float(item.get('balance', 0.0)):.2f}",
            "true" if item.get("include_in_net_worth", True) else "false",
        ])
    return buf.getvalue()
