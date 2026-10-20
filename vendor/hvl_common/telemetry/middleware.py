"""
Flask Operational Telemetry Middleware (`register_telemetry`).
Automatically captures unhandled exceptions / 5xx responses (`ERROR_500`),
slow requests exceeding `slow_threshold_ms` (`SLOW_REQUEST`), and HTTP 429
responses (`RATE_LIMIT`) into `telemetry.db` with zero PII.
"""

from __future__ import annotations

import logging
from pathlib import Path
import os
import time
from typing import Any, Optional, Union

from flask import Flask, Response, g, got_request_exception, has_request_context, request, session

from hvl_common.telemetry.store import (
    EVENT_ERROR_500,
    EVENT_RATE_LIMIT,
    EVENT_SLOW_REQUEST,
    record_telemetry_event,
)

logger = logging.getLogger(__name__)

_STATIC_PREFIXES = ("/static/", "/common/")
_STATIC_EXACT = {"/favicon.ico", "/robots.txt"}
_STATIC_SUFFIXES = (".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".map")


def _is_static_asset_path(path: str) -> bool:
    if not path:
        return False
    lower = path.lower()
    if lower in _STATIC_EXACT:
        return True
    if any(lower.startswith(p) for p in _STATIC_PREFIXES):
        return True
    if any(lower.endswith(s) for s in _STATIC_SUFFIXES):
        return True
    return False


def is_internal_or_owner_request(app: Optional[Flask] = None) -> bool:
    """
    Returns True if the active HTTP request originates from:
    1. The internal `admin` operations hub service itself.
    2. Automated performance benchmarks (`X-HVL-Benchmark: 1` or `HVL-BenchmarkRunner` / `python-requests`).
    3. An authenticated non-demo site administrator / owner session (`ADMIN_EMAIL`, `ALLOWED_EMAILS`, or `family_id == 1` editor/admin).
    """
    if app is not None and str(app.config.get("HVL_SERVICE_NAME") or "").strip().lower() == "admin":
        return True

    if not has_request_context():
        return False

    try:
        if request.headers.get("X-HVL-Benchmark") == "1":
            return True
        ua = (request.headers.get("User-Agent") or "").strip().lower()
        if "hvl-benchmarkrunner" in ua or ua.startswith("python-requests/"):
            return True
    except Exception:
        pass

    try:
        if session.get("authenticated") and not session.get("is_demo"):
            raw_admin_emails = ",".join([
                os.getenv("ADMIN_EMAIL", ""),
                os.getenv("HVL_ADMIN_EMAIL", ""),
                os.getenv("ALLOWED_EMAILS", ""),
            ])
            admin_emails = {e.strip().lower() for e in raw_admin_emails.split(",") if e.strip()}
            user_email = str(session.get("user_email") or "").strip().lower()
            if user_email and user_email in admin_emails:
                return True

            fid = int(session.get("family_id") or session.get("user_family_id") or 0)
            role = str(session.get("role") or session.get("user_role") or "").strip().lower()
            universe = str(session.get("universe") or "public").strip().lower()
            if fid == 1 and role in ("admin", "editor") and universe == "public":
                return True
    except Exception:
        pass

    return False


def _should_record_telemetry(
    app: Flask,
    explicit_db_path: Optional[Union[str, Path]] = None,
) -> bool:
    enabled = app.config.get("TELEMETRY_ENABLED")
    if enabled is False:
        return False
    if is_internal_or_owner_request(app):
        return False
    if enabled is True:
        return True
    if explicit_db_path is not None or app.config.get("TELEMETRY_DB_PATH"):
        return True
    if app.config.get("TESTING"):
        return False
    return True


def _resolve_active_db_path(
    app: Flask,
    explicit_db_path: Optional[Union[str, Path]] = None,
) -> Optional[Union[str, Path]]:
    return app.config.get("TELEMETRY_DB_PATH") or explicit_db_path


def register_telemetry(
    app: Flask,
    service_name: str,
    *,
    slow_threshold_ms: float = 1000.0,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """
    Registers `before_request`, `after_request`, `teardown_request`, and
    `got_request_exception` hooks on `app` to record operational telemetry.
    Idempotent: safe to call multiple times on the same Flask app instance.
    """
    app.config.setdefault("HVL_SERVICE_NAME", str(service_name or "app"))
    app.config.setdefault("TELEMETRY_SLOW_THRESHOLD_MS", float(slow_threshold_ms))
    if db_path is not None:
        app.config["TELEMETRY_DB_PATH"] = str(db_path)

    if app.extensions.get("hvl_telemetry_registered"):
        return
    app.extensions["hvl_telemetry_registered"] = True

    def _on_request_exception(sender: Any, exception: BaseException, **extra: Any) -> None:
        try:
            g._hvl_exc_type = type(exception).__name__
            g._hvl_exc_detail = f"Unhandled {type(exception).__name__}"
        except Exception:
            pass

    got_request_exception.connect(_on_request_exception, app, weak=False)

    @app.before_request
    def _hvl_telemetry_before_request() -> None:
        g._hvl_req_start = time.perf_counter()

    @app.after_request
    def _hvl_telemetry_after_request(response: Response) -> Response:
        try:
            if not _should_record_telemetry(app, db_path):
                return response

            start = getattr(g, "_hvl_req_start", None)
            duration_ms = (
                (time.perf_counter() - start) * 1000.0 if start is not None else 0.0
            )
            svc = str(app.config.get("HVL_SERVICE_NAME") or service_name or "app")
            threshold = float(
                app.config.get("TELEMETRY_SLOW_THRESHOLD_MS", slow_threshold_ms)
            )
            active_db = _resolve_active_db_path(app, db_path)
            req_path = request.path or "/"
            req_method = request.method or "GET"
            status_code = int(response.status_code or 200)

            if status_code >= 500 and not getattr(g, "_hvl_error_recorded", False):
                err_type = getattr(g, "_hvl_exc_type", None) or f"HTTP{status_code}"
                detail = (
                    getattr(g, "_hvl_exc_detail", None)
                    or f"HTTP {status_code} on {req_method} {req_path}"
                )
                g._hvl_error_recorded = True
                record_telemetry_event(
                    service=svc,
                    event_type=EVENT_ERROR_500,
                    method=req_method,
                    path=req_path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    error_type=err_type,
                    detail=detail,
                    db_path=active_db,
                )
            elif status_code == 429 and not getattr(g, "_hvl_ratelimit_recorded", False):
                g._hvl_ratelimit_recorded = True
                record_telemetry_event(
                    service=svc,
                    event_type=EVENT_RATE_LIMIT,
                    method=req_method,
                    path=req_path,
                    status_code=429,
                    duration_ms=duration_ms,
                    error_type="RateLimitExceeded",
                    detail=f"HTTP 429 Rate Limit on {req_method} {req_path}",
                    db_path=active_db,
                )
            elif duration_ms >= threshold and not _is_static_asset_path(req_path):
                record_telemetry_event(
                    service=svc,
                    event_type=EVENT_SLOW_REQUEST,
                    method=req_method,
                    path=req_path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    error_type="SlowRequest",
                    detail=f"Slow response ({duration_ms:.1f}ms >= {threshold:.0f}ms)",
                    db_path=active_db,
                )
        except Exception as exc:
            logger.debug("Telemetry after_request hook skipped: %s", exc)
        return response

    @app.teardown_request
    def _hvl_telemetry_teardown_request(exc: Optional[BaseException] = None) -> None:
        if exc is None:
            return
        try:
            if getattr(g, "_hvl_error_recorded", False):
                return
            if not _should_record_telemetry(app, db_path):
                return

            start = getattr(g, "_hvl_req_start", None)
            duration_ms = (
                (time.perf_counter() - start) * 1000.0 if start is not None else 0.0
            )
            svc = str(app.config.get("HVL_SERVICE_NAME") or service_name or "app")
            active_db = _resolve_active_db_path(app, db_path)
            req_path = request.path or "/"
            req_method = request.method or "GET"
            err_type = type(exc).__name__

            g._hvl_error_recorded = True
            record_telemetry_event(
                service=svc,
                event_type=EVENT_ERROR_500,
                method=req_method,
                path=req_path,
                status_code=500,
                duration_ms=duration_ms,
                error_type=err_type,
                detail=f"Unhandled {err_type}",
                db_path=active_db,
            )
        except Exception as log_exc:
            logger.debug("Telemetry teardown_request hook skipped: %s", log_exc)
