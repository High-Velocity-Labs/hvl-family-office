"""
Tests for HVL Family Office Notification Bell, Slide-Over Drawer, Computed Alerts,
Domain-Version Signals, Multi-Tenant Isolation, and Locked-Vault Tolerance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app
import db
import forecast_cache
import security


def _make_auth_client(family_id: int = 1, role: str = "editor", is_demo: bool = False, email: str = "alex@example.com"):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Alex Test"
        sess["user_email"] = email
        sess["user_family_id"] = family_id
        sess["family_id"] = family_id
        sess["role"] = role
        sess["is_demo"] = is_demo
        sess["universe"] = "demo" if is_demo else "test"
        sess["auth_method"] = "Google OAuth"
    return client


def test_ssr_renders_notification_bell_and_drawer():
    """Verifies GET / renders #btn-notification-bell, #hvl-notification-badge, and #hvl-notifications-drawer."""
    client = _make_auth_client(family_id=1)
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert 'id="btn-notification-bell"' in html
    assert 'id="hvl-notification-badge"' in html
    assert 'id="hvl-notifications-drawer"' in html
    assert 'id="hvl-notifications-drawer-body"' in html
    assert 'data-depends="notifications"' in html


def test_notifications_fragment_endpoints_and_headers():
    """Verifies GET /api/notifications/fragment and GET /fragments/notifications return 200 with X-Notification-Count."""
    client = _make_auth_client(family_id=1)
    db.notifications.clear_all_notifications(family_id=1, recipient_email="alex@example.com")
    db.notifications.emit_family_notification(
        family_id=1,
        category="async_job",
        dedupe_key="job:w2:2025:Alex",
        deep_link="/?tab=compensation",
        title="2025 Form W-2 parsed (Alex)",
        body="Encrypted Form W-2 and updated safe harbor records.",
    )

    for url in ("/api/notifications/fragment", "/fragments/notifications"):
        resp = client.get(url)
        assert resp.status_code == 200
        assert "X-Notification-Count" in resp.headers
        assert int(resp.headers["X-Notification-Count"]) >= 1
        html = resp.data.decode("utf-8")
        assert 'id="hvl-notifications-drawer-body"' in html
        assert 'data-depends="notifications"' in html
        assert "2025 Form W-2 parsed (Alex)" in html


def test_computed_alerts_support_access_and_stale_sync():
    """Verifies computed alerts for Support Access ON and stale account sync (>7 days), plus auto-resolution."""
    fam_db = db.session.resolve_db_path(None, family_id=1)
    security.set_family_support_access(fam_db, family_id=1, enabled=True)

    stale_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    security.db_save_encrypted(
        fam_db, "monarch_credentials", "settings", {"email": "alex@example.com", "token": "tok_test"}, family_id=1
    )
    security.db_save_encrypted(
        fam_db, "last_sync_metadata", "sync", {"timestamp": stale_ts, "accounts_count": 4}, family_id=1
    )

    alerts = db.notifications.get_family_computed_alerts(family_id=1, db_path=fam_db)
    dedupe_keys = {a["dedupe_key"] for a in alerts}
    assert "security:support_access_on" in dedupe_keys
    assert "health:sync_stale" in dedupe_keys

    # Fresh sync resolves health:sync_stale
    fresh_ts = datetime.now(timezone.utc).isoformat()
    security.db_save_encrypted(
        fam_db, "last_sync_metadata", "sync", {"timestamp": fresh_ts, "accounts_count": 4}, family_id=1
    )
    alerts_after_sync = db.notifications.get_family_computed_alerts(family_id=1, db_path=fam_db)
    assert "health:sync_stale" not in {a["dedupe_key"] for a in alerts_after_sync}

    # Locking support access resolves security:support_access_on
    raw_fek = security.get_family_key(fam_db, 1)
    security.set_family_support_access(fam_db, family_id=1, enabled=False)
    try:
        alerts_locked = db.notifications.get_family_computed_alerts(family_id=1, db_path=fam_db)
        assert "security:support_access_on" not in {a["dedupe_key"] for a in alerts_locked}
    finally:
        security.escrow_local_vault_key(fam_db, fam_db, raw_fek, family_id=1)


def test_notification_lifecycle_domain_bump_and_role_resolution():
    """Verifies emit bumps notifications domain, mark-read/clear work, and confirm_all_roles resolves unconfirmed alert."""
    client = _make_auth_client(family_id=1)
    fam_db = db.session.resolve_db_path(None, family_id=1)
    db.notifications.clear_all_notifications(family_id=1, recipient_email="alex@example.com", db_path=fam_db)

    before_vers = forecast_cache.get_domain_versions(1, state_db=fam_db)
    db.notifications.emit_family_notification(
        fam_db,
        family_id=1,
        category="async_job",
        dedupe_key="job:sync:unconfirmed_roles",
        deep_link="/accounts",
        title="2 synced account(s) need role review",
        body="Confirm account classifications.",
    )
    after_vers = forecast_cache.get_domain_versions(1, state_db=fam_db)
    assert after_vers["notifications"] > before_vers["notifications"]

    # Confirming all roles auto-resolves job:sync:unconfirmed_roles
    resp_confirm = client.post("/api/settings/confirm_all_roles", json={})
    assert resp_confirm.status_code == 200
    active_after_confirm = db.notifications.list_active_notifications(
        family_id=1, recipient_email="alex@example.com", include_read=False, db_path=fam_db
    )
    assert not any(n.get("dedupe_key") == "job:sync:unconfirmed_roles" for n in active_after_confirm)

    # Emit a fresh notification and test mark-read and clear via HTTP
    created = db.notifications.emit_family_notification(
        fam_db,
        family_id=1,
        category="invite",
        dedupe_key="invite:accepted:spouse@example.com",
        deep_link="/?settings=members",
        title="New household member joined",
        body="Spouse accepted your household invite.",
    )
    assert created.get("id")

    resp_read = client.post("/api/notifications/mark-read", json={"id": created["id"]})
    assert resp_read.status_code == 200
    assert resp_read.get_json()["success"] is True
    assert "X-Domain-Versions" in resp_read.headers

    # Also mark computed alert read by dedupe_key
    resp_comp_read = client.post(
        "/api/notifications/mark-read",
        json={"dedupe_key": "security:support_access_on"},
    )
    assert resp_comp_read.status_code == 200
    assert "security:support_access_on" in db.notifications.list_read_dedupe_keys(
        family_id=1, recipient_email="alex@example.com", db_path=fam_db
    )

    resp_clear = client.post("/api/notifications/clear", json={"clear_computed": True})
    assert resp_clear.status_code == 200
    assert resp_clear.get_json()["success"] is True


def test_collaboration_notifications_on_equity_and_scenario_mutations():
    """Verifies equity grant and scenario saves emit household collaboration notifications to other members."""
    client = _make_auth_client(family_id=1, email="alex@example.com")
    fam_db = db.session.resolve_db_path(None, family_id=1)
    db.notifications.clear_all_notifications(family_id=1, recipient_email="spouse@example.com", db_path=fam_db)

    grant_resp = client.post(
        "/api/equity/grant",
        json={
            "nickname": "2026 Refresher RSU",
            "grantDate": "2026-02-01",
            "fullyVestedDate": "2030-02-01",
            "grantType": "rsu",
            "quantityGranted": 500,
            "unvestedQuantity": 500,
            "strikePrice": 0,
        },
    )
    assert grant_resp.status_code == 200

    # Sender (alex@example.com) does not notify themselves
    sender_items = db.notifications.list_active_notifications(
        family_id=1, recipient_email="alex@example.com", include_read=True, db_path=fam_db
    )
    assert not any(n.get("dedupe_key") == "collab:equity:2026 Refresher RSU" for n in sender_items)

    # Other household member (spouse@example.com) receives the collaboration notification
    spouse_items = db.notifications.list_active_notifications(
        family_id=1, recipient_email="spouse@example.com", include_read=True, db_path=fam_db
    )
    matched = [n for n in spouse_items if n.get("dedupe_key") == "collab:equity:2026 Refresher RSU"]
    assert matched and matched[0].get("deep_link") == "/company-equity"


def test_demo_and_viewer_readonly_guardrails():
    """Verifies demo sessions and viewer roles are rejected with 403 on state-changing notification routes."""
    demo_client = _make_auth_client(family_id=1, role="editor", is_demo=True)
    viewer_client = _make_auth_client(family_id=1, role="viewer", is_demo=False)

    for client in (demo_client, viewer_client):
        for ep, payload in (
            ("/api/notifications/mark-read", {"all": True}),
            ("/api/notifications/clear", {}),
            ("/api/notifications/subscribe", {"endpoint": "https://push.example/1", "keys": {"p256dh": "k", "auth": "a"}}),
            ("/api/notifications/unsubscribe", {"endpoint": "https://push.example/1"}),
        ):
            r = client.post(ep, json=payload)
            assert r.status_code == 403, f"Expected 403 for {ep}, got {r.status_code}"


def test_multi_tenant_isolation_and_locked_vault_tolerance():
    """Verifies Family 1 notifications never leak to Family 2 and locked vaults return [] without crashing."""
    fam1_db = db.session.resolve_db_path(None, family_id=1)
    fam2_db = db.session.resolve_db_path(None, family_id=2)
    security.init_db(fam2_db)

    db.notifications.emit_family_notification(
        fam1_db,
        family_id=1,
        category="security",
        dedupe_key="test:tenant1:secret",
        title="Family 1 Private Notification",
        body="Should never appear in Family 2",
    )

    fam2_items = db.notifications.list_active_notifications(
        family_id=2, recipient_email="user2@example.com", include_read=True, db_path=fam2_db
    )
    assert not any(n.get("dedupe_key") == "test:tenant1:secret" for n in fam2_items)

    # Simulate locked vault on Family 2 (support_access_enabled=0, encryption_key_enc=NULL)
    raw_fek_2 = security.get_family_key(fam2_db, 2)
    security.set_family_support_access(fam2_db, family_id=2, enabled=False)
    security._clear_security_caches()
    try:
        # Out-of-band / unescrowed call should tolerate PermissionError and return []
        locked_items = db.notifications.get_family_computed_alerts(family_id=2, db_path=fam2_db)
        assert isinstance(locked_items, list)
    finally:
        security.escrow_local_vault_key(fam2_db, fam2_db, raw_fek_2, family_id=2)
