"""
Guardrail Tests for Multi-Tenant Architecture & De-personalization.
Enforces that:
1. A completely fresh family (with 0 seeded records) loads all endpoints with HTTP 200 without crashing.
"""

from __future__ import annotations
import glob
import os
import re
import subprocess
import sys
from pathlib import Path
import pytest
from wsgi import app
import security

UNSEEDED_EMPTY_FAMILY_ID = 88888


BASE_DIR = Path(__file__).resolve().parent.parent
ROOT = BASE_DIR


def test_empty_state_new_family():
    """
    Verifies that a brand-new tenant with 0 records in database
    can access all major endpoints without throwing 500 server errors.
    """
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "New Tenant"
            sess["family_id"] = UNSEEDED_EMPTY_FAMILY_ID
            sess["role"] = "editor"

        endpoints = [
            "/api/dashboard",
            "/api/education",
            "/api/gifting",
            "/api/compensation",
            "/api/scenarios",
            "/api/family",
        ]

        for ep in endpoints:
            res = client.get(ep)
            assert res.status_code == 200, f"Endpoint {ep} failed with status {res.status_code}: {res.data.decode('utf-8')[:200]}"
            data = res.get_json()
            assert data is not None, f"Endpoint {ep} returned non-JSON payload"
            assert data.get("success") is True, f"Endpoint {ep} reported success: False"
            if ep == "/api/scenarios":
                sc_data = data.get("data", {})
                assert sc_data.get("annual_living_spend", 0.0) == 0.0, "Empty household must not have a hardcoded annual_living_spend"
                assert sc_data.get("annual_savings", 0.0) == 0.0, "Empty household must not have hardcoded annual_savings"
                for pt in sc_data.get("active_cash_flow_series", []):
                    for key in ("living_core", "travel_gogo", "gifting", "household_salary", "gross_compensation"):
                        assert pt.get(key, 0.0) == 0.0, f"Empty household year {pt.get('year')} leaked non-zero {key}={pt.get(key)}"

        fragments = [
            "overview",
            "equity",
            "college",
            "gifting",
            "arbitrage",
            "compensation",
            "holdings",
            "scenarios",
            "estate",
            "philanthropy",
            "accounts",
            "settings",
        ]
        for frag in fragments:
            res_frag = client.get(f"/fragments/{frag}")
            assert res_frag.status_code == 200, f"Fragment /fragments/{frag} failed with status {res_frag.status_code}"


def test_public_universe_family_id_hard_locked():
    """
    Verifies that in the 'public' (production) universe, an admin cannot switch
    family_id to another tenant's family_id unless that tenant has explicitly enabled
    support access (`support_access_enabled = True`). Locked households reject with 403
    and leave the session strictly bound to user_family_id.
    """
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "Family 1 Admin"
            sess["user_email"] = "admin@example.com"
            sess["is_site_admin"] = True
            sess["user_family_id"] = 1
            sess["family_id"] = 1
            sess["role"] = "admin"
            sess["universe"] = "public"

        # Attempt to tamper and switch family_id to 999 (locked/non-existent) in public universe
        res = client.post("/api/admin/switch_universe", json={
            "universe": "public",
            "family_id": 999
        })
        assert res.status_code == 403
        data = res.get_json()
        assert data["success"] is False

        # Check status endpoint: session remains strictly locked to user_family_id (1)
        res_status = client.get("/api/auth/status")
        assert res_status.status_code == 200
        assert res_status.get_json()["family_id"] == 1


def test_per_family_envelope_encryption(tmp_path):
    """
    Verifies that distinct families receive distinct encryption keys and cannot
    cross-decrypt each other's encrypted records.
    """
    test_db = tmp_path / "test_envelope.db"
    key1 = security.get_family_key(test_db, family_id=1)
    key2 = security.get_family_key(test_db, family_id=2)

    assert key1 != key2, "Family 1 and Family 2 must have distinct encryption keys!"

    # Save data for Family 2
    secret_payload = {"salary": 500000, "note": "Classified"}
    security.db_save_encrypted(test_db, "comp_secret", "test", secret_payload, family_id=2)

    # Family 2 can load it
    loaded_fam2 = security.db_load_encrypted(test_db, "comp_secret", family_id=2)
    assert loaded_fam2 == secret_payload

    # Family 1 cannot load Family 2's data
    loaded_fam1 = security.db_load_encrypted(test_db, "comp_secret", family_id=1)
    assert loaded_fam1 is None, "Family 1 must not be able to load Family 2's encrypted payload!"


def test_no_fragment_loader_or_dual_pipeline_guards():
    """
    Structural guardrail: Enforces zero FragmentLoader / fragment_loader.js references
    across static/js/**/*.js and templates/**/*.html, and zero guarded dual-pipeline
    fallback branches (e.g., if (window.Idiomorph) / if (window.htmx) / else if (window.FragmentLoader)).
    """
    js_files = [Path(p) for p in glob.glob(str(BASE_DIR / "static" / "js" / "**" / "*.js"), recursive=True)]
    html_files = [Path(p) for p in glob.glob(str(BASE_DIR / "templates" / "**" / "*.html"), recursive=True)]

    violations = []
    for path in js_files + html_files:
        content = path.read_text(encoding="utf-8")
        if re.search(r"\bFragmentLoader\b|fragment_loader\.js", content):
            violations.append(f"{path.relative_to(BASE_DIR)} references deprecated FragmentLoader/fragment_loader.js")

    dual_pipeline_pattern = re.compile(
        r"if\s*\(\s*window\.(?:Idiomorph|htmx|FragmentLoader)\b|"
        r"else\s+if\s*\(\s*window\.(?:Idiomorph|htmx|FragmentLoader)\b|"
        r"typeof\s+(?:Idiomorph|htmx|FragmentLoader)\s*!==\s*['\"]undefined['\"]"
    )
    for path in js_files:
        content = path.read_text(encoding="utf-8")
        for match in dual_pipeline_pattern.finditer(content):
            violations.append(
                f"{path.relative_to(BASE_DIR)} contains guarded dual-pipeline check: '{match.group(0)}'"
            )

    assert not violations, "Guarded dual-pipeline / FragmentLoader violations found:\n" + "\n".join(violations)


def test_no_duplicate_local_utils():
    """
    Structural guardrail: Enforces that static/js/utils.js is deleted and that
    fmtCurrency, fmtShortCurrency, fmtPct, and escapeHtml are not locally re-implemented
    with duplicate formatting logic in static/js/**/*.js.
    """
    local_utils = BASE_DIR / "static" / "js" / "utils.js"
    assert not local_utils.exists(), "static/js/utils.js must not exist; use /common/utils.js single source of truth."

    js_files = [Path(p) for p in glob.glob(str(BASE_DIR / "static" / "js" / "**" / "*.js"), recursive=True)]
    redef_pattern = re.compile(
        r"function\s+(?:fmtCurrency|fmtShortCurrency|fmtPct|escapeHtml)\s*\(|"
        r"(?:const|let|var)\s+(?:fmtCurrency|fmtShortCurrency|fmtPct|escapeHtml)\s*=\s*(?:function|\([^)]*\)\s*=>\s*\{)"
    )
    violations = []
    for path in js_files:
        content = path.read_text(encoding="utf-8")
        for match in redef_pattern.finditer(content):
            violations.append(
                f"{path.relative_to(BASE_DIR)} locally redefines shared utility: '{match.group(0)}'"
            )

    assert not violations, "Duplicate local utility definitions found:\n" + "\n".join(violations)


def test_no_raw_sql_outside_db_layer():
    """Enforces zero raw SQL execution or SQL statement strings outside db/ layer."""
    py_files = [p for pkg in ("routes", "services", "ssr", "forecast", "monarch", "equity", "security") for p in BASE_DIR.glob(f"{pkg}/**/*.py")] + list(BASE_DIR.glob("*.py"))
    exempt_files = {"deploy.py"}  # release tooling, outside the app layers; scripts/ and db/ are exempt as directories
    exempt_dirs = {"db", "tests", "scripts", "migrations", "alembic", "dist", "build"}
    sql_re = re.compile(
        r"""(?ix)\b(?:import\s+sqlite3|from\s+sqlite3\b|get_db_connection|sqlite3\.connect)\b|\b(?:cursor|cur|conn|gconn|s_conn|d_conn|fconn|u_cur|c_cur|hp_cur|db)\.execute\s*\(|["']\s*(?:SELECT\s+.+\s+FROM|INSERT\s+(?:OR\s+REPLACE\s+)?INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b"""
    )
    violations = []
    for path in sorted(set(py_files)):
        if path.name in exempt_files or path.name.startswith("security_") or path.name.endswith("_db.py") or any(part in exempt_dirs for part in path.parts):
            continue
        for idx, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if not line.strip().startswith("#") and sql_re.search(line):
                violations.append(f"{path.relative_to(BASE_DIR)}:{idx} raw SQL outside db/: '{line.strip()[:60]}'")
    assert not violations, "Raw SQL found outside db/ layer:\n" + "\n".join(violations)


test_no_raw_sql_in_routes = test_no_raw_sql_outside_db_layer


def test_theme_css_inherits_common_tokens():
    """
    Structural guardrail: Enforces that static/css/theme.css imports /common/theme.css
    and does not redeclare foundational design tokens owned by hvl_common.
    """
    theme_css = BASE_DIR / "static" / "css" / "theme.css"
    content = theme_css.read_text(encoding="utf-8")
    assert '@import "/common/theme.css";' in content[:200], (
        "static/css/theme.css must begin with @import \"/common/theme.css\";"
    )
    redeclared = re.findall(
        r"^\s*(--(?:font-sans|text-main|text-body|text-dim|bg-primary|text-primary))\s*:",
        content,
        flags=re.MULTILINE,
    )
    assert not redeclared, (
        f"static/css/theme.css redeclares foundational tokens owned by /common/theme.css: {redeclared}"
    )


def test_ssr_wealth_decomposition_and_no_raw_sql_in_ssr():
    """
    Structural guardrail: Enforces that ssr/wealth.py is decomposed into
    ssr/equity.py, ssr/holdings.py, and ssr/accounts.py, ssr/wealth.py is a
    re-export facade, and zero raw SQL exists in ssr/*.py.
    """
    for mod_name in ("equity.py", "holdings.py", "accounts.py"):
        mod_path = BASE_DIR / "ssr" / mod_name
        assert mod_path.exists(), f"Expected decomposed module ssr/{mod_name} to exist"

    wealth_facade = BASE_DIR / "ssr" / "wealth.py"
    assert wealth_facade.exists(), "Expected ssr/wealth.py facade to exist"

    ssr_files = [Path(p) for p in glob.glob(str(BASE_DIR / "ssr" / "*.py"))]
    sql_pattern = re.compile(r"\b(?:conn|cursor)\.execute\s*\(", re.IGNORECASE)
    violations = []
    for path in ssr_files:
        content = path.read_text(encoding="utf-8")
        for match in sql_pattern.finditer(content):
            violations.append(f"{path.relative_to(BASE_DIR)} contains raw SQL in SSR layer: '{match.group(0)}'")
    assert not violations, "Raw SQL found in ssr/*.py:\n" + "\n".join(violations)


def test_no_duplicate_common_assets_and_ssr_formatting_delegation():
    """
    Structural guardrail: Enforces that assets promoted to /common/
    (theme_toggle.js, modal-dialog.js, modal-dialog.css, marked.min.js, and local brand logos)
    do not exist in family-office, and ssr/formatting.py delegates to hvl_common.ui.
    """
    promoted_files = [
        "static/js/theme_toggle.js",
        "static/js/modal-dialog.js",
        "static/css/modal-dialog.css",
        "static/js/marked.min.js",
        "favicon.ico",
        "static/favicon.ico",
        "static/fo-logo-mark.svg",
        "static/hvl-logo-mark.svg",
        "static/img/fo-logo-mark.svg",
        "static/img/fo-logo-120.png",
        "static/img/fo-logo-512.png",
        "static/img/hvl-logo-120.png",
        "static/img/hvl-logo-512.png",
        "static/img/hvl-logo-lockup.svg",
        "static/img/hvl-logo-mark.svg",
    ]
    for rel in promoted_files:
        assert not (BASE_DIR / rel).exists(), f"{rel} must not exist locally; use /common/ single source of truth."

    import hvl_common.ui as common_ui
    import ssr.formatting as ssr_fmt

    for fn_name in ("fmt_currency", "fmt_short_currency", "fmt_pct"):
        assert getattr(ssr_fmt, fn_name, None) is getattr(common_ui, fn_name), (
            f"ssr.formatting.{fn_name} must delegate directly to hvl_common.ui.{fn_name}"
        )

    formatting_py = (BASE_DIR / "ssr" / "formatting.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*def\s+fmt_(?:currency|short_currency|pct)\s*\(", formatting_py, flags=re.MULTILINE), (
        "ssr/formatting.py must not locally redefine fmt_currency, fmt_short_currency, or fmt_pct"
    )


def test_state_version_etag_304_and_cache_control_headers():
    """
    Verifies that HTMX fragments and read-only dashboard APIs attach weak ETags
    bound to `forecast_cache.get_state_version(family_id)` + `Cache-Control: private, no-cache`,
    short-circuit with `304 Not Modified` on matching `If-None-Match`, and immediately
    invalidate (`200 OK` with new ETag) when household state is mutated.
    """
    from forecast import cache as forecast_cache
    from wsgi import app

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["is_demo"] = False
        sess["universe"] = "test"
        sess["user_email"] = "etag_tester@example.com"
        sess["family_id"] = 1
        sess["user_family_id"] = 1
        sess["role"] = "editor"

    for path in ("/fragments/overview", "/api/dashboard", "/api/holdings/policy", "/api/networth/history", "/fragments/scenarios"):
        r1 = client.get(path)
        assert r1.status_code == 200
        etag1 = r1.headers.get("ETag")
        assert etag1 and etag1.startswith('W/"'), f"Missing weak ETag on {path}: {etag1}"
        assert r1.headers.get("Cache-Control") == "private, no-cache"

        # Repeat request with If-None-Match returns 304 Not Modified with empty body
        r2 = client.get(path, headers={"If-None-Match": etag1})
        assert r2.status_code == 304
        assert len(r2.get_data()) == 0

    # Mutating a leaf domain (philanthropy) invalidates /fragments/philanthropy (200 OK) while keeping /fragments/overview warm (304 Not Modified)
    old_overview_etag = client.get("/fragments/overview").headers.get("ETag")
    old_philanthropy_etag = client.get("/fragments/philanthropy").headers.get("ETag")
    mut_resp = client.post("/api/philanthropy/budget", json={"year": "2026", "budget": 50000})
    assert mut_resp.status_code == 200
    r_overview_unrelated = client.get("/fragments/overview", headers={"If-None-Match": old_overview_etag})
    assert r_overview_unrelated.status_code == 304
    r_phil_after = client.get("/fragments/philanthropy", headers={"If-None-Match": old_philanthropy_etag})
    assert r_phil_after.status_code == 200
    assert r_phil_after.headers.get("ETag") != old_philanthropy_etag
    assert len(r_phil_after.get_data()) > 100

    # Mutating a domain that overview depends on (scenarios) invalidates /fragments/overview (200 OK with fresh ETag)
    scen_resp = client.post("/api/scenarios/active", json={"scenario_id": "base"})
    assert scen_resp.status_code == 200
    r_after = client.get("/fragments/overview", headers={"If-None-Match": old_overview_etag})
    assert r_after.status_code == 200
    assert r_after.headers.get("ETag") != old_overview_etag
    assert len(r_after.get_data()) > 100


# In every checkout (main, release worktree, public export, server) hvl_common comes from the sibling `../common`
# through the normal install (`-e ../common` in requirements.txt): no sys.path hacks, nothing copied into the app.
def test_packaging_spec_bundles_the_sibling_common_and_auth_module_has_no_path_hacks():
    spec = (ROOT / "packaging" / "family_office.spec").read_text()
    auth = (ROOT / "services" / "auth_google.py").read_text()
    assert 'ROOT_DIR.parent / "common"' in spec and "vendor" not in spec
    assert "sys.path" not in auth
    assert "-e ../common" in (ROOT / "requirements.txt").read_text().splitlines()


def test_auth_google_resolves_hvl_common_from_the_sibling_common():
    """Tests (pyproject `pythonpath`) import the common/ of this checkout, never another checkout's editable install."""
    import hvl_common
    import services.auth_google  # noqa: F401

    assert Path(hvl_common.__file__).resolve().is_relative_to((ROOT.parent / "common").resolve())
