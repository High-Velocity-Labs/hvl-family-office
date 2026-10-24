"""
Family Profile and Member Management APIs (Multi-Tenant RBAC).
"""

from __future__ import annotations
from flask import Blueprint, request, jsonify, render_template, redirect, session

import security
from routes.helpers import (
    login_required,
    editor_required,
    DB_PATH,
    get_current_db_path,
    get_current_family_id,
    get_current_universe,
    sanitize_text,
)

family_bp = Blueprint("family", __name__)


@family_bp.route("/api/family", methods=["GET"])
@login_required
def api_get_family():
    family_id = get_current_family_id()
    fam = security.get_family(DB_PATH, family_id=family_id) or {}
    members = security.get_family_members(DB_PATH, family_id=family_id)
    return jsonify({
        "success": True,
        "family": fam,
        "members": members,
        "current_user_role": session.get("role", "editor"),
    })


@family_bp.route("/api/family", methods=["POST", "PUT"])
@editor_required
def api_update_family():
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json() or {}
    try:
        name = sanitize_text(data.get("name"), max_length=100, field_name="Family name", required=True)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    settings = data.get("settings")
    security.update_family(DB_PATH, family_id=family_id, name=name, settings=settings)
    return jsonify({"success": True})


@family_bp.route("/api/family/support-access", methods=["POST"])
@editor_required
def api_update_family_support_access():
    """Toggles uniform tenant Developer & Admin Support Access lock for the active family."""
    from routes.helpers import is_sandbox_session
    if is_sandbox_session():
        return jsonify({"success": False, "error": "Not available in single-browser Sandbox Mode."}), 403
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Support access settings cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    if not family_id or family_id <= 0:
        return jsonify({"success": False, "error": "Valid family session required."}), 400
    own_fid = int(session.get("user_family_id") or session.get("family_id") or 0)
    if own_fid != int(family_id):
        return jsonify({"success": False, "error": "Only members of this household can modify support access."}), 403
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    try:
        security.set_family_support_access(DB_PATH, family_id=family_id, enabled=enabled)
    except PermissionError as e:
        return jsonify({"success": False, "error": str(e)}), 403
    return jsonify({
        "success": True,
        "family_id": family_id,
        "support_access_enabled": enabled,
    })


@family_bp.route("/api/family/deletion-status", methods=["GET"])
@login_required
def api_get_family_deletion_status():
    """Returns the household's current 30-day deletion quarantine status."""
    family_id = get_current_family_id()
    fam = security.get_family(DB_PATH, family_id=family_id) if family_id > 0 else None
    del_status = security.get_family_deletion_status(DB_PATH, family_id=family_id) if family_id > 0 else None
    return jsonify({
        "success": True,
        "family_id": family_id,
        "family_name": (fam.get("name") if fam else None) or "Family Office",
        "deletion_status": del_status,
    })


@family_bp.route("/api/family/delete", methods=["POST"])
@editor_required
def api_delete_family():
    """Schedules the active household for deletion (30-day grace) or permanently shreds immediately (`immediate=True`)."""
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Household deletion is disabled in demo mode."}), 403
    family_id = get_current_family_id()
    if not family_id or family_id <= 0:
        return jsonify({"success": False, "error": "Valid family session required."}), 400
    if int(session.get("user_family_id") or session.get("family_id") or 0) != int(family_id):
        return jsonify({"success": False, "error": "Only members of this household can delete household data."}), 403

    data = request.get_json(silent=True) or {}
    fam = security.get_family(DB_PATH, family_id=family_id)
    expected_name = ((fam.get("name") if fam else None) or "Family Office").strip()
    try:
        confirm_name = sanitize_text(data.get("confirm_name", ""), max_length=100, field_name="Confirmation household name", required=True)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    if confirm_name.strip().lower() != expected_name.lower():
        return jsonify({"success": False, "error": f"Confirmation text must match your Family Office name ('{expected_name}')."}), 400

    uni = get_current_universe()
    if bool(data.get("immediate", False)):
        result = security.permanently_delete_family(DB_PATH, family_id=family_id, universe=uni)
        session.clear()
        resp = jsonify({
            "success": True, "mode": "immediate", "permanently_deleted": True,
            "family_id": family_id, "unlinked_files": result.get("unlinked_files", []), "redirect": "/login?deleted=1",
        })
        resp.delete_cookie(security.VAULT_COOKIE_NAME)
        return resp

    actor_raw = str(session.get("user_display") or session.get("user_email") or session.get("user") or "Household Editor")
    actor = sanitize_text(actor_raw, max_length=120, field_name="Requested by") or "Household Editor"
    del_status = security.schedule_family_deletion(DB_PATH, family_id=family_id, requested_by=actor, grace_days=30, universe=uni)
    return jsonify({"success": True, "mode": "grace_period", "family_id": family_id, "deletion_status": del_status, "redirect": "/account-recovery"})


@family_bp.route("/api/family/restore", methods=["POST"])
@editor_required
def api_restore_family():
    """Cancels a scheduled 30-day household deletion and restores full access to the household vault."""
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    if not family_id or family_id <= 0:
        return jsonify({"success": False, "error": "Valid family session required."}), 400
    own_fid = int(session.get("user_family_id") or session.get("family_id") or 0)
    if own_fid != int(family_id):
        return jsonify({"success": False, "error": "Only members of this household can restore household data."}), 403

    security.cancel_family_deletion(DB_PATH, family_id=family_id, universe=get_current_universe())
    return jsonify({"success": True, "family_id": family_id, "redirect": "/"})


@family_bp.route("/account-recovery", methods=["GET"])
@login_required
def account_recovery_view():
    """Serves the 30-day deletion quarantine interstitial screen."""
    family_id = get_current_family_id()
    if not family_id or family_id <= 0 or session.get("is_demo"):
        return redirect("/")
    del_status = security.get_family_deletion_status(DB_PATH, family_id=family_id)
    if not del_status or not del_status.get("is_scheduled"):
        return redirect("/")
    if del_status.get("is_expired"):
        security.permanently_delete_family(DB_PATH, family_id=family_id, universe=get_current_universe())
        session.clear()
        return redirect("/login?deleted=1")

    fam = security.get_family(DB_PATH, family_id=family_id)
    family_name = (fam.get("name") if fam else None) or "Family Office"
    role = (session.get("role") or session.get("user_role") or "viewer").strip().lower()
    return render_template(
        "account_recovery.html",
        family_id=family_id,
        family_name=family_name,
        deletion_status=del_status,
        can_manage=role in ("editor", "admin"),
    )


def _find_matching_existing_member(existing_members: list[dict], relationship: str, name: str) -> dict | None:
    target_member = None
    if relationship == "primary":
        target_member = next((m for m in existing_members if m.get("relationship") == "primary"), None)
        if not target_member:
            target_member = next((m for m in existing_members if m.get("name") in ("Household Owner", "Owner")), None)
    elif relationship == "spouse":
        target_member = next((m for m in existing_members if m.get("relationship") == "spouse"), None)
    if not target_member:
        target_member = next((m for m in existing_members if (m.get("name") or "").strip().lower() == name.lower()), None)
    return target_member


@family_bp.route("/api/family/members", methods=["POST"])
@editor_required
def api_add_family_member():
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json() or {}
    try:
        name = sanitize_text(data.get("name"), max_length=100, field_name="Member name", required=True)
        email = sanitize_text(data.get("email", ""), max_length=120, field_name="Member email")
        birthdate = sanitize_text(data.get("birthdate", ""), max_length=30, field_name="Birthdate")
        relationship = sanitize_text(data.get("relationship", "child"), max_length=50, field_name="Relationship")
        role = sanitize_text(data.get("role", "viewer"), max_length=20, field_name="Role")
        from routes.helpers import is_sandbox_session
        if is_sandbox_session():
            email, role = "", "editor"
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    target_db = get_current_db_path(family_id=family_id)
    try:
        existing_members = security.get_family_members(target_db, family_id=family_id) or []
        target_member = _find_matching_existing_member(existing_members, relationship, name)
        if target_member:
            security.update_family_member(
                db_path=target_db, family_id=family_id, user_id=int(target_member["user_id"]), name=name,
                email=email or target_member.get("email", ""), birthdate=birthdate or target_member.get("birthdate", ""),
                relationship=relationship, role=role or target_member.get("role", "viewer"),
            )
            return jsonify({"success": True, "user_id": int(target_member["user_id"]), "updated": True})

        user_id = security.add_family_member(
            db_path=target_db, family_id=family_id, name=name, email=email,
            birthdate=birthdate, relationship=relationship, role=role,
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({"success": True, "user_id": user_id})


@family_bp.route("/api/family/members/<int:user_id>", methods=["PUT"])
@editor_required
def api_update_family_member(user_id: int):
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    data = request.get_json() or {}
    try:
        name = sanitize_text(data.get("name"), max_length=100, field_name="Member name", required=True)
        email = sanitize_text(data.get("email", ""), max_length=120, field_name="Member email")
        birthdate = sanitize_text(data.get("birthdate", ""), max_length=30, field_name="Birthdate")
        relationship = sanitize_text(data.get("relationship", "child"), max_length=50, field_name="Relationship")
        role = sanitize_text(data.get("role", "viewer"), max_length=20, field_name="Role")
        from routes.helpers import is_sandbox_session
        if is_sandbox_session():
            email, role = "", "editor"
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    security.update_family_member(
        db_path=DB_PATH, family_id=family_id, user_id=user_id,
        name=name, email=email, birthdate=birthdate, relationship=relationship, role=role,
    )
    return jsonify({"success": True})


@family_bp.route("/api/family/members/<int:user_id>", methods=["DELETE"])
@editor_required
def api_delete_family_member(user_id: int):
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Settings cannot be changed in demo mode."}), 403
    family_id = get_current_family_id()
    members = security.get_family_members(DB_PATH, family_id=family_id)
    target = next((m for m in members if m.get("user_id") == user_id), None)
    if target and target.get("relationship") == "primary":
        return jsonify({"success": False, "error": "Cannot delete primary account holder"}), 400
    security.delete_family_member(DB_PATH, family_id=family_id, user_id=user_id)
    return jsonify({"success": True})


from routes.family_invites import (
    _parse_int_or_default,
    api_complete_onboarding,
    api_create_family_invite,
    api_get_onboarding_status,
    api_list_family_invites,
    api_revoke_family_invite,
    register_family_invite_routes,
)

register_family_invite_routes(family_bp)

