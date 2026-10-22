"""
Authentication Routes (Passkey, Session Management).
"""

from __future__ import annotations

from pathlib import Path
from flask import Blueprint, jsonify, render_template, redirect, request, url_for, session
from hvl_common.web import rate_limit
from routes.helpers import DB_PATH, get_current_family_id, get_current_universe, sanitize_text
import security
from services.auth_helpers import (
    DEMO_PERSONAS,
    _apply_universe_switch_session,
    _is_site_admin_request,
    _normalize_target_universe,
    _resolve_persona_id,
    _resolve_verified_admin_email,
    ensure_demo_database,
    is_beta_gate_authorized,
    maybe_attach_admin_gate_cookie,
)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/invite/<code>")
@rate_limit("20/min")
def invite_landing_view(code: str):
    """Validates a Magic Invite link and redirects to /login with the active invite stored in session."""
    clean_code = sanitize_text(code, 64, "code").upper()
    token = security.validate_invite_token(Path(DB_PATH), clean_code) if clean_code else None
    if token:
        session["pending_invite_code"] = token["code"]
        return redirect(f"/login?invite={token['code']}")
    session.pop("pending_invite_code", None)
    return redirect("/login?invite_error=1")


@auth_bp.route("/login")
@rate_limit("20/min")
def login_view():
    """Serves the login page with WebAuthn Passkeys, Google OAuth, and optional Magic Invite context."""
    raw_invite = sanitize_text(request.args.get("invite"), 64, "invite").upper()
    invite_error_flag = request.args.get("invite_error") == "1"
    invite_info = None
    invite_error = None

    if raw_invite:
        token = security.validate_invite_token(Path(DB_PATH), raw_invite)
        if token:
            session["pending_invite_code"] = token["code"]
            invite_info = token
        else:
            session.pop("pending_invite_code", None)
            invite_error = "This invite code is invalid, expired, or has already been redeemed."
    elif invite_error_flag:
        session.pop("pending_invite_code", None)
        invite_error = "This invite code is invalid, expired, or has already been redeemed."
    elif session.get("pending_invite_code"):
        token = security.validate_invite_token(Path(DB_PATH), str(session.get("pending_invite_code")))
        if token:
            invite_info = token
        else:
            session.pop("pending_invite_code", None)

    if session.get("authenticated") and not session.get("is_demo") and not raw_invite:
        try:
            return redirect(url_for("dashboard.index_view"))
        except Exception:
            return redirect("/")

    import config
    from routes.desktop import has_local_passphrase_configured, is_local_vault_unclaimed

    local_mode = config.is_local_mode()
    has_passphrase = has_local_passphrase_configured(Path(DB_PATH)) if local_mode else False
    vault_unclaimed = (is_local_vault_unclaimed(Path(DB_PATH)) and not has_passphrase) if local_mode else False
    return render_template(
        "login.html",
        invite_info=invite_info,
        invite_error=invite_error,
        is_local_mode=local_mode,
        local_vault_unclaimed=vault_unclaimed,
        has_local_passphrase=has_passphrase,
    )


@auth_bp.route("/features")
def features_view():
    """Serves the public features, architecture, and capabilities showcase page."""
    import config
    from ssr.dashboard import parse_changelog_releases
    return render_template(
        "features.html",
        demo_personas=DEMO_PERSONAS,
        is_authenticated=bool(session.get("authenticated")),
        is_demo=bool(session.get("is_demo")),
        app_version=config.APP_VERSION,
        changelog_releases=parse_changelog_releases(max_releases=3),
    )


@auth_bp.route("/help")
def help_view():
    """Serves the public & offline User Guide, Setup Manual, and Troubleshooting Knowledge Base."""
    import config
    return render_template(
        "help.html",
        is_authenticated=bool(session.get("authenticated")),
        is_demo=bool(session.get("is_demo")),
        is_local_mode=config.is_local_mode(),
        app_version=config.APP_VERSION,
    )


@auth_bp.route("/helm")
def helm_comparison_view():
    """Serves the unlisted AI-generated builder comparison page between Helm and HVL Family Office."""
    import config
    return render_template(
        "helm.html",
        is_authenticated=bool(session.get("authenticated")),
        is_demo=bool(session.get("is_demo")),
        is_local_mode=config.is_local_mode(),
        app_version=config.APP_VERSION,
    )


@auth_bp.route("/projectionlab")
@auth_bp.route("/projection-lab")
def projectionlab_comparison_view():
    """Serves the unlisted AI-generated builder comparison page between ProjectionLab and HVL Family Office."""
    import config
    return render_template(
        "projectionlab.html",
        is_authenticated=bool(session.get("authenticated")),
        is_demo=bool(session.get("is_demo")),
        is_local_mode=config.is_local_mode(),
        app_version=config.APP_VERSION,
    )


@auth_bp.route("/playbooks")
@auth_bp.route("/scenarios-guide")
def scenario_playbooks_view():
    """Serves the Scenario Planning Playbooks & Common What-Ifs guide page."""
    import config
    return render_template(
        "playbooks.html",
        is_authenticated=bool(session.get("authenticated")),
        is_demo=bool(session.get("is_demo")),
        is_local_mode=config.is_local_mode(),
        app_version=config.APP_VERSION,
    )


@auth_bp.route("/beta-gate")
@rate_limit("30/min")
def beta_gate_view():
    """Serves a minimal Site-Administrator gate page on `finances-beta`."""
    if is_beta_gate_authorized():
        return redirect("/")
    from auth_google import get_oauth_credentials
    client_id, _ = get_oauth_credentials()
    return render_template("beta_gate.html", google_client_id=client_id), 403


@auth_bp.route("/whats-new")
@auth_bp.route("/changes")
def whats_new_view():
    """Serves the Customer-Facing Public Visual Release Notes page."""
    import config
    from ssr.dashboard import parse_changelog_releases
    return render_template(
        "whats_new.html",
        is_authenticated=bool(session.get("authenticated")),
        is_demo=bool(session.get("is_demo")),
        is_local_mode=config.is_local_mode(),
        is_site_admin=_is_site_admin_request(),
        app_version=config.APP_VERSION,
        changelog_releases=parse_changelog_releases(max_releases=16),
    )


@auth_bp.route("/admin/release-review")
def admin_release_review_view():
    """Serves the Site-Admin-Only Pre-Deploy Copy & UI Review page."""
    import config
    from ssr.dashboard import parse_changelog_releases
    if not _is_site_admin_request():
        if not session.get("authenticated"):
            return redirect(url_for("auth.login_view", next=request.path))
        return jsonify({"success": False, "error": "Site administrator privileges required."}), 403
    return render_template(
        "admin_release_review.html",
        is_authenticated=bool(session.get("authenticated")),
        is_demo=bool(session.get("is_demo")),
        is_local_mode=config.is_local_mode(),
        is_site_admin=True,
        app_version=config.APP_VERSION,
        changelog_releases=parse_changelog_releases(max_releases=16),
    )


@auth_bp.route("/privacy")
def privacy_view():
    """Redirects to the central High Velocity Labs master Privacy Policy."""
    return redirect("https://highvelocitylabs.dev/privacy", code=301)


@auth_bp.route("/terms")
def terms_view():
    """Redirects to the central High Velocity Labs master Terms of Service."""
    return redirect("https://highvelocitylabs.dev/terms", code=301)


@auth_bp.route("/download/<target>")
@rate_limit("30/min")
def download_redirect_view(target: str):
    """Logs an anonymous customer download or GitHub link click in `global.db` and redirects (`302`)."""
    import config
    from db.telemetry import resolve_download_redirect_target, resolve_telemetry_db_path
    raw_target = sanitize_text(target, 32, "target").lower()
    norm_target, dest = resolve_download_redirect_target(
        raw_target, config.GITHUB_REPO_SLUG, direct=(request.args.get("direct") == "1")
    )
    ref_hint = sanitize_text(request.args.get("ref") or request.referrer or "", 200)
    ua_hint = sanitize_text(request.headers.get("User-Agent") or "", 200)

    is_admin_or_internal = (
        request.headers.get("X-HVL-Benchmark") == "1"
        or "hvl-benchmark" in ua_hint.lower()
        or bool(session.get("authenticated") and not session.get("is_demo") and _is_site_admin_request())
    )
    if not is_admin_or_internal:
        try:
            security.record_download_event(
                resolve_telemetry_db_path(),
                target=norm_target,
                app_version=config.APP_VERSION,
                referrer=ref_hint,
                user_agent=ua_hint,
            )
        except Exception:
            pass

    return redirect(dest, code=302)


@auth_bp.route("/api/auth/logout", methods=["POST"])
@rate_limit("20/min")
def auth_logout():
    session.clear()
    resp = jsonify({"success": True})
    import config
    import security
    sec_cookie = getattr(security, "VAULT_COOKIE_NAME", "hvl_vault_fek")
    cfg_cookie = getattr(config, "get_vault_cookie_name", lambda: "hvl_vault_fek")()
    for c in {sec_cookie, cfg_cookie, "hvl_vault_fek", "hvl_vault_fek_beta"}:
        resp.delete_cookie(c, path="/")
    return resp


@auth_bp.route("/demo")
@auth_bp.route("/demo/<slug>")
def demo_view(slug: str | None = None):
    """Public entry point for exploring demo personas in the Demo universe."""
    if slug and ("." in slug or len(slug) > 32):
        from flask import abort
        abort(404)
    ensure_demo_database()
    target_id = _resolve_persona_id(slug or request.args.get("family_id") or request.args.get("persona"))
    persona = next((p for p in DEMO_PERSONAS if p["id"] == target_id), DEMO_PERSONAS[0])

    was_authenticated = bool(session.get("authenticated") and not session.get("is_demo"))
    prev_user = session.get("user") if was_authenticated else session.get("prev_user")
    prev_user_email = session.get("user_email") if was_authenticated else session.get("prev_user_email")
    prev_user_role = session.get("user_role") if was_authenticated else session.get("prev_user_role")
    prev_user_family_id = session.get("user_family_id") if was_authenticated else session.get("prev_user_family_id")
    prev_auth_method = session.get("auth_method") if was_authenticated else session.get("prev_auth_method")

    session.clear()
    if prev_user:
        session["prev_user"] = prev_user
        session["prev_user_email"] = prev_user_email
        session["prev_user_role"] = prev_user_role
        session["prev_user_family_id"] = prev_user_family_id
        session["prev_auth_method"] = prev_auth_method

    session["authenticated"] = True
    session["user"] = "Demo Guest"
    session["user_display"] = f"Demo Guest ({persona['name']})"
    session["role"] = "viewer"
    session["user_role"] = "viewer"
    session["universe"] = "demo"
    session["family_id"] = target_id
    session["is_demo"] = True
    session["auth_method"] = "Demo Mode"
    session.permanent = False
    try:
        return redirect(url_for("dashboard.index_view", demo=1))
    except Exception:
        return redirect("/?demo=1")


@auth_bp.route("/api/demo/families", methods=["GET"])
def api_demo_families():
    """Returns metadata for all available demo personas."""
    ensure_demo_database()
    return jsonify({
        "success": True,
        "current_family_id": get_current_family_id(),
        "current_universe": get_current_universe(),
        "is_demo": bool(session.get("is_demo", False)),
        "families": DEMO_PERSONAS,
    })


@auth_bp.route("/exit-demo")
def exit_demo():
    """Restores real family account session or redirects to login."""
    if session.get("prev_user"):
        session["user"] = session.pop("prev_user")
        session["user_email"] = session.pop("prev_user_email", "")
        session["user_role"] = session.pop("prev_user_role", "admin")
        session["role"] = session.get("user_role", "admin")
        session["family_id"] = int(session.pop("prev_user_family_id", 1))
        session["user_family_id"] = session["family_id"]
        session["universe"] = "public"
        session["is_demo"] = False
        session["authenticated"] = True
        session["auth_method"] = session.pop("prev_auth_method", "Authenticated")
        session.permanent = True
        try:
            return redirect(url_for("dashboard.index_view"))
        except Exception:
            return redirect("/")

    session.clear()
    try:
        return redirect(url_for("auth.login_view"))
    except Exception:
        return redirect("/login")


@auth_bp.route("/api/admin/switch_universe", methods=["POST"])
@auth_bp.route("/api/admin/switch-universe", methods=["POST"])
@auth_bp.route("/switch-universe", methods=["POST"])
@rate_limit("20/min")
def admin_switch_universe():
    """Allows authenticated admin users to switch between 'public', 'demo', 'sandbox', and 'test' universes."""
    if not session.get("authenticated"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    current_role = session.get("role") or session.get("user_role") or "viewer"
    if current_role not in ("admin", "editor") or session.get("is_demo"):
        return jsonify({"success": False, "error": "Forbidden: Admin required"}), 403

    body = request.get_json() or {}
    target_universe = _normalize_target_universe(str(body.get("universe", "demo")).strip().lower())
    if target_universe not in ("public", "demo", "sandbox", "test"):
        return jsonify({"success": False, "error": f"Invalid universe '{target_universe}'"}), 400

    own_fid = int(session.get("user_family_id") or session.get("family_id") or 0)
    payload, status_code = _apply_universe_switch_session(target_universe, body, own_fid)
    return jsonify(payload), status_code


@auth_bp.route("/api/auth/status", methods=["GET"])
def auth_status():
    if not session.get("authenticated"):
        return jsonify({
            "authenticated": False,
            "user": None,
            "role": None,
            "family_id": None,
            "universe": None,
            "is_demo": False,
            "auth_method": None,
        })
    return jsonify({
        "authenticated": True,
        "user": session.get("user"),
        "role": session.get("role", "viewer"),
        "family_id": get_current_family_id(),
        "universe": get_current_universe(),
        "is_demo": bool(session.get("is_demo", False)),
        "auth_method": session.get("auth_method"),
    })
