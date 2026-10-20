"""
Local Desktop Mode Service Helpers (Vault Setup, Passphrase Session Activation, Restore, and Auto-Shutdown).
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import jsonify, request, session

import config
import security
import security_crypto
from desktop_app import (
    get_default_local_data_dir,
    get_local_lan_ip,
    remove_server_lockfile,
)
from routes.helpers import get_current_universe, sanitize_text


def _is_loopback_remote() -> bool:
    """Returns True if the HTTP request originates from a loopback interface."""
    remote = (request.remote_addr or "").strip().lower()
    return remote in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1")


def _is_loopback_or_authenticated() -> bool:
    """Returns True if the caller has an authenticated session OR is calling from loopback."""
    is_auth = bool(session.get("authenticated"))
    raw_host = (request.headers.get("Host") or request.host or "").strip().lower()
    if raw_host.startswith("[") and "]" in raw_host:
        hostname = raw_host.split("]")[0] + "]"
    else:
        hostname = raw_host.split(":")[0]

    loopback_hosts = {"127.0.0.1", "localhost", "::1", "[::1]", ""}
    if is_auth:
        allowed_hosts = loopback_hosts | {get_local_lan_ip().lower()}
        return hostname in allowed_hosts

    if not _is_loopback_remote():
        return False
    return hostname in loopback_hosts


def _mask_data_dir(data_dir: Path) -> str:
    """Masks the OS home directory or user path prefix for unauthenticated callers."""
    home_str = str(Path.home())
    full_str = str(data_dir)
    if home_str and full_str.startswith(home_str):
        suffix = full_str[len(home_str):]
        return f"~{suffix}" if suffix else "~"
    return f"~/{data_dir.name}"


def is_local_mode() -> bool:
    """Returns True when the application is running in Local Desktop Mode."""
    return config.is_local_mode()


def get_active_data_dir() -> Path:
    """Returns the active data directory (respecting `FAMILY_OFFICE_DATA_DIR` when set)."""
    override = os.environ.get("FAMILY_OFFICE_DATA_DIR", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    if is_local_mode():
        p = get_default_local_data_dir()
        p.mkdir(parents=True, exist_ok=True)
        return p
    return config.get_data_dir()


def is_local_vault_unclaimed(db_path: Optional[Path] = None) -> bool:
    """Returns True if the global database has 0 registered users (fresh local install)."""
    target_db = Path(db_path) if db_path is not None else config.get_global_db_path(get_current_universe())
    return security.is_local_vault_unclaimed(target_db)


def has_local_passphrase_configured(db_path: Optional[Path] = None, family_id: int = 0) -> bool:
    """Returns True if Household `family_id` has a PBKDF2-wrapped Master Passphrase/PIN configured."""
    target_db = Path(db_path) if db_path is not None else config.get_global_db_path(get_current_universe())
    return security.has_local_passphrase_configured(target_db, family_id=family_id)


def _provision_first_local_household(
    owner_name: str,
    household_name: str,
    owner_email: str = "",
    wrapped_passphrase_fek: Optional[str] = None,
) -> Tuple[int, int, bytes]:
    """Initializes the primary local household and owner across both `global.db` and `families/1.db`."""
    primary_fid = int("1")
    uni = get_current_universe()
    global_db = config.get_global_db_path(uni)
    family_db = config.get_family_db_path(primary_fid, uni)
    return security.provision_first_local_household(
        global_db=global_db,
        family_db=family_db,
        owner_name=owner_name,
        household_name=household_name,
        owner_email=owner_email,
        wrapped_passphrase_fek=wrapped_passphrase_fek,
    )


def bootstrap_local_google_owner(
    email: str,
    display_name: str = "Household Owner",
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Automatically claims Household #1 for the first person who signs in with Google OAuth in Local Mode."""
    if not is_local_mode() or not is_local_vault_unclaimed(db_path):
        return None
    clean_email = (email or "").strip().lower()
    if not clean_email:
        return None
    clean_name = sanitize_text(display_name or clean_email.split("@")[0].capitalize(), 100) or "Household Owner"
    hh_name = f"{clean_name.split()[0]}'s Family Office"
    fid, uid, raw_fek = _provision_first_local_household(
        owner_name=clean_name, household_name=hh_name, owner_email=clean_email,
    )
    return {
        "user_id": uid,
        "family_id": fid,
        "name": security.encrypt_string(clean_name, key=raw_fek),
        "email": security.encrypt_string(clean_email, key=raw_fek),
        "role": "editor",
        "pending_fek_enc": None,
        "google_vault_synced": 0,
        "is_new_local_household": True,
    }


def _compute_vault_size_bytes(data_dir: Path) -> int:
    total = 0
    if not data_dir.exists():
        return 0
    for f in data_dir.rglob("*.db"):
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total


def _parse_semver(ver: str) -> Tuple[int, ...]:
    clean = (ver or "").strip().lstrip("vV").split("-")[0]
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0, 0, 0])


def fetch_github_release_status() -> dict[str, Any]:
    """Queries GitHub Releases for a newer version of HVL Family Office."""
    current_ver = config.APP_VERSION
    repo_slug = config.GITHUB_REPO_SLUG
    releases_page = f"https://github.com/{repo_slug}/releases"
    api_url = f"https://api.github.com/repos/{repo_slug}/releases/latest"
    try:
        req = urllib.request.Request(
            api_url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"HVLFamilyOffice/{current_ver}"},
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        tag_name = str(data.get("tag_name") or "").strip()
        latest_ver = tag_name.lstrip("vV") or current_ver
        html_url = str(data.get("html_url") or releases_page)
        return {
            "success": True,
            "current_version": current_ver,
            "latest_version": latest_ver,
            "update_available": _parse_semver(latest_ver) > _parse_semver(current_ver),
            "release_url": html_url,
        }
    except Exception:
        return {
            "success": True,
            "current_version": current_ver,
            "latest_version": current_ver,
            "update_available": False,
            "release_url": releases_page,
        }


def _activate_local_passphrase_session(
    fid: int, uid: int, full_name: str, user_role: str, uni: str,
    auth_method: str, raw_fek: bytes, global_db: Path, family_db: Path,
) -> str:
    first_name = full_name.split()[0] if full_name else "Owner"
    session.clear()
    session["authenticated"] = True
    session["family_id"] = fid
    session["user_family_id"] = fid
    session["user_id"] = uid
    session["user"] = first_name
    session["user_display"] = full_name
    session["user_email"] = ""
    session["role"] = "admin" if user_role in ("admin", "editor") else user_role
    session["user_role"] = user_role
    session["universe"] = uni
    session["is_demo"] = False
    session["auth_method"] = auth_method
    session.permanent = True
    security.stash_request_vault_fek(fid, raw_fek)
    security.escrow_local_vault_key(global_db, family_db, raw_fek, family_id=fid)
    return first_name


def execute_local_passphrase_login(passphrase: str) -> tuple[dict[str, Any], int]:
    """Unlocks the local household vault using the owner's offline Master Passphrase or PIN."""
    uni = get_current_universe()
    global_db = config.get_global_db_path(uni)
    if not global_db.exists():
        return {"success": False, "error": "Local vault is not initialized yet."}, 404

    login_rec = security.get_local_login_record(global_db)
    fid, uid = int(login_rec.get("family_id") or 1), int(login_rec["user_id"])
    wrapped_blob = login_rec["wrapped_blob"]
    enc_user_name = str(login_rec["enc_user_name"] or "")
    user_role = str(login_rec["user_role"] or "editor")
    if not wrapped_blob:
        return {"success": False, "error": "No offline Master Passphrase or PIN is configured for this vault."}, 400

    raw_fek = security_crypto.unwrap_fek_with_passphrase(wrapped_blob, passphrase)
    if raw_fek is None:
        return {"success": False, "error": "Invalid Master Passphrase or PIN."}, 401

    family_db = config.get_family_db_path(fid, uni)
    full_name = security.decrypt_field(enc_user_name, default="Owner", key=raw_fek).strip() or "Owner"
    if full_name in ("Household Owner", "Owner"):
        resolved_name = security.resolve_local_user_name(family_db, global_db, fid, uid, raw_fek)
        if resolved_name:
            full_name = resolved_name

    first_name = _activate_local_passphrase_session(
        fid, uid, full_name, user_role, uni, "Local Passphrase", raw_fek, global_db, family_db
    )
    return {"success": True, "family_id": fid, "user": first_name, "redirect": "/"}, 200


def execute_local_passphrase_reset(new_passphrase: str, supplied_recovery: str) -> tuple[dict[str, Any], int]:
    """Recovers and resets a forgotten Master Passphrase / PIN in Local Desktop Mode using `.secret.key`."""
    local_root_key = security.get_or_create_key().decode("utf-8", errors="ignore").strip()
    if not supplied_recovery or not secrets.compare_digest(supplied_recovery, local_root_key):
        return {
            "success": False,
            "error": "Invalid or missing Local Recovery Key (.secret.key). Paste the key from your local HVLFamilyOffice data folder, or sign in with Google.",
        }, 403

    uni = get_current_universe()
    global_db = config.get_global_db_path(uni)
    if not global_db.exists() or is_local_vault_unclaimed(global_db):
        return {"success": False, "error": "Local vault is not initialized yet."}, 404

    primary_fid = int("1")
    family_db = config.get_family_db_path(primary_fid, uni)
    raw_fek = security.get_family_key(global_db, primary_fid)
    wrapped_fek = security_crypto.wrap_fek_with_passphrase(raw_fek, new_passphrase)
    security.update_local_passphrase_fek(global_db, family_db, wrapped_fek, family_id=primary_fid)

    login_rec = security.get_local_login_record(global_db, family_id=primary_fid)
    uid = int(login_rec["user_id"])
    enc_user_name = str(login_rec["enc_user_name"] or "")
    user_role = str(login_rec["user_role"] or "editor")
    full_name = security.decrypt_field(enc_user_name, default="Household Owner", key=raw_fek).strip() or "Household Owner"
    first_name = _activate_local_passphrase_session(
        primary_fid, uid, full_name, user_role, uni, "Local Master Passphrase", raw_fek, global_db, family_db
    )
    return {"success": True, "family_id": primary_fid, "user": first_name, "redirect": "/"}, 200


def _submit_async_desktop_restore(
    raw_bytes: bytes, dst_db: Path, fid: int, is_sb: bool, is_loc: bool, backup_dir: Path | None, uni: str
):
    import background_jobs
    from services.fovault_service import apply_fovault_restore_to_db, get_vault_import_summary

    def _bg_restore():
        ok, err, fek = apply_fovault_restore_to_db(
            raw_bytes, dst_db, fid, is_sandbox=is_sb, is_local=is_loc, backup_dir=backup_dir, universe=uni
        )
        if not ok:
            raise ValueError(err or "Vault restore failed.")
        summary = get_vault_import_summary(dst_db, fid, raw_fek=fek)
        return {
            "success": True,
            "family_id": fid,
            "raw_fek_b64": fek.decode("utf-8") if isinstance(fek, bytes) else None,
            "summary": summary,
            "message": summary.get("summary_text", "Vault backup restored successfully."),
        }

    job_id = background_jobs.submit_job(_bg_restore, family_id=fid, universe=uni, job_type="vault_restore")
    return jsonify({"success": True, "job_id": job_id, "status": "processing"})


def _trigger_auto_shutdown(data_dir: Path) -> None:
    """Cleanly removes `server.json` and exits the local desktop server process when all windows close."""
    remove_server_lockfile(data_dir)
    if os.environ.get("FAMILY_OFFICE_AUTO_SHUTDOWN", "1").strip().lower() in ("0", "false", "no"):
        return
    os._exit(0)
