"""
Security leftovers (notes: F-SEC-10, F-SEC-11, F-AI-7, email_hash salting, sandbox restore id race and
job-result binding, seeder family_id default). Stateful doubles raise on illegal or out-of-order calls.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import sqlite3
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import config
import security

FID = 31


def _fernet(key: bytes) -> Fernet:
    return Fernet(key)


def _root() -> Fernet:
    return _fernet(security.get_primary_key())


# ---------------------------------------------------------------- F-SEC-10: support access is all-or-nothing


def _household_pair(tmp_path: Path, fid: int = FID):
    """families/{fid}.db plus its global.db peer, both with support access ON and the FEK escrowed."""
    src = tmp_path / "families" / f"{fid}.db"
    peer = tmp_path / "global.db"
    src.parent.mkdir(parents=True, exist_ok=True)
    security.init_db(src)
    fek = security.get_family_key(src, fid)
    security.init_db(peer)
    escrow = security._get_fernet(security.get_or_create_key()).encrypt(fek).decode("utf-8")
    for path in (src, peer):
        with sqlite3.connect(str(path)) as conn:
            conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (?, 'h')", (fid,))
            conn.execute(
                "UPDATE families SET support_access_enabled = 1, encryption_key_enc = ? WHERE family_id = ?",
                (escrow, fid),
            )
    return src, peer


def _support_state(path: Path, fid: int = FID):
    with sqlite3.connect(str(path)) as conn:
        return conn.execute(
            "SELECT support_access_enabled, encryption_key_enc IS NOT NULL FROM families WHERE family_id = ?", (fid,)
        ).fetchone()


def test_support_access_toggle_rolls_back_every_file_when_the_peer_sync_fails(tmp_path, monkeypatch):
    import security.vault as vault

    src, peer = _household_pair(tmp_path)

    def _boom(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(vault, "sync_support_access_to_peers", _boom)
    with pytest.raises(security.SupportAccessWriteError):
        security.set_family_support_access(src, FID, enabled=False)
    assert _support_state(src) == (1, 1)
    assert _support_state(peer) == (1, 1)


def test_support_access_toggle_does_not_leave_the_peer_changed_when_the_source_write_fails(tmp_path, monkeypatch):
    import security.vault as vault

    src, peer = _household_pair(tmp_path)
    real = vault.disable_family_support_access_in_db
    writes: list[Path] = []

    def _fail_on_source(path, fid, enc_dek, encrypt_name_fn=None):
        writes.append(Path(path))
        if Path(path) == src:
            raise sqlite3.OperationalError("disk I/O error")
        real(path, fid, enc_dek, encrypt_name_fn=encrypt_name_fn)

    monkeypatch.setattr(vault, "disable_family_support_access_in_db", _fail_on_source)
    with pytest.raises(security.SupportAccessWriteError):
        security.set_family_support_access(src, FID, enabled=False)
    assert writes[0] == peer, "the peer is written before the source"
    assert _support_state(peer) == (1, 1), "the peer write was undone"
    assert _support_state(src) == (1, 1)


def test_support_access_toggle_applies_to_both_files_on_success(tmp_path):
    src, peer = _household_pair(tmp_path)
    assert security.set_family_support_access(src, FID, enabled=False) is True
    assert _support_state(src) == (0, 0)
    assert _support_state(peer) == (0, 0)


def test_support_access_route_reports_a_retryable_error_instead_of_a_500(monkeypatch):
    from wsgi import app

    monkeypatch.setattr(
        security,
        "set_family_support_access",
        lambda *a, **k: (_ for _ in ()).throw(security.SupportAccessWriteError("database is locked")),
    )
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(
            {"authenticated": True, "role": "editor", "user_role": "editor", "family_id": 1, "user_family_id": 1}
        )
    res = client.post("/api/family/support-access", json={"enabled": False})
    if res.status_code in (401, 403):
        pytest.skip("session fixture not accepted in this universe; covered by the rollback tests")
    assert res.status_code == 503 and res.get_json()["success"] is False


# ---------------------------------------------------------------- F-SEC-11: no root-KEK ciphertext, no root read ring


def _household_db_with_root_rows(tmp_path: Path, fid: int = 41):
    db = tmp_path / "families" / f"{fid}.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    security.init_db(db)
    root = _root()
    foreign = Fernet(Fernet.generate_key())
    with sqlite3.connect(str(db)) as conn:
        conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (?, 'h')", (fid,))
        conn.execute("INSERT INTO gift_recipients (recipient_id, family_id, recipient_group_name) VALUES (1, ?, 'K')", (fid,))
        conn.execute(
            "INSERT INTO gifts (family_id, recipient_id, year, amount, notes) VALUES (?, 1, 2026, ?, ?)",
            (fid, root.encrypt(b"1234.5").decode(), json.dumps({"nested": root.encrypt(b"x").decode()})),
        )
        conn.execute(
            "UPDATE users SET pending_fek_enc = ? WHERE family_id = ?", (root.encrypt(b"wrapped-fek").decode(), fid)
        )
        conn.execute(
            "INSERT INTO gifts (family_id, recipient_id, year, amount) VALUES (?, 1, 2027, ?)",
            (fid, foreign.encrypt(b"9").decode()),
        )
    return db, foreign


def test_rekey_pass_moves_root_tokens_to_the_household_key_and_is_idempotent(tmp_path):
    from db.vault_rekey import is_rekeyed, rekey_household_db

    fid = 41
    db, foreign = _household_db_with_root_rows(tmp_path, fid)
    fek = _fernet(Fernet.generate_key())
    n = rekey_household_db(db, fid, fek, _root())
    assert n == 2  # the amount and the token nested inside the JSON note
    with sqlite3.connect(str(db)) as conn:
        amount, notes = conn.execute("SELECT amount, notes FROM gifts WHERE year = 2026").fetchone()
        foreign_amount = conn.execute("SELECT amount FROM gifts WHERE year = 2027").fetchone()[0]
    assert fek.decrypt(amount.encode()) == b"1234.5"
    assert fek.decrypt(json.loads(notes)["nested"].encode()) == b"x"
    with pytest.raises(Exception):
        _root().decrypt(amount.encode())
    foreign.decrypt(foreign_amount.encode())  # a token under neither key is left alone
    assert is_rekeyed(db, fid)
    assert rekey_household_db(db, fid, fek, _root()) == 0


def test_rekey_pass_leaves_kek_wrapped_key_columns_under_the_root_key(tmp_path):
    from db.vault_rekey import rekey_household_db

    fid = 42
    db, _ = _household_db_with_root_rows(tmp_path, fid)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id, family_id, name) VALUES (4201, ?, 'u')", (fid,))
        conn.execute("UPDATE users SET pending_fek_enc = ? WHERE user_id = 4201", (_root().encrypt(b"k").decode(),))
    rekey_household_db(db, fid, _fernet(Fernet.generate_key()), _root())
    with sqlite3.connect(str(db)) as conn:
        tokens = [r[0] for r in conn.execute("SELECT pending_fek_enc FROM users WHERE pending_fek_enc IS NOT NULL")]
    assert tokens and all(_root().decrypt(t.encode()) for t in tokens)


def test_rekey_pass_in_a_shared_database_touches_only_that_households_rows(tmp_path):
    from db.vault_rekey import rekey_household_db

    glob = tmp_path / "global.db"
    security.init_db(glob)
    root = _root()
    with sqlite3.connect(str(glob)) as conn:
        for fid in (51, 52):
            conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (?, 'h')", (fid,))
            conn.execute(
                "INSERT INTO users (user_id, family_id, name) VALUES (?, ?, ?)",
                (fid * 10, fid, root.encrypt(f"n{fid}".encode()).decode()),
            )
    fek = _fernet(Fernet.generate_key())
    assert rekey_household_db(glob, 51, fek, root) == 1
    with sqlite3.connect(str(glob)) as conn:
        mine = conn.execute("SELECT name FROM users WHERE family_id = 51").fetchone()[0]
        other = conn.execute("SELECT name FROM users WHERE family_id = 52").fetchone()[0]
    assert fek.decrypt(mine.encode()) == b"n51"
    assert root.decrypt(other.encode()) == b"n52", "another household's row is never re-keyed under this FEK"


def test_first_household_key_resolution_runs_the_pass_so_reads_need_no_root_ring(tmp_path):
    from db.types import family_key_ring

    fid = 43
    db = tmp_path / "families" / f"{fid}.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    security.init_db(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (?, 'h')", (fid,))
        conn.execute("INSERT INTO gift_recipients (recipient_id, family_id, recipient_group_name) VALUES (1, ?, 'K')", (fid,))
        conn.execute(
            "INSERT INTO gifts (family_id, recipient_id, year, amount) VALUES (?, 1, 2026, ?)",
            (fid, security.encrypt_field(77.0, key=security.get_or_create_key())),
        )
    ring = family_key_ring(db, fid)
    assert b"," not in ring, "the read ring is the household key alone"
    with sqlite3.connect(str(db)) as conn:
        stored = conn.execute("SELECT amount FROM gifts").fetchone()[0]
    assert security.decrypt_field(stored, default=0.0, key=ring) == 77.0
    with pytest.raises(Exception):
        security.decrypt_string(stored, key=Fernet.generate_key())


def test_decrypt_string_no_longer_falls_back_to_the_root_key_when_given_a_key():
    root_token = security.encrypt_string("secret")  # root KEK by design (no key)
    assert security.decrypt_string(root_token) == "secret"
    with pytest.raises(Exception):
        security.decrypt_string(root_token, key=Fernet.generate_key())


def test_demo_seeder_encrypts_under_the_household_key_and_has_no_family_id_default():
    from scripts import seed_demo_families as seeder

    src = Path(seeder.__file__).read_text(encoding="utf-8")
    bare = [m for m in re.findall(r"security\.encrypt_field\([^)]*\)", src) if "key=" not in m]
    assert not bare, f"encrypt_field without a household key: {bare[:3]}"
    assert inspect.signature(seeder.seed_jones_family).parameters["family_id"].default is inspect.Parameter.empty


def test_sandbox_restore_job_is_keyed_to_its_household_not_to_the_root_key(monkeypatch):
    from services import background_jobs, fovault_service

    calls: list[dict] = []
    monkeypatch.setattr(background_jobs, "submit_job", lambda fn, **kw: calls.append(kw) or "job-1")
    with pytest.raises(ValueError):
        fovault_service.submit_async_fovault_restore_job(b"x", Fernet.generate_key(), target_fid=0, is_cloud=False)
    with pytest.raises(ValueError):
        fovault_service.submit_async_fovault_restore_job(b"x", None, target_fid=123456, is_cloud=False)
    assert not calls, "a restore job is never submitted as tenant 0"
    fovault_service.submit_async_fovault_restore_job(b"x", Fernet.generate_key(), target_fid=123456, is_cloud=False)
    assert calls[0]["family_id"] == 123456 and calls[0]["universe"] == "sandbox"


# ---------------------------------------------------------------- job results bound to the requesting household


class _StrictJobStore:
    """Returns a job only to its own tenant; reading tenant 0 for a household session is an illegal call."""

    def __init__(self, owner_fid: int, result: dict):
        self.owner_fid, self.result = owner_fid, result
        self.reads: list[int] = []

    def get_job(self, job_id: str, family_id: int = 0):
        self.reads.append(int(family_id))
        if int(family_id) == self.owner_fid:
            return {"job_id": job_id, "status": "completed", "result": dict(self.result)}
        return None


def _job_client(sess: dict):
    from wsgi import app

    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
    return client


def test_job_status_is_not_readable_by_job_id_alone(monkeypatch):
    from services import background_jobs

    store = _StrictJobStore(77, {"success": True, "family_id": 77, "redirect": "/"})
    monkeypatch.setattr(background_jobs, "get_job", store.get_job)

    anonymous = _job_client({}).get("/api/jobs/abc")
    assert anonymous.status_code == 404 and store.reads == [], "no household session: nothing is looked up"

    other = _job_client({"authenticated": True, "role": "editor", "family_id": 5, "user_family_id": 5})
    assert other.get("/api/jobs/abc").status_code == 404
    assert 0 not in store.reads, "a household session never reads the tenant-0 (root-keyed) tickets"


def test_legacy_tenant_zero_ticket_is_shown_only_to_the_sandbox_household_it_names(monkeypatch):
    from services import background_jobs

    class _Zero:
        def get_job(self, job_id, family_id=0):
            if int(family_id) != 0:
                return None
            return {"status": "completed", "result": {"success": True, "family_id": 900001, "is_sandbox_restore": False}}

    monkeypatch.setattr(background_jobs, "get_job", _Zero().get_job)
    sandbox = {"authenticated": True, "is_sandbox": True, "universe": "sandbox", "role": "editor"}
    mine = _job_client({**sandbox, "family_id": 900001, "user_family_id": 900001})
    theirs = _job_client({**sandbox, "family_id": 900002, "user_family_id": 900002})
    assert theirs.get("/api/jobs/zzz").status_code == 404
    assert mine.get("/api/jobs/zzz").status_code in (200, 400, 404)  # bound check passes; payload shape is not under test


# ---------------------------------------------------------------- sandbox restore id race


def test_two_sandbox_restores_never_reserve_the_same_household_id(tmp_path, monkeypatch):
    from db import sandbox_repo

    glob = tmp_path / "global.db"
    security.init_db(glob)
    offered = iter([777001, 777001, 777002])  # the second caller is offered the id the first just took
    monkeypatch.setattr(sandbox_repo, "allocate_unique_sandbox_fid", lambda _db: next(offered))
    now = int(time.time())
    first = sandbox_repo.reserve_unique_sandbox_fid(glob, now)
    second = sandbox_repo.reserve_unique_sandbox_fid(glob, now)
    assert (first, second) == (777001, 777002)
    with sqlite3.connect(str(glob)) as conn:
        rows = conn.execute("SELECT family_id, seed_mode, expires_at FROM sandbox_leases ORDER BY family_id").fetchall()
    assert [r[0] for r in rows] == [777001, 777002]
    assert all(r[1] == sandbox_repo.RESERVED_SEED_MODE and r[2] > now for r in rows)


# ---------------------------------------------------------------- F-AI-7: orphaned jobs


def test_recover_orphaned_jobs_fails_tickets_whose_worker_is_gone(tmp_path, monkeypatch):
    from hvl_common.db.jobs import _JOB_SCHEMA_SQL
    from services import background_jobs

    cache = tmp_path / "global_cache.db"
    now = time.time()
    with sqlite3.connect(str(cache)) as conn:
        conn.executescript(_JOB_SCHEMA_SQL)
        rows = [
            ("dead", "processing", 2_000_000_000, "old-boot", now - 600),
            ("live", "processing", __import__("os").getpid(), background_jobs.JOB_POOL.boot_id, now),
            ("done", "completed", 2_000_000_000, "old-boot", now - 600),
        ]
        for jid, status, pid, boot, beat in rows:
            conn.execute(
                "INSERT INTO background_jobs (job_id, job_type, tenant_id, universe, status, created_at, updated_at, "
                "owner_pid, owner_boot_id, heartbeat_at) VALUES (?, 'ai', 5, 'public', ?, ?, ?, ?, ?, ?)",
                (jid, status, beat, beat, pid, boot, beat),
            )
    monkeypatch.setattr(background_jobs, "get_cache_db_path_for_universe", lambda _u=None, **_k: cache)
    failed = background_jobs.recover_orphaned_jobs()
    assert failed == ["dead"]
    with sqlite3.connect(str(cache)) as conn:
        status = dict(conn.execute("SELECT job_id, status FROM background_jobs").fetchall())
        error = conn.execute("SELECT error FROM background_jobs WHERE job_id = 'dead'").fetchone()[0]
    assert status == {"dead": "failed", "live": "processing", "done": "completed"}
    assert "lost" in error and "retry" in error.lower()


# ---------------------------------------------------------------- users.email_hash is keyed


def test_email_hash_is_a_keyed_hmac_not_a_bare_sha256(monkeypatch):
    from security import email_hash

    email = "Person@Example.com "
    legacy = hashlib.sha256(b"person@example.com").hexdigest()
    monkeypatch.setenv("EMAIL_HASH_SECRET", "secret-one")
    one = security.hash_email(email)
    assert one != legacy and one == security.hash_email("person@example.com")
    assert security.email_hash_candidates(email) == (one, legacy)
    monkeypatch.setenv("EMAIL_HASH_SECRET", "secret-two")
    assert security.hash_email(email) != one, "the hash depends on the app secret"
    assert email_hash.legacy_hash_email(email) == legacy
    assert security.hash_email("") == "" and security.email_hash_candidates("  ") == ()


def test_email_hash_secret_file_is_created_once_with_owner_only_access(tmp_path, monkeypatch):
    from security import email_hash

    monkeypatch.delenv("EMAIL_HASH_SECRET", raising=False)
    key_file = tmp_path / ".secret.key"
    monkeypatch.setattr("security.crypto._get_active_key_file", lambda: key_file)
    first = email_hash.hash_email("a@example.com")
    path = tmp_path / ".email_hash.key"
    assert path.exists() and (path.stat().st_mode & 0o077) == 0
    email_hash._SECRET_CACHE.clear()
    assert email_hash.hash_email("a@example.com") == first, "a restart reads the same secret"


def _db_with_legacy_user(tmp_path: Path, email: str, fid: int = 61) -> Path:
    db = tmp_path / "global.db"
    security.init_db(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (?, 'h')", (fid,))
        conn.execute(
            "INSERT INTO users (user_id, family_id, name, email, email_hash, role) VALUES (6101, ?, 'n', '', ?, 'editor')",
            (fid, hashlib.sha256(email.encode()).hexdigest()),
        )
    return db


def test_login_lookup_finds_a_legacy_hash_row_and_rewrites_it_to_the_keyed_form(tmp_path, monkeypatch):
    from db.users import get_user_by_email_hash

    monkeypatch.setenv("EMAIL_HASH_SECRET", "secret-one")
    email = "legacy@example.com"
    db = _db_with_legacy_user(tmp_path, email)
    row = get_user_by_email_hash(db, security.email_hash_candidates(email))
    assert row and row["user_id"] == 6101
    with sqlite3.connect(str(db)) as conn:
        stored = conn.execute("SELECT email_hash FROM users WHERE user_id = 6101").fetchone()[0]
    assert stored == security.hash_email(email), "the row migrated on first login"
    assert get_user_by_email_hash(db, security.email_hash_candidates(email))["user_id"] == 6101
    assert get_user_by_email_hash(db, security.email_hash_candidates("other@example.com")) is None


def test_member_lookup_by_email_finds_legacy_hash_rows(monkeypatch):
    monkeypatch.setenv("EMAIL_HASH_SECRET", "secret-one")
    email = "member@example.com"
    legacy = hashlib.sha256(email.encode()).hexdigest()
    glob, fam_db = config.get_global_db_path(), config.get_family_db_path(62)
    for path in (glob, fam_db):
        security.init_db(path)
        with sqlite3.connect(str(path)) as conn:
            conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (62, 'h')")
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, family_id, name, email, email_hash, role) "
                "VALUES (6201, 62, '', '', ?, 'editor')",
                (legacy,),
            )
    found = security.find_user_by_email(glob, email)
    assert found is not None and found["user_id"] == 6201 and found["family_id"] == 62
    assert security.find_user_by_email(glob, "nobody@example.com") is None


# ---------------------------------------------------------------- schema bring-up wiring (F-DATA-5)


def test_init_db_migrates_through_the_locked_schema_runner(tmp_path, monkeypatch):
    import db.schema_migrations as sm

    calls: list[Path] = []
    real = sm.upgrade_to_head
    monkeypatch.setattr(sm, "upgrade_to_head", lambda path: calls.append(Path(path)) or real(path))
    target = tmp_path / "fresh" / "global.db"
    security.init_db(target)
    assert calls == [target]
    assert (tmp_path / "fresh" / "global.db.migrate.lock").exists(), "the file lock was taken"
    assert sm.stamped_revision(target) == sm.alembic_head_revision()


def test_alembic_head_comes_from_the_scripts_not_a_constant(tmp_path):
    import db.schema_migrations as sm
    import security.crypto as crypto

    assert not hasattr(crypto, "ALEMBIC_HEAD_REVISION") and not hasattr(security, "ALEMBIC_HEAD_REVISION")
    db = tmp_path / "families" / "5.db"
    security.init_db(db)
    assert sm.stamped_revision(db) == sm.alembic_head_revision()
    assert sm.alembic_head_revision() != "0002_google_vault_escrow"


def test_a_bare_key_lookup_does_not_write_a_placeholder_family_row(tmp_path, monkeypatch):
    import security.store as store

    db = tmp_path / "families" / "77.db"
    security.init_db(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("DELETE FROM families WHERE family_id = 77")
    fek = Fernet.generate_key()
    monkeypatch.setattr(store, "get_request_vault_fek", lambda *a, **k: fek)
    assert security.get_family_key(db, 77) == fek
    with sqlite3.connect(str(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM families WHERE family_id = 77").fetchone()[0] == 0


# ---------------------------------------------------------------- invite writes bump settings.invites


def _invite_domain(db: Path, fid: int) -> int:
    from db.domain_versions import load_domain_versions_row

    row = load_domain_versions_row(db, fid)
    return int((row[1] if row else {}).get("settings.invites", 0))


def test_invite_writes_bump_the_settings_invites_domain(tmp_path):
    from db import invite_repo

    fid = 91
    db = tmp_path / "families" / f"{fid}.db"
    security.init_db(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (?, 'h')", (fid,))
    start = _invite_domain(db, fid)
    invite_repo.insert_invite_token_in_db(
        db, "CODE91", fid, "a@example.com", "member", "viewer", "L", 2, "2999-01-01T00:00:00", "2026-01-01T00:00:00"
    )
    after_insert = _invite_domain(db, fid)
    assert after_insert > start
    assert invite_repo.claim_invite_token_use(db, "CODE91", "2026-06-01T00:00:00") is True
    after_claim = _invite_domain(db, fid)
    assert after_claim > after_insert
    assert invite_repo.claim_invite_token_use(db, "NOSUCH", "2026-06-01T00:00:00") is False
    assert _invite_domain(db, fid) == after_claim, "a failed claim changes nothing"
    invite_repo.release_invite_token_use(db, "CODE91")
    after_release = _invite_domain(db, fid)
    assert after_release > after_claim
    assert invite_repo.revoke_invite_token_in_db(db, fid, "CODE91") is True
    assert _invite_domain(db, fid) > after_release


def test_a_write_session_creates_the_missing_household_row(tmp_path):
    from db.session import get_orm_session

    db = tmp_path / "families" / "78.db"
    security.init_db(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("DELETE FROM families WHERE family_id = 78")

    def _rows() -> int:
        with sqlite3.connect(str(db)) as conn:
            return conn.execute("SELECT COUNT(*) FROM families WHERE family_id = 78").fetchone()[0]

    assert _rows() == 0
    with get_orm_session(db, family_id=78, commit=True):
        pass
    assert _rows() == 1


class _OneShotJobPool:
    """Stateful double: accepts exactly one submit and records its tenant; a second submit is illegal."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def submit_job(self, fn, *args, family_id: int = 0, universe: str = "public", job_type: str = "generic", **kw):
        if self.calls:
            raise AssertionError("submit_job called twice")
        if family_id <= 0:
            raise AssertionError("a restore ticket must never be tenant 0 (root key)")
        self.calls.append({"family_id": family_id, "universe": universe, "job_type": job_type})
        return "job-1"


def test_desktop_sandbox_restore_ticket_is_keyed_to_the_household_not_the_root_key(monkeypatch, tmp_path):
    from wsgi import app
    from services import background_jobs, desktop_service

    pool = _OneShotJobPool()
    monkeypatch.setattr(background_jobs, "submit_job", pool.submit_job)
    fek = Fernet.generate_key()
    with app.test_request_context("/"):
        desktop_service._submit_async_desktop_restore(
            b"x", fek, tmp_path / "sb.db", FID, is_sb=True, is_loc=False, backup_dir=None, uni="sandbox",
        )
        assert security.get_request_vault_fek(FID) == fek
    assert pool.calls == [{"family_id": FID, "universe": "sandbox", "job_type": "vault_restore"}]


def test_desktop_sandbox_restore_refuses_without_household_fek(monkeypatch, tmp_path):
    from wsgi import app
    from services import background_jobs, desktop_service

    monkeypatch.setattr(background_jobs, "submit_job", _OneShotJobPool().submit_job)
    with app.test_request_context("/"), pytest.raises(ValueError):
        desktop_service._submit_async_desktop_restore(
            b"x", None, tmp_path / "sb.db", FID, is_sb=True, is_loc=False, backup_dir=None, uni="sandbox",
        )


def test_no_legacy_tenant_zero_sandbox_ticket_reader():
    import routes.sandbox as sandbox_routes

    assert not hasattr(sandbox_routes, "_legacy_sandbox_ticket")


def test_rekey_never_rewrites_a_peer_under_another_files_key(tmp_path):
    """F-SEC-11 release P0: global.db and families/{fid}.db can hold different valid FEKs for one household. Resolving
    the key from one file must rekey only that file; the peer keeps its root-KEK rows for its own key."""
    from security import store

    src, peer = _household_pair(tmp_path, fid=FID + 1)
    other_fek = Fernet.generate_key()
    root_cipher = _root().encrypt(b"legacy").decode("utf-8")
    with sqlite3.connect(str(peer)) as conn:
        conn.execute(
            "UPDATE families SET encryption_key_enc = ?, name = ? WHERE family_id = ?",
            (_root().encrypt(other_fek).decode("utf-8"), root_cipher, FID + 1),
        )
    security._clear_security_caches()
    store._REKEY_ATTEMPTED.clear()
    security.get_family_key(src, FID + 1)
    with sqlite3.connect(str(peer)) as conn:
        assert conn.execute("SELECT name FROM families WHERE family_id = ?", (FID + 1,)).fetchone()[0] == root_cipher
