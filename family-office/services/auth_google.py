"""
Google OAuth 2.0 & Google Identity Services Authentication Module
Provides secure multi-user authentication with self-serve isolated household provisioning,
database-backed family member lookups, and zero-knowledge Google Drive `appDataFolder` FEK escrow.
Powered by shared module `hvl_common.auth`.
"""

from __future__ import annotations

import json
import logging
from sqlalchemy.exc import SQLAlchemyError
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography.fernet import InvalidToken
from flask import g, has_request_context, request, session

import config  # noqa: F401 
from hvl_common.auth import (
    GOOGLE_APPDATA_SCOPE,
    build_redirect_uri,
    create_google_auth_blueprint,
    read_google_appdata_json,
    verify_google_id_token,
)
from hvl_common.security import VAULT_COOKIE_NAME
from hvl_common.web import rate_limit

__all__ = ["GOOGLE_APPDATA_SCOPE", "build_redirect_uri", "verify_google_id_token", "VAULT_COOKIE_NAME"]

from config import get_global_db_path
from security.init import VaultLockedError
from services import person_name, residence_state
from services.auth_sandbox_migration import apply_pending_sandbox_migration, capture_pending_sandbox_migration
from services.auth_vault_fek import escrow_resolved_fek, resolve_household_vault_fek
from db.household_activity import (
    provision_self_serve_household,
    record_family_login,
)


logger = logging.getLogger(__name__)


def get_auth_db_path() -> Path:
    """Resolves the global authentication database path for user and family whitelist lookups."""
    from services.request_context import get_current_universe

    return get_global_db_path(get_current_universe())


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
        import security
        from db.auth_repo import get_all_users_with_email

        # A failure here raises: an empty whitelist would read as "no such user" and sign up a new household.
        security.init_db(db_path)
        for r in get_all_users_with_email(db_path):
            fam_id = r["family_id"]
            fam_key: Optional[bytes] = None
            if fam_id:
                try:
                    fam_key = security.get_family_key(db_path, fam_id)
                except PermissionError:
                    fam_key = None  # locked vault: this household's members stay unreadable
                except (ValueError, InvalidToken, SQLAlchemyError, OSError) as exc:
                    logger.warning("Household %s key unavailable; its members are left out of the whitelist: %s",
                                   fam_id, exc)
                    fam_key = None
            if fam_key is None and r["pending_fek_enc"]:
                try:
                    fam_key = security._get_fernet(security.get_or_create_key()).decrypt(
                        str(r["pending_fek_enc"]).encode("utf-8")
                    )
                except (InvalidToken, ValueError):
                    fam_key = None
            if fam_key is None and str(r["email"] or "").startswith("gAAAAA"):
                continue
            em = security.decrypt_field(r["email"], default="", key=fam_key).strip().lower()
            if em:
                full_name = security.decrypt_field(r["name"], default="User", key=fam_key).strip()
                whitelist[em] = _member_record(r["user_id"], r["family_id"], full_name, _admin_role(r["role"]))

    return whitelist


def _admin_role(raw_role: Any) -> str:
    """A users.role as the session role: editors sign in as admins; an empty role is a viewer."""
    role = str(raw_role or "viewer").strip().lower()
    return "admin" if role in ("admin", "editor") else role


def _member_record(user_id: Any, family_id: Any, full_name: str, role: str) -> Dict[str, Any]:
    """The signed-in member as the session and the login blueprint see it."""
    return {
        "user_id": user_id,
        "family_id": family_id,
        "name": person_name.first_name(full_name, "User"),
        "display_name": full_name,
        "role": role,
        "permissions": ["all"] if role == "admin" else ["view_dashboard", "view_education", "view_overview"],
    }


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
            payload = response.get_json(silent=True)
            if isinstance(payload, dict) and payload.get("success"):
                payload["redirect"] = "/?onboarding=1"
                response.set_data(json.dumps(payload))
    return response


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


def _leave_non_public_universe() -> Tuple[Optional[Any], Optional[Any]]:
    """
    Drops demo/sandbox session keys before a real sign-in and moves the session to the public universe.
    Returns the `(vault_fek, vault_fek_family_id)` a public session may carry over, else `(None, None)`.
    """
    was_non_public = bool(
        session.get("is_demo")
        or session.get("is_sandbox")
        or str(session.get("universe") or "public").strip().lower() not in ("public", "test", "")
    )
    if not was_non_public:
        return session.get("vault_fek"), session.get("vault_fek_family_id")
    for k in (
        "is_demo", "is_sandbox", "vault_fek", "vault_fek_family_id",
        "authenticated", "role", "user_role", "user_family_id", "family_id",
    ):
        session.pop(k, None)
    session["universe"] = "public"
    return None, None


def _pending_invite_code(profile_info: Optional[Dict[str, Any]]) -> str:
    """The household invite code this sign-in carries: from the session, the OAuth profile, or `?invite=`."""
    code = str(session.get("pending_invite_code") or "").strip().upper()
    if not code and isinstance(profile_info, dict) and profile_info.get("invite_code"):
        code = str(profile_info.get("invite_code") or "").strip().upper()
    if not code and has_request_context():
        code = str(request.args.get("invite") or "").strip().upper()
    return code


def _find_or_provision_user(
    clean_email: str,
    profile_name: str,
    member: Optional[Dict[str, Any]],
    invite_code: str,
) -> Tuple[Optional[Dict[str, Any]], bool, Optional[str]]:
    """
    Finds the signed-in user's row, redeeming a pending invite or provisioning a new household when there is none.
    Returns `(user_row, is_new_household, denial_message)`; a denial message means the sign-in is refused.
    """
    import security

    is_new_household = False
    user_row: Optional[Dict[str, Any]] = None
    if DB_PATH.exists():
        # A lookup failure raises: reading it as "no such user" would sign an existing member up as a new household.
        security.init_db(DB_PATH)
        em_hash = security.email_hash_candidates(clean_email)
        from db.auth_repo import get_user_by_email_hash
        user_row = get_user_by_email_hash(DB_PATH, em_hash)

    if user_row is None and invite_code and DB_PATH.exists():
        try:
            redeem_res = security.redeem_invite_token(
                Path(DB_PATH), invite_code, clean_email, profile_name, home_state=_visitor_state()
            )
            if redeem_res:
                is_new_household = bool(redeem_res.get("is_new_household"))
                em_hash = security.email_hash_candidates(clean_email)
                from db.session import resolve_db_path
                from db.auth_repo import get_user_by_email_hash
                lookup_db = resolve_db_path(DB_PATH, family_id=int(redeem_res["family_id"]))
                for cand_db in (lookup_db, Path(DB_PATH)):
                    user_row = get_user_by_email_hash(cand_db, em_hash)
                    if user_row is not None:
                        break
        except VaultLockedError as exc:
            return None, False, str(exc)
        except (OSError, SQLAlchemyError) as exc:
            # The redeem hit a storage fault: deny (fail closed) without showing the path to the visitor.
            logger.warning("Invite redemption failed for a pending invite: %s", type(exc).__name__)
        if user_row is None and member is None:
            session.pop("pending_invite_code", None)
            return (
                None,
                False,
                "Invalid, expired, or already-redeemed household invite code. Please verify the code with your household owner or sign in without an invite code to create a new vault.",
            )

    if member is None and user_row is None and config.is_local_mode():
        from routes.desktop import bootstrap_local_google_owner
        local_owner = bootstrap_local_google_owner(email=clean_email, display_name=profile_name, db_path=Path(DB_PATH))
        if local_owner:
            user_row = local_owner
            is_new_household = True

    if member is None and user_row is None and not config.is_local_mode():
        public_signup = os.getenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "1").strip().lower() not in ("0", "false", "no")
        if public_signup and DB_PATH.exists():
            provisioned = provision_self_serve_household(
                Path(DB_PATH), user_email=clean_email, user_name=profile_name, state=_visitor_state()
            )
            if provisioned:
                user_row = provisioned
                is_new_household = True

    if member is None and user_row is None:
        return (
            None,
            False,
            f"Access denied. '{clean_email}' is not registered on this instance and self-serve sign-up is currently disabled.",
        )
    return user_row, is_new_household, None


def _write_authenticated_session(
    member: Dict[str, Any], clean_email: str, fid: int, uid: int, profile_info: Optional[Dict[str, Any]]
) -> None:
    """Writes the signed-in member into the Flask session (public universe, Google OAuth)."""
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


def _establish_family_session(email: str, profile_info: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Validates email against existing household records (or auto-provisions an isolated household vault),
    resolves/self-heals the Family Encryption Key (FEK) across Google `appDataFolder` and browser cookie,
    records the household login timestamp, and establishes the authenticated session.
    """
    import security

    sb_migration_ctx = capture_pending_sandbox_migration()
    prev_vault_fek, prev_vault_fid = _leave_non_public_universe()

    if DB_PATH.exists():
        try:
            security.purge_expired_deleted_families(Path(DB_PATH))
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("Expired-household purge skipped: %s", exc)

    clean_email = email.strip().lower()
    member: Optional[Dict[str, Any]] = get_family_whitelist().get(clean_email)
    profile_name = str((profile_info or {}).get("name") or "").strip() if isinstance(profile_info, dict) else ""

    user_row, is_new_household_from_invite, denial = _find_or_provision_user(
        clean_email, profile_name, member, _pending_invite_code(profile_info)
    )
    if denial is not None:
        return False, None, denial

    if user_row is not None:
        uid = int(user_row["user_id"])
        fid = int(user_row["family_id"] or 0)
        admin_role = _admin_role(user_row.get("role"))
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
        escrow_resolved_fek(
            access_token, fid, uid if user_row is not None else None, raw_fek, fek_source, already_synced, DB_PATH,
        )

    if DB_PATH.exists() and not is_new_household_from_invite:
        try:
            record_family_login(Path(DB_PATH), family_id=fid)
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("Could not record the login for household %s: %s", fid, exc)

    if user_row is not None:
        full_name = security.decrypt_field(user_row.get("name") or "", default="User", key=raw_fek).strip()
        if not full_name:
            full_name = str((profile_info or {}).get("name") or "User").strip()
        member = _member_record(uid, fid, full_name, admin_role)

    assert member is not None
    _write_authenticated_session(member, clean_email, fid, uid, profile_info)

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
