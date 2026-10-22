"""
Google OAuth 2.0 & Google Identity Services Authentication Module
Provides secure multi-user authentication with self-serve isolated household provisioning,
database-backed family member lookups, and zero-knowledge Google Drive `appDataFolder` FEK escrow.
Powered by shared module `hvl_common.auth`.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional, Tuple

from flask import g, has_request_context, request, session

_common_path = Path(__file__).resolve().parent.parent / "common"
if _common_path.exists() and str(_common_path) not in sys.path:
    sys.path.insert(0, str(_common_path))

from hvl_common.auth import (
    GOOGLE_APPDATA_SCOPE,
    build_redirect_uri,
    create_google_auth_blueprint,
    read_google_appdata_json,
    verify_google_id_token,
    write_google_appdata_json,
)
from hvl_common.security import VAULT_COOKIE_NAME
from hvl_common.web import rate_limit

__all__ = ["GOOGLE_APPDATA_SCOPE", "build_redirect_uri", "verify_google_id_token", "VAULT_COOKIE_NAME"]

import config
from config import get_global_db_path
from auth_google_helpers import (
    _GlobalDbPathProxy,
    _attach_vault_cookie,
    _extract_appdata_fek,
    _is_valid_candidate_fek,
    apply_pending_sandbox_migration,
    capture_pending_sandbox_migration,
    get_auth_db_path,
    get_oauth_credentials,
    get_redirect_uri,
    load_family_whitelist,
    resolve_household_vault_fek,
)
from db.household_activity import (
    provision_self_serve_household,
    record_family_login,
)


DB_PATH = _GlobalDbPathProxy()


def get_family_whitelist() -> Dict[str, Dict[str, Any]]:
    """Returns the family whitelist loaded dynamically from the SQLite users table and `.env`."""
    return load_family_whitelist(DB_PATH)


def _sync_fek_to_google_and_db(
    access_token: Optional[str],
    fid: int,
    uid: Optional[int],
    raw_fek: bytes,
    fek_source: Optional[str],
    needs_google_write: bool,
    db_path: Path,
    family_db_path: Optional[Path] = None,
) -> bool:
    """Syncs the resolved FEK to Google Drive appDataFolder (when needed) and marks the user vault as synced in SQLite."""
    import security

    synced_to_google = False
    if access_token:
        if needs_google_write:
            synced_to_google = bool(
                write_google_appdata_json(
                    str(access_token),
                    {"family_id": fid, "fek": raw_fek.decode("utf-8")},
                    filename=config.get_vault_appdata_filename(),
                )
            )
        else:
            synced_to_google = True

    if uid is not None and (synced_to_google or fek_source == "pending"):
        target_paths = [Path(db_path)]
        if family_db_path is not None and Path(family_db_path) != Path(db_path) and Path(family_db_path).exists():
            target_paths.append(Path(family_db_path))
        from db.auth_repo import clear_pending_vault_and_sync
        clear_pending_vault_and_sync(target_paths, uid, fid)
        for k in [k for k in list(security._FAMILY_KEY_CACHE) if k[1] == fid]:
            security._FAMILY_KEY_CACHE.pop(k, None)

    return synced_to_google


def authenticate_family_email(email: str, profile_info: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Validates email against existing household records (or auto-provisions an isolated household vault),
    resolves/self-heals the Family Encryption Key (FEK) across Google `appDataFolder` and browser cookie,
    records the household login timestamp, and establishes the authenticated session.
    """
    import security

    sb_migration_ctx = capture_pending_sandbox_migration()
    was_non_public = bool(
        session.get("is_demo")
        or session.get("is_sandbox")
        or str(session.get("universe") or "public").strip().lower() not in ("public", "test", "")
    )
    prev_vault_fek = None if was_non_public else session.get("vault_fek")
    prev_vault_fid = None if was_non_public else session.get("vault_fek_family_id")
    if was_non_public:
        for k in ("is_demo", "is_sandbox", "vault_fek", "vault_fek_family_id"):
            session.pop(k, None)
        session["universe"] = "public"

    if DB_PATH.exists():
        try:
            security.purge_expired_deleted_families(Path(DB_PATH))
        except Exception:
            pass

    clean_email = email.strip().lower()
    whitelist = get_family_whitelist()
    member: Optional[Dict[str, Any]] = whitelist.get(clean_email)

    pending_invite_code = str(session.get("pending_invite_code") or "").strip().upper()
    if not pending_invite_code and isinstance(profile_info, dict) and profile_info.get("invite_code"):
        pending_invite_code = str(profile_info.get("invite_code") or "").strip().upper()
    if not pending_invite_code and has_request_context():
        pending_invite_code = str(request.args.get("invite") or "").strip().upper()

    is_new_household_from_invite = False
    user_row: Optional[Dict[str, Any]] = None
    if DB_PATH.exists():
        try:
            security.init_db(DB_PATH)
            em_hash = security.hash_email(clean_email)
            from db.auth_repo import get_user_by_email_hash
            user_row = get_user_by_email_hash(DB_PATH, em_hash)
        except Exception:
            user_row = None

    profile_name = str((profile_info or {}).get("name") or "").strip() if isinstance(profile_info, dict) else ""

    if user_row is None and pending_invite_code and DB_PATH.exists():
        try:
            redeem_res = security.redeem_invite_token(Path(DB_PATH), pending_invite_code, clean_email, profile_name)
            if redeem_res:
                is_new_household_from_invite = bool(redeem_res.get("is_new_household"))
                em_hash = security.hash_email(clean_email)
                from db.session import resolve_db_path
                from db.auth_repo import get_user_by_email_hash
                lookup_db = resolve_db_path(DB_PATH, family_id=int(redeem_res["family_id"]))
                for cand_db in (lookup_db, Path(DB_PATH)):
                    user_row = get_user_by_email_hash(cand_db, em_hash)
                    if user_row is not None:
                        break
        except Exception:
            pass
        if user_row is None and member is None:
            session.pop("pending_invite_code", None)
            return (
                False,
                None,
                "Invalid, expired, or already-redeemed household invite code. Please verify the code with your household owner or sign in without an invite code to create a new vault.",
            )

    if member is None and user_row is None and config.is_local_mode():
        try:
            from routes.desktop import bootstrap_local_google_owner
            local_owner = bootstrap_local_google_owner(email=clean_email, display_name=profile_name, db_path=Path(DB_PATH))
            if local_owner:
                user_row = local_owner
                is_new_household_from_invite = True
        except Exception:
            pass

    if member is None and user_row is None and not config.is_local_mode():
        public_signup = os.getenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "1").strip().lower() not in ("0", "false", "no")
        if public_signup and DB_PATH.exists():
            try:
                provisioned = provision_self_serve_household(Path(DB_PATH), user_email=clean_email, user_name=profile_name)
                if provisioned:
                    user_row = provisioned
                    is_new_household_from_invite = True
            except Exception:
                pass

    if member is None and user_row is None:
        return (
            False,
            None,
            f"Access denied. '{clean_email}' is not registered on this instance and self-serve sign-up is currently disabled.",
        )

    if user_row is not None:
        uid = int(user_row["user_id"])
        fid = int(user_row["family_id"] or 1)
        r_role = str(user_row.get("role") or "viewer").strip().lower()
        admin_role = "admin" if r_role in ("admin", "editor") else r_role
    else:
        assert member is not None
        uid = int(member.get("user_id", 1))
        fid = int(member.get("family_id", 1))
        admin_role = member["role"]

    if DB_PATH.exists():
        del_status = security.get_family_deletion_status(Path(DB_PATH), family_id=fid)
        if del_status and del_status.get("is_expired"):
            security.permanently_delete_family(Path(DB_PATH), family_id=fid)
            session.clear()
            return False, None, "This household account and all associated data have been permanently deleted."

    session.clear()
    session["family_id"] = fid
    session["user_family_id"] = fid
    if prev_vault_fek and (prev_vault_fid is None or int(prev_vault_fid or 0) == fid):
        session["vault_fek"] = prev_vault_fek
        session["vault_fek_family_id"] = fid

    raw_fek: Optional[bytes] = None
    fek_source: Optional[str] = None
    oauth_tokens = (profile_info or {}).get("_oauth_tokens") if isinstance(profile_info, dict) else None
    access_token = oauth_tokens.get("access_token") if isinstance(oauth_tokens, dict) else None
    already_synced = bool(
        user_row is not None
        and int(user_row.get("google_vault_synced") or 0) == 1
        and not user_row.get("pending_fek_enc")
    )

    if user_row is not None or DB_PATH.exists():
        raw_fek, fek_source, fek_err = resolve_household_vault_fek(
            db_path=DB_PATH,
            fid=fid,
            user_row=user_row,
            clean_email=clean_email,
            access_token=access_token,
            already_synced=already_synced,
            read_appdata_fn=read_google_appdata_json,
        )
        if fek_err:
            session.clear()
            return False, None, fek_err

    if raw_fek is not None:
        security.stash_request_vault_fek(fid, raw_fek)
        migrated_sb, user_row = apply_pending_sandbox_migration(sb_migration_ctx, fid, raw_fek, user_row, DB_PATH)
        if migrated_sb:
            is_new_household_from_invite = False
        needs_google_write = bool(access_token and fek_source != "appdata" and not already_synced)
        needs_db_sync = bool(user_row is not None and not already_synced and (access_token or fek_source == "pending"))
        if needs_google_write or needs_db_sync:
            import background_jobs

            resolved_db_path = Path(DB_PATH)
            sync_uid = uid if user_row is not None else None
            if needs_google_write and not background_jobs.should_run_synchronously():
                background_jobs.EXECUTOR.submit(
                    _sync_fek_to_google_and_db, access_token, fid, sync_uid, raw_fek, fek_source, needs_google_write, resolved_db_path
                )
            else:
                _sync_fek_to_google_and_db(
                    access_token, fid, sync_uid, raw_fek, fek_source, needs_google_write, resolved_db_path
                )

    if DB_PATH.exists() and not is_new_household_from_invite:
        try:
            record_family_login(Path(DB_PATH), family_id=fid)
        except Exception:
            pass

    if user_row is not None:
        full_name = security.decrypt_field(user_row.get("name") or "", default="User", key=raw_fek).strip()
        if not full_name:
            full_name = str((profile_info or {}).get("name") or "User").strip()
        first_name = full_name.split()[0] if full_name else "User"
        member = {
            "user_id": uid,
            "family_id": fid,
            "name": first_name,
            "display_name": full_name,
            "role": admin_role,
            "permissions": ["all"] if admin_role == "admin" else ["view_dashboard", "view_education", "view_overview"],
        }

    assert member is not None

    session["authenticated"] = True
    session["is_demo"] = False
    session["user"] = member["name"]
    session["user_display"] = member["display_name"]
    session["user_email"] = clean_email
    session["user_role"] = member["role"]
    session["role"] = member["role"]
    session["user_family_id"] = member.get("family_id", 1)
    session["family_id"] = member.get("family_id", 1)
    session["universe"] = "public"
    session["user_id"] = member.get("user_id", 1)
    session["user_permissions"] = member.get("permissions", ["all"])
    session["auth_method"] = "Google OAuth 2.0"
    session["avatar_picture"] = (profile_info or {}).get("picture")
    session.permanent = True

    if is_new_household_from_invite:
        member["is_new_household"] = True
        member["redirect"] = "/?onboarding=1"
        session["onboarding_redirect"] = True
        if has_request_context():
            g._onboarding_redirect = True

    return True, member, "Authenticated successfully"


def _on_authenticate_adapter(email: str, profile_info: Dict[str, Any]) -> Tuple[bool, Any]:
    """Adapter bridging authenticate_family_email to create_google_auth_blueprint contract."""
    ok, member, msg = authenticate_family_email(email, profile_info)
    if ok and member:
        return True, {
            "user": member["name"],
            "display_name": member["display_name"],
            "email": email,
            "role": member["role"],
            "is_new_household": bool(member.get("is_new_household")),
            "redirect": member.get("redirect", "/"),
        }
    return False, msg


auth_google_bp = create_google_auth_blueprint(
    get_credentials=get_oauth_credentials,
    on_authenticate=_on_authenticate_adapter,
    get_redirect_uri=lambda: os.getenv("GOOGLE_REDIRECT_URI", "").strip() or None,
    redirect_on_success="/",
    redirect_on_error="/login?auth_error={error}",
    redirect_on_logout="/login",
    scope="openid email",
    include_appdata_scope=True,
    after_login_response=_attach_vault_cookie,
)

rate_limit("20/min")(auth_google_bp)
