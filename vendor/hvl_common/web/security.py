"""
Shared HVL Web Security Headers, CSP, Cache-Control, and Asset Version Fingerprinting.
"""

from __future__ import annotations

from datetime import timedelta
from functools import wraps
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import urlparse

from flask import (
    Flask,
    Response,
    current_app,
    has_app_context,
    has_request_context,
    jsonify,
    request,
    session,
)

DEFAULT_CSP_TEMPLATE = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "script-src 'self' 'unsafe-inline' https://accounts.google.com https://cdn.jsdelivr.net https://static.cloudflareinsights.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com; "
    "frame-src https://accounts.google.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "connect-src 'self'{extra_connect} https://accounts.google.com https://cdn.jsdelivr.net https://cloudflareinsights.com https://*.cloudflareinsights.com https://static.cloudflareinsights.com;"
)

_STATIC_ROOT_FILES = frozenset({
    "/favicon.ico",
    "/hvl-logo-mark.svg",
    "/fo-logo-mark.svg",
    "/ff-logo-mark.svg",
})


def compute_asset_version(
    base_dir: Path | str,
    static_dirs: Sequence[Path | str] = (),
) -> str:
    """Computes git short-SHA and max static file mtime across static_dirs."""
    base_path = Path(base_dir)
    sha = ""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(base_path),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        pass

    dirs = (
        [Path(d) for d in static_dirs]
        if static_dirs
        else [
            base_path / "static",
            base_path / "vendor" / "hvl_common" / "ui" / "static",
        ]
    )

    max_mtime = 0
    try:
        for root_dir in dirs:
            if root_dir.exists():
                for p in root_dir.rglob("*"):
                    if p.is_file():
                        mt = int(p.stat().st_mtime)
                        if mt > max_mtime:
                            max_mtime = mt
    except Exception:
        pass

    if sha and max_mtime:
        return f"{sha}-{max_mtime}"
    if sha:
        return sha
    return str(max_mtime or int(time.time()))


def _parse_email_items(raw: Any) -> set[str]:
    """Normalizes a string or iterable of email addresses into a lowercase set."""
    if not raw:
        return set()
    items: list[str] = []
    if isinstance(raw, str):
        items.extend(raw.split(","))
    elif isinstance(raw, Iterable):
        for elem in raw:
            items.extend(str(elem or "").split(","))
    return {e.strip().lower() for e in items if e and "@" in e.strip()}


def get_site_admin_emails() -> set[str]:
    """Resolves the set of allowlisted site-admin emails from Flask config and environment."""
    allowed: set[str] = set()
    if has_app_context():
        for cfg_key in ("ADMIN_EMAILS", "ALLOWED_ADMIN_EMAILS", "ADMIN_EMAIL"):
            allowed |= _parse_email_items(current_app.config.get(cfg_key))
    for env_key in ("HVL_ADMIN_EMAILS", "ALLOWED_ADMIN_EMAILS", "ADMIN_EMAIL"):
        allowed |= _parse_email_items(os.getenv(env_key, ""))
    return allowed


def is_verified_site_admin(email: str | None = None) -> bool:
    """Returns True ONLY if the given (or active authenticated session) email is in the site-admin allowlist."""
    candidate = (email or "").strip().lower()
    if not candidate and has_request_context():
        if session.get("is_demo"):
            return False
        if session.get("authenticated") or session.get("user_email"):
            candidate = str(session.get("user_email") or session.get("email") or "").strip().lower()
    if not candidate:
        return False
    allowlist = get_site_admin_emails()
    if not allowlist:
        return False
    return candidate in allowlist


def require_site_admin(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Flask route decorator enforcing that the caller is an authenticated, allowlisted site admin."""

    @wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        if not has_request_context():
            return jsonify({"success": False, "error": "Authentication required"}), 401
        sess_email = str(session.get("user_email") or session.get("email") or "").strip().lower()
        if not (session.get("authenticated") or sess_email) or session.get("is_demo"):
            return jsonify({"success": False, "error": "Authentication required"}), 401
        if not is_verified_site_admin(sess_email):
            return jsonify({"success": False, "error": "Site administrator access required"}), 403
        return fn(*args, **kwargs)

    return _wrapped


def apply_hvl_session_config(app: Any, *, max_age_days: int = 30) -> None:
    """Applies hardened HVL session cookie and lifetime settings to a Flask application."""
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = not bool(app.debug or app.testing)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=int(max_age_days))
    app.config["SESSION_REFRESH_EACH_REQUEST"] = True


def check_csrf_origin(
    *,
    require_session_cookie: bool = True,
    exempt_prefixes: Sequence[str] | None = None,
) -> tuple[Response, int] | None:
    """Validates Sec-Fetch-Site and Origin headers on state-changing requests to prevent CSRF."""
    if not has_request_context():
        return None
    if (request.method or "GET").upper() not in ("POST", "PUT", "PATCH", "DELETE"):
        return None

    path = request.path or "/"
    prefixes = exempt_prefixes
    if prefixes is None and has_app_context():
        prefixes = current_app.config.get("CSRF_EXEMPT_PREFIXES", ("/api/siri", "/mcp", "/admin/mcp"))
    if prefixes and any(path.startswith(p) for p in prefixes):
        return None

    auth_hdr = request.headers.get("Authorization", "").strip()
    if auth_hdr.lower().startswith("bearer "):
        return None

    if require_session_cookie:
        cookie_name = "session"
        if has_app_context():
            cookie_name = str(current_app.config.get("SESSION_COOKIE_NAME", "session"))
        has_cookie = (
            cookie_name in request.cookies
            or bool(request.cookies)
            or bool(session.get("authenticated") or session.get("user_email"))
        )
        if not has_cookie and not request.headers.get("Origin") and not request.headers.get("Sec-Fetch-Site"):
            return None

    sec_fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    if sec_fetch_site == "cross-site":
        return jsonify({"success": False, "error": "Cross-site request blocked (CSRF protection)"}), 403

    origin = request.headers.get("Origin", "").strip()
    if origin:
        if origin.lower() == "null":
            return jsonify({"success": False, "error": "Null Origin header rejected (CSRF protection)"}), 403
        parsed_origin = urlparse(origin).netloc.strip().lower()
        fwd_host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip().lower()
        req_host = (request.host or "").strip().lower()
        allowed_hosts = {h for h in (req_host, fwd_host) if h}
        if not parsed_origin or (allowed_hosts and parsed_origin not in allowed_hosts):
            return jsonify({"success": False, "error": "Origin mismatch rejected (CSRF protection)"}), 403

    return None


def apply_hvl_security_headers(
    response: Response | Any,
    *,
    is_dev: bool = False,
    asset_version: str | None = None,
    frame_options: str = "DENY",
    csp: str | None = None,
    extra_connect_src: str = "",
    robots_tag: str | None = None,
) -> Response:
    """Applies canonical HVL security headers, CSP, HSTS, and Cache-Control (or registers on Flask app)."""
    if isinstance(response, Flask) or (hasattr(response, "after_request") and hasattr(response, "before_request")):
        app = response

        @app.before_request
        def _hvl_csrf_guard() -> Any:
            return check_csrf_origin(require_session_cookie=True)

        @app.after_request
        def _hvl_sec_headers(resp: Response) -> Response:
            return apply_hvl_security_headers(
                resp,
                is_dev=is_dev,
                asset_version=asset_version,
                frame_options=frame_options,
                csp=csp,
                extra_connect_src=extra_connect_src,
                robots_tag=robots_tag,
            )

        return app

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = frame_options
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if robots_tag:
        response.headers["X-Robots-Tag"] = robots_tag

    if asset_version:
        response.headers["X-App-Version"] = str(asset_version)

    if csp is not None:
        if csp:
            response.headers["Content-Security-Policy"] = csp
    else:
        extra = (extra_connect_src or os.getenv("CSP_EXTRA_CONNECT_SRC", "")).strip()
        extra_str = f" {extra}" if extra else ""
        response.headers["Content-Security-Policy"] = DEFAULT_CSP_TEMPLATE.format(
            extra_connect=extra_str
        )

    if has_request_context():
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
        if request.is_secure or forwarded_proto == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        path = request.path or "/"
        is_static = (
            path.startswith(("/static/", "/common/"))
            or path in _STATIC_ROOT_FILES
        )
        cc_header = response.headers.get("Cache-Control", "")
        if path in ("/sw.js", "/manifest.json") or path.endswith("/sw.js"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            if path.endswith("/sw.js"):
                response.headers["Service-Worker-Allowed"] = "/"
        elif is_static and (
            not cc_header or cc_header.startswith("public, max-age=43200")
        ):
            if "v" in request.args and not is_dev:
                response.headers["Cache-Control"] = (
                    "public, max-age=2592000, immutable"
                )
            else:
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif not cc_header:
            content_type = response.content_type or ""
            if path.startswith("/fragments/") or "text/html" in content_type:
                response.headers["Cache-Control"] = (
                    "no-cache, must-revalidate"
                    if is_dev
                    else "no-cache, must-revalidate, private"
                )
            elif "application/json" in content_type or path.startswith("/api/"):
                response.headers["Cache-Control"] = "private, no-cache"

    return response
