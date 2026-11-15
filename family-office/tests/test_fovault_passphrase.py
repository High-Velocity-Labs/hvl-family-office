"""
`.fovault` format v2: passphrase-protected key wrapping, legacy-import gate, and keeping secrets out of persisted jobs.

Real components throughout; the only double is `_SubmitRecorder`, a stateful spy that forwards to the real
`background_jobs.submit_job` and records everything a persisted ticket could be built from.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import sqlite3
import time
import zlib
from pathlib import Path

import pytest
from wsgi import app
import config
import security
from db.fovault_repo import _legacy_fernet
from hvl_common.security import PassphraseRequired
from security import fovault_passphrase
from services import background_jobs, sandbox_service
from services.fovault_service import get_vault_import_summary, prepare_fovault_restore

PASSPHRASE = "correct-horse-battery"
SAMPLE_PASSPHRASE = "synthetic-sample-vault"
SAMPLE_VAULT = Path(__file__).resolve().parent.parent / "sample_data" / "sample_family_vault.fovault"
EXPORT_BODY = {"passphrase": PASSPHRASE, "passphrase_confirm": PASSPHRASE}


@pytest.fixture(autouse=True)
def _reset_security_caches():
    security._clear_security_caches()
    yield
    security._clear_security_caches()


class _SubmitRecorder:
    """Forwards to the real `submit_job` and remembers every call's args, kwargs and the ids it returned."""

    def __init__(self, real):
        self._real = real
        self.calls: list[dict] = []
        self.job_ids: list[str] = []

    def __call__(self, fn, *args, **kwargs):
        job_id = self._real(fn, *args, **kwargs)
        self.calls.append({"args": args, "kwargs": kwargs, "job_type": kwargs.get("job_type")})
        self.job_ids.append(job_id)
        return job_id


@pytest.fixture
def force_async(monkeypatch):
    """Routes consult `should_run_synchronously()` (always True under pytest); production always runs restores as jobs."""
    import hvl_common.web.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "should_run_synchronously", lambda *a, **k: False)


def _sandbox_client(template: str = "miller"):
    app.config["TESTING"] = True
    client = app.test_client()
    res = client.post("/api/sandbox/launch", json={"template": template})
    assert res.status_code == 200
    return client, res.get_json()["family_id"]


@pytest.fixture(autouse=True)
def _drop_signed_in_households():
    """`_signed_in_client` creates real public households under the data dir; remove them after each test."""
    yield
    for fid in _SIGNED_IN_FIDS:
        paths = [config.get_family_db_path(fid, uni) for uni in ("public", "test")]
        paths += [p.parent.parent.parent / "families" / f"{fid}_cache.db" for p in paths]
        for base in paths:
            for suffix in ("", "-wal", "-shm"):
                Path(str(base) + suffix).unlink(missing_ok=True)


_SIGNED_IN_FIDS = (4242, 4243, 4244)


def _signed_in_client(role: str = "editor", fid: int = 4242):
    """A real signed-in Cloud Vault member (public universe, own household DB and directory row), not a sandbox."""
    security.init_db(config.get_global_db_path("public"))
    fam_db = config.get_family_db_path(fid, "public")
    security.init_db(fam_db)
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.clear()
        sess.update(authenticated=True, user_email=f"member{fid}@example.com", user_family_id=fid, family_id=fid,
                    role=role, user_role=role, universe="public")
    return client


def _export(client, body=None):
    return client.post("/api/sandbox/download-vault", json=EXPORT_BODY if body is None else body)


def _restore(client, vault_bytes: bytes, path: str = "/api/sandbox/restore", **fields):
    data = {"file": (io.BytesIO(vault_bytes), "vault.fovault"), **fields}
    return client.post(path, data=data, content_type="multipart/form-data")


def _envelope(vault_bytes: bytes, tmp_path: Path) -> dict:
    p = tmp_path / f"peek_{hashlib.sha1(vault_bytes).hexdigest()[:8]}.db"
    p.write_bytes(vault_bytes)
    with sqlite3.connect(p) as conn:
        envelope = conn.execute("SELECT portable_vault_fek FROM families ORDER BY family_id DESC").fetchone()[0]
    return json.loads(envelope)


def _rewrite_key_material(vault_bytes: bytes, tmp_path: Path, wrapped_value: str) -> bytes:
    """Builds a pre-v2 file by replacing the v2 envelope with an old-style wrap (or raw key)."""
    p = tmp_path / f"legacy_{hashlib.sha1(wrapped_value.encode()).hexdigest()[:8]}.fovault"
    p.write_bytes(vault_bytes)
    with sqlite3.connect(p) as conn:
        conn.execute(
            "UPDATE families SET portable_vault_fek = ?, encryption_key_enc = NULL", (json.dumps(wrapped_value),)
        )
        conn.commit()
    return p.read_bytes()


def _job_table_text(universe: str) -> str:
    """Decrypts (root key) and decompresses every persisted job blob + plain column for scanning."""
    root = security._get_fernet(None)
    chunks: list[str] = []
    for cache_db in sorted(config.get_data_dir().rglob("*cache.db")):  # global and per-family job/cache DBs
        with sqlite3.connect(cache_db) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'background_jobs'").fetchone():
                continue
            rows = conn.execute("SELECT * FROM background_jobs").fetchall()
        for row in rows:
            for col in row:
                if isinstance(col, bytes):
                    try:
                        chunks.append(zlib.decompress(root.decrypt(col)).decode("utf-8", "replace"))
                    except Exception:
                        chunks.append(col.decode("latin-1"))  # household-keyed ticket: still must not contain secrets
                elif col is not None:
                    chunks.append(str(col))
    return "\n".join(chunks)


# ---------------------------------------------------------------- export

def test_export_without_passphrase_is_refused():
    client, _ = _sandbox_client()
    for body in ({}, {"passphrase": ""}, {"passphrase": "short", "passphrase_confirm": "short"},
                 {"passphrase": PASSPHRASE, "passphrase_confirm": "something else entirely"}):
        res = _export(client, body)
        assert res.status_code == 400, body
        assert res.get_json()["success"] is False and res.get_json()["error"]
        assert not res.data.startswith(b"SQLite format 3")
    assert client.get("/api/sandbox/download-vault").status_code == 405  # no passphrase-in-URL export
    with pytest.raises(PassphraseRequired):
        from services.fovault_service import build_fovault_backup_bytes
        build_fovault_backup_bytes(Path("/nonexistent.db"), 1, "")


def test_two_exports_have_different_salts_and_ciphertexts(tmp_path):
    client, _ = _sandbox_client()
    a, b = _export(client).data, _export(client).data
    ea, eb = _envelope(a, tmp_path), _envelope(b, tmp_path)
    assert ea["fovault_format"] == 2 and ea["kdf"]["name"] == "scrypt" and ea["kdf"]["n"] >= 2**17
    assert ea["kdf"]["salt"] != eb["kdf"]["salt"]
    assert ea["ct"] != eb["ct"] and ea["nonce"] != eb["nonce"]
    assert prepare_fovault_restore(a, PASSPHRASE).fek == prepare_fovault_restore(b, PASSPHRASE).fek
    # No server-KEK escrow and no raw FEK in the exported file.
    fek = prepare_fovault_restore(a, PASSPHRASE).fek
    assert fek not in a and base64.b64encode(fek) not in a



def test_export_carries_no_server_key_wrapped_member_keys(tmp_path):
    """Members' pending key wraps (users.pending_fek_enc, under the server KEK) must not ship in a backup."""
    client, fid = _sandbox_client()
    fam_db = config.get_family_db_path(fid, "sandbox")
    with sqlite3.connect(fam_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
        conn.execute("UPDATE users SET pending_fek_enc = 'server-kek-wrapped-token'")
        conn.commit()
    peek = tmp_path / "export_peek.db"
    peek.write_bytes(_export(client).data)
    with sqlite3.connect(peek) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE pending_fek_enc IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM families WHERE encryption_key_enc IS NOT NULL").fetchone()[0] == 0


def test_scrubbed_member_keys_leave_no_bytes_in_the_exported_file(tmp_path):
    """Clearing a column must not leave the old value in the file's free pages (audit: 5+ member households)."""
    client, fid = _sandbox_client()
    fam_db = config.get_family_db_path(fid, "sandbox")
    marker = "SERVERKEKWRAP" + "x" * 200
    with sqlite3.connect(fam_db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
        base_id = conn.execute("SELECT MAX(user_id) FROM users").fetchone()[0]
        copy_cols = [c for c in cols if c not in ("user_id", "email_hash", "email")]
        for i in range(1, 25):
            conn.execute(
                f"INSERT INTO users (user_id, {', '.join(copy_cols)}) "
                f"SELECT ?, {', '.join(copy_cols)} FROM users WHERE user_id = ?",
                (base_id + i, base_id),
            )
        conn.execute("UPDATE users SET pending_fek_enc = ? || user_id", (marker,))
        conn.commit()
    raw = _export(client).data
    assert raw, "export failed"
    assert marker.encode() not in raw


def test_shipped_sample_vault_carries_no_server_key_wrapped_member_keys():
    sample = Path(__file__).resolve().parent.parent / "sample_data" / "sample_family_vault.fovault"
    with sqlite3.connect(f"file:{sample}?mode=ro", uri=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE pending_fek_enc IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM families WHERE encryption_key_enc IS NOT NULL").fetchone()[0] == 0

# ---------------------------------------------------------------- restore

def test_wrong_passphrase_fails_clearly_and_writes_nothing():
    client, fid = _sandbox_client()
    vault = _export(client).data
    db = config.get_family_db_path(fid, universe="sandbox")
    before_hash = hashlib.sha256(db.read_bytes()).hexdigest()
    before_active = sandbox_service.get_sandbox_storage_stats()["active_sandboxes"]

    for attempt in ({"passphrase": "not-the-right-passphrase"}, {}):
        res = _restore(client, vault, **attempt)
        assert res.status_code == 400
        assert res.get_json()["success"] is False
        assert res.get_json()["code"] == "passphrase"
    assert "wrong passphrase" in _restore(client, vault, passphrase="not-the-right-passphrase").get_json()["error"].lower()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before_hash
    assert sandbox_service.get_sandbox_storage_stats()["active_sandboxes"] == before_active

    fresh = app.test_client()  # a visitor with no sandbox: still no new sandbox created
    assert _restore(fresh, vault, passphrase="not-the-right-passphrase").status_code == 400
    assert sandbox_service.get_sandbox_storage_stats()["active_sandboxes"] == before_active


def test_right_passphrase_round_trips_all_data(tmp_path):
    client, src_fid = _sandbox_client()
    vault = _export(client).data
    fek = prepare_fovault_restore(vault, PASSPHRASE).fek
    src_summary = get_vault_import_summary(config.get_family_db_path(src_fid, "sandbox"), src_fid, raw_fek=fek)
    assert src_summary["accounts"] > 0

    other = app.test_client()
    res = _restore(other, vault, passphrase=PASSPHRASE)
    assert res.status_code == 200 and res.get_json()["success"] is True
    new_fid = res.get_json()["family_id"]
    assert new_fid != src_fid
    summary = res.get_json()["summary"]
    for key in ("household_name", "accounts", "holdings", "members", "scenarios", "equity_grants", "compensation_years", "advisor_threads"):
        assert summary[key] == src_summary[key], key
    with sqlite3.connect(config.get_family_db_path(new_fid, "sandbox")) as conn:
        name_enc, enc_key, portable = conn.execute(
            "SELECT name, encryption_key_enc, portable_vault_fek FROM families WHERE family_id = ?", (new_fid,)
        ).fetchone()
    assert enc_key is None and portable is None
    assert "Miller" in security.decrypt_field(name_enc, default="", key=fek)


# ---------------------------------------------------------------- legacy

def test_legacy_files_refused_by_default_and_import_only_with_editor_option(tmp_path):
    client, _ = _sandbox_client()
    vault = _export(client).data
    fek = prepare_fovault_restore(vault, PASSPHRASE).fek
    empty_wrap = _legacy_fernet("").encrypt(fek).decode()  # what the old default produced
    legacy_files = {
        "empty-passphrase wrap": _rewrite_key_material(vault, tmp_path, empty_wrap),
        "raw key": _rewrite_key_material(vault, tmp_path, fek.decode()),
    }
    for label, legacy in legacy_files.items():
        with pytest.raises(fovault_passphrase.LegacyFovaultFormat):
            prepare_fovault_restore(legacy, "")
        res = _restore(client, legacy, passphrase=PASSPHRASE)
        assert res.status_code == 400, label
        body = res.get_json()
        assert body["code"] == "legacy_format" and "old unprotected format" in body["error"], label

    # An anonymous sandbox session (role=editor) may never use the legacy path.
    for label, legacy in legacy_files.items():
        res = _restore(client, legacy, allow_legacy="1")
        assert res.status_code == 403, label

    editor = _signed_in_client("editor")
    for label, legacy in legacy_files.items():
        logging.getLogger().setLevel(logging.WARNING)
        res = _restore(editor, legacy, path="/api/vault/restore", allow_legacy="1")
        assert res.status_code == 200, (label, res.get_json())
        assert res.get_json()["summary"]["accounts"] > 0

    # Viewer: the legacy option is editor-only (the route itself refuses a viewer).
    viewer = _signed_in_client("viewer", fid=4243)
    res = _restore(viewer, legacy_files["raw key"], path="/api/vault/restore", allow_legacy="1")
    assert res.status_code == 403
    # ...and a sandbox viewer cannot export either.
    with client.session_transaction() as sess:
        sess["role"] = sess["user_role"] = "viewer"
    assert _export(client).status_code == 403


def test_legacy_import_is_logged(tmp_path, caplog):
    client, _ = _sandbox_client()
    vault = _export(client).data
    fek = prepare_fovault_restore(vault, PASSPHRASE).fek
    legacy = _rewrite_key_material(vault, tmp_path, fek.decode())
    editor = _signed_in_client("editor", fid=4244)
    with caplog.at_level(logging.INFO):
        assert _restore(editor, legacy, path="/api/vault/restore", allow_legacy="1").status_code == 200
    assert any("legacy-format import accepted" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- secrets stay out of jobs, logs, session

def test_passphrase_appears_in_no_job_log_or_session(monkeypatch, caplog, force_async):
    recorder = _SubmitRecorder(background_jobs.submit_job)
    monkeypatch.setattr(background_jobs, "submit_job", recorder)
    secret = "unique-secret-passphrase-9f3a"
    client, fid = _sandbox_client()
    with caplog.at_level(logging.DEBUG):
        vault = _export(client, {"passphrase": secret, "passphrase_confirm": secret}).data
        fek = prepare_fovault_restore(vault, secret).fek
        res = _restore(client, vault, "/api/sandbox/restore_async", passphrase=secret)
        assert res.status_code == 200, res.get_json()
        job_id = res.get_json()["job_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            poll = client.get(f"/api/jobs/{job_id}")
            if poll.get_json().get("status") != "processing":
                break
            time.sleep(0.2)
        assert poll.get_json()["status"] == "completed", poll.get_json()

    assert recorder.job_ids == [job_id]
    assert job_id in _job_table_text("sandbox"), "scan must actually cover the persisted ticket"
    haystack = {
        "submit args": repr(recorder.calls),
        "job table": _job_table_text("sandbox"),
        "submit response": res.get_data(as_text=True),
        "poll response": poll.get_data(as_text=True),
        "logs": caplog.text + repr([(r.getMessage(), r.args) for r in caplog.records]),
    }
    with client.session_transaction() as sess:
        haystack["session"] = repr(dict(sess))
    for where, text in haystack.items():
        assert secret not in text, f"passphrase leaked into {where}"
        assert fek.decode() not in text or where == "session", f"FEK leaked into {where}"


def test_sandbox_restore_job_result_has_no_fek_and_sandbox_still_works(monkeypatch, force_async):
    recorder = _SubmitRecorder(background_jobs.submit_job)
    monkeypatch.setattr(background_jobs, "submit_job", recorder)
    sample = SAMPLE_VAULT.read_bytes()
    fek = prepare_fovault_restore(sample, SAMPLE_PASSPHRASE).fek
    fek_b64 = fek.decode()

    app.config["TESTING"] = True
    client = app.test_client()
    res = _restore(client, sample, "/api/sandbox/restore_async", passphrase=SAMPLE_PASSPHRASE)
    assert res.status_code == 200 and res.get_json()["status"] == "processing"
    new_fid, job_id = res.get_json()["family_id"], res.get_json()["job_id"]
    assert fek_b64 not in res.get_data(as_text=True)  # FEK travels only in the HttpOnly cookie

    deadline = time.time() + 30
    while time.time() < deadline:
        poll = client.get(f"/api/jobs/{job_id}")
        if poll.get_json().get("status") != "processing":
            break
        time.sleep(0.2)
    body = poll.get_json()
    assert body["status"] == "completed" and body["family_id"] == new_fid
    assert body["summary"]["accounts"] == 7  # computed by the polling request, not stored in the ticket
    assert "raw_fek_b64" not in body

    assert background_jobs.get_job(job_id, family_id=0) is None  # not a root-key ticket: readable only by its household
    assert fek_b64 not in repr(recorder.calls)
    assert job_id in _job_table_text("sandbox")
    assert fek_b64 not in _job_table_text("sandbox")
    assert recorder.calls[0]["kwargs"]["family_id"] == new_fid and recorder.calls[0]["job_type"] == "vault_restore"

    # The sandbox is usable afterwards: its cookie FEK decrypts the restored data and export still works.
    again = _export(client)
    assert again.status_code == 200
    assert prepare_fovault_restore(again.data, PASSPHRASE).fek == fek
