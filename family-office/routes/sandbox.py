"""
Interactive Ephemeral Sandbox Route Blueprint.
Provides zero-login sandbox provisioning, 7-day retention, immediate wipe, and vault restore.
Strictly disabled when running in Local Desktop Mode.
"""

from __future__ import annotations

import logging
from cryptography.fernet import Fernet
from flask import Blueprint, g, jsonify, redirect, render_template, request, session
from hvl_common.security import VAULT_COOKIE_NAME, unwrap_cookie_fek, wrap_cookie_fek
from hvl_common.web.rate_limit import _default_limiter

import config
import security
from db.telemetry import record_portal_telemetry_event
from routes.context import editor_required, get_current_family_id, is_sandbox_session, sanitize_text
from services.sandbox_service import (
    SandboxCapacityError,
    bind_sandbox_key,
    create_sandbox_session,
    extend_sandbox_lease_7d,
    get_sandbox_lease_info,
    reserve_sandbox_restore_fid,
    restore_sandbox_from_fovault_bytes,
    sandbox_key_matches,
    wipe_sandbox_immediately,
)

logger = logging.getLogger(__name__)

sandbox_bp = Blueprint("sandbox", __name__)
SANDBOX_FID_COOKIE = "hvl_sandbox_fid"
SANDBOX_RESUME_LIMIT = "60/hr"


def _set_vault_fek_cookie(response, raw_fek: bytes, max_age: int = 86400, fid: int = 0) -> None:
    """Attaches the FEK and sandbox family_id to HttpOnly cookies so the server never retains decryption keys."""
    wrapped = wrap_cookie_fek(raw_fek, security.get_or_create_key())
    cookie_name = getattr(config, "get_vault_cookie_name", lambda: VAULT_COOKIE_NAME)()
    is_sec = bool(request.is_secure or request.headers.get("X-Forwarded-Proto") == "https")
    for c_name in {VAULT_COOKIE_NAME, cookie_name}:
        response.set_cookie(c_name, wrapped, max_age=max_age, httponly=True, samesite="Lax", secure=is_sec, path="/")
    if fid > 0:
        bind_sandbox_key(fid, raw_fek)
        g.sandbox_cookies_issued = True
        response.set_cookie(SANDBOX_FID_COOKIE, str(fid), max_age=max_age, httponly=True, samesite="Lax", secure=is_sec, path="/")


def _unwrap_sandbox_fek(wrapped_fek: str) -> bytes | None:
    """Unwraps a key cookie with the current or any previous server key; None if it is not one of ours."""
    raw_root = security.get_or_create_key()
    keks = list(security._parse_fernet_keys(raw_root))
    if raw_root and raw_root not in keks:
        keks.append(raw_root)
    return next((fek for fek in (unwrap_cookie_fek(wrapped_fek, k) for k in keks) if fek), None)


def get_resumable_sandbox_lease() -> tuple[int, bytes | None, dict | None]:
    """
    Detects whether the current browser has an active, non-expired sandbox session
    (either active in session or preserved via cookies across /login or Demo mode).
    The key must be the one bound to that sandbox id; any other key is refused and its cookies are cleared.
    Returns (family_id, raw_fek, lease_dict).
    """
    if config.is_local_mode():
        return 0, None, None

    fid = get_current_family_id() if is_sandbox_session() else 0
    if fid <= 0 and request.cookies.get(SANDBOX_FID_COOKIE, "").isdigit():
        fid = int(request.cookies[SANDBOX_FID_COOKIE])
    if fid <= 0:
        return 0, None, None

    cookie_name = getattr(config, "get_vault_cookie_name", lambda: VAULT_COOKIE_NAME)()
    wrapped_fek = (
        request.cookies.get(cookie_name)
        or request.cookies.get(VAULT_COOKIE_NAME)
        or (session.get("vault_fek") if session.get("vault_fek_family_id") == fid else None)
    )
    if not wrapped_fek:
        return 0, None, None

    raw_fek = _unwrap_sandbox_fek(wrapped_fek)
    lease = get_sandbox_lease_info(fid) if raw_fek and sandbox_key_matches(fid, raw_fek) else None
    if not lease or lease.get("remaining_seconds", 0) <= 0:
        g.sandbox_cookies_rejected = True
        return 0, None, None
    return fid, raw_fek, lease


@sandbox_bp.after_request
def _clear_rejected_sandbox_cookies(response):
    """Drops stale or foreign sandbox cookies once a resume attempt was refused, unless a fresh sandbox was just issued."""
    if g.get("sandbox_cookies_rejected") and not g.get("sandbox_cookies_issued"):
        cookie_name = getattr(config, "get_vault_cookie_name", lambda: VAULT_COOKIE_NAME)()
        for c in {VAULT_COOKIE_NAME, cookie_name, SANDBOX_FID_COOKIE}:
            response.delete_cookie(c, path="/")
    return response


def _check_rate_limit(scope: str, limit_str: str = "20/hr") -> tuple[bool, int]:
    """Evaluates an IP rate limit and logs a telemetry event on rejection."""
    if config.is_local_mode():
        return True, 0
    allowed, retry_after, _ = _default_limiter.evaluate(limit_str, scope=scope)
    if not allowed:
        record_portal_telemetry_event("sandbox", "rate_limit_hit", feature_key=scope)
    return allowed, retry_after


def _initialize_sandbox_session(fid: int, raw_fek: bytes) -> None:
    """Initializes standard in-memory session keys for an ephemeral sandbox household."""
    session.clear()
    session["authenticated"] = True
    session["is_sandbox"] = True
    session["is_demo"] = False
    session["universe"] = "sandbox"
    session["user_id"] = fid
    session["family_id"] = fid
    session["user_family_id"] = fid
    session["role"] = "editor"
    session["user_role"] = "editor"
    session["vault_fek"] = wrap_cookie_fek(raw_fek, security.get_or_create_key())
    session["vault_fek_family_id"] = fid
    try:
        from flask import g
        active_feks = getattr(g, "_active_vault_feks", None)
        if not isinstance(active_feks, dict):
            active_feks = {}
            g._active_vault_feks = active_feks
        active_feks[int(fid)] = raw_fek
    except Exception:
        pass


def _handle_async_sandbox_restore(raw_bytes: bytes, restore_fek: bytes | None, target_fid: int = 0, is_cloud: bool = False):
    """
    Offloads sandbox or Cloud Vault restore to a non-blocking background job (`SQLiteJobPool`).
    The FEK was unwrapped in this request and never enters the job ticket or result: for a sandbox restore the
    household id is reserved here and the browser gets the FEK cookie on this very response.
    """
    from services.fovault_service import submit_async_fovault_restore_job

    if is_cloud:
        job_id = submit_async_fovault_restore_job(raw_bytes, restore_fek, target_fid=target_fid, is_cloud=True)
        return jsonify({"success": True, "job_id": job_id, "status": "processing"})
    try:
        fid = reserve_sandbox_restore_fid(target_fid)
    except SandboxCapacityError as e:
        return jsonify({"success": False, "error": str(e)}), 503
    sandbox_fek = restore_fek if restore_fek is not None else Fernet.generate_key()
    # Session first: the job ticket is stored in the cache DB that the polling requests (same session) will read.
    _initialize_sandbox_session(fid, sandbox_fek)
    job_id = submit_async_fovault_restore_job(raw_bytes, sandbox_fek, target_fid=fid, is_cloud=False)
    resp = jsonify({"success": True, "job_id": job_id, "status": "processing", "family_id": fid})
    _set_vault_fek_cookie(resp, sandbox_fek, max_age=86400, fid=fid)
    return resp


@sandbox_bp.route("/api/sandbox/jobs/<job_id>", methods=["GET"])
@sandbox_bp.route("/api/jobs/<job_id>", methods=["GET"])
def api_sandbox_job_status(job_id: str):
    """Polls a background sandbox or vault restore job and attaches the updated FEK cookie on completion."""
    from services import background_jobs

    fid = get_current_family_id()
    if fid <= 0:
        return jsonify({"success": False, "status": "not_found", "error": "Job not found."}), 404
    clean_id = sanitize_text(job_id, max_length=64, field_name="Job ID")
    job = background_jobs.get_job(clean_id, family_id=fid)
    if not job:
        return jsonify({"success": False, "status": "not_found", "error": "Job not found."}), 404
    if job["status"] == "processing":
        return jsonify({"success": True, "status": "processing", "job_id": clean_id})
    if job["status"] == "failed":
        return jsonify({"success": False, "status": "failed", "job_id": clean_id, "error": job.get("error") or "Vault restore failed."}), 400

    res_payload = dict(job.get("result") or {})
    is_sb_restore = bool(res_payload.pop("is_sandbox_restore", is_sandbox_session()))
    new_fid = int(res_payload.get("family_id") or fid or 0)
    if is_sb_restore and new_fid > 0 and "summary" not in res_payload:
        from services.fovault_service import get_vault_import_summary
        summary = get_vault_import_summary(
            config.get_family_db_path(new_fid, "sandbox"), new_fid, raw_fek=security.get_request_vault_fek(new_fid)
        )
        res_payload["summary"] = summary
        res_payload["message"] = summary.get("summary_text", res_payload.get("message"))
    return jsonify({**res_payload, "success": True, "status": "completed", "job_id": clean_id})


@sandbox_bp.route("/sandbox", methods=["GET"])
@sandbox_bp.route("/sandbox/start", methods=["POST"])
@sandbox_bp.route("/api/sandbox/launch", methods=["POST"])
def sandbox_launch_view():
    """Initializes a new ephemeral sandbox session (or resumes an active one) and redirects to the interactive app."""
    if config.is_local_mode():
        return jsonify({"error": "Sandbox mode is only available on web."}), 404

    from routes.context import _is_demo_session
    if _is_demo_session() and request.method == "POST":
        return jsonify({"error": "Forbidden: Demo personas are read-only. Exit demo to create a sandbox."}), 403

    # Throttle before any cookie is trusted: guessing sandbox ids must cost the attacker requests.
    if request.cookies.get(SANDBOX_FID_COOKIE):
        resume_ok, resume_retry = _check_rate_limit("sandbox_resume", SANDBOX_RESUME_LIMIT)
        if not resume_ok:
            msg = f"Rate limit reached. Retry in {resume_retry}s."
            return (jsonify({"success": False, "error": msg, "retry_after": resume_retry}), 429) if (request.is_json or request.path.startswith("/api/")) else (f"<h3>429 Too Many Requests</h3><p>{msg}</p>", 429)

    existing_fid, existing_fek, existing_lease = get_resumable_sandbox_lease()
    if request.method == "GET" and request.args.get("new") != "1" and not (request.args.get("template") or request.args.get("seed")) and existing_fid > 0 and existing_fek and existing_lease:
        _initialize_sandbox_session(existing_fid, existing_fek)
        return redirect("/?sandbox=1" if existing_lease.get("has_data") else "/?sandbox=1&onboarding=1")

    if existing_fid > 0 and request.args.get("new") == "1":
        try:
            wipe_sandbox_immediately(existing_fid, reason="new_sandbox_requested")
        except Exception:
            pass

    allowed, retry_after = _check_rate_limit("sandbox_create", "20/hr")
    if not allowed:
        msg = f"Rate limit reached (max 20 sessions/hour). Retry in {retry_after}s."
        return (jsonify({"success": False, "error": msg, "retry_after": retry_after}), 429) if (request.is_json or request.path.startswith("/api/")) else (f"<h3>429 Too Many Requests</h3><p>{msg}</p>", 429)

    raw_template = (request.get_json(silent=True) or {}).get("template") if request.is_json else None
    seed_mode = sanitize_text(str(raw_template or request.args.get("template") or request.args.get("seed") or "blank"), max_length=32, field_name="Template") or "blank"
    try:
        fid, raw_fek, expires_at = create_sandbox_session(seed_mode=seed_mode)
    except SandboxCapacityError as e:
        return jsonify({"success": False, "error": str(e)}), 503

    _initialize_sandbox_session(fid, raw_fek)
    try:
        from db.telemetry import record_portal_telemetry_event
        record_portal_telemetry_event("sandbox", "action", feature_key=seed_mode, action="launch_sandbox", tab="sandbox")
    except Exception:
        pass
    redirect_url = "/?sandbox=1&onboarding=1" if seed_mode == "blank" else "/?sandbox=1"
    resp = jsonify({"success": True, "family_id": fid, "expires_at": expires_at, "redirect": redirect_url}) if (request.is_json or request.path.startswith("/api/")) else redirect(redirect_url)
    _set_vault_fek_cookie(resp, raw_fek, max_age=86400, fid=fid)
    return resp


@sandbox_bp.route("/api/sandbox/status", methods=["GET"])
def api_sandbox_status():
    """Returns the current sandbox session expiry and lease status."""
    if config.is_local_mode():
        return jsonify({"error": "Not available in Local Desktop Mode."}), 404

    is_sb = is_sandbox_session()
    fid = get_current_family_id() if is_sb else 0
    lease = get_sandbox_lease_info(fid) if fid > 0 else None
    return jsonify({"success": True, "is_sandbox": is_sb, "lease": lease})


@sandbox_bp.route("/api/sandbox/extend", methods=["POST"])
@editor_required
def api_sandbox_extend():
    """Extends the current sandbox session expiration to 7 days from now."""
    if config.is_local_mode():
        return jsonify({"error": "Not available in Local Desktop Mode."}), 404
    if not is_sandbox_session():
        return jsonify({"success": False, "error": "Only active sandbox sessions can be extended."}), 400

    fid = get_current_family_id()
    try:
        info = extend_sandbox_lease_7d(fid)
        from db.telemetry import record_portal_telemetry_event
        record_portal_telemetry_event("sandbox", "action", feature_key="extend_7d", action="extend_sandbox", tab="sandbox")
    except SandboxCapacityError as e:
        return jsonify({"success": False, "error": str(e)}), 503
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400

    resp = jsonify({"success": True, **info})
    try:
        raw_fek = security.get_family_key(config.get_family_db_path(fid, "sandbox"), fid)
        if raw_fek:
            _set_vault_fek_cookie(resp, raw_fek, max_age=7 * 86400, fid=fid)
    except Exception:
        pass
    return resp


@sandbox_bp.route("/api/sandbox/wipe", methods=["POST"])
@editor_required
def api_sandbox_wipe():
    """Immediately shreds all sandbox household database files and clears session."""
    if config.is_local_mode():
        return jsonify({"error": "Not available in Local Desktop Mode."}), 404
    if not is_sandbox_session():
        return jsonify({"success": False, "error": "Only active sandbox sessions can be wiped."}), 400

    fid = get_current_family_id()
    wipe_sandbox_immediately(fid, reason="manual_wipe")
    try:
        from db.telemetry import record_portal_telemetry_event
        record_portal_telemetry_event("sandbox", "action", feature_key="manual_wipe", action="wipe_sandbox", tab="sandbox")
    except Exception:
        pass
    session.clear()
    resp = jsonify({"success": True, "message": "Your sandbox database has been completely shredded.", "redirect": "/login?sandbox_wiped=1"})
    cookie_name = getattr(config, "get_vault_cookie_name", lambda: VAULT_COOKIE_NAME)()
    for c in {VAULT_COOKIE_NAME, cookie_name, "hvl_vault_fek", "hvl_vault_fek_beta"}:
        resp.delete_cookie(c, path="/")
    resp.delete_cookie(SANDBOX_FID_COOKIE, path="/")
    return resp


@sandbox_bp.route("/sandbox/migrate-to-cloud", methods=["GET"])
def sandbox_migrate_to_cloud_view():
    """Exits the active sandbox view into the Cloud Vault Google Sign-In flow while preserving the sandbox lease for automatic migration."""
    if config.is_local_mode():
        return redirect("/login")
    for k in ("authenticated", "is_sandbox", "is_demo", "universe"):
        session.pop(k, None)
    session["migrate_sandbox_to_cloud"] = True
    return redirect("/login?migrate_sandbox=1")


@sandbox_bp.route("/api/sandbox/download-vault", methods=["POST"])
@editor_required
def api_sandbox_download_vault():
    """Delegates vault backup export for the active sandbox household."""
    if config.is_local_mode():
        return jsonify({"error": "Not available in Local Desktop Mode."}), 404
    try:
        record_portal_telemetry_event("sandbox", "action", feature_key="fovault_download", action="download_vault", tab="sandbox")
    except Exception:
        pass
    from routes.desktop import api_desktop_backup
    return api_desktop_backup()


@sandbox_bp.route("/api/sandbox/restore", methods=["POST"])
@sandbox_bp.route("/api/sandbox/restore_async", methods=["POST"])
def api_sandbox_restore():
    """Uploads and restores a .fovault file into the active (or a new) sandbox household."""
    if config.is_local_mode():
        return jsonify({"error": "Not available in Local Desktop Mode."}), 404
    from routes.context import _is_demo_session
    if _is_demo_session():
        return jsonify({"error": "Forbidden: Demo personas are read-only. Exit demo to restore a sandbox."}), 403

    allowed, retry_after = _check_rate_limit("sandbox_upload", "5/hr")
    if not allowed:
        return jsonify({"success": False, "error": "Rate limit exceeded (5 uploads/hour).", "retry_after": retry_after}), 429

    uploaded = request.files.get("file") or request.files.get("backup_file") or request.files.get("vault_file")
    if uploaded is None:
        return jsonify({"success": False, "error": "No .fovault file provided."}), 400
    raw_bytes = uploaded.read(100 * 1024 * 1024)
    if len(raw_bytes) < 100 or not raw_bytes.startswith(b"SQLite format 3\x00"):
        return jsonify({"success": False, "error": "Invalid file: not a valid SQLite .fovault archive."}), 400

    active_fid = get_current_family_id() if is_sandbox_session() else 0
    if active_fid <= 0:
        active_fid = max(0, get_resumable_sandbox_lease()[0])

    from hvl_common.web.jobs import should_run_synchronously
    from routes.fovault_request import prepare_restore_from_request
    from services.fovault_service import get_vault_import_summary

    prepared, err_resp = prepare_restore_from_request(raw_bytes, "sandbox")
    if err_resp is not None:
        return err_resp
    wants_async = request.path.endswith("_async") or str(request.args.get("async") or "").lower() in ("1", "true", "yes")
    if wants_async and not should_run_synchronously():
        return _handle_async_sandbox_restore(raw_bytes, prepared.fek, target_fid=active_fid)

    try:
        new_fid, raw_fek, expires_at = restore_sandbox_from_fovault_bytes(raw_bytes, restore_fek=prepared.fek, target_fid=active_fid)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

    summary = get_vault_import_summary(config.get_family_db_path(new_fid, "sandbox"), new_fid, raw_fek=raw_fek)
    _initialize_sandbox_session(new_fid, raw_fek)
    resp = jsonify({"success": True, "family_id": new_fid, "expires_at": expires_at, "redirect": "/?sandbox=1", "summary": summary, "message": summary.get("summary_text", "Vault backup restored successfully.")})
    _set_vault_fek_cookie(resp, raw_fek, max_age=86400, fid=new_fid)
    return resp


@sandbox_bp.route("/api/vault/restore", methods=["POST"])
@sandbox_bp.route("/api/vault/restore_async", methods=["POST"])
@editor_required
def api_cloud_vault_restore():
    """Restores a portable `.fovault` backup file into the authenticated user's active Cloud Vault."""
    if is_sandbox_session():
        return api_sandbox_restore()
    if config.is_local_mode():
        from routes.desktop import api_desktop_restore
        return api_desktop_restore()

    fid = get_current_family_id()
    if fid <= 0:
        return jsonify({"success": False, "error": "No active household vault session."}), 400

    uploaded = request.files.get("file") or request.files.get("backup_file") or request.files.get("vault_file")
    if uploaded is None:
        return jsonify({"success": False, "error": "No .fovault backup file provided."}), 400
    raw_bytes = uploaded.read(100 * 1024 * 1024)
    if len(raw_bytes) < 100 or not raw_bytes.startswith(b"SQLite format 3\x00"):
        return jsonify({"success": False, "error": "Invalid file: not a valid SQLite .fovault archive."}), 400

    from hvl_common.web.jobs import should_run_synchronously
    from routes.fovault_request import prepare_restore_from_request
    from services.fovault_service import apply_fovault_restore_to_db, get_vault_import_summary

    prepared, err_resp = prepare_restore_from_request(raw_bytes, "public")
    if err_resp is not None:
        return err_resp
    wants_async = request.path.endswith("_async") or str(request.args.get("async") or "").lower() in ("1", "true", "yes")
    if wants_async and not should_run_synchronously():
        return _handle_async_sandbox_restore(raw_bytes, prepared.fek, target_fid=fid, is_cloud=True)

    dst_db = config.get_family_db_path(fid, "public")
    ok, err_msg, active_fek = apply_fovault_restore_to_db(raw_bytes, dst_db, fid, restore_fek=prepared.fek, is_sandbox=False, is_local=False, universe="public")
    if not ok:
        return jsonify({"success": False, "error": err_msg}), 400

    summary = get_vault_import_summary(dst_db, fid, raw_fek=active_fek)
    return jsonify({"success": True, "family_id": fid, "redirect": "/", "summary": summary, "message": summary.get("summary_text", "Vault backup restored into your Cloud Vault.")})
