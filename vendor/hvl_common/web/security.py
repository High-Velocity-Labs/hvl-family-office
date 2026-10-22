"""
Shared HVL Web Security Headers, CSP, Cache-Control, and Asset Version Fingerprinting.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Sequence

from flask import Response, has_request_context, request

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


def apply_hvl_security_headers(
    response: Response,
    *,
    is_dev: bool = False,
    asset_version: str | None = None,
    frame_options: str = "DENY",
    csp: str | None = None,
    extra_connect_src: str = "",
    robots_tag: str | None = None,
) -> Response:
    """Applies canonical HVL security headers, CSP, HSTS, and Cache-Control."""
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
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        if "Cache-Control" not in response.headers:
            path = request.path or "/"
            is_static = (
                path.startswith(("/static/", "/common/"))
                or path in _STATIC_ROOT_FILES
            )
            content_type = response.content_type or ""
            if is_static:
                if "v" in request.args:
                    max_age = 3600 if is_dev else 2592000
                    response.headers["Cache-Control"] = (
                        f"public, max-age={max_age}, immutable"
                    )
                else:
                    response.headers["Cache-Control"] = "no-cache, must-revalidate"
            elif path in ("/manifest.json", "/sw.js"):
                response.headers["Cache-Control"] = "no-cache, public, must-revalidate"
            elif path.startswith("/fragments/") or "text/html" in content_type:
                response.headers["Cache-Control"] = (
                    "no-cache, must-revalidate"
                    if is_dev
                    else "no-cache, must-revalidate, private"
                )
            elif "application/json" in content_type or path.startswith("/api/"):
                response.headers["Cache-Control"] = "private, no-cache"

    return response
