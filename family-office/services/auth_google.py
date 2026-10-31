"""
Google OAuth 2.0 & Google Identity Services Authentication Module
Provides secure multi-user authentication with self-serve isolated household provisioning,
database-backed family member lookups, and zero-knowledge Google Drive `appDataFolder` FEK escrow.
Powered by shared module `hvl_common.auth`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from flask import g, has_request_context, request, session

import config  # noqa: F401 
from hvl_common.auth import (
    GOOGLE_APPDATA_SCOPE,
    build_redirect_uri,
    create_google_auth_blueprint,
    read_google_appdata_json,
    verify_google_id_token,
    write_google_appdata_json,
)
from hvl_common.security import VAULT_COOKIE_NAME, is_valid_candidate_fek
from hvl_common.web import rate_limit

__all__ = ["GOOGLE_APPDATA_SCOPE", "build_redirect_uri", "verify_google_id_token", "VAULT_COOKIE_NAME"]

from config import get_global_db_path
from security.init import VaultLockedError
from services import person_name, residence_state
from db.household_activity import (
    provision_self_serve_household,
    record_family_login,
)


def get_auth_db_path() -> Path:
    """Resolves the global authentication database path for user and family whitelist lookups."""
    try:
        from services.request_context import get_current_universe
        uni = get_current_universe()
    except Exception:
        uni = os.getenv("APP_UNIVERSE", "public")
    return get_global_db_path(uni)


class _GlobalDbPathProxy(os.PathLike):
    """Transparent proxy resolving to the active global authentication database."""
    def _path(self) -> Path:
        return get_auth_db_path()

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return f"<GlobalDbPathProxy: {self._path()}>"

    def __eq__(self, other) -> bool:
        return self._path() == other

    def __hash__(self) -> int:
        return hash(self._path())

    def exists(self) -> bool:
        return self._path().exists()

    @property
    def parent(self) -> Path:
        return self._path().parent

    @property
    def name(self) -> str:
        return self._path().name

    def resolve(self) -> Path:
        return self._path().resolve()

    def stat(self):
        return self._path().stat()

    def open(self, *args, **kwargs):
        return self._path().open(*args, **kwargs)


DB_PATH = _GlobalDbPathProxy()


def load_family_whitelist(db_path: Any) -> Dict[str, Dict[str, Any]]:
    """
    Loads the family whitelist dynamically from the SQLite users table,
    keyed by lowercase email.
    """
    whitelist: Dict[str, Dict[str, Any]] = {}

    if db_path.exists():
        try:
            import security
            security.init_db(db_path)
            from db.auth_repo import get_all_users_with_email
            for r in get_all_users_with_email(db_path):
                fam_id = r["family_id"]
                fam_key: Optional[bytes] = None
                if fam_id:
                    try:
                        fam_key = security.get_family_key(db_path, fam_id)
                    except Exception:
                        fam_key = None
                if fam_key is None and r["pending_fek_enc"]:
                    try:
                        fam_key = security._get_fernet(security.get_or_create_key()).decrypt(
                            str(r["pending_fek_enc"]).encode("utf-8")
                        )
                    except Exception:
                        fam_key = None
                if fam_key is None and str(r["email"] or "").startswith("gAAAAA"):
                    continue
                em = security.decrypt_field(r["email"], default="", key=fam_key).strip().lower()
                if em:
                    full_name = security.decrypt_field(r["name"], default="User", key=fam_key).strip()
                    first_name = person_name.first_name(full_name, "User")
                    r_role = (r["role"] or "viewer").strip().lower()
                    admin_role = "admin" if r_role in ("admin", "editor") else r_role
                    whitelist[em] = {
                        "user_id": r["user_id"],
                        "family_id": r["family_id"],
                        "name": first_name,
                        "display_name": full_name,
                        "role": admin_role,
                        "permissions": ["all"] if admin_role == "admin" else ["view_dashboard", "view_education", "view_overview"],
                    }
        except Exception:
            pass

    return whitelist


def get_family_whitelist() -> Dict[str, Dict[str, Any]]:
    """Returns the family whitelist loaded dynamically from the SQLite users table."""
    return load_family_whitelist(DB_PATH)


def get_oauth_credentials() -> Tuple[str, str]:
    """Retrieves Google Client ID and Secret from environment."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    return client_id, client_secret


def get_redirect_uri() -> str:
    """Computes dynamic redirect URI based on current request host or environment override."""
    env_redirect = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    return build_redirect_uri(env_redirect or None)


def _extract_appdata_fek(appdata: Optional[Dict[str, Any]], family_id: int) -> Optional[bytes]:
    """Extracts and validates a Fernet FEK for `family_id` from a Google appDataFolder JSON dict."""
    if not isinstance(appdata, dict):
        return None
    import security

    candidate: Optional[str] = None
    fek_map = appdata.get("fek_map")
    if isinstance(fek_map, dict) and str(family_id) in fek_map:
        candidate = str(fek_map[str(family_id)] or "").strip()
    elif appdata.get("fek"):
        stored_fid = appdata.get("family_id")
        if stored_fid is None or int(stored_fid or 0) == int(family_id):
            candidate = str(appdata["fek"]).strip()

    if not candidate:
        return None
    try:
        raw_bytes = candidate.encode("utf-8")
        security._get_fernet(raw_bytes)
        return raw_bytes
    except Exception:
        return None


def _is_valid_candidate_fek(
    candidate_fek: Optional[bytes],
    user_row: Optional[Dict[str, Any]],
    clean_email: str,
) -> bool:
    """Verifies that a candidate FEK from cookie/session can decrypt the user's encrypted email record."""
    if not candidate_fek:
        return False
    enc_email = str(user_row.get("email") or "") if user_row is not None else ""
    return is_valid_candidate_fek(
        candidate_fek,
        [enc_email] if enc_email else (),
        expected_email=clean_email if enc_email.startswith("gAAAAA") else None,
    )


def _resolve_appdata_fek(
    read_fn: Callable[..., Any],
    access_token: str,
    fid: int,
    user_row: Optional[Dict[str, Any]],
    clean_email: str,
) -> Optional[bytes]:
    """Reads and validates a household FEK from the user's Google Drive appDataFolder."""
    appdata_fname = config.get_vault_appdata_filename()
    appdata = read_fn(str(access_token), filename=appdata_fname)
    cand_appdata_fek = _extract_appdata_fek(appdata, fid)
    if not _is_valid_candidate_fek(cand_appdata_fek, user_row, clean_email) and appdata_fname != "hvl_vault_key.json":
        appdata = read_fn(str(access_token), filename="hvl_vault_key.json")
        cand_appdata_fek = _extract_appdata_fek(appdata, fid)
    if _is_valid_candidate_fek(cand_appdata_fek, user_row, clean_email):
        return cand_appdata_fek
    return None


def resolve_household_vault_fek(
    db_path: Any,
    fid: int,
    user_row: Optional[Dict[str, Any]],
    clean_email: str,
    access_token: Optional[str],
    already_synced: bool,
    read_appdata_fn: Callable[..., Any],
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """
    Resolves the Family Encryption Key (FEK) across browser cookie, Google Drive appDataFolder,
    one-time `pending_fek_enc`, and server-escrowed `families.encryption_key_enc`.
    Returns `(raw_fek, fek_source, error_message)`.
    """
    import security

    raw_fek: Optional[bytes] = None
    fek_source: Optional[str] = None
    locked_err = "Household vault is cryptographically locked and no key was found in your Google Drive appDataFolder or device cookie."

    if already_synced:
        cand_fek = security.get_request_vault_fek(fid)
        if _is_valid_candidate_fek(cand_fek, user_row, clean_email):
            raw_fek = cand_fek
            fek_source = "cookie"
        else:
            session.pop("vault_fek", None)
            if has_request_context() and hasattr(g, "_active_vault_feks"):
                getattr(g, "_active_vault_feks", {}).pop(fid, None)

        vault_locked = False
        if raw_fek is None and db_path.exists():
            try:
                raw_fek = security.get_family_key(db_path, fid)
                if raw_fek is not None:
                    fek_source = "family_table"
            except PermissionError:
                vault_locked = True
            except Exception:
                raw_fek = None

        if raw_fek is None and access_token:
            raw_fek = _resolve_appdata_fek(read_appdata_fn, str(access_token), fid, user_row, clean_email)
            if raw_fek is not None:
                fek_source = "appdata"

        if raw_fek is None and vault_locked and user_row is not None:
            return None, None, locked_err
        return raw_fek, fek_source, None

    if access_token:
        raw_fek = _resolve_appdata_fek(read_appdata_fn, str(access_token), fid, user_row, clean_email)
        if raw_fek is not None:
            fek_source = "appdata"

    if raw_fek is None:
        cand_fek = security.get_request_vault_fek(fid)
        if _is_valid_candidate_fek(cand_fek, user_row, clean_email):
            raw_fek = cand_fek
            fek_source = "cookie"
        else:
            session.pop("vault_fek", None)
            if has_request_context() and hasattr(g, "_active_vault_feks"):
                getattr(g, "_active_vault_feks", {}).pop(fid, None)

    if raw_fek is None and user_row is not None and user_row.get("pending_fek_enc"):
        try:
            raw_fek = security._get_fernet(security.get_or_create_key()).decrypt(
                str(user_row["pending_fek_enc"]).encode("utf-8")
            )
            fek_source = "pending"
        except Exception:
            raw_fek = None

    if raw_fek is None and db_path.exists():
        try:
            raw_fek = security.get_family_key(db_path, fid)
            fek_source = "family_table"
        except PermissionError:
            if user_row is not None:
                return None, None, locked_err
        except Exception:
            raw_fek = None

    return raw_fek, fek_source, None


def capture_pending_sandbox_migration() -> Tuple[int, Optional[bytes], bool]:
    """Captures any active resumable Anonymous Workspace lease before OAuth session reset."""
    if config.is_local_mode() or not has_request_context():
        return 0, None, False
    wants_migrate = bool(
        session.pop("migrate_sandbox_to_cloud", False)
        or request.args.get("migrate_sandbox") == "1"
    )
    try:
        from routes.sandbox import get_resumable_sandbox_lease
        sb_fid, sb_fek, sb_lease = get_resumable_sandbox_lease()
        if sb_fid > 0 and sb_fek and (wants_migrate or (sb_lease and sb_lease.get("has_data"))):
            return sb_fid, sb_fek, wants_migrate
    except Exception:
        pass
    return 0, None, False


def apply_pending_sandbox_migration(
    sb_ctx: Tuple[int, Optional[bytes], bool],
    fid: int,
    raw_fek: Optional[bytes],
    user_row: Optional[Dict[str, Any]],
    db_path: Any,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Migrates an active Anonymous Workspace into the newly authenticated Cloud Vault when applicable."""
    sb_fid, sb_fek, wants_migrate = sb_ctx
    if sb_fid <= 0 or not sb_fek or not raw_fek or fid <= 0:
        return False, user_row
    try:
        from services.fovault_service import migrate_active_sandbox_to_cloud_vault
        migrated = migrate_active_sandbox_to_cloud_vault(
            sb_fid, sb_fek, fid, raw_fek, force_overwrite=wants_migrate
        )
        if not migrated:
            return False, user_row
        if has_request_context():
            g._clear_sandbox_cookie = True
        if user_row is not None and db_path.exists():
            from db.auth_repo import get_user_by_id
            refreshed = get_user_by_id(db_path, int(user_row["user_id"]))
            if refreshed is not None:
                user_row = refreshed
        return True, user_row
    except Exception:
        return False, user_row


def _attach_vault_cookie(response: Any) -> Any:
    """Attaches any pending wrapped FEK cookie to the outgoing OAuth login response."""
    if getattr(g, "_clear_sandbox_cookie", False):
        response.delete_cookie("hvl_sandbox_fid", path="/")
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
    if getattr(g, "_onboarding_redirect", False) or session.pop("onboarding_redirect", False):
        if response.status_code in (301, 302, 303, 307, 308):
            loc = str(response.headers.get("Location") or "")
            if loc in ("/", "http://localhost/", "https://localhost/"):
                response.headers["Location"] = "/?onboarding=1"
        elif getattr(response, "is_json", False):
            try:
                payload = response.get_json(silent=True)
                if isinstance(payload, dict) and payload.get("success"):
                    payload["redirect"] = "/?onboarding=1"
                    response.set_data(json.dumps(payload))
            except Exception:
                pass
    return response


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
    """Authenticates `email` and establishes the session; any denial clears the whole session (no half-logged-in demo/sandbox leftovers)."""
    try:
        ok, member, msg = _establish_family_session(email, profile_info)
    except BaseException:
        session.clear()
        raise
    if not ok:
        session.clear()
    return ok, member, msg


def _visitor_state() -> str:
    """A new household's starting state from the visitor's Cloudflare location, or "" (onboarding asks)."""
    return residence_state.from_request_headers(request.headers) if has_request_context() else residence_state.UNSET


def _establish_family_session(email: str, profile_info: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]], str]:
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
        for k in (
            "is_demo", "is_sandbox", "vault_fek", "vault_fek_family_id",
            "authenticated", "role", "user_role", "user_family_id", "family_id",
        ):
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
            em_hash = security.email_hash_candidates(clean_email)
            from db.auth_repo import get_user_by_email_hash
            user_row = get_user_by_email_hash(DB_PATH, em_hash)
        except Exception:
            user_row = None

    profile_name = str((profile_info or {}).get("name") or "").strip() if isinstance(profile_info, dict) else ""

    if user_row is None and pending_invite_code and DB_PATH.exists():
        try:
            redeem_res = security.redeem_invite_token(
                Path(DB_PATH), pending_invite_code, clean_email, profile_name, home_state=_visitor_state()
            )
            if redeem_res:
                is_new_household_from_invite = bool(redeem_res.get("is_new_household"))
                em_hash = security.email_hash_candidates(clean_email)
                from db.session import resolve_db_path
                from db.auth_repo import get_user_by_email_hash
                lookup_db = resolve_db_path(DB_PATH, family_id=int(redeem_res["family_id"]))
                for cand_db in (lookup_db, Path(DB_PATH)):
                    user_row = get_user_by_email_hash(cand_db, em_hash)
                    if user_row is not None:
                        break
        except VaultLockedError as exc:
            return False, None, str(exc)
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
                provisioned = provision_self_serve_household(
                    Path(DB_PATH), user_email=clean_email, user_name=profile_name, state=_visitor_state()
                )
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
        fid = int(user_row["family_id"] or 0)
        r_role = str(user_row.get("role") or "viewer").strip().lower()
        admin_role = "admin" if r_role in ("admin", "editor") else r_role
    else:
        assert member is not None
        uid = int(member.get("user_id") or 0)
        fid = int(member.get("family_id") or 0)
        admin_role = member["role"]

    if fid <= 0 or uid <= 0:
        return False, None, f"Access denied. '{clean_email}' is not linked to a household on this instance."

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
            from services import background_jobs

            resolved_db_path = Path(DB_PATH)
            # The per-family DB holds its own copy of users/families; clearing escrow only in
            # global.db would leave the household server-decryptable through families/{fid}.db.
            peer_dbs = security.household_auth_peer_dbs(resolved_db_path, fid)
            family_db_path = peer_dbs[0] if peer_dbs else None
            sync_uid = uid if user_row is not None else None
            if needs_google_write and not background_jobs.should_run_synchronously():
                background_jobs.EXECUTOR.submit(
                    _sync_fek_to_google_and_db, access_token, fid, sync_uid, raw_fek, fek_source,
                    needs_google_write, resolved_db_path, family_db_path,
                )
            else:
                _sync_fek_to_google_and_db(
                    access_token, fid, sync_uid, raw_fek, fek_source, needs_google_write, resolved_db_path, family_db_path,
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
        first_name = person_name.first_name(full_name, "User")
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
    session["user_family_id"] = fid
    session["family_id"] = fid
    session["universe"] = "public"
    session["user_id"] = uid
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
