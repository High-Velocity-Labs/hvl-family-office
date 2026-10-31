"""
Sandbox key binding: a sandbox's cookie-held key only resumes the sandbox it was issued for.
Real sandbox DBs in tmp dirs; no stubs. Covers the cookie-swap takeover (hvl_sandbox_fid -> another sandbox's id).
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest
from app import app
import config
import security
from hvl_common.security import VAULT_COOKIE_NAME
from routes import sandbox as sandbox_routes
from services import sandbox_service

FID_COOKIE = sandbox_routes.SANDBOX_FID_COOKIE


@pytest.fixture
def sb_env(tmp_path, monkeypatch):
    uni = lambda u: config.normalize_universe(u) if hasattr(config, "normalize_universe") else u
    monkeypatch.setattr(config, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "get_global_db_path", lambda universe="public": tmp_path / uni(universe) / "global.db")
    monkeypatch.setattr(config, "get_family_db_path", lambda fid, universe="public": tmp_path / uni(universe) / "families" / f"{fid}.db")
    monkeypatch.setitem(app.config, "TESTING", True)
    security._clear_security_caches()
    yield tmp_path
    security._clear_security_caches()


def _launch(client=None):
    client = client or app.test_client(use_cookies=False)
    res = client.post("/api/sandbox/launch", json={"template": "blank"})
    assert res.status_code == 200, res.get_data(as_text=True)
    jar = {}
    for hdr in res.headers.getlist("Set-Cookie"):
        name, _, rest = hdr.partition("=")
        if name != "session":  # browser-side state only: the signed Flask session is the server's, not the cookie-swap input
            jar[name] = rest.split(";", 1)[0]
    return res.get_json()["family_id"], jar


def _cookie_header(jar):
    return "; ".join(f"{k}={v}" for k, v in jar.items())


def _get(path, jar, **kw):
    return app.test_client(use_cookies=False).get(path, headers={"Cookie": _cookie_header(jar)}, **kw)


def _db_digest(fid):
    return hashlib.sha256(config.get_family_db_path(fid, "sandbox").read_bytes()).hexdigest()


def _lease_exists(fid):
    with sqlite3.connect(config.get_global_db_path("sandbox")) as c:
        return c.execute("SELECT 1 FROM sandbox_leases WHERE family_id = ?", (fid,)).fetchone() is not None


def _assert_not_victim(res, victim_fid, attacker_fid):
    """A refused resume never elevates into the victim: the caller either gets a brand-new sandbox or nothing."""
    set_cookies = " ".join(res.headers.getlist("Set-Cookie"))
    assert f"{FID_COOKIE}={victim_fid}" not in set_cookies
    if f"{FID_COOKIE}=" in set_cookies and f"{FID_COOKIE}=;" not in set_cookies:
        issued = set_cookies.split(f"{FID_COOKIE}=", 1)[1].split(";", 1)[0]
        assert issued not in (str(victim_fid), str(attacker_fid))  # a fresh sandbox of the caller's own
    else:
        assert f"{FID_COOKIE}=;" in set_cookies  # refused cookies were cleared


def test_cookie_swap_to_victim_sandbox_is_refused(sb_env):
    victim_fid, victim_jar = _launch()
    attacker_fid, attacker_jar = _launch()
    before = _db_digest(victim_fid)

    forged = {**attacker_jar, FID_COOKIE: str(victim_fid)}
    res = _get("/sandbox", forged)
    _assert_not_victim(res, victim_fid, attacker_fid)
    attacker = app.test_client(use_cookies=False)
    wipe = attacker.post("/api/sandbox/wipe", headers={"Cookie": _cookie_header(forged)})
    assert wipe.status_code in (400, 401, 403)

    assert _lease_exists(victim_fid)
    assert _db_digest(victim_fid) == before
    owner = _get("/sandbox", victim_jar)
    assert owner.status_code == 302 and "sandbox=1" in owner.headers["Location"]


def test_cookie_for_nonexistent_sandbox_is_refused(sb_env):
    fid, jar = _launch()
    assert sandbox_service.wipe_sandbox_immediately(fid)
    lease, key, _ = _resume_with(jar)
    assert lease == 0 and key is None


def _resume_with(jar):
    with app.test_request_context("/sandbox", headers={"Cookie": _cookie_header(jar)}):
        return sandbox_routes.get_resumable_sandbox_lease()


def test_tampered_or_garbled_token_is_refused(sb_env):
    fid, jar = _launch()
    assert _resume_with(jar)[0] == fid
    names = [n for n in jar if n != FID_COOKIE]
    for mutate in (lambda v: v[:-6] + ("AAAAAA" if not v.endswith("AAAAAA") else "BBBBBB"), lambda v: "not-a-token", lambda v: ""):
        bad = {**jar, **{n: mutate(jar[n]) for n in names}}
        assert _resume_with(bad) == (0, None, None)
    res = _get("/sandbox", {**jar, **{n: "not-a-token" for n in names}})
    _assert_not_victim(res, fid, fid)


def test_legitimate_owner_keeps_working_across_requests(sb_env):
    fid, jar = _launch()
    for _ in range(3):
        res = _get("/sandbox", jar)
        assert res.status_code == 302 and "sandbox=1" in res.headers["Location"]
    assert _resume_with(jar)[0] == fid


def test_sandbox_without_binding_fails_closed(sb_env):
    fid, jar = _launch()
    with sqlite3.connect(config.get_global_db_path("sandbox")) as c:
        c.execute("UPDATE sandbox_leases SET session_hash = '' WHERE family_id = ?", (fid,))  # lease issued before the binding existed
    assert _resume_with(jar) == (0, None, None)
    assert _lease_exists(fid)


def test_rate_limit_runs_before_binding_check(sb_env, monkeypatch):
    monkeypatch.setitem(app.config, "RATELIMIT_ENABLED", True)
    monkeypatch.setitem(app.config, "RATELIMIT_CACHE_DIR", str(sb_env / "rl"))
    monkeypatch.setattr(sandbox_routes, "SANDBOX_RESUME_LIMIT", "3/hr")
    calls = []
    real = sandbox_routes.sandbox_key_matches
    monkeypatch.setattr(sandbox_routes, "sandbox_key_matches", lambda f, k: (calls.append(f), real(f, k))[1])
    victim_fid, _ = _launch()
    _, attacker_jar = _launch()
    forged = {**attacker_jar, FID_COOKIE: str(victim_fid)}
    codes = [_get("/sandbox", forged).status_code for _ in range(4)]
    assert codes[-1] == 429
    assert 429 not in codes[:3]
    assert len(calls) == 3  # the 4th attempt was throttled before any binding check


def test_loopback_without_forwarded_for_is_rate_limited_outside_local_mode(sb_env, monkeypatch):
    monkeypatch.setitem(app.config, "TESTING", False)
    monkeypatch.setitem(app.config, "RATELIMIT_ENABLED", True)
    monkeypatch.setitem(app.config, "RATELIMIT_CACHE_DIR", str(sb_env / "rl"))
    assert not config.is_local_mode()
    client = app.test_client(use_cookies=False)
    codes = [client.post("/api/sandbox/restore").status_code for _ in range(6)]
    assert codes[:5] == [400] * 5
    assert codes[5] == 429
