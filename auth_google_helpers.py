"""
Helper utilities for Google OAuth 2.0 & Household Vault FEK authentication.
Extracted from `auth_google.py` to maintain modular file sizes (<400 lines).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from flask import g, has_request_context, request, session
from hvl_common.auth import build_redirect_uri

import config
from config import get_global_db_path


def get_auth_db_path() -> Path:
    """Resolves the global authentication database path for user and family whitelist lookups."""
    try:
        from routes.helpers import get_current_universe
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


def load_family_whitelist(db_path: Any) -> Dict[str, Dict[str, Any]]:
    """
    Loads the family whitelist dynamically from the SQLite users table,
    merged with any additional family members configured in `.env`.
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
                    first_name = full_name.split()[0] if full_name else "User"
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

    extra_emails_str = os.getenv("FAMILY_CHILDREN_EMAILS", "")
    if extra_emails_str:
        for entry in extra_emails_str.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                email_part, name_part = entry.split(":", 1)
                email_part = email_part.strip().lower()
                name_part = name_part.strip()
            else:
                email_part = entry.lower()
                name_part = email_part.split("@")[0].capitalize()

            if email_part:
                whitelist[email_part] = {
                    "name": name_part,
                    "display_name": name_part,
                    "role": "family_member",
                    "permissions": ["view_dashboard", "view_education", "view_overview"],
                }

    return whitelist


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
    if user_row is not None:
        enc_email = str(user_row.get("email") or "")
        if enc_email.startswith("gAAAAA"):
            import security
            try:
                dec = security._get_fernet(candidate_fek).decrypt(enc_email.encode("utf-8")).decode("utf-8").strip().lower()
                return dec == clean_email
            except Exception:
                return False
    return True


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
