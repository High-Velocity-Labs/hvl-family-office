"""
HVL Family Office Web Application Backend (Flask)
Hosted on production server via Apache CGI / Passenger WSGI.
Exposes REST APIs and serves Monarch Money-themed dashboard.
"""

from __future__ import annotations
import os
import subprocess
import time
from flask import Flask, g, jsonify, request, redirect, session

from config import (
    BASE_DIR,
    DATA_DIR,
    DB_PATH,
    STATIC_DIR,
    TEMPLATES_DIR,
    FLASK_SECRET_KEY,
    PERMANENT_SESSION_LIFETIME,
    is_local_mode,
)
from hvl_common.ui.blueprint import _ICON_SYMBOLS
from hvl_common.web import (
    apply_hvl_security_headers,
    compute_asset_version,
    create_hvl_lifecycle_blueprint,
)
from auth_google import auth_google_bp
from routes import register_blueprints
from routes.helpers import login_required, editor_required
from routes.auth import login_view, features_view, privacy_view, terms_view
from routes.dashboard import index_view

_ICON_SYMBOLS["icon-shared-bug"] = (
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"',
    '<rect x="8" y="8" width="8" height="11" rx="4" fill="currentColor" fill-opacity="0.10"/>'
    '<path d="M10 8V7a2 2 0 0 1 4 0v1"/><path d="M5.5 11.5H8"/><path d="M16 11.5h2.5"/>'
    '<path d="M5.5 15.5H8"/><path d="M16 15.5h2.5"/>',
)


def _compute_asset_version() -> str:
    return compute_asset_version(BASE_DIR)


ASSET_VERSION = _compute_asset_version()

__all__ = [
    "app",
    "create_app",
    "BASE_DIR",
    "DATA_DIR",
    "DB_PATH",
    "login_required",
    "editor_required",
]


def create_app() -> Flask:
    """Factory to create and configure the Flask application."""
    app = Flask(
        __name__,
        static_folder=str(STATIC_DIR),
        template_folder=str(TEMPLATES_DIR),
    )

    # Session security & configuration
    import config as _cfg
    app.secret_key = FLASK_SECRET_KEY
    app.config["SESSION_COOKIE_NAME"] = "finances_beta_session" if _cfg.is_beta_instance() else "session"
    app.config["PERMANENT_SESSION_LIFETIME"] = PERMANENT_SESSION_LIFETIME
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    is_dev = os.getenv("FLASK_ENV", "development") == "development" or os.getenv("FLASK_DEBUG", "0") == "1"

    # Environment-specific caching & template reloading
    if is_dev:
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    else:
        app.config["TEMPLATES_AUTO_RELOAD"] = False
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 43200  # 12 hours in production
        app.config["SESSION_COOKIE_SECURE"] = True

    # 16 MB maximum file upload cap (DoS protection)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    @app.context_processor
    def inject_global_template_context():
        import config
        local_flag = config.is_local_mode()
        beta_flag = config.is_beta_instance()
        is_site_admin = False
        domain_versions = {}
        try:
            from routes.auth import _is_site_admin_request
            is_site_admin = _is_site_admin_request()
        except Exception:
            pass
        try:
            import forecast_cache
            from routes.helpers import get_current_family_id
            domain_versions = forecast_cache.get_domain_versions(get_current_family_id())
        except Exception:
            pass
        return {
            "asset_v": ASSET_VERSION,
            "local_mode": local_flag,
            "is_local_mode": local_flag,
            "is_beta_instance": beta_flag,
            "is_site_admin": is_site_admin,
            "domain_versions": domain_versions,
        }

    _BETA_GATE_PUBLIC_EXACT = {
        "/health",
        "/api/health",
        "/healthz",
        "/api/version",
        "/beta-gate",
        "/favicon.ico",
        "/robots.txt",
        "/fo-logo-mark.svg",
        "/hvl-logo-mark.svg",
    }

    @app.before_request
    def enforce_beta_instance_gate():
        import config
        if not config.is_beta_instance() or app.config.get("TESTING"):
            return None
        path = request.path or "/"
        if path in _BETA_GATE_PUBLIC_EXACT or path.startswith(("/static/", "/common/", "/auth/google", "/mcp")):
            return None
        # Allow automated benchmark runner and site admins with valid session or cross-subdomain gate cookie
        ua = (request.headers.get("User-Agent") or "").strip().lower()
        if request.headers.get("X-HVL-Benchmark") == "1" or "hvl-benchmarkrunner" in ua:
            return None

        from routes.auth import is_beta_gate_authorized
        if is_beta_gate_authorized():
            return None

        if path.startswith(("/api/", "/fragments/")):
            return jsonify({"error": "Forbidden: Beta instance requires Site Administrator authorization.", "beta_gate": True}), 403
        return redirect("/beta-gate")

    # Global Security Headers & Cryptographic Vault Cookie Attachment
    @app.after_request
    def set_security_headers(response):
        import config
        cookie_val = getattr(g, "_pending_vault_cookie", None)
        if cookie_val:
            is_sec = bool(request.is_secure or request.headers.get("X-Forwarded-Proto") == "https")
            response.set_cookie(
                config.get_vault_cookie_name(),
                str(cookie_val),
                max_age=400 * 24 * 3600,
                httponly=True,
                secure=is_sec,
                samesite="Lax",
            )
        response.headers["X-App-Version"] = ASSET_VERSION
        if request.path.startswith(("/api/", "/fragments/")) and request.path != "/api/health":
            try:
                import json as _json
                import forecast_cache
                from routes.helpers import get_current_family_id
                fid = get_current_family_id()
                if fid and int(fid) > 0:
                    response.headers["X-Domain-Versions"] = _json.dumps(
                        forecast_cache.get_domain_versions(int(fid)),
                        separators=(",", ":"),
                    )
            except Exception:
                pass
        try:
            from routes.auth import maybe_attach_admin_gate_cookie
            maybe_attach_admin_gate_cookie(response)
        except Exception:
            pass
        return apply_hvl_security_headers(
            response,
            is_dev=bool(is_dev or config.is_beta_instance()),
            asset_version=ASSET_VERSION,
            frame_options="DENY",
        )

    # Register Google OAuth Blueprint
    app.register_blueprint(auth_google_bp)

    # Register Shared HVL Design System Blueprint (/common/theme.css)
    from hvl_common.ui import ui_bp
    app.register_blueprint(ui_bp)

    # Register Shared HVL Operational Telemetry Middleware (hosted web services only; strictly bypassed in local desktop mode)
    if not is_local_mode():
        from hvl_common.telemetry import register_telemetry
        import config as _cfg
        _tel_service = os.getenv("HVL_TELEMETRY_SERVICE", "").strip() or (
            "finances-beta" if _cfg.is_beta_instance() else "finances"
        )
        register_telemetry(app, _tel_service)
    else:
        app.config["TELEMETRY_ENABLED"] = False

    # Register all modular route Blueprints
    register_blueprints(app)

    app.register_blueprint(
        create_hvl_lifecycle_blueprint(
            service_name=lambda: "finances-beta" if _cfg.is_beta_instance() else "finances",
            is_beta_fn=_cfg.is_beta_instance,
            asset_version_fn=lambda: ASSET_VERSION,
        )
    )

    # Provide direct URL rule aliases for backwards compatibility with url_for('login_view'), url_for('features_view'), and url_for('index_view')
    app.add_url_rule("/login", endpoint="login_view", view_func=login_view)
    app.add_url_rule("/features", endpoint="features_view", view_func=features_view)
    app.add_url_rule("/privacy", endpoint="privacy_view", view_func=privacy_view)
    app.add_url_rule("/terms", endpoint="terms_view", view_func=terms_view)
    app.add_url_rule("/", endpoint="index_view", view_func=index_view)

    # Global Error Handlers
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Resource not found"}), 404
        # Browser probing / unknown routes: redirect cleanly instead of exposing raw JSON
        if session.get("authenticated") and not session.get("is_demo"):
            return redirect("/")
        return redirect("/login")

    @app.errorhandler(PermissionError)
    def handle_permission_error(e):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "error": str(e), "vault_locked": True}), 403
        return redirect("/login")

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500

    # Transparently support /finances subdirectory prefix and /public alias
    original_wsgi_app = app.wsgi_app

    def prefix_middleware(environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path.startswith("/finances"):
            sub_path = path[len("/finances"):]
            environ["PATH_INFO"] = sub_path if sub_path else "/"
        elif path == "/public":
            environ["PATH_INFO"] = "/"
        return original_wsgi_app(environ, start_response)

    app.wsgi_app = prefix_middleware

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5055))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=debug)
