"""
`.fovault` restore must never let an uploaded archive take over a login that lives outside the restoring
household. Real SQLite DBs in a tmp data dir; no stubs.
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import config
import security
from wsgi import app
from db.fovault_repo import extract_fek_from_backup_snapshot
from db.users import get_user_by_email_hash
from db.vault_archive_schema import ALLOWED_ARCHIVE_TABLES
from hvl_common.security import PassphraseError
from services import auth_google, auth_vault_fek
from services.fovault_service import (
    apply_fovault_restore_to_db,
    build_fovault_backup_bytes,
    prepare_fovault_restore,
)

PASSPHRASE = "correct-horse-battery"
VICTIM_FID, ATTACKER_FID = 7101, 7102


@pytest.fixture
def universe(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("LOCAL_MODE", "0")
    monkeypatch.setenv("PUBLIC_GOOGLE_SIGNUP_ENABLED", "1")
    security._clear_security_caches()
    global_db = config.get_global_db_path("public")
    security.init_db(global_db)
    monkeypatch.setattr(auth_google, "DB_PATH", global_db)
    monkeypatch.setattr(auth_google, "read_google_appdata_json", lambda token, **kw: None)
    monkeypatch.setattr(auth_vault_fek, "write_google_appdata_json", lambda token, payload, **kw: True)
    yield global_db
    security._clear_security_caches()


def _household(fid: int, email: str, role: str = "admin") -> dict:
    fam_db = config.get_family_db_path(fid, "public")
    security.init_db(fam_db)
    fek = Fernet.generate_key()
    security.stash_request_vault_fek(fid, fek)
    security.get_family_key(fam_db, fid)  # creates the households row
    uid = security.add_family_member(fam_db, family_id=fid, name="Member", email=email, relationship="primary", role=role)
    return {"fid": fid, "uid": uid, "db": fam_db, "fek": fek, "hash": security.hash_email(email), "email": email}


def _global_users(global_db: Path) -> list[tuple]:
    with sqlite3.connect(global_db) as conn:
        return conn.execute("SELECT user_id, family_id, email_hash, role FROM users ORDER BY user_id").fetchall()


def _forged_archive(src: dict, tmp_path: Path, forged_rows: list[dict]) -> bytes:
    """The attacker exports their own vault, then edits the SQLite file to add identity rows."""
    raw, _ = build_fovault_backup_bytes(src["db"], src["fid"], PASSPHRASE)
    path = tmp_path / "forged.fovault"
    path.write_bytes(raw)
    with sqlite3.connect(path) as conn:
        for row in forged_rows:
            conn.execute(
                "INSERT INTO users (user_id, family_id, name, email, email_hash, relationship, role) VALUES (?,?,?,?,?,?,?)",
                (row["user_id"], src["fid"], "forged", None, row["email_hash"], "spouse", row.get("role", "admin")),
            )
        conn.commit()
    data = path.read_bytes()
    path.unlink()
    return data


def _restore(raw: bytes, target: dict) -> None:
    prepared = prepare_fovault_restore(raw, PASSPHRASE)
    security.stash_request_vault_fek(target["fid"], target["fek"])
    ok, err, _ = apply_fovault_restore_to_db(raw, target["db"], target["fid"], restore_fek=prepared.fek, universe="public")
    assert ok, err


def test_forged_victim_row_cannot_take_over_victim_login(universe, tmp_path):
    victim = _household(VICTIM_FID, "victim@example.com", "admin")
    attacker = _household(ATTACKER_FID, "attacker@example.com", "admin")
    before = [r for r in _global_users(universe) if r[1] == VICTIM_FID]
    raw = _forged_archive(attacker, tmp_path, [{"user_id": victim["uid"], "email_hash": victim["hash"], "role": "admin"}])

    _restore(raw, attacker)

    assert [r for r in _global_users(universe) if r[1] == VICTIM_FID] == before
    row = get_user_by_email_hash(universe, victim["hash"])
    assert (row["family_id"], row["user_id"], row["role"]) == (VICTIM_FID, victim["uid"], "admin")
    with sqlite3.connect(victim["db"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE email_hash = ?", (victim["hash"],)).fetchone()[0] == 1
    ok, member, _ = _sign_in(victim["email"])
    assert ok and int(member["family_id"]) == VICTIM_FID
    assert not [r for r in _global_users(universe) if r[1] == ATTACKER_FID and r[2] == victim["hash"]]


def test_forged_unregistered_email_creates_no_global_login_and_signup_gets_fresh_household(universe, tmp_path):
    attacker = _household(ATTACKER_FID, "attacker@example.com", "admin")
    squatted = security.hash_email("newcomer@example.com")
    raw = _forged_archive(attacker, tmp_path, [{"user_id": 990001, "email_hash": squatted}])

    _restore(raw, attacker)

    assert all(r[2] != squatted for r in _global_users(universe))
    assert get_user_by_email_hash(universe, squatted) is None
    with sqlite3.connect(attacker["db"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE email_hash = ?", (squatted,)).fetchone()[0] == 0
    ok, member, _ = _sign_in("newcomer@example.com")
    assert ok and int(member["family_id"]) not in (ATTACKER_FID, VICTIM_FID) and member["is_new_household"] is True


def test_restoring_your_own_vault_keeps_your_login(universe, tmp_path):
    me = _household(ATTACKER_FID, "owner@example.com", "admin")
    raw, _ = build_fovault_backup_bytes(me["db"], me["fid"], PASSPHRASE)

    _restore(raw, me)

    row = get_user_by_email_hash(universe, me["hash"])
    assert row is not None and (row["family_id"], row["user_id"], row["role"]) == (ATTACKER_FID, me["uid"], "admin")
    ok, member, _ = _sign_in("owner@example.com")
    assert ok and int(member["family_id"]) == ATTACKER_FID and not member.get("is_new_household")


def test_restored_members_are_rekeyed_login_less_and_beyond_directory_ids(universe, tmp_path):
    victim = _household(VICTIM_FID, "victim@example.com")
    me = _household(ATTACKER_FID, "owner@example.com")
    raw = _forged_archive(me, tmp_path, [{"user_id": 5, "email_hash": security.hash_email("x@example.com")}])
    top = max(r[0] for r in _global_users(universe))

    _restore(raw, me)

    with sqlite3.connect(me["db"]) as conn:
        rows = conn.execute("SELECT user_id, email_hash FROM users").fetchall()
    imported = [r for r in rows if r[0] != me["uid"]]
    assert imported and all(not r[1] and r[0] > top for r in imported)
    assert victim["uid"] not in [r[0] for r in imported]


def _sign_in(email: str):
    with app.test_request_context("/auth/google/callback"):
        return auth_google.authenticate_family_email(email, {"name": "Someone", "_oauth_tokens": {"access_token": "tok"}})


def test_user_lookup_never_mints_global_login_from_household_db_scan(universe):
    other = _household(VICTIM_FID, "someone@example.com")
    with sqlite3.connect(universe) as conn:
        conn.execute("DELETE FROM users WHERE family_id = ?", (VICTIM_FID,))
        conn.commit()
    assert get_user_by_email_hash(universe, other["hash"]) is None
    assert all(r[1] != VICTIM_FID for r in _global_users(universe))


# ---------------------------------------------------------------- legacy key / schema allowlist / root key

def _make_legacy_server_wrapped(src: dict, tmp_path: Path) -> bytes:
    """A v1 file whose only key material is the server-root-key escrow (`encryption_key_enc`)."""
    raw, _ = build_fovault_backup_bytes(src["db"], src["fid"], PASSPHRASE)
    path = tmp_path / "v1.fovault"
    path.write_bytes(raw)
    wrapped = security._get_fernet(security.get_or_create_key()).encrypt(src["fek"]).decode()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE families SET encryption_key_enc = ?, settings = '{}'", (wrapped,))
        conn.commit()
    data = path.read_bytes()
    path.unlink()
    return data


def test_v1_file_with_only_server_key_wrap_is_refused(universe, tmp_path):
    me = _household(ATTACKER_FID, "owner@example.com")
    raw = _make_legacy_server_wrapped(me, tmp_path)
    with pytest.raises(PassphraseError):
        prepare_fovault_restore(raw, "", allow_legacy=True)
    with pytest.raises(PassphraseError):
        prepare_fovault_restore(raw, PASSPHRASE, allow_legacy=True)


@pytest.mark.parametrize("role,expected", [("editor", 200), ("viewer", 403)])
def test_legacy_import_gate_on_signed_in_users(universe, tmp_path, role, expected):
    me = _household(ATTACKER_FID, "owner@example.com")
    legacy = _legacy_raw_key_archive(me, tmp_path)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(authenticated=True, user_email="owner@example.com", user_family_id=ATTACKER_FID, family_id=ATTACKER_FID,
                    role=role, user_role=role, universe="public")
    res = client.post("/api/vault/restore", data={"file": (io.BytesIO(legacy), "v.fovault"), "allow_legacy": "1"},
                      content_type="multipart/form-data")
    assert res.status_code == expected, res.get_json()


def test_legacy_import_refused_for_anonymous_sandbox_session(universe, tmp_path):
    me = _household(ATTACKER_FID, "owner@example.com")
    legacy = _legacy_raw_key_archive(me, tmp_path)
    client = app.test_client()
    assert client.post("/api/sandbox/launch", json={"template": "miller"}).status_code == 200
    res = client.post("/api/sandbox/restore", data={"file": (io.BytesIO(legacy), "v.fovault"), "allow_legacy": "1"},
                      content_type="multipart/form-data")
    assert res.status_code == 403


def _legacy_raw_key_archive(src: dict, tmp_path: Path) -> bytes:
    raw, _ = build_fovault_backup_bytes(src["db"], src["fid"], PASSPHRASE)
    path = tmp_path / "rawkey.fovault"
    path.write_bytes(raw)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE families SET encryption_key_enc = NULL, settings = ?", ('{"_portable_vault_fek_b64": "%s"}' % src["fek"].decode(),))
        conn.commit()
    data = path.read_bytes()
    path.unlink()
    return data


@pytest.mark.parametrize("bad_sql", [
    'CREATE TABLE "evil"" ; DROP TABLE users; --" (family_id INTEGER)',
    "CREATE TABLE not_in_the_schema (family_id INTEGER)",
    'CREATE TABLE users_shadow (family_id INTEGER)',
    "CREATE TRIGGER t AFTER INSERT ON users BEGIN DELETE FROM families; END",
])
def test_archive_with_unknown_table_or_trigger_is_refused(universe, tmp_path, bad_sql):
    me = _household(ATTACKER_FID, "owner@example.com")
    raw, _ = build_fovault_backup_bytes(me["db"], me["fid"], PASSPHRASE)
    path = tmp_path / "bad.fovault"
    path.write_bytes(raw)
    with sqlite3.connect(path) as conn:
        conn.execute(bad_sql)
        conn.commit()
    bad = path.read_bytes()
    with pytest.raises(ValueError):
        prepare_fovault_restore(bad, PASSPHRASE)
    ok, err, _ = apply_fovault_restore_to_db(bad, me["db"], me["fid"], restore_fek=me["fek"], universe="public")
    assert ok is False and err


def test_archive_column_with_quote_is_refused(universe, tmp_path):
    me = _household(ATTACKER_FID, "owner@example.com")
    raw, _ = build_fovault_backup_bytes(me["db"], me["fid"], PASSPHRASE)
    path = tmp_path / "col.fovault"
    path.write_bytes(raw)
    with sqlite3.connect(path) as conn:
        conn.execute('ALTER TABLE gifts ADD COLUMN "x"" OR 1=1 --" TEXT')
        conn.commit()
    with pytest.raises(ValueError):
        prepare_fovault_restore(path.read_bytes(), PASSPHRASE)


def test_schema_allowlist_covers_every_table_a_fresh_household_db_creates(tmp_path):
    db = tmp_path / "fresh.db"
    security.init_db(db)
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'") if not r[0].startswith("sqlite_")}
    assert tables <= ALLOWED_ARCHIVE_TABLES


# ---------------------------------------------------------------- root key is never a household key

@pytest.mark.parametrize("fid", [0, -1, None])
def test_get_family_key_refuses_tenant_zero(universe, fid):
    with pytest.raises(ValueError):
        security.get_family_key(universe, fid)
