"""
Reactive Domain-Version Signals & Declarative Section Invalidation Tests.
Verifies:
1. Granular hierarchical domain-version tracking in forecast_cache and forecast_cache_helpers.
2. Automatic ORM and encrypted-store domain resolution without invalidating unrelated domains.
3. X-Domain-Versions HTTP response header emitted on /api/* and /fragments/* responses.
4. Declarative data-depends attributes across all 11 section placeholders in index.html and component templates.
5. Structural guardrail enforcing complete deletion of legacy imperative invalidation functions
   and switch-based hydration dispatchers across static/js/**/*.js.
"""

from __future__ import annotations
import glob
import json
import re
from pathlib import Path
from app import app
import forecast_cache
from forecast_cache_helpers import (
    CANONICAL_DOMAINS,
    resolve_domains_for_tables,
    resolve_domains_for_encrypted_key,
)
import security

BASE_DIR = Path(__file__).resolve().parent.parent


def test_canonical_domains_and_table_resolution():
    """Verifies that table names and encrypted store keys resolve to narrow hierarchical domains."""
    acc_domains = resolve_domains_for_tables(["monarch_accounts", "monarch_holdings"])
    assert "accounts" in acc_domains
    assert "balance_sheet" in acc_domains
    assert "holdings" in acc_domains
    assert "gifting" not in acc_domains
    assert "philanthropy" not in acc_domains

    gift_domains = resolve_domains_for_tables(["gifts", "gift_recipients"])
    assert gift_domains == {"gifting", "estate"}

    phil_domains = resolve_domains_for_tables(["philanthropy_donations"])
    assert phil_domains == {"philanthropy"}

    sf_domains = resolve_domains_for_encrypted_key("simplefin_access_url", "simplefin")
    assert "accounts" in sf_domains
    assert "balance_sheet" in sf_domains
    assert "gifting" not in sf_domains


def test_selective_domain_version_bump_preserves_unrelated_domains():
    """
    Verifies that bumping a specific domain (e.g. 'gifting') increments only that domain's
    version counter while leaving unrelated domains ('accounts', 'equity', 'philanthropy') untouched.
    """
    forecast_cache.clear_all_caches()
    fam_id = 7101

    v_init = forecast_cache.get_domain_versions(fam_id)
    assert set(v_init.keys()) == set(CANONICAL_DOMAINS)
    assert all(v == 1 for v in v_init.values())

    v_after_gift = forecast_cache.bump_domain_versions(fam_id, ["gifting"])
    assert v_after_gift["gifting"] == 2
    assert v_after_gift["accounts"] == 1
    assert v_after_gift["balance_sheet"] == 1
    assert v_after_gift["philanthropy"] == 1
    assert v_after_gift["equity"] == 1

    # Updating active scenario bumps only scenarios
    forecast_cache.update_active_scenario(fam_id, "scen_custom")
    v_after_scen = forecast_cache.get_domain_versions(fam_id)
    assert v_after_scen["scenarios"] == 2
    assert v_after_scen["gifting"] == 2
    assert v_after_scen["accounts"] == 1


def test_x_domain_versions_header_and_selective_api_mutation():
    """
    Verifies that /api/* and /fragments/* responses emit the X-Domain-Versions JSON header,
    and that mutating philanthropy budget bumps 'philanthropy' without
    bumping unrelated domains like 'gifting' or 'accounts'.
    """
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["is_demo"] = False
        sess["universe"] = "test"
        sess["user_email"] = "signals_tester@example.com"
        sess["family_id"] = 1
        sess["user_family_id"] = 1
        sess["role"] = "editor"

    r_before = client.get("/fragments/overview")
    assert r_before.status_code == 200
    raw_hdr_before = r_before.headers.get("X-Domain-Versions")
    assert raw_hdr_before, "Expected X-Domain-Versions header on /fragments/overview"
    versions_before = json.loads(raw_hdr_before)
    assert set(CANONICAL_DOMAINS).issubset(set(versions_before.keys()))

    r_mut = client.post("/api/philanthropy/budget", json={"year": "2026", "budget": 65000})
    assert r_mut.status_code == 200
    raw_hdr_after = r_mut.headers.get("X-Domain-Versions")
    assert raw_hdr_after, "Expected X-Domain-Versions header on /api/philanthropy/budget"
    versions_after = json.loads(raw_hdr_after)

    assert versions_after["philanthropy"] > versions_before["philanthropy"]
    assert versions_after["gifting"] == versions_before["gifting"]
    assert versions_after["accounts"] == versions_before["accounts"]
    assert versions_after["college"] == versions_before["college"]


def test_encrypted_store_mutation_bumps_mapped_domains(tmp_path):
    """
    Verifies that saving an encrypted SimpleFIN credential via security.db_save_encrypted
    selectively bumps accounts/balance_sheet/onboarding.checklist domains without bumping gifting or college.
    """
    forecast_cache.clear_all_caches()
    test_db = tmp_path / "test_signals_enc.db"
    fam_id = 42

    before = forecast_cache.get_domain_versions(fam_id)
    security.db_save_encrypted(
        test_db,
        "simplefin_access_url",
        "simplefin",
        {"access_url": "https://bridge.simplefin.org/simplefin/demo"},
        family_id=fam_id,
    )
    after = forecast_cache.get_domain_versions(fam_id)

    assert after["accounts"] > before["accounts"]
    assert after["balance_sheet"] > before["balance_sheet"]
    assert after["onboarding.checklist"] > before["onboarding.checklist"]
    assert after["gifting"] == before["gifting"]
    assert after["college"] == before["college"]


def test_templates_declare_data_depends_and_no_legacy_invalidation_functions():
    """
    Structural guardrail:
    1. Every .page-section in templates/index.html and templates/components/*.html
       declares a non-empty data-depends attribute with valid canonical domains.
    2. Zero legacy imperative invalidation symbols (invalidateAndRefreshPortalViews,
       resetOverviewCaches, invalidateScenariosCache, refreshAccountsAndDashboardAfterSync,
       _refreshAfterAccountMutation, hydratedSections) or switch(sectionId) dispatchers
       exist anywhere in static/js/**/*.js.
    """
    index_html = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    assert "window.__DOMAIN_VERSIONS__" in index_html, "templates/index.html must bootstrap window.__DOMAIN_VERSIONS__"

    section_ids = [
        "section-overview",
        "section-equity",
        "section-scenarios",
        "section-holdings",
        "section-arbitrage",
        "section-compensation",
        "section-philanthropy",
        "section-gifting",
        "section-estate",
        "section-college",
        "section-accounts",
    ]
    for sec_id in section_ids:
        pattern = re.compile(rf'<section[^>]*id="{re.escape(sec_id)}"[^>]*data-depends="([^"]+)"')
        match = pattern.search(index_html)
        assert match, f"templates/index.html #{sec_id} is missing data-depends attribute"
        declared = [d.strip() for d in match.group(1).split(",") if d.strip()]
        assert declared, f"templates/index.html #{sec_id} has empty data-depends"
        for dom in declared:
            assert dom in CANONICAL_DOMAINS, f"Unknown domain '{dom}' in #{sec_id} data-depends"

    component_files = [
        "overview.html",
        "equity.html",
        "scenarios.html",
        "holdings_breakdown.html",
        "arbitrage.html",
        "compensation.html",
        "philanthropy.html",
        "gifting.html",
        "estate.html",
        "college.html",
        "accounts.html",
    ]
    for comp_name in component_files:
        comp_html = (BASE_DIR / "templates" / "components" / comp_name).read_text(encoding="utf-8")
        match = re.search(r'<section[^>]*id="section-[^"]+"[^>]*data-depends="([^"]+)"', comp_html)
        assert match, f"templates/components/{comp_name} <section> is missing data-depends attribute"
        for dom in [d.strip() for d in match.group(1).split(",") if d.strip()]:
            assert dom in CANONICAL_DOMAINS, f"Unknown domain '{dom}' in {comp_name} data-depends"

    retired_symbols_re = re.compile(
        r"\b(?:invalidateAndRefreshPortalViews|resetOverviewCaches|invalidateScenariosCache|"
        r"refreshAccountsAndDashboardAfterSync|_refreshAfterAccountMutation|hydratedSections|"
        r"DASHBOARD_DEPENDENT_SECTIONS)\b|"
        r"switch\s*\(\s*sectionId\s*\)"
    )
    js_files = [Path(p) for p in glob.glob(str(BASE_DIR / "static" / "js" / "**" / "*.js"), recursive=True)]
    violations = []
    for path in js_files:
        content = path.read_text(encoding="utf-8")
        for match in retired_symbols_re.finditer(content):
            violations.append(f"{path.relative_to(BASE_DIR)} contains retired imperative symbol: '{match.group(0)}'")

    assert not violations, "Retired imperative invalidation symbols found in static/js:\n" + "\n".join(violations)
