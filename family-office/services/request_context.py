"""
Request/session/background context accessors: current family, universe, DB paths, sandbox/demo flags,
mutation permission.
Not a route module: ssr/, services/, forecast/ and db/ import this; routes use the `routes.context` re-export.
"""

from __future__ import annotations
import os
from pathlib import Path
from flask import session, has_request_context

from config import (
    BASE_DIR, DATA_DIR, APP_UNIVERSE,
    get_cache_db_path_for_universe, get_global_db_path, get_family_db_path,
)

__all__ = [
    "get_current_family_id", "get_current_universe", "get_current_db_path", "get_current_cache_db_path",
    "is_sandbox_session", "_is_demo_session", "_is_demo_persona", "sanitize_text", "set_background_context",
    "reset_background_context", "get_background_vault_fek", "can_mutate", "is_beta_non_admin", "parse_query_params",
    "BASE_DIR", "DATA_DIR", "DB_PATH",
]

import re
import contextvars
from typing import Any, Optional, Tuple
from hvl_common.security import sanitize_text

_bg_family_id_ctx: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("_bg_family_id_ctx", default=None)
_bg_universe_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_bg_universe_ctx", default=None)
_bg_vault_fek_ctx: contextvars.ContextVar[Optional[Tuple[int, bytes]]] = contextvars.ContextVar(
    "_bg_vault_fek_ctx", default=None
)
_bg_can_mutate_ctx: contextvars.ContextVar[Optional[bool]] = contextvars.ContextVar(
    "_bg_can_mutate_ctx", default=None
)


def set_background_context(
    family_id: int, universe: str, vault_fek: Optional[bytes] = None, can_mutate: Optional[bool] = None,
) -> Tuple[contextvars.Token, ...]:
    """Sets contextvar family_id, universe, optional vault_fek and the write permission of the originating request."""
    fid = int(family_id)
    return (
        _bg_family_id_ctx.set(fid),
        _bg_universe_ctx.set(str(universe).strip().lower()),
        _bg_vault_fek_ctx.set((fid, vault_fek) if (fid > 0 and vault_fek) else None),
        _bg_can_mutate_ctx.set(can_mutate),
    )


def reset_background_context(tokens: Tuple[contextvars.Token, ...]) -> None:
    """Resets thread/contextvar family_id, universe, and vault_fek after background worker completes."""
    if not tokens:
        return
    for idx, ctx in enumerate((_bg_family_id_ctx, _bg_universe_ctx, _bg_vault_fek_ctx, _bg_can_mutate_ctx)):
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
        # Only a real login (Google OAuth, local desktop; demo personas set 0) writes user_family_id.
        # A bare session["family_id"] is never trusted in the public universe.
        try:
            login_fid = int(session.get("user_family_id") or 0)
        except (ValueError, TypeError):
            login_fid = 0
        if login_fid > 0:
            return login_fid

        if session.get("authenticated") and not session.get("is_demo"):
            email = (session.get("user_email") or "").strip().lower()
            if email:
                try:
                    from services.auth_google import get_family_whitelist
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


def _is_demo_persona() -> bool:
    """True for demo visitors (explicit demo flag, or a non-admin in the demo universe); never for sandbox."""
    if is_sandbox_session() or not has_request_context():
        return False
    if session.get("is_demo"):
        return True
    return get_current_universe() == "demo" and session.get("role") != "admin"


def _is_demo_session() -> bool:
    """Returns True if the active session is a read-only demo persona or a viewer."""
    if is_sandbox_session() or not has_request_context():
        return False
    return _is_demo_persona() or session.get("role") == "viewer"


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
            _heal_stale_demo_flag()
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
    Honors any monkeypatched test overrides on `forecast_engine.DB_PATH` or `account_sync.DB_PATH`.
    When family_id > 0 (or active in context), isolates cache writes to that family's cache DB.
    """
    if db_path is not None and not isinstance(db_path, _DbPathProxy):
        p = Path(db_path)
        return p.parent / f"{p.stem}_cache.db"

    try:
        import sys
        fe = sys.modules.get("forecast.engine") or sys.modules.get("forecast_engine")
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


_MUTATING_ROLES = ("editor", "admin", "owner")


def _session_role() -> str:
    """The caller's role; a session with no role is a viewer (deny by default)."""
    return session.get("role") or session.get("user_role") or "viewer"


def _heal_stale_demo_flag() -> None:
    """Authentic public user sessions can retain a stale is_demo flag from a prior demo visit; clear it."""
    if session.get("authenticated") and session.get("user_email") and session.get("universe") == "public":
        if session.get("is_demo"):
            session["is_demo"] = False


def is_beta_non_admin() -> bool:
    """Beta-universe sessions are read-only for everyone except admins (only endpoints that opt in use this)."""
    return get_current_universe() == "beta" and _session_role() != "admin"


def can_mutate() -> bool:
    """
    The single definition of "may change household data".
    Background work uses the permission captured from its originating request and denies by default.
    A missing role is a viewer; demo personas and viewers can never mutate.
    """
    captured = _bg_can_mutate_ctx.get()
    if captured is not None:
        return captured
    if not has_request_context():
        return False
    if not session.get("authenticated"):
        return False
    _heal_stale_demo_flag()
    if _is_demo_session():
        return False
    return _session_role() in _MUTATING_ROLES
