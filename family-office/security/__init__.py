"""
Security and Encryption Utility Facade & Family/Member Management.
Delegates cryptographic primitives to security.crypto,
multi-tenant SQLite store/DEK lifecycle to security.store,
and household lifecycle/invites/vault/audit across focused security.* modules,
while exposing the unified public API and preserving 100% monkeypatch compatibility.
"""

from __future__ import annotations

from hvl_common.security import VAULT_COOKIE_NAME, wrap_cookie_fek, unwrap_cookie_fek

__all__ = ["VAULT_COOKIE_NAME", "wrap_cookie_fek", "unwrap_cookie_fek"]

from security.crypto import (
    BASE_DIR,
    ENV_FILE,
    KEY_FILE,
    _DB_INIT_CACHE,
    _FAMILY_KEY_CACHE,
    _FERNET_CACHE,
    _ROOT_KEY_CACHE,
    _clear_security_caches,
    _get_fernet,
    _is_authenticated_for_family,
    _parse_fernet_keys,
    decrypt_data,
    decrypt_field,
    decrypt_string,
    encrypt_data,
    encrypt_field,
    encrypt_string,
    get_or_create_key,
    get_primary_key,
    get_request_vault_fek,
    get_stored_cookies,
    get_stored_credentials,
    save_encrypted_cookies,
    save_encrypted_credentials,
    stash_request_vault_fek,
    _BoundedDict,
    _BoundedSet,
    _get_active_env_file,
    _get_active_key_file,
    _PBKDF2_ITERATIONS,
    derive_passphrase_fernet_key,
    wrap_fek_with_passphrase,
    unwrap_fek_with_passphrase,
)
from security.email_hash import email_hash_candidates, hash_email, legacy_hash_email
from security.store import (
    _is_household_vault_initialized,
    _resolve_family_key_on_conn,
    db_load_encrypted,
    db_save_encrypted,
    get_family_key,
    init_db,
    rotate_family_keys,
    run_alembic_migrations,
    validate_vault_snapshot_file,
)
from security.init import (
    _resolve_universe_from_db_path,
    _candidate_family_metadata_dbs,
    get_family,
    update_family,
    _provision_invited_household,
    _join_invited_household,
)
from security.members import (
    get_family_members,
    add_family_member,
    update_family_member,
    delete_family_member,
    find_user_by_email,
    resolve_local_user_name,
)
from security.vault import (
    SupportAccessWriteError,
    household_auth_peer_dbs,
    set_family_support_access,
    is_local_vault_unclaimed,
    has_local_passphrase_configured,
    provision_first_local_household,
    get_local_login_record,
    update_local_passphrase_fek,
    escrow_local_vault_key,
)
from security.audit import (
    _TENANT_CLEANUP_TABLES,
    _TENANT_CLEANUP_STATEMENTS,
    _parse_deletion_status,
    get_family_deletion_status,
    schedule_family_deletion,
    cancel_family_deletion,
    permanently_delete_family,
    purge_expired_deleted_families,
)
from security.invites import (
    _INVITE_ALPHABET,
    _generate_invite_code,
    _format_invite_row,
    _invite_candidate_dbs,
    allocate_household_id,
    create_invite_token,
    list_invite_tokens,
    revoke_invite_token,
    validate_invite_token,
    redeem_invite_token,
)
from db.telemetry import (
    VALID_DOWNLOAD_TARGETS,
    _GITHUB_TELEMETRY_CACHE,
    _fetch_github_release_metrics,
    get_download_telemetry_summary,
    record_download_event,
)
