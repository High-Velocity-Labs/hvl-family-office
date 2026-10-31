"""
account_sync/simplefin_sync.py: Normalization, SSRF URL validation, and balance history reconstruction for SimpleFIN.
"""

from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from account_sync.categorizer_rules import is_coverdell_name


def _validate_simplefin_url(raw_url: str) -> Tuple[bool, str, Optional[Any]]:
    """
    Validates that a SimpleFIN claim URL or access URL uses HTTPS and points to
    an official `simplefin.org` host to prevent Server-Side Request Forgery (SSRF).
    """
    clean = (raw_url or "").strip()
    if not clean:
        return False, "SimpleFIN URL is empty.", None
    try:
        parsed = urlparse(clean)
    except Exception:
        return False, "Invalid SimpleFIN URL format.", None

    if parsed.scheme != "https":
        return False, "SimpleFIN URL must use HTTPS.", None

    host = (parsed.hostname or "").strip().lower()
    if not host or (host != "simplefin.org" and not host.endswith(".simplefin.org")):
        return (
            False,
            "Invalid SimpleFIN host. Token must point to an official simplefin.org bridge endpoint.",
            None,
        )

    return True, "", parsed


def _infer_simplefin_account_type(name: str, balance: float, has_holdings: bool) -> Tuple[str, str, str]:
    """
    Infers `(type_name, type_display, subtype_name)` for a SimpleFIN account based on
    its account name, balance sign, and whether it contains investment holdings.
    """
    lower = (name or "").lower()
    if "529" in lower or "college" in lower or "education" in lower:
        return "investment", "529 Education", "529"
    if is_coverdell_name(lower):
        return "investment", "Coverdell ESA", "530a"
    if any(k in lower for k in ("roth", "ira")):
        return "investment", "Retirement", "ira"
    if any(k in lower for k in ("401(k)", "401k", "403(b)", "403b", "pension", "retirement")):
        return "investment", "Retirement", "401k"
    if any(k in lower for k in ("mortgage", "home loan", "heloc", "auto loan")):
        return "loan", "Loan / Mortgage", "mortgage"
    if any(k in lower for k in ("credit card", "visa", "mastercard", "amex", "american express", "discover", "sapphire", "card")):
        return "credit", "Credit Card", "credit_card"
    if any(k in lower for k in ("brokerage", "investment", "individual", "joint", "trust", "portfolio", "vanguard", "fidelity", "schwab")):
        return "brokerage", "Brokerage", "brokerage"
    if any(k in lower for k in ("checking", "savings", "money market", "cash", "cd", "high yield", "hysa")):
        return "depository", "Cash / Depository", ("savings" if "saving" in lower else "checking")
    if has_holdings:
        return "brokerage", "Brokerage", "brokerage"
    if balance < 0:
        return "credit", "Liability", "credit_card"
    return "depository", "Bank Account", "checking"


def _normalize_simplefin_payload(
    sfin_data: Dict[str, Any],
    existing_nw_flags: Optional[Dict[str, bool]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """
    Converts a raw SimpleFIN `/accounts` JSON response into normalized
    `(accounts_list, holdings_by_account)` matching the `MonarchAccount` / `MonarchHolding` schema.
    """
    raw_accounts = sfin_data.get("accounts") if isinstance(sfin_data, dict) else []
    if not isinstance(raw_accounts, list):
        raw_accounts = []

    accounts: List[Dict[str, Any]] = []
    holdings_by_account: Dict[str, List[Dict[str, Any]]] = {}
    nw_flags = existing_nw_flags or {}

    for idx, raw_acc in enumerate(raw_accounts):
        if not isinstance(raw_acc, dict):
            continue
        acc_id = _sfin_account_id(raw_acc, idx)

        org = raw_acc.get("org") if isinstance(raw_acc.get("org"), dict) else {}
        org_name = str(org.get("name") or org.get("domain") or "SimpleFIN Institution").strip()
        raw_name = str(raw_acc.get("name") or "SimpleFIN Account").strip()

        try:
            balance = float(raw_acc.get("balance") or 0.0)
        except (ValueError, TypeError):
            balance = 0.0

        raw_holdings = raw_acc.get("holdings") if isinstance(raw_acc.get("holdings"), list) else []
        norm_holdings: List[Dict[str, Any]] = []
        for h_idx, h in enumerate(raw_holdings):
            if not isinstance(h, dict):
                continue
            ticker = str(h.get("symbol") or h.get("ticker") or "").strip().upper()
            desc = str(h.get("description") or h.get("name") or ticker or "Security").strip()
            if not ticker:
                ticker = desc[:12].upper()
            try:
                shares = float(h.get("shares") or h.get("quantity") or 0.0)
            except (ValueError, TypeError):
                shares = 0.0
            try:
                market_val = float(h.get("market_value") or h.get("totalValue") or 0.0)
            except (ValueError, TypeError):
                market_val = 0.0
            try:
                cost_basis = float(h.get("cost_basis") or h.get("basis") or 0.0)
            except (ValueError, TypeError):
                cost_basis = 0.0

            norm_holdings.append({
                "id": str(h.get("id") or f"{acc_id}_h_{h_idx}"),
                "ticker": ticker,
                "name": desc,
                "quantity": shares,
                "totalValue": market_val,
                "basis": cost_basis,
                "security": {
                    "ticker": ticker,
                    "name": desc,
                },
                "provider": "simplefin",
            })

        if norm_holdings:
            holdings_by_account[acc_id] = norm_holdings

        t_name, t_display, sub_name = _infer_simplefin_account_type(
            raw_name, balance, has_holdings=bool(norm_holdings)
        )
        inc_nw = nw_flags.get(acc_id, True)

        accounts.append({
            "id": acc_id,
            "displayName": raw_name,
            "name": raw_name,
            "currentBalance": balance,
            "displayBalance": balance,
            "balance": balance,
            "type": {"name": t_name, "display": t_display},
            "subtype": {"name": sub_name, "display": t_display},
            "institution": {"name": org_name},
            "credential": {"displayName": org_name},
            "isManual": False,
            "includeInNetWorth": inc_nw,
            "includeBalanceInNetWorth": inc_nw,
            "isHidden": False,
            "holdingsCount": len(norm_holdings),
            "provider": "simplefin",
            "source_label": "SimpleFIN",
            "orgId": str(org.get("id") or ""),
            "orgDomain": str(org.get("domain") or ""),
            "connId": str(raw_acc.get("conn_id") or ""),
            "currency": str(raw_acc.get("currency") or "USD"),
        })

    return accounts, holdings_by_account


def _reconstruct_simplefin_balance_history(sfin_data: Union[Dict[str, Any], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Reconstructs dated historical balance snapshots from SimpleFIN `/accounts` payload by
    walking backwards from `current_balance` across any returned `transactions`
    (`balance_at_t = current_balance - sum(tx.amount for tx after t)`).
    """
    if isinstance(sfin_data, list):
        raw_accounts = sfin_data
    elif isinstance(sfin_data, dict):
        raw_accounts = sfin_data.get("accounts")
    else:
        raw_accounts = []
    if not isinstance(raw_accounts, list):
        return []

    snapshots: List[Dict[str, Any]] = []
    for idx, raw_acc in enumerate(raw_accounts):
        if not isinstance(raw_acc, dict):
            continue
        raw_id = str(raw_acc.get("id") or f"idx_{idx}").strip()
        acc_id = raw_id if raw_id.startswith("sfin_") else f"sfin_{raw_id}"
        raw_name = str(raw_acc.get("name") or "SimpleFIN Account").strip()
        org = raw_acc.get("org") if isinstance(raw_acc.get("org"), dict) else {}
        org_name = str(org.get("name") or org.get("domain") or "SimpleFIN Institution").strip()

        try:
            current_bal = float(raw_acc.get("balance") or 0.0)
        except (ValueError, TypeError):
            current_bal = 0.0

        bal_ts = raw_acc.get("balance-date")
        if bal_ts is not None:
            try:
                bal_dt_str = datetime.fromtimestamp(float(bal_ts), tz=timezone.utc).strftime("%Y-%m-%d")
                snapshots.append({
                    "account_id": acc_id,
                    "account_name": raw_name,
                    "institution": org_name,
                    "date": bal_dt_str,
                    "balance": round(current_bal, 2),
                })
            except Exception:
                pass

        raw_txs = raw_acc.get("transactions")
        if not isinstance(raw_txs, list) or not raw_txs:
            continue

        parsed_txs: List[Tuple[str, float]] = []
        for tx in raw_txs:
            if not isinstance(tx, dict):
                continue
            raw_posted = tx.get("posted")
            if raw_posted is None:
                raw_posted = tx.get("transacted_at", tx.get("date"))
            if raw_posted is None:
                continue
            tx_date_str: Optional[str] = None
            if isinstance(raw_posted, (int, float)) or (isinstance(raw_posted, str) and raw_posted.strip().isdigit()):
                try:
                    tx_date_str = datetime.fromtimestamp(float(raw_posted), tz=timezone.utc).strftime("%Y-%m-%d")
                except Exception:
                    tx_date_str = None
            elif isinstance(raw_posted, str) and len(raw_posted.strip()) >= 10:
                tx_date_str = raw_posted.strip()[:10]
            if not tx_date_str:
                continue
            try:
                tx_amt = float(tx.get("amount") or 0.0)
            except (ValueError, TypeError):
                continue
            parsed_txs.append((tx_date_str, tx_amt))

        if not parsed_txs:
            continue

        unique_dates = sorted({d for d, _ in parsed_txs})
        try:
            earliest_dt = date.fromisoformat(unique_dates[0])
            prior_day_str = (earliest_dt - timedelta(days=1)).isoformat()
            checkpoint_dates = [prior_day_str] + unique_dates
        except Exception:
            checkpoint_dates = unique_dates

        for cp_date in checkpoint_dates:
            after_sum = sum(amt for d, amt in parsed_txs if d > cp_date)
            bal_at_cp = round(current_bal - after_sum, 2)
            snapshots.append({
                "account_id": acc_id,
                "account_name": raw_name,
                "institution": org_name,
                "date": cp_date,
                "balance": bal_at_cp,
            })

    return snapshots


def _sfin_account_id(raw_acc: Dict[str, Any], idx: int) -> str:
    raw_id = str(raw_acc.get("id") or f"idx_{idx}").strip()
    return raw_id if raw_id.startswith("sfin_") else f"sfin_{raw_id}"


def accounts_with_unknown_holdings(sfin_data: Dict[str, Any]) -> List[str]:
    """
    Ids of returned accounts whose payload has no `holdings` list. A missing key means "unknown" (keep the
    stored holdings); an empty list is a genuine zero and still replaces them.
    """
    raw_accounts = sfin_data.get("accounts") if isinstance(sfin_data, dict) else []
    return [
        _sfin_account_id(raw, idx)
        for idx, raw in enumerate(raw_accounts if isinstance(raw_accounts, list) else [])
        if isinstance(raw, dict) and not isinstance(raw.get("holdings"), list)
    ]


def _bridge_errors(sfin_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Normalizes `errors` (strings) and `errlist` ({code,msg,conn_id,account_id}) into `{text, conn_id, account_id}`."""
    out: List[Dict[str, str]] = []
    for e in (sfin_data.get("errors") if isinstance(sfin_data.get("errors"), list) else []):
        out.append({"text": str(e).lower(), "conn_id": "", "account_id": ""})
    for e in (sfin_data.get("errlist") if isinstance(sfin_data.get("errlist"), list) else []):
        if isinstance(e, dict):
            acc_id = str(e.get("account_id") or "")
            out.append({
                "text": f"{e.get('code') or ''} {e.get('msg') or ''}".lower(),
                "conn_id": str(e.get("conn_id") or ""),
                "account_id": (acc_id if acc_id.startswith("sfin_") or not acc_id else f"sfin_{acc_id}"),
            })
    return out


def has_bridge_errors(sfin_data: Dict[str, Any]) -> bool:
    return bool(_bridge_errors(sfin_data))


def _org_keys(*values: Any) -> List[str]:
    return [str(v).strip().lower() for v in values if len(str(v or "").strip()) >= 3]


def _error_covers(err: Dict[str, str], account_id: str, conn_id: str, org_keys: List[str]) -> bool:
    if err["account_id"] and err["account_id"] == account_id:
        return True
    if err["conn_id"] and conn_id and err["conn_id"] == conn_id:
        return True
    return any(k in err["text"] for k in org_keys)


def failed_existing_account_ids(
    sfin_data: Dict[str, Any], existing_accounts: List[Dict[str, Any]], returned_ids: set
) -> List[str]:
    """
    Existing `sfin_` accounts missing from the payload that a bridge error plausibly explains.
    Each error is tied to its institution (org id/domain/name, conn_id or account_id); only that institution's
    missing accounts are kept. An error naming no known institution protects every missing account.
    """
    errors = _bridge_errors(sfin_data)
    existing = [a for a in existing_accounts if str(a.get("id") or "").startswith("sfin_")]
    missing = [a for a in existing if str(a.get("id")) not in returned_ids]
    if not errors or not missing:
        return []

    def _keys(a: Dict[str, Any]) -> List[str]:
        inst = a.get("institution") if isinstance(a.get("institution"), dict) else {}
        return _org_keys(inst.get("name"), a.get("orgDomain"), a.get("orgId"))

    returned_orgs: List[tuple] = []
    raw_accounts = sfin_data.get("accounts") if isinstance(sfin_data.get("accounts"), list) else []
    for idx, raw in enumerate(raw_accounts):
        if isinstance(raw, dict):
            org = raw.get("org") if isinstance(raw.get("org"), dict) else {}
            returned_orgs.append((_sfin_account_id(raw, idx), str(raw.get("conn_id") or ""),
                                  _org_keys(org.get("name"), org.get("domain"), org.get("id"))))

    failed: set = set()
    for err in errors:
        matched = [str(a["id"]) for a in missing
                   if _error_covers(err, str(a["id"]), str(a.get("connId") or ""), _keys(a))]
        known_elsewhere = any(
            _error_covers(err, str(a["id"]), str(a.get("connId") or ""), _keys(a)) for a in existing
        ) or any(_error_covers(err, rid, conn, keys) for rid, conn, keys in returned_orgs)
        if matched:
            failed.update(matched)
        elif not known_elsewhere:
            failed.update(str(a["id"]) for a in missing)
    return sorted(failed)
