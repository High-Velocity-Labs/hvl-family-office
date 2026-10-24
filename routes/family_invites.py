"""
Magic Invite Token Management and Guided Onboarding APIs for Household RBAC.
"""

from __future__ import annotations

from pathlib import Path
from flask import jsonify, request, session

import security
from config import is_site_admin_email, is_standalone_mode
from routes.helpers import (
    DB_PATH,
    editor_required,
    get_current_family_id,
    get_current_universe,
    is_sandbox_session,
    login_required,
    sanitize_text,
)
from ssr.onboarding import build_onboarding_state


def _parse_int_or_default(val, default: int) -> int:
    try:
        return int(val or default)
    except (TypeError, ValueError):
        return default


@login_required
def api_list_family_invites():
    """Returns all Magic Invite tokens created by the active household."""
    if is_standalone_mode():
        return jsonify({"success": True, "invites": [], "standalone_mode": True})
    family_id = get_current_family_id()
    invites = security.list_invite_tokens(Path(DB_PATH), family_id=family_id) if family_id > 0 else []
    base_url = request.host_url.rstrip("/")
    for inv in invites:
        inv["invite_url"] = f"{base_url}/invite/{inv['code']}"
    return jsonify({"success": True, "invites": invites})


@editor_required
def api_create_family_invite():
    """Generates a new Magic Invite token (`new_household` restricted to site admin email, or `join_household`)."""
    if is_standalone_mode():
        return jsonify({"success": False, "error": "Magic invites are disabled in standalone single-user mode."}), 403
    if is_sandbox_session():
        return jsonify({"success": False, "error": "Not available in single-browser Sandbox Mode."}), 403
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Magic invites cannot be created in demo mode."}), 403
    family_id = get_current_family_id()
    if not family_id or family_id <= 0:
        return jsonify({"success": False, "error": "Valid family session required."}), 400

    data = request.get_json(silent=True) or {}
    try:
        invite_type = sanitize_text(data.get("invite_type", "join_household"), max_length=32, field_name="Invite type") or "join_household"
        target_role = sanitize_text(data.get("target_role", "editor"), max_length=20, field_name="Target role") or "editor"
        label = sanitize_text(data.get("label", ""), max_length=100, field_name="Invite label")
        created_by_email = sanitize_text(session.get("user_email") or session.get("user") or "", max_length=120, field_name="Created by")
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    norm_invite_type = "join_household" if invite_type.strip().lower() == "join_household" else "new_household"
    if norm_invite_type == "new_household" and not is_site_admin_email(created_by_email, db_path=Path(DB_PATH)):
        return jsonify({"success": False, "error": "Forbidden: Only the site administrator can generate New Household invites."}), 403

    try:
        invite = security.create_invite_token(
            Path(DB_PATH),
            family_id=family_id,
            created_by_email=created_by_email,
            invite_type=norm_invite_type,
            target_role=target_role,
            label=label,
            max_uses=_parse_int_or_default(data.get("max_uses"), 1),
            expires_days=_parse_int_or_default(data.get("expires_days"), 14),
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    invite["invite_url"] = f"{request.host_url.rstrip('/')}/invite/{invite['code']}"
    return jsonify({"success": True, "invite": invite})


@editor_required
def api_revoke_family_invite(code: str):
    """Revokes an existing Magic Invite token created by the active household."""
    if is_sandbox_session():
        return jsonify({"success": False, "error": "Not available in single-browser Sandbox Mode."}), 403
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Magic invites cannot be revoked in demo mode."}), 403
    family_id = get_current_family_id()
    if not family_id or family_id <= 0:
        return jsonify({"success": False, "error": "Valid family session required."}), 400

    clean_code = sanitize_text(code, max_length=64, field_name="Invite code").upper()
    revoked = security.revoke_invite_token(Path(DB_PATH), family_id=family_id, code=clean_code)
    return jsonify({"success": True, "revoked": bool(revoked), "code": clean_code})


@login_required
def api_get_onboarding_status():
    """Returns onboarding wizard and setup checklist progress for the active household."""
    family_id = get_current_family_id()
    state = build_onboarding_state(family_id=family_id)
    return jsonify({"success": True, **state})


@editor_required
def api_complete_onboarding():
    """Marks the guided onboarding wizard or setup checklist as completed or dismissed in household settings."""
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Onboarding state cannot be modified in demo mode."}), 403
    family_id = get_current_family_id()
    if not family_id or family_id <= 0:
        return jsonify({"success": False, "error": "Valid family session required."}), 400

    data = request.get_json(silent=True) or {}
    dismissed = bool(data.get("dismissed", False))
    wizard_dismissed = bool(data.get("wizard_dismissed", False))
    completed = bool(data.get("completed", not dismissed and not wizard_dismissed))

    fam = security.get_family(Path(DB_PATH), family_id=family_id) or {}
    settings = dict(fam.get("settings") or {})
    if wizard_dismissed and not dismissed and not completed:
        settings["onboarding_wizard_dismissed"] = True
    if dismissed:
        settings["onboarding_dismissed"] = True
        settings["onboarding_wizard_dismissed"] = True
    if completed:
        settings["onboarding_completed"] = True
        settings["onboarding_dismissed"] = False
        settings["onboarding_wizard_dismissed"] = False

    security.update_family(Path(DB_PATH), family_id=family_id, settings=settings)
    return jsonify({
        "success": True,
        "onboarding_completed": bool(settings.get("onboarding_completed")),
        "onboarding_dismissed": bool(settings.get("onboarding_dismissed")),
        "onboarding_wizard_dismissed": bool(settings.get("onboarding_wizard_dismissed")),
    })


def register_family_invite_routes(bp) -> None:
    """Registers Magic Invite and Onboarding endpoints onto `family_bp`."""
    bp.add_url_rule("/api/family/invites", view_func=api_list_family_invites, methods=["GET"])
    bp.add_url_rule("/api/family/invites", view_func=api_create_family_invite, methods=["POST"])
    bp.add_url_rule("/api/family/invites/<code>", view_func=api_revoke_family_invite, methods=["DELETE"])
    bp.add_url_rule("/api/onboarding/status", view_func=api_get_onboarding_status, methods=["GET"])
    bp.add_url_rule("/api/onboarding/complete", view_func=api_complete_onboarding, methods=["POST"])


__all__ = [
    "_parse_int_or_default",
    "api_complete_onboarding",
    "api_create_family_invite",
    "api_get_onboarding_status",
    "api_list_family_invites",
    "api_revoke_family_invite",
    "register_family_invite_routes",
]
