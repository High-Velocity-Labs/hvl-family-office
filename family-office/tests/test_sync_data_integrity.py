"""Sync data-integrity tests: partial Monarch/SimpleFIN failures never delete data, token persistence, metadata merge."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import account_sync
import db
import security
from account_sync import monarch_client, monarch_sync, simplefin
from config import get_family_db_path, get_global_db_path
from hvl_common.db import get_db_connection

FID = 9051
UNI = "test"


@pytest.fixture()
def fam_db():
    fam = get_family_db_path(FID, universe=UNI)
    security.init_db(fam)
    security.init_db(get_global_db_path(universe=UNI))
    with get_db_connection(fam) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO families (family_id, name, settings, support_access_enabled) VALUES (?, ?, ?, 1)",
            (FID, "Sync Integrity Test", "{}"),
        )
        conn.commit()
    security.update_family(fam, family_id=FID, name="Sync Integrity Test")
    db.accounts.replace_accounts(family_id=FID, accounts=[], db_path=fam, provider="monarch")
    db.accounts.replace_accounts(family_id=FID, accounts=[], db_path=fam, provider="simplefin")
    db.accounts.replace_holdings(family_id=FID, holdings_by_account={}, db_path=fam, provider="monarch")
    db.accounts.replace_holdings(family_id=FID, holdings_by_account={}, db_path=fam, provider="simplefin")
    security.db_save_encrypted(fam, "monarch_credentials", "settings", {"token": "tok-good"}, family_id=FID)
    security.db_save_encrypted(fam, "last_sync_metadata", "sync", {}, family_id=FID)
    yield fam
    db.accounts.replace_accounts(family_id=FID, accounts=[], db_path=fam, provider="monarch")
    db.accounts.replace_holdings(family_id=FID, holdings_by_account={}, db_path=fam, provider="monarch")
    db.accounts.replace_accounts(family_id=FID, accounts=[], db_path=fam, provider="simplefin")
    db.accounts.replace_holdings(family_id=FID, holdings_by_account={}, db_path=fam, provider="simplefin")


def _acct(aid):
    return {"id": aid, "displayName": aid, "currentBalance": 100.0, "type": {"name": "brokerage"}, "holdingsCount": 1}


def _holding(hid, value):
    return {"id": hid, "ticker": "VTI", "name": "VTI", "quantity": 1.0, "totalValue": value, "basis": 1.0,
            "security": {"ticker": "VTI", "name": "VTI"}}


class FakeMonarch:
    """Stateful Monarch double: requires a valid token, rejects unknown accounts, raises on illegal use."""
    fail_holdings: set = set()
    holdings: dict = {}
    accounts: list = []

    def __init__(self):
        self._token = None

    def set_token(self, token):
        if not token:
            raise ValueError("empty token")
        self._token = token

    async def get_accounts(self):
        if self._token != "tok-good":
            raise RuntimeError("401 Unauthorized")
        return {"accounts": list(type(self).accounts)}

    async def get_account_holdings(self, account_id):
        if self._token != "tok-good":
            raise RuntimeError("401 Unauthorized")
        if account_id not in {a["id"] for a in type(self).accounts}:
            raise KeyError(account_id)
        if account_id in type(self).fail_holdings:
            raise RuntimeError("holdings upstream 500")
        nodes = type(self).holdings.get(account_id, [])
        return {"portfolio": {"aggregateHoldings": {"edges": [{"node": n} for n in nodes]}}}


@pytest.fixture()
def fake_monarch(monkeypatch):
    import monarchmoney
    FakeMonarch.fail_holdings = set()
    FakeMonarch.accounts = [_acct("m1"), _acct("m2"), _acct("m3")]
    FakeMonarch.holdings = {a: [_holding(f"{a}_new", 999.0)] for a in ("m1", "m2", "m3")}
    monkeypatch.setattr(monarchmoney, "MonarchMoney", FakeMonarch)
    return FakeMonarch


def _seed_old_holdings(fam):
    db.accounts.replace_accounts(family_id=FID, accounts=FakeMonarch.accounts, db_path=fam, provider="monarch")
    db.accounts.replace_holdings(
        family_id=FID, db_path=fam, provider="monarch",
        holdings_by_account={a: [_holding(f"{a}_old", 1.0)] for a in ("m1", "m2", "m3")},
    )


def _ids(fam):
    return {a: [h["id"] for h in hs] for a, hs in db.accounts.get_holdings_by_account(family_id=FID, db_path=fam).items()}


def test_one_of_three_accounts_failing_keeps_its_holdings_and_reports_partial(fam_db, fake_monarch):
    _seed_old_holdings(fam_db)
    fake_monarch.fail_holdings = {"m2"}
    res = monarch_client.trigger_monarch_sync(family_id=FID, db_path=fam_db)
    assert res["success"] is True and res["status"] == "partial" and res["failed_accounts"] == ["m2"]
    assert _ids(fam_db) == {"m1": ["m1_new"], "m2": ["m2_old"], "m3": ["m3_new"]}
    meta = security.db_load_encrypted(fam_db, "last_sync_metadata", family_id=FID)
    mon = meta["providers"]["monarch"]
    assert mon["status"] == "partial" and mon["failed_holdings_accounts"] == ["m2"]


def test_all_accounts_failing_deletes_nothing_and_reports_failed(fam_db, fake_monarch):
    _seed_old_holdings(fam_db)
    fake_monarch.fail_holdings = {"m1", "m2", "m3"}
    res = monarch_client.trigger_monarch_sync(family_id=FID, db_path=fam_db)
    assert res["success"] is False and res["status"] == "failed"
    assert _ids(fam_db) == {"m1": ["m1_old"], "m2": ["m2_old"], "m3": ["m3_old"]}


def test_full_success_replaces_everything(fam_db, fake_monarch):
    _seed_old_holdings(fam_db)
    res = monarch_client.trigger_monarch_sync(family_id=FID, db_path=fam_db)
    assert res["success"] is True and res["status"] == "success"
    assert _ids(fam_db) == {"m1": ["m1_new"], "m2": ["m2_new"], "m3": ["m3_new"]}


def test_exception_mid_write_rolls_back_accounts_and_holdings(fam_db, monkeypatch):
    _seed_old_holdings_accounts = [_acct("m1"), _acct("m2")]
    db.accounts.replace_accounts(family_id=FID, accounts=_seed_old_holdings_accounts, db_path=fam_db, provider="monarch")
    db.accounts.replace_holdings(family_id=FID, db_path=fam_db, provider="monarch",
                                 holdings_by_account={"m1": [_holding("m1_old", 1.0)]})
    import config
    monkeypatch.setattr(config, "MAX_HOUSEHOLD_HOLDINGS", 1)  # new rows exceed the cap after deletes ran
    with pytest.raises(ValueError):
        db.accounts.replace_accounts_and_holdings(
            family_id=FID, db_path=fam_db, provider="monarch",
            accounts=[_acct("m9")],
            holdings_by_account={"m9": [_holding("a", 1.0), _holding("b", 2.0)]},
        )
    assert {a["id"] for a in db.accounts.list_accounts(family_id=FID, db_path=fam_db)} == {"m1", "m2"}
    assert _ids(fam_db) == {"m1": ["m1_old"]}


class FlakyVault:
    """security.db_save_encrypted double that tracks calls and either raises or stores a different token."""
    def __init__(self, real, mode):
        self.real, self.mode, self.calls = real, mode, 0

    def __call__(self, db_path, key, category, data, family_id=0):
        if key != "monarch_credentials":
            return self.real(db_path, key, category, data, family_id=family_id)
        self.calls += 1
        if self.mode == "raise":
            raise OSError("disk full")
        self.real(db_path, key, category, {**data, "token": "someone-else"}, family_id=family_id)


@pytest.mark.parametrize("mode", ["raise", "mismatch"])
def test_failed_token_save_keeps_legacy_pickle_and_raises(fam_db, tmp_path, monkeypatch, mode):
    monkeypatch.setattr(monarch_sync, "SESSION_DIR", tmp_path)
    legacy = monarch_sync.get_family_session_file(FID)
    legacy.write_bytes(b"pickle")
    flaky = FlakyVault(security.db_save_encrypted, mode)
    monkeypatch.setattr(monarch_sync.security, "db_save_encrypted", flaky)
    with pytest.raises(monarch_sync.MonarchTokenPersistError):
        monarch_sync._persist_vault_token(fam_db, FID, "tok-new")
    assert flaky.calls == 1 and legacy.exists()


def test_confirmed_token_save_removes_legacy_pickle(fam_db, tmp_path, monkeypatch):
    monkeypatch.setattr(monarch_sync, "SESSION_DIR", tmp_path)
    legacy = monarch_sync.get_family_session_file(FID)
    legacy.write_bytes(b"pickle")
    monarch_sync._persist_vault_token(fam_db, FID, "tok-new")
    assert not legacy.exists()
    assert security.db_load_encrypted(fam_db, "monarch_credentials", family_id=FID)["token"] == "tok-new"


def test_sync_surfaces_token_save_error_and_keeps_pickle(fam_db, fake_monarch, tmp_path, monkeypatch):
    monkeypatch.setattr(monarch_sync, "SESSION_DIR", tmp_path)
    legacy = monarch_sync.get_family_session_file(FID)
    legacy.write_bytes(b"pickle")
    security.db_save_encrypted(fam_db, "monarch_credentials", "settings", {"token": ""}, family_id=FID)
    monkeypatch.setattr(monarch_sync.security, "db_save_encrypted", FlakyVault(security.db_save_encrypted, "raise"))
    monkeypatch.setattr(FakeMonarch, "load_session", lambda self, path: self.set_token("tok-good"), raising=False)
    res = monarch_client.trigger_monarch_sync(family_id=FID, db_path=fam_db)
    assert legacy.exists()
    assert res["warnings"] and "could not be saved" in res["warnings"][0] and "disk full" not in res["warnings"][0]


def test_simplefin_sync_keeps_monarch_upstream_refresh_ts(fam_db, monkeypatch):
    security.db_save_encrypted(fam_db, "simplefin_credentials", "settings",
                               {"access_url": "https://u:p@bridge.simplefin.org/simplefin"}, family_id=FID)
    security.db_save_encrypted(
        fam_db, "last_sync_metadata", "monarch_sync",
        {"timestamp": "2026-01-01T00:00:00+00:00", "provider": "monarch", "last_upstream_refresh_ts": "2026-01-01T00:00:00+00:00"},
        family_id=FID,
    )
    monkeypatch.setattr(simplefin, "fetch_simplefin_data", lambda url: {"success": True, "data": {"accounts": [
        {"id": "a1", "name": "Checking", "balance": "5.00", "org": {"name": "Bank"}}]}})
    res = simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)
    assert res["success"] and res["status"] == "success"
    meta = security.db_load_encrypted(fam_db, "last_sync_metadata", family_id=FID)
    assert meta["providers"]["monarch"]["last_upstream_refresh_ts"] == "2026-01-01T00:00:00+00:00"
    assert meta["providers"]["simplefin"]["status"] == "success"
    assert set(meta) == {"timestamp", "providers"}  # no lingering top-level provider state


def test_simplefin_bridge_error_keeps_missing_account_and_reports_partial(fam_db, monkeypatch):
    security.db_save_encrypted(fam_db, "simplefin_credentials", "settings",
                               {"access_url": "https://u:p@bridge.simplefin.org/simplefin"}, family_id=FID)
    def acc(i, bal, holdings=()):
        return {"id": i, "name": "Brokerage", "balance": bal, "org": {"name": "Bank"}, "holdings": list(holdings)}
    h = lambda s: {"id": s, "symbol": s, "shares": 1, "market_value": 10}
    state = {"data": {"accounts": [acc("a1", "1", [h("OLD1")]), acc("a2", "2", [h("OLD2")])]}}
    monkeypatch.setattr(simplefin, "fetch_simplefin_data", lambda url: {"success": True, "data": state["data"]})
    assert simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)["status"] == "success"
    state["data"] = {"errors": ["Connection to Bank requires re-auth"], "accounts": [acc("a1", "1", [h("NEW1")])]}
    res = simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)
    assert res["success"] and res["status"] == "partial" and res["failed_accounts"] == ["sfin_a2"]
    held = db.accounts.get_holdings_by_account(family_id=FID, db_path=fam_db)
    assert [x["ticker"] for x in held["sfin_a2"]] == ["OLD2"] and [x["ticker"] for x in held["sfin_a1"]] == ["NEW1"]
    assert "sfin_a2" in {a["id"] for a in db.accounts.list_accounts(family_id=FID, db_path=fam_db)}


def test_trigger_monarch_sync_family_zero_does_nothing(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must not resolve any db for family 0")
    monkeypatch.setattr(monarch_client, "get_db_path", _boom)
    monkeypatch.setattr(monarch_client, "_async_sync_monarch", _boom)
    res = account_sync.trigger_monarch_sync(family_id=0)
    assert res["success"] is False and res["status"] == "failed"


# ---- audit follow-ups: M2, L3, L4, L5 ----

def _enable_simplefin(fam, monkeypatch, payload_fn):
    security.db_save_encrypted(fam, "simplefin_credentials", "settings",
                               {"access_url": "https://u:p@bridge.simplefin.org/simplefin"}, family_id=FID)
    monkeypatch.setattr(simplefin, "fetch_simplefin_data", lambda url: {"success": True, "data": payload_fn()})


def _sfin_acc(i, org, holdings="absent", bal="1"):
    a = {"id": i, "name": f"Acct {i}", "balance": bal, "org": {"name": org}}
    if holdings != "absent":
        a["holdings"] = holdings
    return a


def _sfin_h(sym):
    return {"id": sym, "symbol": sym, "shares": 1, "market_value": 10}


def test_monarch_failed_while_simplefin_succeeds_is_partial_and_notifies(fam_db, fake_monarch, monkeypatch):
    _seed_old_holdings(fam_db)
    fake_monarch.fail_holdings = {"m1", "m2", "m3"}
    _enable_simplefin(fam_db, monkeypatch, lambda: {"accounts": [_sfin_acc("a1", "Bank")]})
    res = monarch_client.trigger_monarch_sync(family_id=FID, db_path=fam_db)
    assert res["success"] is True and res["status"] == "partial"
    assert res["providers"]["monarch"]["status"] == "failed" and res["providers"]["simplefin"]["status"] == "success"
    assert "Monarch" in res["error"]
    assert _ids(fam_db)["m1"] == ["m1_old"]  # failed provider's data untouched

    from routes import notifications
    emitted, resolved = [], []
    monkeypatch.setattr(notifications, "emit_family_notification", lambda *a, **k: emitted.append(k))
    monkeypatch.setattr(notifications, "resolve_family_notification", lambda *a, **k: resolved.append(k))
    notifications.record_sync_outcome_notification(family_id=FID, sync_res=res, db_path=fam_db)
    status_emits = [e for e in emitted if e.get("dedupe_key") == "job:sync:status"]
    assert status_emits and "Monarch sync failed" in status_emits[0]["body"]
    assert not [r for r in resolved if r.get("dedupe_key") == "job:sync:status"]


def test_both_providers_failing_is_failed(fam_db, fake_monarch, monkeypatch):
    fake_monarch.fail_holdings = {"m1", "m2", "m3"}
    security.db_save_encrypted(fam_db, "simplefin_credentials", "settings",
                               {"access_url": "https://u:p@bridge.simplefin.org/simplefin"}, family_id=FID)
    monkeypatch.setattr(simplefin, "fetch_simplefin_data", lambda url: {"success": False, "error": "bridge down"})
    res = monarch_client.trigger_monarch_sync(family_id=FID, db_path=fam_db)
    assert res["success"] is False and res["status"] == "failed"
    assert set(res["providers"]) == {"monarch", "simplefin"} and "bridge down" in res["error"]


def test_simplefin_exception_is_recorded_as_provider_failure(fam_db, fake_monarch, monkeypatch):
    security.db_save_encrypted(fam_db, "simplefin_credentials", "settings",
                               {"access_url": "https://u:p@bridge.simplefin.org/simplefin"}, family_id=FID)

    def _explode(family_id=0, db_path=None):
        raise RuntimeError("write failed for https://user:hunter2@bridge.simplefin.org")
    monkeypatch.setattr(simplefin, "trigger_simplefin_sync", _explode)
    res = monarch_client.trigger_monarch_sync(family_id=FID, db_path=fam_db)
    assert res["status"] == "partial" and res["success"] is True
    assert res["providers"]["simplefin"]["status"] == "failed"
    assert "hunter2" not in repr(res)


def test_simplefin_error_is_scoped_to_its_institution(fam_db, monkeypatch):
    state = {"data": {"accounts": [
        _sfin_acc("a1", "Alpha Bank", []), _sfin_acc("a2", "Beta Credit", []), _sfin_acc("a3", "Beta Credit", [])]}}
    _enable_simplefin(fam_db, monkeypatch, lambda: state["data"])
    assert simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)["status"] == "success"
    state["data"] = {"errors": ["Alpha Bank connection requires re-auth"], "accounts": [_sfin_acc("a2", "Beta Credit", [])]}
    res = simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)
    assert res["success"] and res["status"] == "partial" and res["failed_accounts"] == ["sfin_a1"]
    ids = {a["id"] for a in db.accounts.list_accounts(family_id=FID, db_path=fam_db)}
    assert ids == {"sfin_a1", "sfin_a2"}  # a3 was genuinely removed at a healthy institution


def test_simplefin_errors_with_no_accounts_is_failed_and_writes_nothing(fam_db, monkeypatch):
    state = {"data": {"accounts": [_sfin_acc("a1", "Bank", [_sfin_h("OLD1")])]}}
    _enable_simplefin(fam_db, monkeypatch, lambda: state["data"])
    simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)
    state["data"] = {"errors": ["Bank unavailable"], "accounts": []}
    res = simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)
    assert res["success"] is False and res["status"] == "failed"
    assert [h["ticker"] for h in db.accounts.get_holdings_by_account(family_id=FID, db_path=fam_db)["sfin_a1"]] == ["OLD1"]
    assert {a["id"] for a in db.accounts.list_accounts(family_id=FID, db_path=fam_db)} == {"sfin_a1"}


def test_simplefin_missing_holdings_key_keeps_holdings_but_empty_list_clears(fam_db, monkeypatch):
    state = {"data": {"accounts": [_sfin_acc("a1", "Bank", [_sfin_h("K1")]), _sfin_acc("a2", "Bank", [_sfin_h("K2")])]}}
    _enable_simplefin(fam_db, monkeypatch, lambda: state["data"])
    simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)
    state["data"] = {"accounts": [_sfin_acc("a1", "Bank"), _sfin_acc("a2", "Bank", [])]}
    assert simplefin.trigger_simplefin_sync(family_id=FID, db_path=fam_db)["status"] == "success"
    held = db.accounts.get_holdings_by_account(family_id=FID, db_path=fam_db)
    assert [h["ticker"] for h in held["sfin_a1"]] == ["K1"]  # unknown -> kept
    assert "sfin_a2" not in held  # genuine zero -> cleared


_MERGE_WORKER = """
import sys
sys.path.insert(0, {root!r})
from pathlib import Path
from db.sync_metadata import merge_provider_sync_entry
for i in range(80):
    merge_provider_sync_entry(Path({db!r}), {fid}, "{tag}_" + str(i), {{"timestamp": "2026-01-01T00:00:%02d+00:00" % i, "status": "success"}})
"""


def test_concurrent_merges_from_two_processes_lose_nothing(fam_db):
    import subprocess
    root = str(Path(__file__).resolve().parent.parent)
    procs = [
        subprocess.Popen([sys.executable, "-c", _MERGE_WORKER.format(root=root, db=str(fam_db), fid=FID, tag=tag)],
                         cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for tag in ("p1", "p2")
    ]
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode()[-800:]
    meta = security.db_load_encrypted(fam_db, "last_sync_metadata", family_id=FID)
    assert {f"{t}_{i}" for t in ("p1", "p2") for i in range(80)} <= set(meta["providers"])


def test_token_persist_with_missing_db_raises_and_keeps_pickle(tmp_path, monkeypatch):
    monkeypatch.setattr(monarch_sync, "SESSION_DIR", tmp_path)
    missing = tmp_path / "nope.db"
    monkeypatch.setattr(monarch_sync, "get_db_path", lambda family_id=0: missing)
    legacy = monarch_sync.get_family_session_file(FID)
    legacy.write_bytes(b"pickle")
    with pytest.raises(monarch_sync.MonarchTokenPersistError):
        monarch_sync._persist_vault_token(missing, FID, "tok-new")
    assert legacy.exists()
