"""
Settings Service Helpers (Account Role Formatting, Sandbox Sync Guard, Monarch & SimpleFIN Sync Dispatch).
"""

from __future__ import annotations

from typing import Any
from flask import jsonify, request
from monarch.categorizer import ROLE_ALIASES, suggest_account_role_and_beneficiary
from routes.helpers import get_current_db_path, get_current_universe, is_sandbox_session
from routes.notifications import record_sync_outcome_notification
import security

_SANDBOX_LAST_SYNC_TS: float = 0.0


def _invoke_simplefin_sync(family_id: int) -> dict:
    import monarch_service
    fn = getattr(monarch_service, "trigger_simplefin_sync", None) or getattr(monarch_service, "sync_simplefin_accounts", None)
    if not fn:
        return {}
    target_db = get_current_db_path(family_id=family_id)
    try:
        res = fn(family_id=family_id, db_path=target_db)
    except TypeError:
        res = fn(family_id=family_id)
    return record_sync_outcome_notification(family_id=family_id, sync_res=res, db_path=target_db)


def _invoke_monarch_sync(family_id: int) -> dict:
    import monarch_service
    fn = getattr(monarch_service, "trigger_monarch_sync", None) or getattr(monarch_service, "sync_from_monarch", None)
    if not fn:
        return {}
    target_db = get_current_db_path(family_id=family_id)
    try:
        res = fn(family_id=family_id, db_path=target_db)
    except TypeError:
        res = fn(family_id=family_id)
    return record_sync_outcome_notification(family_id=family_id, sync_res=res, db_path=target_db)


def _run_unified_account_sync(family_id: int) -> dict:
    """Syncs all connected providers (Monarch Money and/or SimpleFIN Bridge) for the household."""
    import monarch_service
    monarch_configured = sfin_configured = False
    target_db = get_current_db_path(family_id=family_id)
    try:
        if target_db.exists() and family_id:
            creds = security.db_load_encrypted(target_db, "monarch_credentials", family_id=family_id) or {}
            sess_file = monarch_service.get_family_session_file(family_id)
            monarch_configured = bool((isinstance(creds, dict) and (creds.get("token") or creds.get("email"))) or (sess_file and sess_file.exists()))
            sfin_status = monarch_service.get_simplefin_status(family_id=family_id, db_path=target_db)
            sfin_configured = bool(isinstance(sfin_status, dict) and sfin_status.get("is_connected"))
    except Exception:
        pass

    if sfin_configured and not monarch_configured:
        return _invoke_simplefin_sync(family_id)
    if monarch_configured and not sfin_configured:
        return _invoke_monarch_sync(family_id)
    if monarch_configured and sfin_configured:
        m_res = _invoke_monarch_sync(family_id)
        if not isinstance(m_res, dict):
            m_res = {"success": False}
        if not m_res.get("simplefin_synced"):
            s_res = _invoke_simplefin_sync(family_id)
            if isinstance(s_res, dict) and s_res.get("success"):
                if not m_res.get("success"):
                    return s_res
                m_res["accounts_count"] = int(m_res.get("accounts_count", 0)) + int(s_res.get("accounts_count", 0))
                m_res["holdings_count"] = int(m_res.get("holdings_count", 0)) + int(s_res.get("holdings_count", 0))
                m_res["simplefin_synced"] = True
                m_res["providers"] = ["monarch", "simplefin"]
                m_res["message"] = f"Account sync complete! Refreshed {m_res['accounts_count']} accounts across Monarch Money & SimpleFIN."
        return m_res
    return _invoke_monarch_sync(family_id)


def _resolve_unconfirmed_roles_if_complete(family_id: int, db_path: Any, force: bool = False) -> None:
    import db
    from db.notifications import resolve_family_notification
    if force:
        resolve_family_notification(db_path, family_id=family_id, dedupe_key="job:sync:unconfirmed_roles")
        return
    try:
        accounts = db.accounts.list_accounts(family_id=family_id, db_path=db_path) or []
        roles = db.families.get_account_roles(family_id=family_id, db_path=db_path) or []
        confirmed = {str(r.get("monarch_account_id")) for r in roles if r.get("is_user_confirmed")}
        unconfirmed = sum(
            1 for a in accounts
            if not a.get("isManual") and not str(a.get("id") or "").startswith("manual_")
            and str(a.get("id") or "") not in confirmed
        )
        if unconfirmed == 0:
            resolve_family_notification(db_path, family_id=family_id, dedupe_key="job:sync:unconfirmed_roles")
    except Exception:
        pass


def _format_account_role_entry(acc: dict, role_info: dict, children: list[dict], family_id: int) -> dict:
    acc_id = str(acc.get("id"))
    is_confirmed = bool(role_info.get("is_user_confirmed", 0))
    db_role, db_ben = role_info.get("role"), role_info.get("beneficiary_user_id")
    sugg_role, sugg_ben = suggest_account_role_and_beneficiary(acc, children, family_id=family_id)

    if is_confirmed and db_role:
        active_role, active_ben = ROLE_ALIASES.get(db_role, db_role), db_ben
    elif db_role:
        active_role, active_ben = ROLE_ALIASES.get(db_role, db_role), db_ben or sugg_ben
    else:
        active_role, active_ben = sugg_role, sugg_ben

    is_hidden_fo = bool(role_info.get("is_hidden_from_family_office", 0)) or (
        active_role in ("company_equity_nso", "tax_liability", "hidden_from_family_office", "manual_tax_offset")
    )
    raw_acc_type = acc.get("type")
    clean_type = raw_acc_type if isinstance(raw_acc_type, str) else (raw_acc_type or {}).get("name", "other")
    bal = float(acc.get("currentBalance") or acc.get("current_balance") or 0.0)
    raw_prov = str(acc.get("provider") or "").lower()
    if acc_id.startswith("manual_") or raw_prov == "manual":
        prov, src_label = "manual", "Manual"
    elif acc_id.startswith("sfin_") or raw_prov == "simplefin":
        prov, src_label = "simplefin", "SimpleFIN"
    else:
        prov, src_label = "monarch", "Monarch Money"
    inst_val = (
        ((acc.get("credential") or {}).get("displayName") if isinstance(acc.get("credential"), dict) else None)
        or ((acc.get("institution") or {}).get("name") if isinstance(acc.get("institution"), dict) else None)
        or "Institution"
    )
    return {
        "account_id": acc_id, "display_name": acc.get("displayName") or acc.get("name"),
        "institution": inst_val, "provider": prov, "source_label": src_label, "balance": bal,
        "type": clean_type, "role": active_role, "is_confirmed": is_confirmed,
        "is_hidden_from_family_office": is_hidden_fo, "beneficiary_user_id": active_ben,
    }


def _check_sandbox_sync_guard(family_id: int, feature_key: str = "monarch_sync") -> tuple[bool, int, str]:
    """Enforces max 2 syncs/hr per sandbox household and a minimum 3s outbound pacing interval."""
    if not is_sandbox_session():
        return True, 0, ""
    from hvl_common.web.rate_limit import _default_limiter
    allowed, retry_after, _ = _default_limiter.evaluate("2/hr", scope=f"sandbox_sync:{family_id}")
    if not allowed:
        from db.telemetry import record_portal_telemetry_event
        record_portal_telemetry_event("sandbox", "rate_limit_hit", feature_key=feature_key)
        return False, retry_after, (
            "Sandbox Mode allows up to 2 live institution syncs per hour to protect shared server limits. "
            "You can continue editing accounts manually, download your vault, or sign in for unlimited syncs."
        )
    global _SANDBOX_LAST_SYNC_TS
    import time
    _SANDBOX_LAST_SYNC_TS = time.time()
    return True, 0, ""


def _dispatch_monarch_sync(family_id: int, target_db: Any) -> Any:
    import inspect
    import monarch_service
    from db.telemetry import record_portal_telemetry_event
    record_portal_telemetry_event(get_current_universe(), "monarch_sync", feature_key=str(family_id))
    params = inspect.signature(monarch_service.trigger_monarch_sync).parameters
    if "db_path" in params:
        res = monarch_service.trigger_monarch_sync(family_id=family_id, db_path=target_db)
    else:
        res = monarch_service.trigger_monarch_sync(family_id=family_id)
    return record_sync_outcome_notification(family_id=family_id, sync_res=res, db_path=target_db)


def _execute_simplefin_sync_response(family_id: int, body: dict, connected_msg: bool = False):
    import background_jobs
    import monarch_service

    target_db = get_current_db_path(family_id=family_id)
    if background_jobs.should_run_synchronously(
        sync_param=body.get("sync", request.args.get("sync")),
        async_param=body.get("async", request.args.get("async")),
    ):
        sync_res = record_sync_outcome_notification(
            family_id=family_id, sync_res=monarch_service.trigger_simplefin_sync(family_id=family_id), db_path=target_db
        )
        if not sync_res.get("success"):
            return jsonify(sync_res), 400
        if not connected_msg:
            return jsonify(sync_res)
        return jsonify({
            "success": True, "provider": "simplefin", "sync": sync_res,
            "message": f"Connected to SimpleFIN Bridge ({sync_res.get('accounts_count', 0)} accounts synced).",
            "accounts_count": sync_res.get("accounts_count", 0), "holdings_count": sync_res.get("holdings_count", 0),
        })

    job_id = background_jobs.submit_job(
        lambda: record_sync_outcome_notification(
            family_id=family_id, sync_res=monarch_service.trigger_simplefin_sync(family_id=family_id), db_path=target_db
        ),
        family_id=family_id, universe=get_current_universe(), job_type="simplefin_sync",
    )
    return jsonify({
        "success": True, "provider": "simplefin", "job_id": job_id, "sync_job_id": job_id,
        "status": "processing", "sync_status": "processing", "sync": {"status": "processing", "job_id": job_id},
        "message": (
            "SimpleFIN Bridge connected! Synchronizing accounts in background..."
            if connected_msg
            else "SimpleFIN Bridge sync started in background..."
        ),
    })
