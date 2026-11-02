"""
Authentication and Authorization Decorators for route blueprints.
Request-context accessors live in `services/request_context.py` and are re-exported here for routes only.
"""

from __future__ import annotations
import logging
from functools import wraps
from flask import session, request, jsonify, redirect, url_for

from services.request_context import (  # noqa: F401  (re-exported for routes)
    DB_PATH, _DbPathProxy, _is_demo_persona, _is_demo_session, can_mutate, get_current_cache_db_path,
    get_current_db_path, get_current_family_id, get_current_universe, is_beta_non_admin, is_sandbox_session,
    reset_background_context, sanitize_text, set_background_context,
)

logger = logging.getLogger(__name__)

__all__ = [
    "login_required", "editor_required", "get_current_family_id", "get_current_universe",
    "get_current_db_path", "get_current_cache_db_path", "is_sandbox_session", "_is_demo_session",
    "sanitize_text", "set_background_context", "reset_background_context",
    "can_mutate", "is_beta_non_admin", "DB_PATH",
]

_QUARANTINE_ALLOWED_PATHS = frozenset({
    "/account-recovery",
    "/api/family/delete",
    "/api/family/restore",
    "/api/family/deletion-status",
    "/api/auth/logout",
    "/auth/logout",
    "/login",
    "/exit-demo",
})


def _enforce_deletion_quarantine_guard():
    """
    If the authenticated household is inside its 30-day soft-delete quarantine:
    - Automatically purges the household if the 30-day window has expired.
    - Otherwise blocks normal dashboard/API routes and directs the user to `/account-recovery`
      so they can either restore their household or permanently shred it immediately.
    """
    if session.get("is_demo") or request.path in _QUARANTINE_ALLOWED_PATHS:
        return None
    fid = get_current_family_id()
    if not fid or fid <= 0:
        return None
    from db import store as _store

    del_status = _store.get_deletion_status(fid)
    if not del_status or not del_status.get("is_scheduled"):
        return None

    if del_status.get("is_expired"):
        import security

        # A failed purge raises (500): never tell the user the household is gone while its data is still there.
        security.permanently_delete_family(DB_PATH, family_id=fid, universe=get_current_universe())
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error": "Household account has been permanently deleted.", "login_required": True}), 401
        return redirect("/login?deleted=1")

    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "error": "Household account is scheduled for deletion. Restore your household to view or modify data.",
            "deletion_scheduled": True,
            "deletion_status": del_status,
            "redirect": "/account-recovery",
        }), 403
    return redirect("/account-recovery")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "login_required": True}), 401
            return redirect(url_for("auth.login_view"))
        quarantine_resp = _enforce_deletion_quarantine_guard()
        if quarantine_resp is not None:
            return quarantine_resp
        return f(*args, **kwargs)
    return decorated_function



def editor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Unauthorized", "login_required": True}), 401
        if not can_mutate():
            if _is_demo_persona():
                return jsonify({"error": "Forbidden: Demo personas are read-only. Settings and data cannot be changed."}), 403
            return jsonify({"error": "Forbidden: Editor permissions required"}), 403
        quarantine_resp = _enforce_deletion_quarantine_guard()
        if quarantine_resp is not None:
            return quarantine_resp
        return f(*args, **kwargs)
    return decorated_function
