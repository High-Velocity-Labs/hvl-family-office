"""
Security and Access Control Test Suite
Validates that:
1. Unauthorized users cannot view any data or bypass authentication.
2. Unauthenticated /api/auth/status returns null role and false.
3. OWASP security headers (CSP, X-Frame-Options, X-Content-Type-Options) are emitted.
4. Multi-tenant IDOR scoping protects records between families.
"""

from __future__ import annotations
import os
import io
import pytest
from app import app
import security
from routes.helpers import DB_PATH


def test_unauthenticated_api_endpoints_denied():
    """Confirms that unauthenticated visitors cannot access sensitive API endpoints."""
    client = app.test_client()
    endpoints = [
        "/api/dashboard",
        "/api/compensation",
        "/api/gifting",
        "/api/education",
        "/api/scenarios",
        "/api/holdings/policy",
        "/api/estate",
        "/api/philanthropy",
        "/api/family",
    ]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 401, f"Endpoint {ep} allowed unauthenticated access!"
        data = resp.get_json()
        assert data.get("error") == "Unauthorized"
        assert data.get("login_required") is True


def test_auth_status_unauthenticated():
    """Confirms /api/auth/status leaks no role or user info when unauthenticated."""
    client = app.test_client()
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["authenticated"] is False
    assert data["user"] is None
    assert data["role"] is None
    assert data["family_id"] is None


def test_owasp_security_headers_emitted():
    """Confirms all OWASP defensive security headers are emitted on HTTP responses."""
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200

    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in resp.headers


def test_multi_tenant_idor_member_deletion():
    """Confirms Family A cannot delete or modify family members belonging to Family B."""
    import config

    security.init_db(config.get_global_db_path())
    security.init_db(config.get_family_db_path(2))
    # Create test member in Family 2
    user_b_id = security.add_family_member(
        db_path=DB_PATH,
        family_id=2,
        name="Family B Member",
        email="b_member@example.com",
        relationship="child",
        role="viewer"
    )

    client = app.test_client()
    # Log in as Family 1 Editor
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user"] = "Family A Editor"
        sess["role"] = "editor"
        sess["family_id"] = 1

    # Attempt to delete Family B's member
    resp_del = client.delete(f"/api/family/members/{user_b_id}")
    assert resp_del.status_code in (200, 400, 404)

    # Verify user_b still exists in Family 2
    members_fam2 = security.get_family_members(DB_PATH, family_id=2)
    member_ids_fam2 = [m["user_id"] for m in members_fam2]
    assert user_b_id in member_ids_fam2, "IDOR Vulnerability: Family 1 was able to delete Family 2's member!"

    # Clean up Family B member using Family 2 scope
    security.delete_family_member(DB_PATH, family_id=2, user_id=user_b_id)
