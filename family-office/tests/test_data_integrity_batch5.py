"""
F-DATA-1 (a failed relational save is never reported as success or diverted to a legacy blob)
and F-SEC-3 (race-free household id allocation and single-claim invite redemption).
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

import security
from db import accounts, data_migration

REPO = Path(__file__).resolve().parent.parent


def _blob_rows(db: Path, fid: int, key: str) -> int:
    with sqlite3.connect(str(db)) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM family_encrypted_store WHERE family_id = ? AND key = ?", (fid, key)
        ).fetchone()[0]


@pytest.fixture
def family_db(tmp_path):
    db = tmp_path / "families" / "3.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    security.init_db(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("INSERT OR IGNORE INTO families (family_id, name) VALUES (3, 'Test Family')")
    return db


class FailingAccountsStore:
    """Stateful double for db.accounts.replace_accounts: fails while armed, otherwise writes for real."""

    def __init__(self, real):
        self.real = real
        self.armed = True
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.armed:
            raise sqlite3.OperationalError("disk I/O error")
        return self.real(*args, **kwargs)


def _account(name: str) -> dict:
    return {"account_id": f"acc-{name}", "name": name, "type": "checking", "balance": 10.0}


def test_failed_relational_save_raises_keeps_old_value_and_writes_no_blob(family_db, monkeypatch):
    security.db_save_encrypted(family_db, "accounts", "monarch_sync", [_account("old")], family_id=3)
    before = security.db_load_encrypted(family_db, "accounts", family_id=3)
    assert [a["name"] for a in before] == ["old"]

    double = FailingAccountsStore(accounts.replace_accounts)
    monkeypatch.setattr(accounts, "replace_accounts", double)
    with pytest.raises(sqlite3.OperationalError):
        security.db_save_encrypted(family_db, "accounts", "monarch_sync", [_account("new")], family_id=3)

    assert double.calls == 1
    assert _blob_rows(family_db, 3, "accounts") == 0
    after = security.db_load_encrypted(family_db, "accounts", family_id=3)
    assert [a["name"] for a in after] == ["old"]

    double.armed = False
    security.db_save_encrypted(family_db, "accounts", "monarch_sync", [_account("new")], family_id=3)
    assert [a["name"] for a in security.db_load_encrypted(family_db, "accounts", family_id=3)] == ["new"]


def test_try_relational_save_raises_on_failure_and_on_wrong_payload_type(family_db, monkeypatch):
    with pytest.raises(TypeError):
        data_migration.try_relational_save(family_db, "accounts", {"not": "a list"}, 3)
    monkeypatch.setattr(accounts, "replace_accounts", FailingAccountsStore(accounts.replace_accounts))
    with pytest.raises(sqlite3.OperationalError):
        data_migration.try_relational_save(family_db, "accounts", [_account("x")], 3)
    assert data_migration.try_relational_save(family_db, "not_a_migrated_key", {}, 3) is False


def test_non_migrated_key_still_uses_encrypted_blob(family_db):
    security.db_save_encrypted(family_db, "tax_document_checklist", "tax_checklist", {"w2": True}, family_id=3)
    assert _blob_rows(family_db, 3, "tax_document_checklist") == 1
    assert security.db_load_encrypted(family_db, "tax_document_checklist", family_id=3) == {"w2": True}


def test_no_production_route_or_service_saves_a_migrated_key_through_the_blob_api():
    """Migrated keys have dedicated relational writers; only seed/ingest scripts call db_save_encrypted with them."""
    keys = "|".join(data_migration.MIGRATED_STORE_KEYS)
    pattern = re.compile(r"db_save_encrypted\(\s*[\w.]+,\s*[\"'](%s)[\"']" % keys)
    offenders = []
    for sub in ("routes", "services", "ssr", "forecast", "db", "account_sync", "security"):
        for f in (REPO / sub).rglob("*.py"):
            if pattern.search(f.read_text()):
                offenders.append(str(f.relative_to(REPO)))
    assert offenders == []


def _locked_household_db(tmp_path, fid: int) -> Path:
    db = tmp_path / "locked" / f"{fid}.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    security.init_db(db)
    security.get_family_key(db, fid)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE families SET support_access_enabled = 1, name = 'gAAAAAplaceholder' WHERE family_id = ?", (fid,))
    assert security.get_family_key(db, fid)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE families SET support_access_enabled = 0, encryption_key_enc = NULL WHERE family_id = ?", (fid,))
    security._clear_security_caches()
    return db


@pytest.mark.parametrize("key,payload", [("accounts", [_account("x")]), ("tax_document_checklist", {"w2": True})])
def test_locked_vault_still_fails_closed_on_save(tmp_path, key, payload):
    db = _locked_household_db(tmp_path, 9)
    with pytest.raises(PermissionError):
        security.db_save_encrypted(db, key, "test", payload, family_id=9)
    assert _blob_rows(db, 9, key) == 0


# ---------------------------------------------------------------- F-SEC-3 id allocation

_ALLOC_SCRIPT = """
import sys
from pathlib import Path
from db.family_id_allocator import allocate_family_id
print(",".join(str(allocate_family_id(Path(sys.argv[1]), int(sys.argv[2]))) for _ in range(int(sys.argv[3]))))
"""


def test_allocator_distinct_across_threads(tmp_path):
    from db.family_id_allocator import allocate_family_id

    gdb = tmp_path / "global.db"
    security.init_db(gdb)
    allocate_family_id(gdb, 1)
    results, errors = [], []
    barrier = threading.Barrier(8)

    def work():
        try:
            barrier.wait()
            for _ in range(5):
                results.append(allocate_family_id(gdb, 1))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert len(results) == 40 and len(set(results)) == 40
    assert min(results) >= 3


def test_allocator_distinct_across_processes(tmp_path):
    from db.family_id_allocator import allocate_family_id

    gdb = tmp_path / "global.db"
    security.init_db(gdb)
    allocate_family_id(gdb, 1)
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _ALLOC_SCRIPT, str(gdb), "1", "6"],
            cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
        )
        for _ in range(4)
    ]
    ids = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        ids += [int(x) for x in out.strip().split(",")]
    assert len(ids) == 24 and len(set(ids)) == 24


def test_allocator_seeds_above_existing_ids_and_never_reuses_disk_ids(tmp_path, monkeypatch):
    import config
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "data"))
    main_db = tmp_path / "alloc_main.db"
    security.init_db(main_db)
    uni = security._resolve_universe_from_db_path(main_db)
    fam_dir = config.get_family_db_path(1, universe=uni).parent
    fam_dir.mkdir(parents=True, exist_ok=True)
    (fam_dir / "41.db").write_bytes(b"")
    with sqlite3.connect(str(main_db)) as conn:
        conn.execute("INSERT INTO families (family_id, name) VALUES (57, 'Existing')")

    first = security.allocate_household_id(main_db, 1)
    second = security.allocate_household_id(main_db, 1)
    assert first == 58 and second == 59
    # A household created outside the allocator after the fact is still never handed out again.
    (fam_dir / "60.db").write_bytes(b"")
    third = security.allocate_household_id(main_db, 1)
    assert third == 61


def test_self_serve_households_get_distinct_ids(tmp_path, monkeypatch):
    from db.household_activity import provision_self_serve_household

    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "data"))
    main_db = tmp_path / "selfserve.db"
    security.init_db(main_db)
    a = provision_self_serve_household(main_db, "alloc.a@example.com", "A")
    b = provision_self_serve_household(main_db, "alloc.b@example.com", "B")
    assert a["family_id"] != b["family_id"] and min(a["family_id"], b["family_id"]) >= 2


# ---------------------------------------------------------------- F-SEC-3 invite redemption

def _invite_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "invite_data"))
    db = tmp_path / "invite_claims.db"
    security._clear_security_caches()
    security.init_db(db)
    return db


def test_single_use_invite_redeemed_concurrently_succeeds_once(tmp_path, monkeypatch):
    db = _invite_db(tmp_path, monkeypatch)
    inv = security.create_invite_token(
        db, family_id=1, created_by_email="a@example.com", invite_type="join_household",
        target_role="viewer", max_uses=1, expires_days=7,
    )
    results = []
    barrier = threading.Barrier(2)

    def redeem(n):
        barrier.wait()
        results.append(security.redeem_invite_token(db, inv["code"], f"racer{n}@example.com", f"Racer {n}"))

    threads = [threading.Thread(target=redeem, args=(n,)) for n in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(r is not None for r in results) == 1
    assert security.validate_invite_token(db, inv["code"]) is None
    assert security.redeem_invite_token(db, inv["code"], "late@example.com", "Late") is None


_CLAIM_SCRIPT = """
import sys
from datetime import datetime, timezone
from pathlib import Path
from db.security_repo import claim_invite_token_use
print(int(claim_invite_token_use(Path(sys.argv[1]), sys.argv[2], datetime.now(timezone.utc).isoformat())))
"""


def test_invite_claim_is_exclusive_across_processes(tmp_path, monkeypatch):
    db = _invite_db(tmp_path, monkeypatch)
    inv = security.create_invite_token(
        db, family_id=1, created_by_email="a@example.com", invite_type="join_household",
        target_role="viewer", max_uses=1, expires_days=7,
    )
    env = {**__import__("os").environ, "PYTHONPATH": str(REPO)}
    procs = [
        subprocess.Popen([sys.executable, "-c", _CLAIM_SCRIPT, str(db), inv["code"]], cwd=str(REPO),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        for _ in range(4)
    ]
    wins = 0
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        wins += int(out.strip())
    assert wins == 1
    with sqlite3.connect(str(db)) as conn:
        assert conn.execute("SELECT uses_count FROM invite_tokens WHERE code = ?", (inv["code"],)).fetchone()[0] == 1


def test_claim_refuses_expired_and_revoked_and_release_restores_use(tmp_path, monkeypatch):
    from db.security_repo import claim_invite_token_use, release_invite_token_use

    db = _invite_db(tmp_path, monkeypatch)
    inv = security.create_invite_token(
        db, family_id=1, created_by_email="a@example.com", invite_type="join_household",
        target_role="viewer", max_uses=2, expires_days=7,
    )
    now = datetime.now(timezone.utc).isoformat()
    assert claim_invite_token_use(db, inv["code"], now) is True
    release_invite_token_use(db, inv["code"])
    assert claim_invite_token_use(db, inv["code"], now) is True
    assert claim_invite_token_use(db, inv["code"], "9999-01-01T00:00:00+00:00") is False
    assert security.revoke_invite_token(db, family_id=1, code=inv["code"]) is True
    assert claim_invite_token_use(db, inv["code"], now) is False


def test_provisioning_failure_gives_the_invite_use_back(tmp_path, monkeypatch):
    db = _invite_db(tmp_path, monkeypatch)
    inv = security.create_invite_token(
        db, family_id=1, created_by_email="a@example.com", invite_type="new_household",
        target_role="editor", max_uses=1, expires_days=7,
    )

    def boom(*_a, **_k):
        raise RuntimeError("provisioning failed")

    monkeypatch.setattr(security, "_provision_invited_household", boom)
    with pytest.raises(RuntimeError):
        security.redeem_invite_token(db, inv["code"], "new@example.com", "New")
    assert security.validate_invite_token(db, inv["code"]) is not None


def test_used_up_invite_is_refused_with_existing_user_message(tmp_path, monkeypatch):
    from app import create_app
    from services import auth_google

    db = _invite_db(tmp_path, monkeypatch)
    monkeypatch.setattr(auth_google, "DB_PATH", db)
    monkeypatch.setattr(auth_google, "read_google_appdata_json", lambda token, **kw: None)
    monkeypatch.setattr(auth_google, "write_google_appdata_json", lambda token, payload, **kw: True)
    inv = security.create_invite_token(
        db, family_id=1, created_by_email="a@example.com", invite_type="join_household",
        target_role="viewer", max_uses=1, expires_days=7,
    )
    assert security.redeem_invite_token(db, inv["code"], "first@example.com", "First") is not None

    from flask import session

    with create_app().test_request_context("/auth/google/callback"):
        session["pending_invite_code"] = inv["code"]
        ok, member, msg = auth_google.authenticate_family_email(
            "second@example.com", {"name": "Second", "_oauth_tokens": {"access_token": "tok"}}
        )
    assert ok is False and member is None
    assert "already-redeemed household invite code" in msg


# ---------------------------------------------------------------- audit follow-ups

class FailingSessionFactory:
    """Stateful double for db.session.get_orm_session: the real session, but add() fails on the Nth call."""

    def __init__(self, real, fail_on_add: int):
        self.real, self.fail_on_add, self.adds = real, fail_on_add, 0

    def __call__(self, *args, **kwargs):
        factory = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner.cm = factory.real(*args, **kwargs)
                real_session = self_inner.cm.__enter__()

                class _Proxy:
                    def __getattr__(self_p, name):
                        return getattr(real_session, name)

                    def add(self_p, obj):
                        factory.adds += 1
                        if factory.adds == factory.fail_on_add:
                            raise sqlite3.IntegrityError("injected insert failure")
                        return real_session.add(obj)

                return _Proxy()

            def __exit__(self_inner, *exc):
                return self_inner.cm.__exit__(*exc)

        return _Ctx()


def _gift_payload(*names):
    return {"recipients": [{"name": n, "member_count": 1, "gifts": [{"year": 2024, "amount": 100.0}]} for n in names]}


def test_gift_save_is_one_transaction_and_rolls_back(family_db, monkeypatch):
    import db.session as dbs

    data_migration.try_relational_save(family_db, "family_gifts", _gift_payload("Old A", "Old B"), 3)
    monkeypatch.setattr(dbs, "get_orm_session", FailingSessionFactory(dbs.get_orm_session, fail_on_add=2))
    with pytest.raises(sqlite3.IntegrityError):
        data_migration.try_relational_save(family_db, "family_gifts", _gift_payload("R1", "R3"), 3)
    monkeypatch.undo()
    names = sorted(r["name"] for r in security.db_load_encrypted(family_db, "family_gifts", family_id=3)["recipients"])
    assert names == ["Old A", "Old B"]


def test_gift_save_over_limit_leaves_old_data(family_db, monkeypatch):
    import config

    data_migration.try_relational_save(family_db, "family_gifts", _gift_payload("Old A", "Old B"), 3)
    monkeypatch.setattr(config, "MAX_GIFT_RECIPIENTS", 1)
    with pytest.raises(ValueError):
        data_migration.try_relational_save(family_db, "family_gifts", _gift_payload("R1", "R3"), 3)
    names = sorted(r["name"] for r in security.db_load_encrypted(family_db, "family_gifts", family_id=3)["recipients"])
    assert names == ["Old A", "Old B"]


def test_compensation_save_is_one_transaction_and_rolls_back(family_db, monkeypatch):
    import db.session as dbs

    old = [{"year": 2022, "company": "Old Co", "salary": 1.0, "bonus": 0.0}]
    new = [{"year": 2023, "company": "R1 Co", "salary": 2.0}, {"year": 2024, "company": "R3 Co", "salary": 3.0}]
    data_migration.try_relational_save(family_db, "career_compensation", old, 3)
    monkeypatch.setattr(dbs, "get_orm_session", FailingSessionFactory(dbs.get_orm_session, fail_on_add=2))
    with pytest.raises(sqlite3.IntegrityError):
        data_migration.try_relational_save(family_db, "career_compensation", new, 3)
    monkeypatch.undo()
    loaded = security.db_load_encrypted(family_db, "career_compensation", family_id=3)
    assert [h["year"] for h in loaded] == [2022]


def test_save_of_none_payload_for_migrated_key_raises(family_db):
    with pytest.raises(ValueError):
        security.db_save_encrypted(family_db, "accounts", "monarch_sync", None, family_id=3)


def test_save_with_unsavable_dict_shape_raises_and_keeps_old_value(family_db):
    old = [{"year": 2022, "company": "Old Co", "salary": 1.0}]
    security.db_save_encrypted(family_db, "career_compensation", "comp", old, family_id=3)
    with pytest.raises(ValueError):
        security.db_save_encrypted(family_db, "career_compensation", "comp", {"unexpected": []}, family_id=3)
    with pytest.raises(ValueError):
        security.db_save_encrypted(family_db, "company_equity_grants", "equity", {"unexpected": []}, family_id=3)
    assert [h["year"] for h in security.db_load_encrypted(family_db, "career_compensation", family_id=3)] == [2022]


def test_save_of_migrated_key_without_family_id_raises(family_db):
    with pytest.raises(ValueError):
        security.db_save_encrypted(family_db, "accounts", "monarch_sync", [_account("x")], family_id=0)


def test_relational_read_error_propagates_instead_of_falling_back_to_blob(family_db, monkeypatch):
    security.db_save_encrypted(family_db, "accounts", "monarch_sync", [_account("kept")], family_id=3)

    class FailingReader:
        def __init__(self):
            self.calls = 0

        def __call__(self, *a, **k):
            self.calls += 1
            raise sqlite3.OperationalError("database disk image is malformed")

    reader = FailingReader()
    monkeypatch.setattr(accounts, "list_accounts", reader)
    with pytest.raises(sqlite3.OperationalError):
        security.db_load_encrypted(family_db, "accounts", family_id=3)
    assert reader.calls == 1


def _two_copy_invite(tmp_path, monkeypatch, **kw):
    db = _invite_db(tmp_path, monkeypatch)
    inv = security.create_invite_token(
        db, family_id=1, created_by_email="a@example.com", invite_type=kw.get("invite_type", "join_household"),
        target_role="viewer", max_uses=1, expires_days=7,
    )
    return db, inv


def test_revoke_fails_loudly_when_authoritative_copy_cannot_be_revoked(tmp_path, monkeypatch):
    import security.invites as inv_mod

    db, inv = _two_copy_invite(tmp_path, monkeypatch)
    cands = [c for c in security._invite_candidate_dbs(db, 1) if c.exists()]
    assert len(cands) >= 2
    authority = cands[0]
    real = inv_mod.revoke_invite_token_in_db
    calls = []

    def revoke_double(cand, fid, code):
        calls.append(cand)
        if cand == authority:
            raise sqlite3.OperationalError("database is locked")
        return real(cand, fid, code)

    monkeypatch.setattr(inv_mod, "revoke_invite_token_in_db", revoke_double)
    with pytest.raises(sqlite3.OperationalError):
        security.revoke_invite_token(db, family_id=1, code=inv["code"])
    assert calls == [authority]
    monkeypatch.setattr(inv_mod, "revoke_invite_token_in_db", real)
    assert security.redeem_invite_token(db, inv["code"], "still@example.com", "Still") is not None


def test_failed_household_provisioning_is_undone_and_retry_creates_one_household(tmp_path, monkeypatch):
    import security.init as init_mod

    db, inv = _two_copy_invite(tmp_path, monkeypatch, invite_type="new_household")
    real_sync = init_mod.sync_user_row_between_dbs

    class FailOnce:
        def __init__(self):
            self.calls = 0

        def __call__(self, *a, **k):
            self.calls += 1
            if self.calls == 1:
                raise sqlite3.OperationalError("disk I/O error")
            return real_sync(*a, **k)

    double = FailOnce()
    monkeypatch.setattr(init_mod, "sync_user_row_between_dbs", double)
    with pytest.raises(sqlite3.OperationalError):
        security.redeem_invite_token(db, inv["code"], "new@example.com", "New")

    def household_ids():
        ids = set()
        for cand in security._invite_candidate_dbs(db, 1):
            if cand.exists():
                with sqlite3.connect(str(cand)) as conn:
                    ids |= {r[0] for r in conn.execute("SELECT family_id FROM families WHERE family_id > 1")}
        return ids

    assert household_ids() == set()
    assert security.validate_invite_token(db, inv["code"]) is not None
    assert security.redeem_invite_token(db, inv["code"], "new@example.com", "New") is not None
    assert len(household_ids()) == 1


def test_allocator_scan_error_raises(tmp_path):
    from db.family_id_allocator import allocate_new_family_id

    good = tmp_path / "good.db"
    security.init_db(good)
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not a sqlite database" * 50)
    with pytest.raises(sqlite3.DatabaseError):
        allocate_new_family_id(tmp_path / "global.db", [good, corrupt], tmp_path / "families")


def test_scan_max_family_id_raises_on_unreadable_database(tmp_path):
    from db.family_id_allocator import scan_max_family_id

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not a sqlite database" * 50)
    with pytest.raises(sqlite3.DatabaseError):
        scan_max_family_id([corrupt], tmp_path / "families")


def test_db_layer_does_not_import_security_for_allocation():
    src = (REPO / "db" / "family_id_allocator.py").read_text()
    assert "import security" not in src and "from security" not in src


class SequenceIds:
    """Stateful double for allocate_unique_sandbox_id: replays a fixed sequence and fails when exhausted."""

    def __init__(self, ids):
        self.ids = list(ids)
        self.served = []

    def __call__(self, *a, **k):
        self.served.append(self.ids.pop(0))
        return self.served[-1]


def test_sandbox_id_skips_ids_handed_out_by_allocator_or_present_on_disk(tmp_path, monkeypatch):
    import db.sandbox_repo as sandbox_repo
    from db.family_id_allocator import allocate_family_id

    glob = tmp_path / "sandbox" / "global.db"
    security.init_db(glob)
    taken_by_allocator = allocate_family_id(glob, 123455) 
    (glob.parent / "families").mkdir(parents=True, exist_ok=True)
    (glob.parent / "families" / "654321.db").write_bytes(b"")
    seq = SequenceIds([taken_by_allocator, 654321, 777777])
    monkeypatch.setattr(sandbox_repo, "allocate_unique_sandbox_id", seq)
    assert sandbox_repo.allocate_unique_sandbox_fid(glob) == 777777
    assert seq.served == [taken_by_allocator, 654321, 777777]


def test_seed_refuses_to_overwrite_non_demo_household(tmp_path):
    from scripts import seed_demo_families as seeds

    glob = tmp_path / "global.db"
    security.init_db(glob)
    with sqlite3.connect(str(glob)) as conn:
        conn.execute("INSERT INTO families (family_id, name, settings) VALUES (7, 'Real Household', '{\"primary_state\": \"WA\"}')")
    with pytest.raises(RuntimeError):
        seeds.seed_all_demo_families(glob, verbose=False)
    with sqlite3.connect(str(glob)) as conn:
        assert conn.execute("SELECT name FROM families WHERE family_id = 7").fetchone()[0] == "Real Household"
        assert conn.execute("SELECT COUNT(*) FROM families WHERE family_id IN (1,2,3,4,5,6)").fetchone()[0] == 0
