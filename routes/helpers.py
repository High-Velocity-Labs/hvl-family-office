"""
Authentication and Authorization Decorators & Shared Path References.
Avoids circular dependencies across modular route blueprints.
"""

from __future__ import annotations
import logging
import os
from functools import wraps
from pathlib import Path
from flask import session, request, jsonify, redirect, url_for, has_request_context

logger = logging.getLogger(__name__)
from config import (
    BASE_DIR, DATA_DIR, APP_UNIVERSE,
    get_cache_db_path_for_universe, get_global_db_path, get_family_db_path,
)

__all__ = [
    "login_required", "editor_required", "get_current_family_id", "get_current_universe",
    "get_current_db_path", "get_current_cache_db_path", "is_sandbox_session", "_is_demo_session",
    "sanitize_text", "parse_query_params", "set_background_context", "reset_background_context",
    "get_background_vault_fek", "BASE_DIR", "DATA_DIR", "DB_PATH",
]

import re
import contextvars
from typing import Any, Optional, Tuple
from hvl_common.security import sanitize_text

_bg_family_id_ctx: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("_bg_family_id_ctx", default=None)
_bg_universe_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_bg_universe_ctx", default=None)
_bg_vault_fek_ctx: contextvars.ContextVar[Optional[Tuple[int, bytes]]] = contextvars.ContextVar("_bg_vault_fek_ctx", default=None)


def set_background_context(family_id: int, universe: str, vault_fek: Optional[bytes] = None) -> Tuple[contextvars.Token, ...]:
    """Sets thread/contextvar family_id, universe, and optional vault_fek for background worker execution."""
    fid = int(family_id)
    return (
        _bg_family_id_ctx.set(fid),
        _bg_universe_ctx.set(str(universe).strip().lower()),
        _bg_vault_fek_ctx.set((fid, vault_fek) if (fid > 0 and vault_fek) else None),
    )


def reset_background_context(tokens: Tuple[contextvars.Token, ...]) -> None:
    """Resets thread/contextvar family_id, universe, and vault_fek after background worker completes."""
    if not tokens:
        return
    for idx, ctx in enumerate((_bg_family_id_ctx, _bg_universe_ctx, _bg_vault_fek_ctx)):
        if len(tokens) > idx:
            ctx.reset(tokens[idx])


def get_background_vault_fek(family_id: int) -> Optional[bytes]:
    """Returns the ephemeral in-memory FEK for the active background task if matching `family_id`."""
    pair = _bg_vault_fek_ctx.get() if (family_id and int(family_id) > 0) else None
    return pair[1] if (pair and pair[0] == int(family_id)) else None


def parse_query_params(
    args: Any,
    specs: dict[str, Any],
) -> dict[str, Any]:
    """
    Parses and casts query parameters from request.args or dict-like mapping.
    specs maps param_name -> cast_type (e.g. int, float, str) or (cast_type, default_val).
    Values equal to None, "", "inherit", "null", or "undefined" are treated as absent
    and evaluate to the default (None unless a tuple (cast, default) is provided).
    Catches (ValueError, TypeError) on casting and returns the default.
    """
    out: dict[str, Any] = {}
    for key, spec in specs.items():
        if isinstance(spec, tuple):
            cast_fn, default = spec
        else:
            cast_fn, default = spec, None

        val = args.get(key) if hasattr(args, "get") else None
        if val in (None, "", "inherit", "null", "undefined"):
            out[key] = default
            continue

        try:
            out[key] = cast_fn(val)
        except (ValueError, TypeError):
            out[key] = default
    return out


def get_current_family_id() -> int:
    """
    Returns the active family_id.
    In 'public' (production) universe, strictly enforces the authentic user_family_id
    from the authenticated Google OAuth session to prevent cross-tenant tampering.
    Never defaults to primary family for unauthenticated or tenant-less sessions.
    """
    bg_fam = _bg_family_id_ctx.get()
    if bg_fam is not None:
        return int(bg_fam)
    if not has_request_context():
        return 0

    universe = get_current_universe()
    if universe == "public":
        for key in ("user_family_id", "family_id"):
            val = session.get(key)
            if val is not None:
                try:
                    if int(val) > 0:
                        return int(val)
                except (ValueError, TypeError):
                    pass

        if session.get("authenticated") and not session.get("is_demo"):
            email = (session.get("user_email") or "").strip().lower()
            if email:
                try:
                    from auth_google import get_family_whitelist
                    wl = get_family_whitelist()
                    if email in wl and "family_id" in wl[email]:
                        fam_id = int(wl[email]["family_id"])
                        session["user_family_id"] = fam_id
                        session["family_id"] = fam_id
                        return fam_id
                except Exception:
                    pass
        return 0

    explicit_fam_id = session.get("family_id")
    if explicit_fam_id is not None:
        try:
            return int(explicit_fam_id)
        except (ValueError, TypeError):
            pass
    return 1 if universe == "demo" else 0


def is_sandbox_session() -> bool:
    """Returns True when running in web mode with an active ephemeral sandbox session."""
    from config import is_local_mode
    if is_local_mode():
        return False
    if _bg_universe_ctx.get() == "sandbox":
        return True
    return bool(has_request_context() and session.get("is_sandbox"))


def _norm_uni(u: str | None) -> str:
    from config import normalize_universe
    return normalize_universe(u)


def _is_demo_session() -> bool:
    """Returns True if the active session is a read-only demo session."""
    if is_sandbox_session():
        return False
    if not has_request_context():
        return False
    if session.get("is_demo"):
        return True
    if session.get("role") == "viewer":
        return True
    if get_current_universe() == "demo" and session.get("role") != "admin":
        return True
    return False


def get_current_universe() -> str:
    """Returns the active universe ('public', 'demo', 'sandbox', 'test') from session or env."""
    bg_uni = _bg_universe_ctx.get()
    if bg_uni:
        return _norm_uni(bg_uni)
    if has_request_context():
        from config import is_local_mode
        if not is_local_mode() and session.get("is_sandbox"):
            return "sandbox"
        # Authentic logged-in users with email in public universe are never demos
        if session.get("authenticated") and session.get("user_email") and session.get("universe") == "public":
            if session.get("is_demo"):
                session["is_demo"] = False
            return "public"
        # Demo sessions are strictly isolated to demo universe
        if session.get("is_demo"):
            return "demo"
        u = session.get("universe")
        if u:
            return _norm_uni(u)
    return _norm_uni(os.getenv("APP_UNIVERSE", APP_UNIVERSE))


def get_current_db_path(family_id: Optional[int] = None) -> Path:
    """
    Returns the database path based on the active session/universe and family context:
    - If a specific family_id > 0 is provided or active in session/context, resolves
      to that family's dedicated database (data/families/{family_id}.db).
    - Otherwise, resolves to the global authentication database (data/global.db).
    """
    fid = int(family_id if family_id is not None else get_current_family_id() or 0)
    uni = get_current_universe()
    if fid > 0:
        return get_family_db_path(fid, universe=uni)
    return get_global_db_path(universe=uni)


def get_current_cache_db_path(db_path: Optional[Any] = None, family_id: Optional[int] = None) -> Path:
    """
    Returns the dedicated L2 cache & job SQLite database path for the active universe or custom test DB.
    Honors any monkeypatched test overrides on `forecast_engine.DB_PATH` or `monarch_service.DB_PATH`.
    When family_id > 0 (or active in context), isolates cache writes to that family's cache DB.
    """
    if db_path is not None and not isinstance(db_path, _DbPathProxy):
        p = Path(db_path)
        return p.parent / f"{p.stem}_cache.db"

    try:
        import sys
        fe = sys.modules.get("forecast_engine")
        if fe is not None and hasattr(fe, "DB_PATH"):
            fe_db = fe.DB_PATH
            if not isinstance(fe_db, _DbPathProxy) and type(fe_db).__name__ != "_ForecastDbPathProxy":
                p = Path(fe_db)
                return p.parent / f"{p.stem}_cache.db"
        fs = sys.modules.get("forecast.storage")
        if fs is not None and hasattr(fs, "DB_PATH") and getattr(fs.DB_PATH, "_override", None) is not None:
            p = Path(fs.DB_PATH._override)
            return p.parent / f"{p.stem}_cache.db"
    except Exception:
        pass

    fid = int(family_id if family_id is not None else get_current_family_id() or 0)
    return get_cache_db_path_for_universe(get_current_universe(), family_id=fid)


class _DbPathProxy(os.PathLike):
    """
    Transparent proxy for DB_PATH that dynamically resolves to the database
    corresponding to the active request's universe (e.g. public vs demo vs test).
    Ensures existing route blueprints requiring DB_PATH automatically connect
    to the correct database without modifying every route file.
    """
    def _path(self) -> Path:
        return get_current_db_path()

    def for_family(self, family_id: int) -> Path:
        """Explicitly resolves the database for a specific family."""
        return get_family_db_path(family_id, universe=get_current_universe())

    def global_db(self) -> Path:
        """Explicitly resolves the global authentication database."""
        return get_global_db_path(universe=get_current_universe())

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return f"<DbPathProxy: {self._path()}>"

    def __eq__(self, other) -> bool:
        return self._path() == other

    def __hash__(self) -> int:
        return hash(self._path())

    def exists(self) -> bool:
        return self._path().exists()

    @property
    def parent(self) -> Path:
        return self._path().parent

    @property
    def name(self) -> str:
        return self._path().name

    def resolve(self) -> Path:
        return self._path().resolve()

    def stat(self):
        return self._path().stat()

    def open(self, *args, **kwargs):
        return self._path().open(*args, **kwargs)


DB_PATH = _DbPathProxy()

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
    try:
        from db import store as _store
        del_status = _store.get_deletion_status(fid)
    except Exception:
        del_status = None
    if not del_status or not del_status.get("is_scheduled"):
        return None

    if del_status.get("is_expired"):
        try:
            import security
            security.permanently_delete_family(DB_PATH, family_id=fid, universe=get_current_universe())
        except Exception as e:
            logger.error("Failed to permanently delete family %s: %s", fid, e)
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
            try:
                login_url = url_for("auth.login_view")
            except Exception:
                try:
                    login_url = url_for("login_view")
                except Exception:
                    login_url = "/login"
            return redirect(login_url)
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
        # Self-heal authentic user sessions that might retain a stale is_demo flag
        if session.get("authenticated") and session.get("user_email") and session.get("universe") == "public":
            if session.get("is_demo"):
                session["is_demo"] = False
        if _is_demo_session():
            return jsonify({"error": "Forbidden: Demo personas are read-only. Settings and data cannot be changed."}), 403
        role = session.get("role") or session.get("user_role") or "viewer"
        if role not in ("editor", "admin", "owner"):
            return jsonify({"error": "Forbidden: Editor permissions required"}), 403
        quarantine_resp = _enforce_deletion_quarantine_guard()
        if quarantine_resp is not None:
            return quarantine_resp
        return f(*args, **kwargs)
    return decorated_function

