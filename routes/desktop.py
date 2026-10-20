"""
Local Desktop Mode Blueprint (`routes/desktop.py`).
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Dict, Optional

from flask import Blueprint, current_app, jsonify, request, send_file, session

import config
import security
import security_crypto
from desktop_app import get_local_lan_ip, remove_server_lockfile
from hvl_common.web import rate_limit
from routes.helpers import (
    editor_required,
    get_current_db_path,
    get_current_family_id,
    get_current_universe,
    sanitize_text,
)
from services.desktop_service import (
    _activate_local_passphrase_session,
    _compute_vault_size_bytes,
    _is_loopback_or_authenticated,
    _is_loopback_remote,
    _mask_data_dir,
    _parse_semver,
    _provision_first_local_household,
    _submit_async_desktop_restore,
    _trigger_auto_shutdown,
    bootstrap_local_google_owner,
    execute_local_passphrase_login,
    execute_local_passphrase_reset,
    fetch_github_release_status,
    get_active_data_dir,
    has_local_passphrase_configured,
    is_local_mode,
    is_local_vault_unclaimed,
)

desktop_bp = Blueprint("desktop", __name__)

_DESKTOP_HEARTBEAT_LOCK = threading.Lock()
_ACTIVE_DESKTOP_CLIENTS: Dict[str, float] = {}  # client_id -> monotonic timestamp
_LAST_ACTIVITY_MONO: float = 0.0
_CLIENT_STALE_SECONDS: float = 45.0


def _resolve_desktop_port() -> int:
    port_str = os.environ.get("FAMILY_OFFICE_PORT", "").strip()
    if not port_str:
        host_header = request.host or "localhost:5050"
        port_str = host_header.split(":")[-1] if ":" in host_header else "5050"
    try:
        return int(port_str)
    except ValueError:
        return 5050


@desktop_bp.route("/api/desktop/health", methods=["GET"])
def api_desktop_health():
    """Lightweight health check probed by `desktop_app.py` to detect an already-running instance."""
    return jsonify({
        "ok": True, "app": "hvl-family-office", "version": config.APP_VERSION,
        "local_mode": is_local_mode(), "pid": os.getpid(),
        "login_required": not bool(session.get("authenticated")),
    })


@desktop_bp.route("/api/desktop/status", methods=["GET"])
def api_desktop_status():
    """Returns local desktop runtime status, LAN URL, and vault metadata."""
    local_active, data_dir, lan_ip, port = is_local_mode(), get_active_data_dir(), get_local_lan_ip(), _resolve_desktop_port()
    is_auth = bool(session.get("authenticated"))
    exposed_data_dir: Optional[str] = (str(data_dir) if is_auth else _mask_data_dir(data_dir)) if local_active else None
    return jsonify({
        "success": True, "version": config.APP_VERSION, "local_mode": local_active,
        "port": port, "lan_ip": lan_ip, "local_url": f"http://localhost:{port}",
        "lan_url": f"http://{lan_ip}:{port}", "data_dir": exposed_data_dir,
        "vault_size_bytes": _compute_vault_size_bytes(data_dir) if local_active else 0,
        "is_unclaimed": is_local_vault_unclaimed() if local_active else False,
        "has_passphrase": has_local_passphrase_configured() if local_active else False,
        "login_required": not is_auth,
    })


@desktop_bp.route("/api/desktop/check-update", methods=["GET"])
def api_desktop_check_update():
    """Checks GitHub Releases for a newer version of HVL Family Office."""
    if not session.get("authenticated"):
        return jsonify({"success": False, "error": "Authentication required."}), 401
    return jsonify(fetch_github_release_status())


@desktop_bp.route("/api/desktop/local-setup", methods=["POST"])
def api_desktop_local_setup():
    """Initializes Household #1 on a fresh Local Desktop installation using an offline Master Passphrase or PIN."""
    if session.get("is_demo") or session.get("universe") in ("demo", "beta") or not is_local_mode():
        return jsonify({"success": False, "error": "Forbidden: Local Desktop Mode required."}), 403
    if not is_local_vault_unclaimed():
        return jsonify({"success": False, "error": "Local household vault is already claimed."}), 409
    if not _is_loopback_remote() or not _is_loopback_or_authenticated():
        return jsonify({"success": False, "error": "Forbidden: First-time local vault setup must be performed from this computer (localhost)."}), 403

    body = request.get_json(silent=True) or {}
    owner_name = sanitize_text(body.get("name") or "Household Owner", 100) or "Household Owner"
    household_name = sanitize_text(body.get("household_name") or f"{owner_name.split()[0]}'s Family Office", 100) or "Family Office"
    passphrase = str(body.get("passphrase") or body.get("pin") or "").strip()
    if len(passphrase) < 4 or len(passphrase) > 128:
        return jsonify({"success": False, "error": "Master Passphrase or PIN must be between 4 and 128 characters."}), 400

    uni = get_current_universe()
    global_db = config.get_global_db_path(uni)
    security.init_db(global_db)
    raw_fek = security.get_family_key(global_db, 1)
    wrapped_fek = security_crypto.wrap_fek_with_passphrase(raw_fek, passphrase)
    fid, uid, raw_fek = _provision_first_local_household(
        owner_name=owner_name, household_name=household_name, owner_email="", wrapped_passphrase_fek=wrapped_fek,
    )
    first_name = _activate_local_passphrase_session(
        fid, uid, owner_name, "editor", uni, "Local Master Passphrase", raw_fek, global_db, config.get_family_db_path(fid, uni)
    )
    return jsonify({"success": True, "family_id": fid, "user": first_name, "redirect": "/?onboarding=1"})


@desktop_bp.route("/api/desktop/local-login", methods=["POST"])
@rate_limit("10/min")
def api_desktop_local_login():
    """Unlocks the local household vault using the owner's offline Master Passphrase or PIN."""
    if session.get("is_demo") or session.get("universe") in ("demo", "beta") or not is_local_mode():
        return jsonify({"success": False, "error": "Forbidden: Local Desktop Mode required."}), 403
    body = request.get_json(silent=True) or {}
    passphrase = str(body.get("passphrase") or body.get("pin") or "").strip()
    if not passphrase:
        return jsonify({"success": False, "error": "Master Passphrase or PIN is required."}), 400
    payload, status_code = execute_local_passphrase_login(passphrase)
    return jsonify(payload), status_code


@desktop_bp.route("/api/desktop/change-passphrase", methods=["POST"])
@editor_required
def api_desktop_change_passphrase():
    """Allows a logged-in Local Mode household owner to change their Master Passphrase / PIN."""
    if session.get("is_demo") or session.get("universe") in ("demo", "beta") or not is_local_mode():
        return jsonify({"success": False, "error": "Forbidden: Local Desktop Mode required."}), 403
    fid = get_current_family_id()
    if fid <= 0:
        return jsonify({"success": False, "error": "No active household session."}), 400
    body = request.get_json(silent=True) or {}
    new_passphrase = str(body.get("new_passphrase") or body.get("passphrase") or body.get("pin") or "").strip()
    if len(new_passphrase) < 4 or len(new_passphrase) > 128:
        return jsonify({"success": False, "error": "New Master Passphrase or PIN must be between 4 and 128 characters."}), 400
    uni = get_current_universe()
    global_db, family_db = config.get_global_db_path(uni), config.get_family_db_path(fid, uni)
    raw_fek = security.get_request_vault_fek(fid) or security.get_family_key(global_db, fid)
    security.update_local_passphrase_fek(global_db, family_db, security_crypto.wrap_fek_with_passphrase(raw_fek, new_passphrase), family_id=fid)
    return jsonify({"success": True, "message": "Master Passphrase / PIN updated."})


@desktop_bp.route("/api/desktop/reset-passphrase", methods=["POST"])
def api_desktop_reset_passphrase():
    """Recovers and resets a forgotten Master Passphrase / PIN in Local Desktop Mode using `.secret.key`."""
    if session.get("is_demo") or session.get("universe") in ("demo", "beta") or not is_local_mode():
        return jsonify({"success": False, "error": "Forbidden: Local Desktop Mode required."}), 403
    body = request.get_json(silent=True) or {}
    new_passphrase = str(body.get("new_passphrase") or body.get("passphrase") or body.get("pin") or "").strip()
    if len(new_passphrase) < 4 or len(new_passphrase) > 128:
        return jsonify({"success": False, "error": "New Master Passphrase or PIN must be between 4 and 128 characters."}), 400
    payload, status_code = execute_local_passphrase_reset(new_passphrase, str(body.get("recovery_key") or "").strip())
    return jsonify(payload), status_code


@desktop_bp.route("/api/desktop/reset-vault", methods=["POST"])
@editor_required
def api_desktop_reset_vault():
    """Wipes local household and global database files so the owner can test first-time setup from scratch."""
    if not is_local_mode() or not _is_loopback_or_authenticated():
        return jsonify({"success": False, "error": "Forbidden: Local Desktop Mode on localhost required."}), 403
    from hvl_common.db.sqlite import close_all_pools
    close_all_pools()
    data_dir = config.get_data_dir()
    security._clear_security_caches()
    for pattern in ("*.db*", "families/*.db*", "*/*.db*", "*/families/*.db*"):
        for f in data_dir.glob(pattern):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
    session.clear()
    resp = jsonify({"success": True, "redirect": "/login", "message": "Local vault reset successfully."})
    cfg_cookie = getattr(config, "get_vault_cookie_name", lambda: security.VAULT_COOKIE_NAME)()
    for c in {security.VAULT_COOKIE_NAME, cfg_cookie, "hvl_vault_fek", "hvl_vault_fek_beta"}:
        resp.delete_cookie(c)
    return resp


@desktop_bp.route("/api/desktop/backup", methods=["GET"])
@editor_required
def api_desktop_backup():
    """Exports a consistent, encrypted SQLite snapshot of the current household vault (.fovault)."""
    fid = get_current_family_id()
    if fid <= 0:
        return jsonify({"success": False, "error": "No active household vault to export."}), 400
    src_db = get_current_db_path()
    if not src_db.exists():
        return jsonify({"success": False, "error": "Household database file does not exist yet."}), 404
    from routes.helpers import is_sandbox_session
    from services.fovault_service import build_fovault_backup_bytes
    data_bytes, filename = build_fovault_backup_bytes(src_db, fid, is_sandbox=is_sandbox_session(), is_local=is_local_mode())
    return send_file(io.BytesIO(data_bytes), mimetype="application/octet-stream", as_attachment=True, download_name=filename)


@desktop_bp.route("/api/desktop/recovery-key", methods=["GET"])
@editor_required
def api_desktop_recovery_key():
    """Returns the 44-character Local Recovery Key (`.mm/.secret.key`) to an authenticated Local Mode owner."""
    if session.get("is_demo") or session.get("universe") in ("demo", "beta") or not is_local_mode():
        return jsonify({"success": False, "error": "Only available in Local Desktop Mode."}), 403
    recovery_key = security.get_or_create_key().decode("utf-8", errors="ignore").strip()
    return jsonify({"success": True, "recovery_key": recovery_key})


@desktop_bp.route("/api/desktop/restore", methods=["POST"])
@desktop_bp.route("/api/desktop/restore_async", methods=["POST"])
@editor_required
def api_desktop_restore():
    """Restores a previously exported `.fovault` SQLite backup file into the active household vault."""
    from hvl_common.web.jobs import should_run_synchronously
    from routes.helpers import is_sandbox_session
    from services.fovault_service import apply_fovault_restore_to_db, get_vault_import_summary

    is_sb, is_loc = is_sandbox_session(), is_local_mode()
    if session.get("is_demo") or session.get("universe") in ("demo", "beta") or (not is_loc and not is_sb):
        return jsonify({"success": False, "error": "Only available in Local Desktop or Sandbox Mode."}), 403
    fid = get_current_family_id()
    if fid <= 0:
        return jsonify({"success": False, "error": "No active household session."}), 400
    uploaded = request.files.get("file") or request.files.get("backup_file") or request.files.get("vault_file")
    if uploaded is None:
        return jsonify({"success": False, "error": "No .fovault backup file provided."}), 400

    raw_bytes, dst_db, uni = uploaded.read(100 * 1024 * 1024), get_current_db_path(), get_current_universe()
    backup_dir = (get_active_data_dir() / "backups") if is_loc else None
    if (request.path.endswith("_async") or str(request.args.get("async") or "").lower() in ("1", "true", "yes")) and not should_run_synchronously():
        return _submit_async_desktop_restore(raw_bytes, dst_db, fid, is_sb, is_loc, backup_dir, uni)

    ok, err_msg, extracted_fek = apply_fovault_restore_to_db(raw_bytes, dst_db, fid, is_sandbox=is_sb, is_local=is_loc, backup_dir=backup_dir, universe=uni)
    if not ok:
        return jsonify({"success": False, "error": err_msg}), 400
    summary = get_vault_import_summary(dst_db, fid, raw_fek=extracted_fek)
    resp = jsonify({
        "success": True, "family_id": fid, "summary": summary,
        "message": summary.get("summary_text", "Vault backup restored successfully."),
    })
    if is_sb and extracted_fek:
        from routes.sandbox import _initialize_sandbox_session, _set_vault_fek_cookie
        _initialize_sandbox_session(fid, extracted_fek)
        _set_vault_fek_cookie(resp, extracted_fek, max_age=86400, fid=fid)
    return resp


@desktop_bp.route("/api/desktop/reveal-folder", methods=["POST"])
@editor_required
def api_desktop_reveal_folder():
    """Opens the local vault directory in Windows Explorer or macOS Finder when in Local Mode."""
    if not is_local_mode():
        return jsonify({"success": False, "error": "Only available in Local Desktop Mode."}), 403
    data_dir = get_active_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        resolved_dir = str(data_dir.resolve())
        if sys.platform == "win32":
            try:
                os.startfile(resolved_dir)  # type: ignore[attr-defined]
            except Exception:
                subprocess.Popen(["explorer.exe", resolved_dir])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", resolved_dir])
        else:
            subprocess.Popen(["xdg-open", resolved_dir])
        return jsonify({"success": True, "data_dir": resolved_dir})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@desktop_bp.route("/api/desktop/open-browser", methods=["POST"])
def api_desktop_open_browser():
    """Opens the local dashboard in the user's standard web browser tab when in Local Mode."""
    if session.get("is_demo") or session.get("universe") in ("demo", "beta") or not is_local_mode():
        return jsonify({"success": False, "error": "Only available in Local Desktop Mode."}), 403
    if not _is_loopback_or_authenticated():
        return jsonify({"success": False, "error": "Forbidden: Loopback or authenticated session required."}), 403
    target_url = f"http://localhost:{_resolve_desktop_port()}"
    try:
        webbrowser.open(target_url)
        return jsonify({"success": True, "url": target_url})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


def _prune_stale_desktop_clients(now_mono: float) -> int:
    stale_keys = [cid for cid, last_seen in _ACTIVE_DESKTOP_CLIENTS.items() if (now_mono - last_seen) > _CLIENT_STALE_SECONDS]
    for cid in stale_keys:
        _ACTIVE_DESKTOP_CLIENTS.pop(cid, None)
    return len(_ACTIVE_DESKTOP_CLIENTS)


def _schedule_desktop_grace_shutdown(close_epoch: float, data_dir: Path, grace: float, is_testing: bool) -> None:
    def _check_after_grace() -> None:
        time.sleep(max(0.05, grace))
        with _DESKTOP_HEARTBEAT_LOCK:
            _prune_stale_desktop_clients(time.monotonic())
            still_empty = len(_ACTIVE_DESKTOP_CLIENTS) == 0 and _LAST_ACTIVITY_MONO == close_epoch
        if still_empty:
            if is_testing and os.environ.get("FAMILY_OFFICE_TEST_AUTO_SHUTDOWN") != "1":
                remove_server_lockfile(data_dir)
            else:
                _trigger_auto_shutdown(data_dir)

    threading.Thread(target=_check_after_grace, daemon=True).start()


@desktop_bp.route("/api/desktop/heartbeat", methods=["POST"])
def api_desktop_heartbeat():
    """Tracks open desktop/browser windows in Local Mode and auto-stops server after last window closes."""
    if not is_local_mode():
        return jsonify({"success": False, "error": "Only available in Local Desktop Mode."}), 403
    if not _is_loopback_or_authenticated():
        return jsonify({"success": False, "error": "Forbidden: Loopback or authenticated session required."}), 403

    global _LAST_ACTIVITY_MONO
    body = request.get_json(force=True, silent=True) or {}
    client_id = sanitize_text(str(body.get("client_id") or "default"), 64) or "default"
    event = sanitize_text(str(body.get("event") or "ping"), 16).lower()
    now_mono = time.monotonic()

    scheduled_shutdown = False
    with _DESKTOP_HEARTBEAT_LOCK:
        _prune_stale_desktop_clients(now_mono)
        if event == "close":
            _ACTIVE_DESKTOP_CLIENTS.pop(client_id, None)
            active_count = len(_ACTIVE_DESKTOP_CLIENTS)
            if active_count == 0:
                scheduled_shutdown = True
                _schedule_desktop_grace_shutdown(
                    _LAST_ACTIVITY_MONO, get_active_data_dir(),
                    float(os.environ.get("FAMILY_OFFICE_CLOSE_GRACE_SECONDS", "8.0")),
                    bool(current_app.config.get("TESTING")),
                )
        else:
            _ACTIVE_DESKTOP_CLIENTS[client_id] = now_mono
            _LAST_ACTIVITY_MONO = now_mono
            active_count = len(_ACTIVE_DESKTOP_CLIENTS)

    return jsonify({"success": True, "event": event, "active_clients": active_count, "scheduled_shutdown": scheduled_shutdown})


@desktop_bp.route("/api/desktop/shutdown", methods=["POST"])
@editor_required
def api_desktop_shutdown():
    """Cleanly removes `server.json` and stops the local background server when in Local Mode."""
    if not is_local_mode():
        return jsonify({"success": False, "error": "Only available in Local Desktop Mode."}), 403
    remove_server_lockfile(get_active_data_dir())
    session.clear()
    shutdown_fn = request.environ.get("werkzeug.server.shutdown")
    if callable(shutdown_fn):
        shutdown_fn()
    elif not current_app.config.get("TESTING"):
        threading.Timer(0.25, lambda: os._exit(0)).start()
    return jsonify({"success": True, "message": "Local HVL Family Office server stopped."})
