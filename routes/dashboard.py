"""
Financial Dashboard, Net Worth, Holdings, Spending, and Scenario Slider APIs.
"""

from __future__ import annotations

import hashlib
import logging
from flask import Blueprint, Response, jsonify, render_template, request, send_from_directory, session

from config import APP_VERSION
import db
import forecast_cache
from hvl_common.ui.blueprint import STATIC_DIR as COMMON_STATIC_DIR
import monarch_service
from routes.helpers import (
    DB_PATH,
    editor_required,
    get_current_family_id,
    get_current_universe,
    login_required,
    sanitize_text,
)
from ssr.dashboard import (
    FRAGMENT_ETAG_DOMAINS,
    SECTION_METADATA,
    SLUG_TO_SECTION,
    VALID_FRAGMENTS,
    build_dashboard_api_payload,
    build_fragment_ssr_context,
    build_index_ssr_context,
    build_networth_history_payload,
    load_investment_policy_payload,
    save_investment_policy_payload,
)

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)

# Fragments whose output depends strictly on their declared domain versions and request.full_path
_FRAGMENT_ETAG_DOMAINS: dict[str, tuple[str, ...]] = FRAGMENT_ETAG_DOMAINS
_PRE_RENDER_ETAG_FRAGMENTS = frozenset(_FRAGMENT_ETAG_DOMAINS.keys())


def _widget_cookie_token() -> str:
    w_ov = request.cookies.get("hvl_widgets_overview") or ""
    w_sc = request.cookies.get("hvl_widgets_scenarios") or ""
    w_col = request.cookies.get("hvl_collapsed_charts") or ""
    if not (w_ov or w_sc or w_col):
        return ""
    return f"|w:{w_ov}:{w_sc}:{w_col}"


def _compute_state_etag(family_id: int, fragment_name: str = "") -> str:
    """Computes a weak ETag bound to APP_VERSION, universe, family_id, role, domain/state version, and URL."""
    domains = _FRAGMENT_ETAG_DOMAINS.get(fragment_name) if fragment_name else None
    if domains and family_id > 0:
        d_vers = forecast_cache.get_domain_versions(family_id)
        ver_token = ",".join(f"{d}:{d_vers.get(d, 1)}" for d in domains)
    else:
        ver = forecast_cache.get_state_version(family_id) if family_id > 0 else 0
        ver_token = f"v{ver}"
    uni = get_current_universe()
    is_demo = 1 if session.get("is_demo") else 0
    role = str(session.get("role") or "")
    raw = f"{APP_VERSION}:{uni}:{family_id}:{is_demo}:{role}:{ver_token}:{request.full_path}{_widget_cookie_token()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _short_circuit_304(etag: str) -> Response | None:
    """Returns an empty 304 Not Modified response if the client's If-None-Match matches `etag`."""
    if request.if_none_match and request.if_none_match.contains_weak(etag):
        resp = Response(status=304)
        resp.set_etag(etag, weak=True)
        resp.headers["Cache-Control"] = "private, no-cache"
        return resp
    return None


def _attach_state_etag(resp: Response, etag: str) -> Response:
    """Attaches a weak ETag and `Cache-Control: private, no-cache` header to `resp`."""
    resp.set_etag(etag, weak=True)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@dashboard_bp.route("/favicon.ico")
def favicon_view():
    """Serves the centralized application favicon from hvl_common."""
    return send_from_directory(str(COMMON_STATIC_DIR), "favicon.ico", mimetype="image/vnd.microsoft.icon")


@dashboard_bp.route("/hvl-logo-mark.svg")
def hvl_logo_mark_view():
    """Serves the centralized HVL SVG tab icon from hvl_common."""
    return send_from_directory(str(COMMON_STATIC_DIR), "hvl-logo-mark.svg", mimetype="image/svg+xml")


@dashboard_bp.route("/fo-logo-mark.svg")
def fo_logo_mark_view():
    """Serves the centralized Finances stacked squares SVG tab icon from hvl_common."""
    return send_from_directory(str(COMMON_STATIC_DIR), "fo-logo-mark.svg", mimetype="image/svg+xml")


def _record_tab_visit_telemetry(query_tab: str = "", path_slug: str = "") -> None:
    import config
    from flask import current_app
    if config.is_local_mode():
        return
    try:
        from db.telemetry import record_portal_telemetry_event
        from routes.auth import _is_site_admin_request
        from routes.helpers import is_sandbox_session, _is_demo_session
        uni = "admin" if _is_site_admin_request() else ("sandbox" if is_sandbox_session() else ("demo" if _is_demo_session() else "public"))
        sess_token = request.cookies.get("session") or ""
        sess_hash = hashlib.sha256(sess_token.encode("utf-8")).hexdigest()[:16] if sess_token else ""
        target_tab = query_tab or path_slug or "overview"
        if current_app and current_app.config.get("TESTING"):
            record_portal_telemetry_event(
                universe=uni, event_type="tab_visit", feature_key=target_tab, tab=target_tab, session_hash=sess_hash,
            )
        else:
            import background_jobs
            background_jobs.EXECUTOR.submit(
                record_portal_telemetry_event,
                universe=uni, event_type="tab_visit", feature_key=target_tab, tab=target_tab, session_hash=sess_hash,
            )
    except Exception:
        pass


def _compute_index_ver_token(family_id: int, path_slug: str, query_tab: str) -> str:
    """Computes a domain-scoped version token for the index shell and active tab."""
    target_slug = query_tab if (query_tab and query_tab in SLUG_TO_SECTION) else path_slug
    active_sec_id = SLUG_TO_SECTION.get(target_slug, "section-overview")
    index_domains = tuple(SECTION_METADATA.get(active_sec_id, {}).get("depends") or ("accounts", "balance_sheet")) + ("notifications",)
    fam_db = DB_PATH.for_family(family_id) if family_id > 0 else None
    d_vers = forecast_cache.get_domain_versions(family_id, state_db=fam_db) if family_id > 0 else {}
    return f"v{forecast_cache.get_state_version(family_id)}|" + ",".join(
        f"{d}:{d_vers.get(d, 1)}" for d in index_domains
    )


@dashboard_bp.route("/overview", endpoint="overview_view")
@dashboard_bp.route("/forecasting", endpoint="forecasting_view")
@dashboard_bp.route("/scenarios", endpoint="scenarios_view")
@dashboard_bp.route("/company-equity", endpoint="company_equity_view")
@dashboard_bp.route("/equity", endpoint="equity_view")
@dashboard_bp.route("/holdings", endpoint="holdings_view")
@dashboard_bp.route("/investments", endpoint="investments_view")
@dashboard_bp.route("/arbitrage", endpoint="arbitrage_view")
@dashboard_bp.route("/compensation", endpoint="compensation_view")
@dashboard_bp.route("/philanthropy", endpoint="philanthropy_view")
@dashboard_bp.route("/gifting", endpoint="gifting_view")
@dashboard_bp.route("/estate", endpoint="estate_view")
@dashboard_bp.route("/college", endpoint="college_view")
@dashboard_bp.route("/education", endpoint="education_view")
@dashboard_bp.route("/accounts", endpoint="accounts_view")
@dashboard_bp.route("/settings", endpoint="settings_view")
@dashboard_bp.route("/")
@login_required
def index_view():
    """Serves the Monarch Money-themed Family Office dashboard."""
    if session.get("authenticated") and session.get("user_email") and session.get("universe") == "public":
        if session.get("is_demo"):
            session["is_demo"] = False

    family_id = get_current_family_id()
    path_slug = request.path.strip("/").lower()
    query_tab = (request.args.get("tab") or request.args.get("section") or "").strip().lower()
    _record_tab_visit_telemetry(query_tab=query_tab, path_slug=path_slug)

    can_cache = bool(family_id > 0 and not session.get("is_sandbox"))
    user_email_key = (session.get("user_email") or "").strip().lower()
    cache_key = f"__index__:{APP_VERSION}:{get_current_universe()}:{1 if session.get('is_demo') else 0}:{session.get('role') or ''}:{user_email_key}:{path_slug}:{query_tab}{_widget_cookie_token()}"
    ver_tok = _compute_index_ver_token(family_id, path_slug, query_tab) if can_cache else ""
    state_etag = hashlib.sha256(f"{_compute_state_etag(family_id)}:{cache_key}:{ver_tok}".encode("utf-8")).hexdigest()[:20] if can_cache else ""
    if can_cache:
        not_modified = _short_circuit_304(state_etag)
        if not_modified is not None:
            return not_modified
        cached_html = forecast_cache.get_cached_fragment(family_id, cache_key, request.args, domain_ver_token=ver_tok)
        if cached_html is not None and isinstance(cached_html, str) and "<!DOCTYPE html>" in cached_html[:64]:
            return _attach_state_etag(Response(cached_html, status=200, mimetype="text/html"), state_etag)

    try:
        ctx = build_index_ssr_context(family_id=family_id, path_slug=path_slug, query_tab=query_tab)
        html = render_template("index.html", **ctx)
    except Exception as exc:
        logger.warning("Failed to render index.html for %s: %s", path_slug, exc)
        html = render_template("index.html", **build_index_ssr_context(family_id=family_id, path_slug="overview", query_tab=""))

    if can_cache:
        forecast_cache.set_cached_fragment(family_id, cache_key, html, request.args, domain_ver_token=ver_tok)
        return _attach_state_etag(Response(html, status=200, mimetype="text/html"), state_etag)
    return html



@dashboard_bp.route("/api/dashboard", methods=["GET"])
@login_required
def api_dashboard():
    """Returns the aggregated Family Office balance sheet and baseline valuation."""
    try:
        family_id = get_current_family_id()
        not_modified = _short_circuit_304(_compute_state_etag(family_id))
        if not_modified is not None:
            return not_modified
        cached = forecast_cache.get_cached_dashboard_payload(family_id)
        if cached is not None:
            return _attach_state_etag(jsonify(cached), _compute_state_etag(family_id))
        payload = build_dashboard_api_payload(family_id=family_id)
        forecast_cache.set_cached_dashboard_payload(family_id, payload)
        return _attach_state_etag(jsonify(payload), _compute_state_etag(family_id))
    except PermissionError:
        raise
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/holdings/policy", methods=["GET"])
@login_required
def api_get_investment_policy():
    """Returns the household's Investment Policy Statement (anchor preset, drift tolerance, deviations)."""
    try:
        family_id = get_current_family_id()
        not_modified = _short_circuit_304(_compute_state_etag(family_id))
        if not_modified is not None:
            return not_modified
        payload = load_investment_policy_payload(family_id=family_id)
        return _attach_state_etag(jsonify(payload), _compute_state_etag(family_id))
    except PermissionError:
        raise
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/holdings/policy", methods=["POST"])
@editor_required
def api_update_investment_policy():
    """Updates the household's Investment Policy Statement and deviation profile in SQLite."""
    try:
        if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
            return jsonify({"success": False, "error": "Investment policy cannot be changed in demo mode (read-only)."}), 403

        family_id = get_current_family_id()
        body = request.get_json() or {}
        return jsonify(save_investment_policy_payload(family_id=family_id, body=body))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@dashboard_bp.route("/api/networth/history", methods=["GET"])
@login_required
def api_networth_history():
    """Returns historical True Net Worth curves (annual, quarterly, monthly) and annual savings rate."""
    try:
        family_id = get_current_family_id()
        not_modified = _short_circuit_304(_compute_state_etag(family_id))
        if not_modified is not None:
            return not_modified
        granularity = sanitize_text(request.args.get("granularity") or "auto", max_length=20, field_name="Granularity") or "auto"
        payload = build_networth_history_payload(family_id=family_id, granularity=granularity)
        return _attach_state_etag(jsonify(payload), _compute_state_etag(family_id))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/fragments/<fragment_name>")
@login_required
def get_fragment_view(fragment_name: str):
    """Serves on-demand HTML component fragments for lazy hydration."""
    family_id = get_current_family_id()
    if fragment_name == "notifications":
        from routes.notifications import get_session_notifications, render_notifications_fragment_response
        return render_notifications_fragment_response(get_session_notifications(family_id))
    is_pre_etag = fragment_name in _PRE_RENDER_ETAG_FRAGMENTS
    frag_cache_key = f"{fragment_name}{_widget_cookie_token()}"
    if is_pre_etag:
        etag = _compute_state_etag(family_id, fragment_name)
        not_modified = _short_circuit_304(etag)
        if not_modified is not None:
            return not_modified
        cached_html = forecast_cache.get_cached_fragment(family_id, frag_cache_key, request.args)
        if cached_html is not None:
            return _attach_state_etag(Response(cached_html, status=200, mimetype="text/html"), etag)

    tpl, ctx = build_fragment_ssr_context(
        fragment_name=fragment_name,
        family_id=family_id,
        query_args=request.args,
    )
    if not tpl:
        return jsonify({"error": "Fragment not found"}), 404

    _record_tab_visit_telemetry(query_tab=fragment_name.strip().lower(), path_slug="")

    html = render_template(tpl, **ctx)
    if is_pre_etag:
        forecast_cache.set_cached_fragment(family_id, frag_cache_key, html, request.args)
        etag = _compute_state_etag(family_id, fragment_name)
    else:
        etag = hashlib.sha256(html.encode("utf-8")).hexdigest()[:20]
        not_modified = _short_circuit_304(etag)
        if not_modified is not None:
            return not_modified
    return _attach_state_etag(Response(html, status=200, mimetype="text/html"), etag)


@dashboard_bp.route("/api/telemetry/action", methods=["POST"])
def api_telemetry_action_view():
    """Zero-PII client interaction and feature action recording."""
    import config
    if config.is_local_mode():
        return jsonify({"ok": True})
    try:
        data = request.get_json(silent=True) or {}
        act = str(data.get("action") or "").strip()[:50]
        tab = str(data.get("tab") or "").strip()[:50]
        mod = str(data.get("modal") or "").strip()[:50]
        feat = str(data.get("feature_key") or act or "").strip()[:50]
        if act or tab or mod:
            from db.telemetry import record_portal_telemetry_event
            from routes.auth import _is_site_admin_request
            from routes.helpers import is_sandbox_session, _is_demo_session
            is_sb = is_sandbox_session() or request.args.get("sandbox") == "1"
            is_dm = _is_demo_session() or request.args.get("demo") == "1"
            uni = "admin" if _is_site_admin_request() else ("sandbox" if is_sb else ("demo" if is_dm else "public"))
            sess_token = request.cookies.get("session") or request.cookies.get("session_id") or request.cookies.get("fo_vault_fek") or ""
            sess_hash = hashlib.sha256(sess_token.encode("utf-8")).hexdigest()[:16] if sess_token else ""
            record_portal_telemetry_event(
                universe=uni,
                event_type="action",
                feature_key=feat,
                tab=tab,
                action=act,
                modal=mod,
                session_hash=sess_hash,
            )
    except Exception:
        pass
    return jsonify({"ok": True})


from routes.accounts import (  # noqa: E402, F401
    _invalidate_family_forecast_cache,
    _invoke_monarch_sync,
    _invoke_simplefin_sync,
    _parse_snapshot_item,
    _run_unified_account_sync,
    api_accounts_toggle_net_worth,
    api_delete_accounts_history,
    api_delete_manual_account,
    api_export_accounts_csv,
    api_get_accounts_history,
    api_import_accounts_csv,
    api_post_accounts_history,
    api_sync,
    api_sync_status,
    api_upsert_manual_account,
)

