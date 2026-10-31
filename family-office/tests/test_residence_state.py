"""
A new household's state of residence comes from the visitor's location, or stays unset so onboarding asks;
an unset state is taxed as "no state tax" everywhere and never as a particular state.
"""

from __future__ import annotations

import pytest

import db
import security
from services import residence_state
from services.estate_engine import calculate_state_estate_tax
from services.tax_calculations import calculate_state_tax_for_state, compare_state_tax_arbitrage


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"CF-IPCountry": "US", "CF-Region-Code": "TX"}, "TX"),
        ({"CF-IPCountry": "us", "CF-Region-Code": "ny"}, "NY"),
        ({"CF-IPCountry": "US", "CF-Region-Code": "ND"}, ""),  # a state the tax engine does not model
        ({"CF-IPCountry": "CA", "CF-Region-Code": "WA"}, ""),  # outside the US, whatever the region code says
        ({"CF-IPCountry": "US"}, ""),
        ({}, ""),
    ],
)
def test_visitor_state_comes_only_from_a_us_location_in_a_modeled_state(headers, expected):
    assert residence_state.from_request_headers(headers) == expected


def test_oauth_signup_reads_the_visitor_state_from_cloudflare_headers():
    from app import app
    from services.auth_google import _visitor_state

    with app.test_request_context(headers={"CF-IPCountry": "US", "CF-Region-Code": "CO"}):
        assert _visitor_state() == "CO"
    with app.test_request_context():
        assert _visitor_state() == residence_state.UNSET


def _profile_and_settings(main_db, fid):
    profile = db.families.get_household_profile(family_id=fid, db_path=main_db)
    family = security.get_family(main_db, family_id=fid)
    return profile["state"], family["settings"]["primary_state"]


@pytest.mark.parametrize("state", ["TX", ""])
def test_self_serve_household_starts_in_the_visitor_state_or_unset(tmp_path, monkeypatch, state):
    from db.household_activity import provision_self_serve_household

    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "data"))
    main_db = tmp_path / "selfserve.db"
    security.init_db(main_db)
    created = provision_self_serve_household(main_db, f"new.{state or 'none'}@example.com", "New", state=state)
    assert _profile_and_settings(main_db, created["family_id"]) == (state, state)


def test_invited_new_household_starts_in_the_visitor_state(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILY_OFFICE_DATA_DIR", str(tmp_path / "invite_data"))
    main_db = tmp_path / "invites.db"
    security._clear_security_caches()
    security.init_db(main_db)
    inv = security.create_invite_token(
        main_db, family_id=1, created_by_email="a@example.com", invite_type="new_household",
        target_role="editor", max_uses=1, expires_days=7,
    )
    res = security.redeem_invite_token(main_db, inv["code"], "invitee@example.com", "Invitee", home_state="NY")
    assert res and res["is_new_household"]
    assert _profile_and_settings(main_db, res["family_id"]) == ("NY", "NY")


def test_unset_state_applies_no_state_tax_and_says_so():
    income = calculate_state_tax_for_state("", ordinary_income=500_000.0, capital_gains=2_000_000.0)
    assert income["total_state_tax"] == 0.0 and income["state_name"] == "State not set"
    estate = calculate_state_estate_tax(gross_estate=20_000_000.0, state="")
    assert estate["tax_liability"] == 0.0 and estate["has_estate_tax"] is False and estate["state_name"] == "State not set"
    with pytest.raises(ValueError, match="home state is required"):
        compare_state_tax_arbitrage(ordinary_spread=0.0, home_state="")


def test_settings_refuse_an_unsupported_state():
    from tests.test_api_endpoints import get_authenticated_client

    client = get_authenticated_client()
    before = client.get("/api/settings/assumptions").get_json()["assumptions"]["state"]
    resp = client.post("/api/settings/assumptions", json={"state": "ND"})
    assert resp.status_code == 400 and "state" in resp.get_json()["error"].lower()
    assert client.get("/api/settings/assumptions").get_json()["assumptions"]["state"] == before
