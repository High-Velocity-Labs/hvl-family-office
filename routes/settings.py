"""
Settings Management APIs (Editor-Only).
Allows configuring Household Profile Assumptions and Account Role Overrides.
"""

from __future__ import annotations

from flask import Blueprint, request, jsonify, session
from monarch.categorizer import (
    AVAILABLE_ROLES,
    ROLE_ALIASES,
    suggest_account_role_and_beneficiary,
)

import security
import db
from routes.helpers import (
    login_required,
    editor_required,
    DB_PATH,
    get_current_db_path,
    get_current_family_id,
    get_current_universe,
    sanitize_text,
)
from services.settings_service import (
    _check_sandbox_sync_guard,
    _dispatch_monarch_sync,
    _execute_simplefin_sync_response,
    _format_account_role_entry,
    _resolve_unconfirmed_roles_if_complete,
)

settings_bp = Blueprint("settings", __name__)


def _is_demo_locked() -> bool:
    return bool(session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"))


@settings_bp.route("/api/settings/assumptions", methods=["GET"])
@login_required
def api_get_assumptions():
    """Returns household assumptions for the active family."""
    try:
        family_id = get_current_family_id()
        profile = {
            "state": "WA", "filing_status": "MFJ", "annual_spending": 0.0,
            "annual_savings": 0.0, "retirement_age": 65, "inflation_rate": 0.025,
        }
        if DB_PATH.exists():
            hp = db.families.get_household_profile(family_id=family_id, db_path=DB_PATH)
            if hp:
                for k in profile:
                    if k in hp:
                        profile[k] = hp[k]
        return jsonify({"success": True, "assumptions": profile})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), (403 if isinstance(e, PermissionError) else 500)


@settings_bp.route("/api/settings/assumptions", methods=["POST"])
@editor_required
def api_update_assumptions():
    """Updates household assumptions in household_profile table."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        family_id = get_current_family_id()
        body = request.get_json() or {}
        if DB_PATH.exists():
            existing = db.families.get_household_profile(family_id=family_id, db_path=DB_PATH) or {}
            state = sanitize_text(body.get("state", existing.get("state", "WA")), max_length=2, field_name="State", required=True).upper()
            filing_status = sanitize_text(body.get("filing_status", existing.get("filing_status", "MFJ")), max_length=10, field_name="Filing status", required=True).upper()
            db.families.upsert_household_profile(
                family_id=family_id, state=state, filing_status=filing_status,
                annual_spending=float(body.get("annual_spending", existing.get("annual_spending", 0.0))),
                annual_savings=float(body.get("annual_savings", existing.get("annual_savings", 0.0))),
                retirement_age=int(body.get("retirement_age", existing.get("retirement_age", 65))),
                inflation_rate=float(body.get("inflation_rate", existing.get("inflation_rate", 0.025))),
                db_path=DB_PATH,
            )
        return jsonify({"success": True, "message": "Household tax and profile settings updated successfully."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@settings_bp.route("/api/settings/account_roles", methods=["GET"])
@login_required
def api_get_account_roles():
    """Returns all accounts with their confirmed or suggested roles and beneficiary mappings."""
    try:
        family_id = get_current_family_id()
        accounts = db.accounts.list_accounts(family_id=family_id, db_path=DB_PATH) or []
        members = security.get_family_members(DB_PATH, family_id=family_id)
        children = [m for m in members if m.get("relationship") == "child"]
        roles_map = {
            str(r["monarch_account_id"]): dict(r)
            for r in (db.families.get_account_roles(family_id=family_id, db_path=DB_PATH) if DB_PATH.exists() else [])
        }
        accounts_with_roles = [
            _format_account_role_entry(acc, roles_map.get(str(acc.get("id")), {}), children, family_id)
            for acc in accounts
        ]
        return jsonify({"success": True, "accounts": accounts_with_roles, "members": members, "available_roles": AVAILABLE_ROLES})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), (403 if isinstance(e, PermissionError) else 500)


@settings_bp.route("/api/settings/account_roles", methods=["POST"])
@editor_required
def api_update_account_role():
    """Sets or overrides an account's role classification and beneficiary assignment."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        family_id = get_current_family_id()
        body = request.get_json() or {}
        acc_id = sanitize_text(body.get("account_id"), max_length=100, field_name="Account ID", required=True)
        raw_role = sanitize_text(body.get("role"), max_length=50, field_name="Role", required=True)
        role = ROLE_ALIASES.get(raw_role, "") or raw_role
        beneficiary_id = body.get("beneficiary_user_id")
        beneficiary_id = int(beneficiary_id) if beneficiary_id is not None and str(beneficiary_id).isdigit() else None
        is_hidden_val = body.get("is_hidden_from_family_office")
        is_hidden_fo = (1 if role in ("company_equity_nso", "tax_liability", "hidden_from_family_office", "manual_tax_offset") else 0) if is_hidden_val is None else (1 if is_hidden_val else 0)
        if DB_PATH.exists():
            db.families.upsert_account_role(
                family_id=family_id, monarch_account_id=acc_id, role=role,
                beneficiary_user_id=beneficiary_id, is_hidden_from_family_office=is_hidden_fo,
                is_user_confirmed=1, db_path=DB_PATH,
            )
            _resolve_unconfirmed_roles_if_complete(family_id, DB_PATH, force=False)
        return jsonify({"success": True, "message": "Account role updated."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@settings_bp.route("/api/settings/confirm_all_roles", methods=["POST"])
@editor_required
def api_confirm_all_roles():
    """Confirms and locks all currently suggested account roles for the family."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        family_id = get_current_family_id()
        accounts = db.accounts.list_accounts(family_id=family_id, db_path=DB_PATH) or []
        members = security.get_family_members(DB_PATH, family_id=family_id)
        children = [m for m in members if m.get("relationship") == "child"]
        count = 0
        if DB_PATH.exists():
            role_updates = []
            for acc in accounts:
                sugg_role, sugg_ben = suggest_account_role_and_beneficiary(acc, children, family_id=family_id)
                is_hidden_fo = 1 if sugg_role in ("company_equity_nso", "tax_liability", "hidden_from_family_office", "manual_tax_offset") else 0
                role_updates.append({
                    "monarch_account_id": str(acc.get("id")), "role": sugg_role,
                    "beneficiary_user_id": sugg_ben, "is_hidden_from_family_office": is_hidden_fo,
                })
            count = db.families.confirm_all_roles(family_id=family_id, role_updates=role_updates, db_path=DB_PATH)
            _resolve_unconfirmed_roles_if_complete(family_id, DB_PATH, force=True)
        return jsonify({"success": True, "message": f"Confirmed {count} account classifications."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@settings_bp.route("/api/settings/monarch_login", methods=["POST"])
@editor_required
def api_monarch_login():
    """Authenticates with Monarch Money via email, password, and optional TOTP secret key for the active family."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        import background_jobs
        import monarch_service
        family_id = get_current_family_id()
        body = request.get_json() or {}
        email = sanitize_text(body.get("email"), max_length=120, field_name="Email", required=True)
        password = sanitize_text(body.get("password"), max_length=256, field_name="Password", required=True)
        mfa_secret = sanitize_text(body.get("mfa_secret_key", ""), max_length=128, field_name="MFA secret key") or None
        target_db = get_current_db_path(family_id=family_id)
        res = monarch_service.login_monarch(email, password, mfa_secret, family_id=family_id)
        if res.get("success"):
            allowed, retry_after, err_msg = _check_sandbox_sync_guard(family_id, feature_key="monarch_sync")
            if not allowed:
                return jsonify({"success": False, "error": err_msg, "retry_after": retry_after}), 429
            if background_jobs.should_run_synchronously(
                sync_param=body.get("sync", request.args.get("sync")),
                async_param=body.get("async", request.args.get("async")),
            ):
                _dispatch_monarch_sync(family_id, target_db)
            else:
                job_id = background_jobs.submit_job(
                    lambda: _dispatch_monarch_sync(family_id, target_db),
                    family_id=family_id, universe=get_current_universe(), job_type="monarch_sync",
                )
                res = {**res, "job_id": job_id, "sync_job_id": job_id, "status": "processing", "sync_status": "processing"}
        return jsonify(res)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), (403 if isinstance(e, PermissionError) else 500)


@settings_bp.route("/api/settings/monarch_mfa", methods=["POST"])
@editor_required
def api_monarch_mfa():
    """Completes Monarch Money 2FA using user-provided code for the active family."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        import background_jobs
        import monarch_service
        family_id = get_current_family_id()
        target_db = get_current_db_path(family_id=family_id)
        body = request.get_json() or {}
        email = sanitize_text(body.get("email"), max_length=120, field_name="Email", required=True)
        password = sanitize_text(body.get("password"), max_length=256, field_name="Password", required=True)
        code = sanitize_text(body.get("code"), max_length=16, field_name="MFA code", required=True)
        res = monarch_service.mfa_monarch(email, password, code, family_id=family_id)
        if res.get("success"):
            if background_jobs.should_run_synchronously(
                sync_param=body.get("sync", request.args.get("sync")),
                async_param=body.get("async", request.args.get("async")),
            ):
                _dispatch_monarch_sync(family_id, target_db)
            else:
                job_id = background_jobs.submit_job(
                    lambda: _dispatch_monarch_sync(family_id, target_db),
                    family_id=family_id, universe=get_current_universe(), job_type="monarch_sync",
                )
                res = {**res, "job_id": job_id, "sync_job_id": job_id, "status": "processing", "sync_status": "processing"}
        return jsonify(res)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), (403 if isinstance(e, PermissionError) else 500)


@settings_bp.route("/api/settings/monarch_credentials", methods=["POST"])
@editor_required
def api_save_monarch_credentials():
    """Stores encrypted Monarch credentials directly in the database for the active family."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        import background_jobs
        family_id = get_current_family_id()
        target_db = get_current_db_path(family_id=family_id)
        body = request.get_json() or {}
        email = sanitize_text(body.get("email", ""), max_length=120, field_name="Email")
        password = sanitize_text(body.get("password", ""), max_length=256, field_name="Password")
        mfa_secret = sanitize_text(body.get("mfa_secret_key", ""), max_length=128, field_name="MFA secret key") or None
        token = sanitize_text(body.get("token", ""), max_length=2048, field_name="Token") or None

        creds = security.db_load_encrypted(target_db, "monarch_credentials", family_id=family_id) or {}
        for k, v in (("email", email), ("password", password), ("mfa_secret_key", mfa_secret), ("token", token)):
            if v:
                creds[k] = v
        security.db_save_encrypted(target_db, "monarch_credentials", "settings", creds, family_id=family_id)

        if background_jobs.should_run_synchronously(
            sync_param=body.get("sync", request.args.get("sync")),
            async_param=body.get("async", request.args.get("async")),
        ):
            return jsonify({
                "success": True, "sync": _dispatch_monarch_sync(family_id, target_db),
                "message": "Monarch credentials stored in encrypted family vault and synchronized.",
            })
        job_id = background_jobs.submit_job(
            lambda: _dispatch_monarch_sync(family_id, target_db),
            family_id=family_id, universe=get_current_universe(), job_type="monarch_sync",
        )
        return jsonify({
            "success": True, "job_id": job_id, "sync_job_id": job_id, "status": "processing",
            "sync_status": "processing", "sync": {"status": "processing", "job_id": job_id},
            "message": "Monarch credentials stored in encrypted family vault. Synchronization queued in background.",
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), (403 if isinstance(e, PermissionError) else 500)


@settings_bp.route("/api/settings/simplefin_connect", methods=["POST"])
@editor_required
def api_simplefin_connect():
    """Claims a SimpleFIN Bridge Setup Token, saves it in the encrypted family vault, and syncs accounts."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        import monarch_service
        from datetime import datetime, timezone
        from db.telemetry import record_portal_telemetry_event

        family_id = get_current_family_id()
        target_db = get_current_db_path(family_id=family_id)
        body = request.get_json(silent=True) or {}
        raw_token = body.get("setup_token") or body.get("token") or body.get("access_url") or ""
        setup_token = sanitize_text(raw_token, max_length=2048, field_name="SimpleFIN Setup Token", required=True)
        claim_res = monarch_service.claim_simplefin_setup_token(setup_token)
        if not claim_res.get("success"):
            return jsonify(claim_res), 400
        security.db_save_encrypted(
            target_db, "simplefin_credentials", "settings",
            {"access_url": str(claim_res["access_url"]), "updated_at": datetime.now(timezone.utc).isoformat()},
            family_id=family_id,
        )
        allowed, retry_after, err_msg = _check_sandbox_sync_guard(family_id, feature_key="simplefin_sync")
        if not allowed:
            return jsonify({"success": False, "error": err_msg, "retry_after": retry_after}), 429
        record_portal_telemetry_event(get_current_universe(), "simplefin_sync", feature_key=str(family_id))
        return _execute_simplefin_sync_response(family_id, body, connected_msg=True)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), (403 if isinstance(e, PermissionError) else 500)


@settings_bp.route("/api/settings/simplefin_sync", methods=["POST"])
@editor_required
def api_simplefin_sync():
    """Triggers an on-demand SimpleFIN Bridge sync for the active family."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        from db.telemetry import record_portal_telemetry_event
        family_id = get_current_family_id()
        allowed, retry_after, err_msg = _check_sandbox_sync_guard(family_id, feature_key="simplefin_sync")
        if not allowed:
            return jsonify({"success": False, "error": err_msg, "retry_after": retry_after}), 429
        record_portal_telemetry_event(get_current_universe(), "simplefin_sync", feature_key=str(family_id))
        return _execute_simplefin_sync_response(family_id, request.get_json(silent=True) or {}, connected_msg=False)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), (403 if isinstance(e, PermissionError) else 500)


@settings_bp.route("/api/settings/simplefin_disconnect", methods=["POST"])
@editor_required
def api_simplefin_disconnect():
    """Disconnects SimpleFIN Bridge and optionally removes synced SimpleFIN accounts for the active family."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        import monarch_service
        body = request.get_json(silent=True) or {}
        return jsonify(monarch_service.disconnect_simplefin(family_id=get_current_family_id(), remove_accounts=bool(body.get("remove_accounts", True))))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), (403 if isinstance(e, PermissionError) else 500)


@settings_bp.route("/api/settings/ai_key", methods=["POST", "DELETE"])
@editor_required
def api_settings_ai_key():
    """Saves or clears a household-specific Google Gemini API key encrypted at rest."""
    try:
        if _is_demo_locked():
            return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
        from datetime import datetime, timezone
        family_id = get_current_family_id()
        if family_id <= 0:
            return jsonify({"success": False, "error": "Unauthorized household context."}), 403
        if request.method == "DELETE":
            clean_key = ""
        else:
            body = request.get_json(silent=True) or {}
            clean_key = sanitize_text(body.get("gemini_api_key") if "gemini_api_key" in body else body.get("api_key", ""), max_length=256)
        security.db_save_encrypted(
            DB_PATH, "ai_credentials", "settings",
            {"gemini_api_key": clean_key, "updated_at": datetime.now(timezone.utc).isoformat()}, family_id=family_id,
        )
        masked = f"••••{clean_key[-4:]}" if len(clean_key) >= 4 else ("••••" if clean_key else "")
        return jsonify({
            "success": True, "has_custom_key": bool(clean_key), "masked_key": masked,
            "message": "Household Gemini API key saved." if clean_key else "Household Gemini API key cleared.",
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
