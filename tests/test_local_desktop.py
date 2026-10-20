"""
Automated Verification for Local Desktop Mode, Dynamic Port Fallback,
Mobile LAN QR Pairing, Encrypted Vault Backup, and PBKDF2 Passphrase FEK Wrapping.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
import pytest

import config
import desktop_app
import security
import security_crypto
from app import create_app


@pytest.fixture(autouse=True)
def _reset_security_caches():
    security._clear_security_caches()
    yield
    security._clear_security_caches()


def test_default_local_data_dir_cross_platform(monkeypatch, tmp_path):
    """Verifies OS-specific data directories for Windows, macOS, Linux, and explicit env override."""
    monkeypatch.delenv("FAMILY_OFFICE_DATA_DIR", raising=False)

    fake_home = tmp_path / "Home"
    monkeypatch.setattr(desktop_app.Path, "home", lambda: fake_home)

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "WinLocal"))
    win_dir = desktop_app.get_default_local_data_dir(platform_name="win32")
    assert win_dir == (tmp_path / "WinLocal" / "HVLFamilyOffice")

    mac_dir = desktop_app.get_default_local_data_dir(platform_name="darwin")
    assert mac_dir == fake_home / "Library" / "Application Support" / "HVLFamilyOffice"

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "LinuxXdg"))
    linux_dir = desktop_app.get_default_local_data_dir(platform_name="linux")
    assert linux_dir == (tmp_path / "LinuxXdg" / "hvl-family-office")

    # Legacy fallback: existing AIFamilyOffice directory is preserved if HVLFamilyOffice does not exist yet
    legacy_mac = fake_home / "Library" / "Application Support" / "AIFamilyOffice"
    legacy_mac.mkdir(parents=True, exist_ok=True)
    assert desktop_app.get_default_local_data_dir(platform_name="darwin") == legacy_mac

    custom = tmp_path / "MyCustomVault"
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(custom))
    assert desktop_app.get_default_local_data_dir(platform_name="win32") == custom.resolve()
    assert config.get_data_dir() == custom.resolve()
    assert config.get_global_db_path("public") == custom.resolve() / "public" / "global.db"
    assert config.get_family_db_path(1, "public") == custom.resolve() / "public" / "families" / "1.db"


def test_dynamic_port_fallback_when_5050_busy():
    """Verifies that if port 5050 (or preferred start port) is occupied, find_available_port steps to the next free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        occupied_port = blocker.getsockname()[1]

        assert not desktop_app.is_port_available(occupied_port, host="127.0.0.1")
        fallback_port = desktop_app.find_available_port(
            preferred_start=occupied_port,
            preferred_end=occupied_port + 10,
            host="127.0.0.1",
        )
        assert fallback_port != occupied_port
        assert fallback_port > occupied_port


def test_server_lockfile_write_and_cleanup(tmp_path):
    """Verifies writing and cleaning up `server.json` with PID ownership checks."""
    info = desktop_app.write_server_lockfile(tmp_path, port=5053, host="0.0.0.0")
    lock_path = tmp_path / "server.json"
    assert lock_path.exists()
    parsed = json.loads(lock_path.read_text(encoding="utf-8"))
    assert parsed["port"] == 5053
    assert parsed["url"] == "http://localhost:5053"
    assert parsed["pid"] == os.getpid()

    # Mismatched PID should not delete the lockfile
    desktop_app.remove_server_lockfile(tmp_path, expected_pid=os.getpid() + 99999)
    assert lock_path.exists()

    # Matching PID removes the lockfile cleanly
    desktop_app.remove_server_lockfile(tmp_path, expected_pid=os.getpid())
    assert not lock_path.exists()


def test_pbkdf2_passphrase_fek_wrap_and_unwrap():
    """Verifies PBKDF2-HMAC-SHA256 wrapping and unwrapping of a household FEK with a Master Passphrase / PIN."""
    raw_fek = Fernet.generate_key()
    wrapped = security_crypto.wrap_fek_with_passphrase(raw_fek, "Correct-Horse-Battery-9941", iterations=10_000)
    assert wrapped.startswith("pbkdf2_sha256$10000$")

    # Wrong passphrase must return None
    assert security_crypto.unwrap_fek_with_passphrase(wrapped, "Wrong-PIN-1234") is None

    # Correct passphrase recovers exact FEK bytes
    unwrapped = security_crypto.unwrap_fek_with_passphrase(wrapped, "Correct-Horse-Battery-9941")
    assert unwrapped == raw_fek


def test_desktop_endpoints_health_qr_pairing_and_backup(monkeypatch, tmp_path):
    """Verifies `/api/desktop/health`, `/api/desktop/status`, mobile LAN QR pairing, and `.fovault` backup export."""
    vault_dir = tmp_path / "local_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    monkeypatch.setenv("FAMILY_OFFICE_PORT", "5054")
    security._clear_security_caches()

    global_db = config.get_global_db_path("public")
    family_db = config.get_family_db_path(1, "public")
    security.init_db(global_db)
    security.init_db(family_db)
    fek = security.get_family_key(global_db, 1)

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Health endpoint
        res_health = client.get("/api/desktop/health")
        assert res_health.status_code == 200
        h_data = res_health.get_json()
        assert h_data["ok"] is True
        assert h_data["app"] == "hvl-family-office"
        assert h_data["local_mode"] is True

        # 2. Status endpoint on fresh unclaimed vault masks data_dir when unauthenticated
        res_status = client.get("/api/desktop/status")
        assert res_status.status_code == 200
        s_data = res_status.get_json()
        assert s_data["local_mode"] is True
        assert s_data["port"] == 5054
        assert s_data["data_dir"].startswith("~")
        assert str(Path.home()) not in s_data["data_dir"]
        assert s_data["is_unclaimed"] is True

        # 3. Unauthenticated or demo guest cannot export backup
        assert client.get("/api/desktop/backup").status_code in (401, 403)

        # 4. Authenticated editor sees full data_dir and generates single-use phone QR pairing link
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["user"] = "Local Owner"
            sess["role"] = "admin"
            sess["user_role"] = "admin"
            sess["universe"] = "public"
            sess["is_demo"] = False
            sess["vault_fek"] = fek.decode("utf-8")
            sess["vault_fek_family_id"] = 1

        res_status_auth = client.get("/api/desktop/status")
        assert res_status_auth.status_code == 200
        assert res_status_auth.get_json()["data_dir"] == str(vault_dir.resolve())

        # 5. Export encrypted .fovault backup file
        res_bak = client.get("/api/desktop/backup")
        assert res_bak.status_code == 200
        assert res_bak.headers["Content-Disposition"].endswith(".fovault")
        assert res_bak.data.startswith(b"SQLite format 3")


def test_local_passphrase_setup_and_login_flow(monkeypatch, tmp_path):
    """Verifies first-run offline Master Passphrase / PIN setup, onboarding redirect, and subsequent PIN login."""
    vault_dir = tmp_path / "pin_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    security._clear_security_caches()

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Setup with a too-short PIN (<4 chars) fails validation
        res_short = client.post("/api/desktop/local-setup", json={"name": "Alex Morgan", "passphrase": "123"})
        assert res_short.status_code == 400

        # 2. First-run setup with valid PIN claims Household #1 and redirects to /?onboarding=1
        res_setup = client.post(
            "/api/desktop/local-setup",
            json={"name": "Alex Morgan", "household_name": "The Morgan Household", "passphrase": "849201"},
        )
        assert res_setup.status_code == 200
        s_json = res_setup.get_json()
        assert s_json["success"] is True
        assert s_json["family_id"] == 1
        assert s_json["user"] == "Alex"
        assert s_json["redirect"] == "/?onboarding=1"

        # 3. Attempting to run setup a second time on a claimed vault returns 409 Conflict
        res_dup = client.post(
            "/api/desktop/local-setup",
            json={"name": "Intruder", "passphrase": "999999"},
        )
        assert res_dup.status_code == 409

        # 4. Log out, then verify wrong PIN fails (401) and correct PIN succeeds (200)
        client.post("/api/auth/logout")
        res_wrong = client.post("/api/desktop/local-login", json={"passphrase": "000000"})
        assert res_wrong.status_code == 401

        res_ok = client.post("/api/desktop/local-login", json={"passphrase": "849201"})
        assert res_ok.status_code == 200
        ok_json = res_ok.get_json()
        assert ok_json["success"] is True
        assert ok_json["user"] == "Alex"
        assert ok_json["redirect"] == "/"


def test_bootstrap_local_google_owner(monkeypatch, tmp_path):
    """Verifies that the first Google Sign-In on an unclaimed local vault automatically claims Household #1."""
    from routes.desktop import bootstrap_local_google_owner, is_local_vault_unclaimed

    vault_dir = tmp_path / "google_local_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    security._clear_security_caches()

    assert is_local_vault_unclaimed() is True
    claimed = bootstrap_local_google_owner("alex@example.com", "Alex Morgan")
    assert claimed is not None
    assert claimed["family_id"] == 1
    assert claimed["user_id"] == 1
    assert claimed["role"] == "editor"
    assert claimed["is_new_local_household"] is True
    assert is_local_vault_unclaimed() is False

    # Second call with another email must NOT overwrite or auto-claim
    assert bootstrap_local_google_owner("stranger@example.com", "Stranger") is None


def test_local_login_page_ssr_and_google_oauth_bootstrap(monkeypatch, tmp_path):
    """Verifies /login SSR renders #local-setup-form when unclaimed, #local-login-form when claimed, and authenticate_family_email auto-claims Household #1."""
    import auth_google

    vault_dir = tmp_path / "login_ssr_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    security._clear_security_caches()

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Unclaimed vault renders #local-setup-form on /login
        r1 = client.get("/login")
        assert r1.status_code == 200
        html1 = r1.get_data(as_text=True)
        assert 'id="local-setup-form"' in html1
        assert 'id="local-login-form"' not in html1

        # 2. Setup vault via PIN, log out, and verify /login now renders #local-login-form
        res_setup = client.post(
            "/api/desktop/local-setup",
            json={"name": "Alex Morgan", "passphrase": "4829"},
        )
        assert res_setup.status_code == 200
        client.post("/api/auth/logout")

        r2 = client.get("/login")
        assert r2.status_code == 200
        html2 = r2.get_data(as_text=True)
        assert 'id="local-login-form"' in html2
        assert 'id="local-setup-form"' not in html2

    # 3. Verify authenticate_family_email auto-provisions Household #1 on a fresh local vault
    google_vault_dir = tmp_path / "oauth_e2e_vault"
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(google_vault_dir))
    security._clear_security_caches()
    with app.test_request_context("/auth/google/callback"):
        ok, member, msg = auth_google.authenticate_family_email(
            "sam@example.com",
            {"name": "Sam Rivers"},
        )
        assert ok is True
        assert member is not None
        assert member["family_id"] == 1
        assert member["role"] == "admin"
        assert member.get("is_new_household") is True
        assert member.get("redirect") == "/?onboarding=1"


def test_pre_upgrade_backup_and_check_update_endpoint(monkeypatch, tmp_path):
    """Verifies ensure_pre_upgrade_backup snapshots the vault on version bump and /api/desktop/check-update compares semantic versions."""
    import sqlite3

    vault_dir = tmp_path / "upgrade_vault"
    families_dir = vault_dir / "public" / "families"
    families_dir.mkdir(parents=True, exist_ok=True)
    db_file = families_dir / "1.db"
    legacy_families_dir = vault_dir / "families"
    legacy_families_dir.mkdir(parents=True, exist_ok=True)
    legacy_db_file = legacy_families_dir / "1.db"
    for target_db in (db_file, legacy_db_file):
        with sqlite3.connect(str(target_db)) as conn:
            conn.execute("CREATE TABLE sample_vault (id INTEGER PRIMARY KEY, note TEXT)")
            conn.execute("INSERT INTO sample_vault (note) VALUES ('preserved across upgrade')")
            conn.commit()

    # Initial install v1.0.0 writes version.json without creating an upgrade backup
    b1 = desktop_app.ensure_pre_upgrade_backup(vault_dir, "1.0.0")
    assert b1 is None
    assert (vault_dir / "version.json").exists()

    # Same version startup does not create redundant backup
    b2 = desktop_app.ensure_pre_upgrade_backup(vault_dir, "1.0.0")
    assert b2 is None

    # Upgrading to v1.1.0 creates a pre_upgrade_v1.0.0_to_v1.1.0_*.fovault snapshot
    b3 = desktop_app.ensure_pre_upgrade_backup(vault_dir, "1.1.0")
    assert b3 is not None
    assert b3.exists()
    assert "pre_upgrade_v1.0.0_to_v1.1.0_" in b3.name

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        unauth = client.get("/api/desktop/check-update")
        assert unauth.status_code == 401
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["family_id"] = 1
        resp = client.get("/api/desktop/check-update")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["success"] is True
        assert "current_version" in payload
        assert "latest_version" in payload
        assert "update_available" in payload


def test_cloud_mode_rejects_local_desktop_endpoints(monkeypatch, tmp_path):
    """Verifies that when LOCAL_MODE=0 (cloud mode), local-only desktop endpoints return 403 Forbidden and status hides data_dir."""
    monkeypatch.setenv("LOCAL_MODE", "0")
    monkeypatch.delenv("STANDALONE_MODE", raising=False)
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "cloud_vault"))
    security._clear_security_caches()

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Status endpoint in cloud mode reports local_mode=False and data_dir=None
        res_status = client.get("/api/desktop/status")
        assert res_status.status_code == 200
        s_data = res_status.get_json()
        assert s_data["local_mode"] is False
        assert s_data["data_dir"] is None

        # 2. Unauthenticated local-setup and local-login return 403 Forbidden
        assert client.post("/api/desktop/local-setup", json={"name": "Owner", "passphrase": "1234"}).status_code == 403
        assert client.post("/api/desktop/local-login", json={"passphrase": "1234"}).status_code == 403

        # 3. Authenticated editor in cloud mode still gets 403 Forbidden on reveal-folder and shutdown
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["user"] = "Cloud Editor"
            sess["role"] = "editor"
            sess["user_role"] = "editor"
            sess["universe"] = "public"
            sess["is_demo"] = False

        assert client.post("/api/desktop/local-setup", json={"name": "Owner", "passphrase": "1234"}).status_code == 403
        assert client.post("/api/desktop/local-login", json={"passphrase": "1234"}).status_code == 403
        assert client.post("/api/desktop/reveal-folder").status_code == 403
        assert client.post("/api/desktop/shutdown").status_code == 403


def test_local_mode_reveal_folder_and_shutdown(monkeypatch, tmp_path):
    """Verifies authenticated POST /api/desktop/reveal-folder (mocking OS process launch) and POST /api/desktop/shutdown in LOCAL_MODE=1."""
    import subprocess
    import routes.desktop as desktop_routes

    vault_dir = tmp_path / "local_ops_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    security._clear_security_caches()

    # Write a server.json lockfile so shutdown can clean it up
    desktop_app.write_server_lockfile(vault_dir, port=5058)
    assert (vault_dir / "server.json").exists()

    popen_calls = []

    def fake_popen(cmd, *args, **kwargs):
        popen_calls.append(cmd)
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", lambda p: popen_calls.append(["startfile", p]))

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # Unauthenticated calls must be rejected by @editor_required
        assert client.post("/api/desktop/reveal-folder").status_code in (401, 403)
        assert client.post("/api/desktop/shutdown").status_code in (401, 403)

        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["user"] = "Local Admin"
            sess["role"] = "admin"
            sess["user_role"] = "admin"
            sess["universe"] = "public"
            sess["is_demo"] = False

        res_reveal = client.post("/api/desktop/reveal-folder")
        assert res_reveal.status_code == 200
        rev_data = res_reveal.get_json()
        assert rev_data["success"] is True
        assert rev_data["data_dir"] == str(vault_dir.resolve())
        assert len(popen_calls) == 1
        assert str(vault_dir.resolve()) == str(Path(popen_calls[0][1]).resolve())

        shutdown_invoked = []
        res_shut = client.post(
            "/api/desktop/shutdown",
            environ_overrides={"werkzeug.server.shutdown": lambda: shutdown_invoked.append(True)},
        )
        assert res_shut.status_code == 200
        assert res_shut.get_json()["success"] is True
        assert len(shutdown_invoked) == 1
        assert not (vault_dir / "server.json").exists()

        # Session should be cleared after shutdown
        assert client.get("/api/auth/status").get_json()["authenticated"] is False


def test_settings_ssr_local_desktop_controls_card_visibility(monkeypatch, tmp_path):
    """Verifies /fragments/settings?tab=monarch renders #local-desktop-controls-card when LOCAL_MODE=1 and omits it when LOCAL_MODE=0."""
    import routes.dashboard as dashboard_routes
    import routes.helpers as helpers_mod
    import ssr.settings as ssr_settings_mod

    vault_dir = tmp_path / "settings_ssr_vault"
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    global_db = config.get_global_db_path("public")
    family_db = config.get_family_db_path(1, "public")
    security._clear_security_caches()
    security.init_db(global_db)
    security.init_db(family_db)
    monkeypatch.setattr(helpers_mod, "DB_PATH", global_db)
    monkeypatch.setattr(dashboard_routes, "DB_PATH", global_db)
    monkeypatch.setattr(ssr_settings_mod, "DB_PATH", global_db)

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["family_id"] = 1
            sess["user_family_id"] = 1
            sess["user"] = "Local Owner"
            sess["role"] = "editor"
            sess["user_role"] = "editor"
            sess["universe"] = "public"
            sess["is_demo"] = False

        # 1. LOCAL_MODE=1 renders #local-desktop-controls-card and all action buttons
        monkeypatch.setenv("LOCAL_MODE", "1")
        r_local = client.get("/fragments/settings?tab=monarch")
        assert r_local.status_code == 200
        html_local = r_local.get_data(as_text=True)
        assert 'id="local-desktop-controls-card"' in html_local
        assert 'id="btn-desktop-recovery-key"' in html_local
        assert 'id="btn-desktop-backup"' in html_local
        assert 'id="btn-desktop-reveal-folder"' in html_local
        assert 'id="btn-desktop-shutdown"' in html_local

        # 2. LOCAL_MODE=0 omits #local-desktop-controls-card
        monkeypatch.setenv("LOCAL_MODE", "0")
        monkeypatch.delenv("STANDALONE_MODE", raising=False)
        r_cloud = client.get("/fragments/settings?tab=monarch")
        assert r_cloud.status_code == 200
        html_cloud = r_cloud.get_data(as_text=True)
        assert 'id="local-desktop-controls-card"' not in html_cloud


def test_desktop_app_probe_running_instance_launch_and_cli_main(monkeypatch, tmp_path):
    """Unit tests for desktop_app.py: probe_running_instance, get_running_server_info, launch_desktop reuse, and main(argv)."""
    import io
    import urllib.request
    import webbrowser

    vault_dir = tmp_path / "launcher_vault"
    vault_dir.mkdir(parents=True, exist_ok=True)

    # 1. probe_running_instance returns True on valid health JSON and False on wrong app or connection error
    class _FakeResp:
        def __init__(self, status: int, body: dict):
            self.status = status
            self._raw = json.dumps(body).encode("utf-8")

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=0.75: _FakeResp(200, {"ok": True, "app": "hvl-family-office"}),
    )
    assert desktop_app.probe_running_instance(5050) is True

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=0.75: _FakeResp(200, {"ok": True, "app": "other-service"}),
    )
    assert desktop_app.probe_running_instance(5050) is False

    def _raise_conn_err(req, timeout=0.75):
        raise OSError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_conn_err)
    assert desktop_app.probe_running_instance(5050) is False

    # 2. get_running_server_info returns None when no lockfile or when probe fails, and returns info when alive
    assert desktop_app.get_running_server_info(vault_dir) is None
    desktop_app.write_server_lockfile(vault_dir, port=5061)
    assert desktop_app.get_running_server_info(vault_dir) is None  # probe still returns False

    monkeypatch.setattr(desktop_app, "probe_running_instance", lambda port, timeout=0.75: port == 5061)
    active_info = desktop_app.get_running_server_info(vault_dir)
    assert active_info is not None
    assert active_info["port"] == 5061
    assert active_info["url"] == "http://localhost:5061"

    # 3. launch_desktop when an instance is already running opens browser to existing URL and returns 0 without starting a second server
    opened_urls = []
    monkeypatch.setattr(desktop_app, "find_app_mode_browser", lambda *_a, **_kw: None)
    monkeypatch.setattr(webbrowser, "open", lambda url: opened_urls.append(url))
    rc = desktop_app.launch_desktop(preferred_port=5050, open_browser=True, data_dir=vault_dir)
    assert rc == 0
    assert opened_urls == ["http://localhost:5061"]

    # 4. main(argv) CLI flag parsing forwards arguments to launch_desktop
    captured_launch = {}

    def _fake_launch_desktop(preferred_port=5050, host="0.0.0.0", open_browser=True, window_mode="auto", data_dir=None):
        captured_launch.update({
            "preferred_port": preferred_port,
            "host": host,
            "open_browser": open_browser,
            "window_mode": window_mode,
            "data_dir": data_dir,
        })
        return 0

    monkeypatch.setattr(desktop_app, "launch_desktop", _fake_launch_desktop)
    custom_cli_dir = tmp_path / "cli_custom_dir"
    rc_main = desktop_app.main([
        "--port", "5077",
        "--host", "127.0.0.1",
        "--data-dir", str(custom_cli_dir),
        "--no-browser",
    ])
    assert rc_main == 0
    assert captured_launch["preferred_port"] == 5077
    assert captured_launch["host"] == "127.0.0.1"
    assert captured_launch["open_browser"] is False
    assert captured_launch["data_dir"] == custom_cli_dir.resolve()


def test_standalone_app_window_and_heartbeat_auto_shutdown(monkeypatch, tmp_path):
    """
    Verifies:
    1. `open_desktop_window` launches Chromium/Edge in standalone `--app=<url>` mode (no localhost bar)
       when available, or falls back to `webbrowser.open` when `window_mode='browser'`.
    2. `POST /api/desktop/open-browser` opens the standard browser tab on request.
    3. `POST /api/desktop/heartbeat` tracks active windows and removes `server.json` (auto-shutdown)
       after the grace window when the last open window sends `event='close'`.
    """
    import subprocess
    import time
    import webbrowser
    import routes.desktop as desktop_routes

    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_text("binary", encoding="utf-8")
    monkeypatch.setattr(desktop_app, "find_app_mode_browser", lambda *_a, **_kw: str(fake_edge))

    popen_args = []
    browser_urls = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_kw: popen_args.append(cmd))
    monkeypatch.setattr(webbrowser, "open", lambda u, *_a, **_kw: browser_urls.append(u) or True)

    mode_used = desktop_app.open_desktop_window("http://localhost:5050", window_mode="auto")
    assert mode_used == "app"
    assert popen_args == [[str(fake_edge), "--app=http://localhost:5050"]]

    mode_browser = desktop_app.open_desktop_window("http://localhost:5050", window_mode="browser")
    assert mode_browser == "browser"
    assert browser_urls == ["http://localhost:5050"]

    # Verify heartbeat & last-window-close auto-shutdown
    vault_dir = tmp_path / "heartbeat_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    monkeypatch.setenv("FAMILY_OFFICE_PORT", "5061")
    monkeypatch.setenv("FAMILY_OFFICE_CLOSE_GRACE_SECONDS", "0.08")
    desktop_routes._ACTIVE_DESKTOP_CLIENTS.clear()

    desktop_app.write_server_lockfile(vault_dir, port=5061)
    assert (vault_dir / "server.json").exists()

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Open-browser endpoint launches standard browser
        res_ob = client.post("/api/desktop/open-browser")
        assert res_ob.status_code == 200
        assert res_ob.get_json()["url"] == "http://localhost:5061"
        assert "http://localhost:5061" in browser_urls

        # 2. Ping from two windows
        r_p1 = client.post("/api/desktop/heartbeat", json={"client_id": "win_1", "event": "ping"})
        assert r_p1.status_code == 200
        assert r_p1.get_json()["active_clients"] == 1

        r_p2 = client.post("/api/desktop/heartbeat", json={"client_id": "win_2", "event": "ping"})
        assert r_p2.status_code == 200
        assert r_p2.get_json()["active_clients"] == 2

        # 3. Closing win_1 while win_2 is still open must NOT schedule shutdown
        r_c1 = client.post("/api/desktop/heartbeat", json={"client_id": "win_1", "event": "close"})
        assert r_c1.status_code == 200
        assert r_c1.get_json()["active_clients"] == 1
        assert r_c1.get_json()["scheduled_shutdown"] is False
        assert (vault_dir / "server.json").exists()

        # 4. Closing win_2 (the last open window) schedules shutdown and removes server.json after grace period
        r_c2 = client.post("/api/desktop/heartbeat", json={"client_id": "win_2", "event": "close"})
        assert r_c2.status_code == 200
        assert r_c2.get_json()["active_clients"] == 0
        assert r_c2.get_json()["scheduled_shutdown"] is True

        time.sleep(0.18)
        assert not (vault_dir / "server.json").exists()


def test_local_change_and_reset_passphrase(monkeypatch, tmp_path):
    """Verifies changing PIN while logged in (/api/desktop/change-passphrase) and resetting a forgotten PIN (/api/desktop/reset-passphrase) with zero data loss."""
    vault_dir = tmp_path / "pin_reset_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    security._clear_security_caches()

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Initialize vault with initial PIN '1111'
        res_setup = client.post(
            "/api/desktop/local-setup",
            json={"name": "Taylor Reed", "passphrase": "1111"},
        )
        assert res_setup.status_code == 200

        # 2. Change PIN while logged in to '2222'
        res_change = client.post(
            "/api/desktop/change-passphrase",
            json={"new_passphrase": "2222"},
        )
        assert res_change.status_code == 200
        assert res_change.get_json()["success"] is True

        # 3. Log out: old PIN '1111' must fail (401), new PIN '2222' must succeed (200)
        client.post("/api/auth/logout")
        assert client.post("/api/desktop/local-login", json={"passphrase": "1111"}).status_code == 401
        assert client.post("/api/desktop/local-login", json={"passphrase": "2222"}).status_code == 200

        # 4. Log out and simulate forgetting PIN '2222':
        #    Attempting to reset without the .secret.key Recovery Key (even on localhost!) must be rejected (403)
        client.post("/api/auth/logout")
        res_no_key = client.post(
            "/api/desktop/reset-passphrase",
            json={"new_passphrase": "3333"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert res_no_key.status_code == 403

        res_wrong_key = client.post(
            "/api/desktop/reset-passphrase",
            json={"recovery_key": "wrong-key-token", "new_passphrase": "3333"},
        )
        assert res_wrong_key.status_code == 403

        # 5. Supplying the actual 44-character Local Recovery Key (.mm/.secret.key) succeeds and preserves user 'Taylor'
        actual_recovery_key = security.get_or_create_key().decode("utf-8").strip()
        res_reset = client.post(
            "/api/desktop/reset-passphrase",
            json={"recovery_key": actual_recovery_key, "new_passphrase": "3333"},
        )
        assert res_reset.status_code == 200
        r_json = res_reset.get_json()
        assert r_json["success"] is True
        assert r_json["user"] == "Taylor"

        # 5b. While logged in, GET /api/desktop/recovery-key returns the same 44-char key,
        #     and POST /api/desktop/restore restores an exported .fovault backup
        res_rk = client.get("/api/desktop/recovery-key")
        assert res_rk.status_code == 200
        assert res_rk.get_json()["recovery_key"] == actual_recovery_key

        res_bak = client.get("/api/desktop/backup")
        assert res_bak.status_code == 200
        fovault_bytes = res_bak.data

        import io
        res_bad_restore = client.post(
            "/api/desktop/restore",
            data={"file": (io.BytesIO(b"not-a-sqlite-file"), "corrupt.fovault")},
            content_type="multipart/form-data",
        )
        assert res_bad_restore.status_code == 400

        res_restore = client.post(
            "/api/desktop/restore",
            data={"file": (io.BytesIO(fovault_bytes), "backup.fovault")},
            content_type="multipart/form-data",
        )
        assert res_restore.status_code == 200
        assert res_restore.get_json()["success"] is True
        assert len(list((vault_dir / "backups").glob("pre_restore_family_*.fovault"))) == 1

        # 6. Verify '3333' now unlocks the vault and '2222' is rejected, and /help is publicly accessible without login
        client.post("/api/auth/logout")
        res_help = client.get("/help")
        assert res_help.status_code == 200
        help_html = res_help.get_data(as_text=True)
        assert "Complete User &amp; Self-Hosting Guide" in help_html
        assert 'id="help-search-input"' in help_html
        assert client.post("/api/desktop/local-login", json={"passphrase": "2222"}).status_code == 401
        assert client.post("/api/desktop/local-login", json={"passphrase": "3333"}).status_code == 200


def test_desktop_network_binding_and_endpoint_hardening(monkeypatch, tmp_path):
    """
    Verifies:
    1. `desktop_app.main([])` defaults `--host` to `127.0.0.1` so the desktop app is not exposed to public Wi-Fi by default.
    2. `POST /api/desktop/local-setup` rejects non-loopback LAN callers (`192.168.1.99`) with 403 even on an unclaimed vault.
    3. `POST /api/desktop/heartbeat` and `POST /api/desktop/open-browser` reject unauthenticated LAN callers (`192.168.1.99`)
       and DNS-rebinding `Host` headers (`evil.attacker.com:5050`) with 403.
    4. `POST /api/desktop/local-login` enforces rate limiting (`10/min`).
    """
    import inspect
    from hvl_common.web import reset_rate_limits

    sig = inspect.signature(desktop_app.launch_desktop)
    assert sig.parameters["host"].default == "127.0.0.1"

    captured = {}
    monkeypatch.setattr(
        desktop_app,
        "launch_desktop",
        lambda **kw: captured.update(kw) or 0,
    )
    desktop_app.main(["--no-browser"])
    assert captured["host"] == "127.0.0.1"

    vault_dir = tmp_path / "hardened_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    security._clear_security_caches()

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. LAN neighbor cannot race first-time local-setup
        res_lan_setup = client.post(
            "/api/desktop/local-setup",
            json={"name": "LAN Attacker", "passphrase": "9999"},
            environ_base={"REMOTE_ADDR": "192.168.1.99"},
        )
        assert res_lan_setup.status_code == 403

        # 2. Unauthenticated LAN caller and DNS-rebinding Host header are blocked on heartbeat and open-browser
        res_lan_hb = client.post(
            "/api/desktop/heartbeat",
            json={"client_id": "c1", "event": "close"},
            environ_base={"REMOTE_ADDR": "192.168.1.99"},
        )
        assert res_lan_hb.status_code == 403

        res_rebind_hb = client.post(
            "/api/desktop/heartbeat",
            json={"client_id": "c1", "event": "close"},
            headers={"Host": "evil.attacker.com:5050"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert res_rebind_hb.status_code == 403

        res_lan_ob = client.post(
            "/api/desktop/open-browser",
            environ_base={"REMOTE_ADDR": "192.168.1.99"},
        )
        assert res_lan_ob.status_code == 403

        res_rebind_ob = client.post(
            "/api/desktop/open-browser",
            headers={"Host": "evil.attacker.com:5050"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert res_rebind_ob.status_code == 403

        # 3. Localhost setup succeeds
        res_local_setup = client.post(
            "/api/desktop/local-setup",
            json={"name": "Local Owner", "passphrase": "5555"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert res_local_setup.status_code == 200
        client.post("/api/auth/logout")

        # 4. Rate limit on local-login blocks after 10 attempts per minute
        rl_dir = tmp_path / "rl_cache"
        monkeypatch.setenv("HVL_RATELIMIT_CACHE_DIR", str(rl_dir))
        app.config["RATELIMIT_ENABLED"] = True
        reset_rate_limits(rl_dir)
        for _ in range(10):
            r = client.post("/api/desktop/local-login", json={"passphrase": "0000"})
            assert r.status_code == 401
        r_limited = client.post("/api/desktop/local-login", json={"passphrase": "0000"})
        assert r_limited.status_code == 429
        reset_rate_limits(rl_dir)

        # 5. /features renders formatted Release Notes from CHANGELOG.md
        res_feat = client.get("/features")
        assert res_feat.status_code == 200
        feat_html = res_feat.get_data(as_text=True)
        assert 'id="release-notes"' in feat_html
        assert "<code>.fovault</code>" in feat_html
        assert "<code>PBKDF2-HMAC-SHA256</code>" in feat_html


def test_desktop_reset_vault_endpoint(monkeypatch, tmp_path):
    """Verifies that /api/desktop/reset-vault wipes local DB files and returns redirect to /login."""
    from routes.desktop import is_local_vault_unclaimed
    vault_dir = tmp_path / "reset_vault_test"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    security._clear_security_caches()

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Setup local vault
        res_setup = client.post(
            "/api/desktop/local-setup",
            json={"name": "Alex", "passphrase": "secret-pin-1234"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert res_setup.status_code == 200
        assert not is_local_vault_unclaimed()

        # 2. Reset vault
        res_reset = client.post("/api/desktop/reset-vault", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert res_reset.status_code == 200
        assert res_reset.get_json()["redirect"] == "/login"

        # 3. Verify vault is now unclaimed
        assert is_local_vault_unclaimed()

        # 8. /features, /help, and /whats-new render Back to Local Vault buttons and desktop heartbeat
        for path in ("/features", "/help", "/whats-new"):
            res_p = client.get(path)
            assert res_p.status_code == 200
            html_p = res_p.get_data(as_text=True)
            assert "Back to Local Vault" in html_p
            assert "/api/desktop/heartbeat" in html_p

        # 9. Demo persona in LOCAL_MODE renders "← Back to Local Vault" and heartbeats cleanly
        res_demo = client.get("/demo/jones", follow_redirects=True)
        assert res_demo.status_code == 200
        demo_html = res_demo.get_data(as_text=True)
        assert "← Back to Local Vault" in demo_html
        assert "/api/desktop/heartbeat" in demo_html

        # Heartbeat endpoint must accept pings from demo sessions in LOCAL_MODE
        with client.session_transaction() as sess:
            sess["is_demo"] = True
        r_hb_demo = client.post("/api/desktop/heartbeat", json={"client_id": "demo_win", "event": "ping"})
        assert r_hb_demo.status_code == 200
        assert r_hb_demo.get_json()["success"] is True


def test_local_vault_recovers_claimed_status_when_users_in_family_db(monkeypatch, tmp_path):
    """Verifies that if users are in families/1.db but missing from global.db, the vault remains claimed and heals automatically."""
    from routes.desktop import is_local_vault_unclaimed, has_local_passphrase_configured

    vault_dir = tmp_path / "sync_recovery_vault"
    monkeypatch.setenv("LOCAL_MODE", "1")
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(vault_dir))
    security._clear_security_caches()

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # 1. Setup vault via PIN
        res_setup = client.post(
            "/api/desktop/local-setup",
            json={"name": "Primary Owner", "passphrase": "9999"},
        )
        assert res_setup.status_code == 200

        # 2. Simulate users table wiped in global.db but intact in families/1.db
        uni = "test"
        global_db = config.get_global_db_path(uni)
        with security.get_db_connection(global_db) as conn:
            conn.execute("DELETE FROM users WHERE family_id = 1")
            conn.commit()

        # 3. Log out and navigate to /login
        client.post("/api/auth/logout")

        # 4. Vault must be detected as claimed with passphrase configured
        assert has_local_passphrase_configured(global_db) is True
        assert is_local_vault_unclaimed(global_db) is False

        # 5. /login must render #local-login-form (Unlock) instead of #local-setup-form
        res_login = client.get("/login")
        assert res_login.status_code == 200
        html = res_login.get_data(as_text=True)
        assert 'id="local-login-form"' in html
        assert 'id="local-setup-form"' not in html

        # 6. Verify users table in global.db was healed from families/1.db
        with security.get_db_connection(global_db) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM users WHERE family_id = 1").fetchone()[0]
            assert cnt >= 1



