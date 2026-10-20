#!/usr/bin/env python3
"""
Comprehensive Security, Privacy & Multi-Tenant Audit Script.
Performs adversarial, first-principles verification:
1. Raw Database Dump Inspection (Disk level: zero plaintext PII).
2. Codebase Backdoor & Bypass Scan (No master keys, bypass tokens, or mock auth).
3. UI Template Authenticity & Input Scan (No unverified PIN/secret inputs, fake buttons).
4. Environment & Secret Hygiene (No PII in .env, strict .gitignore coverage).
5. Multi-Tenant Scoping & Zero-State Isolation.
"""

from __future__ import annotations
import glob
import os
import re
import sys
import sqlite3
from pathlib import Path
from typing import Any, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
if (BASE_DIR / "vendor").exists() and str(BASE_DIR / "vendor") not in sys.path:
    sys.path.append(str(BASE_DIR / "vendor"))

from hvl_common.db import get_db_connection
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DENYLIST_PATH = BASE_DIR / "data" / "denylist.txt"


class AuditReporter:
    def __init__(self) -> None:
        self.failures: List[str] = []
        self.warnings: List[str] = []

    def record_failure(self, category: str, msg: str) -> None:
        self.failures.append(f"[{category.upper()} FAIL] {msg}")

    def record_warning(self, category: str, msg: str) -> None:
        self.warnings.append(f"[{category.upper()} WARN] {msg}")


DEFAULT_REPORTER = AuditReporter()
failures = DEFAULT_REPORTER.failures
warnings = DEFAULT_REPORTER.warnings
record_failure = DEFAULT_REPORTER.record_failure
record_warning = DEFAULT_REPORTER.record_warning

from scripts.audit_db_and_backdoors import (
    audit_database as _audit_database,
    audit_codebase_backdoors as _audit_codebase_backdoors,
    audit_environment_and_gitignore as _audit_environment_and_gitignore,
)
from scripts.audit_templates_and_assets import (
    audit_templates as _audit_templates,
    audit_client_side_assets as _audit_client_side_assets,
    audit_data_purity_and_hardcoded_financials as _audit_data_purity_and_hardcoded_financials,
)


def audit_database(reporter: Optional[AuditReporter] = None) -> None:
    _audit_database(reporter or DEFAULT_REPORTER)


def audit_codebase_backdoors(reporter: Optional[AuditReporter] = None) -> None:
    _audit_codebase_backdoors(reporter or DEFAULT_REPORTER)


def audit_templates(reporter: Optional[AuditReporter] = None) -> None:
    _audit_templates(reporter or DEFAULT_REPORTER)


def audit_environment_and_gitignore(reporter: Optional[AuditReporter] = None) -> None:
    _audit_environment_and_gitignore(reporter or DEFAULT_REPORTER)


def audit_client_side_assets(reporter: Optional[AuditReporter] = None) -> None:
    _audit_client_side_assets(reporter or DEFAULT_REPORTER)


def audit_data_purity_and_hardcoded_financials(reporter: Optional[AuditReporter] = None) -> None:
    _audit_data_purity_and_hardcoded_financials(reporter or DEFAULT_REPORTER)


# =========================================================================
# 7. DYNAMIC ADVERSARIAL ROUTE FUZZING & MULTI-TENANT ISOLATION
# =========================================================================
def audit_dynamic_route_fuzzing(reporter: Optional[AuditReporter] = None) -> None:
    rep = reporter or DEFAULT_REPORTER
    print("--> 7. Running Dynamic Adversarial Route Fuzzing & Header Verification...")
    try:
        from app import app
        app.config["TESTING"] = True

        with app.test_client() as client:
            res = client.get("/")
            if res.headers.get("X-Frame-Options") != "DENY":
                rep.record_failure("headers", f"Missing or invalid X-Frame-Options: {res.headers.get('X-Frame-Options')}")
            if res.headers.get("X-Content-Type-Options") != "nosniff":
                rep.record_failure("headers", f"Missing or invalid X-Content-Type-Options: {res.headers.get('X-Content-Type-Options')}")
            if "Content-Security-Policy" not in res.headers:
                rep.record_failure("headers", "Missing Content-Security-Policy header on application responses")

            exempt_from_write_lock = {
                "auth.auth_logout",
                "auth_google.logout",
                "auth.auth_passkey",
                "auth.api_demo_switch_family",
                "auth_google.google_callback",
                "auth_google.verify_credential_post",
                "tax.api_arbitrage",
                "tax.api_withholding",
                "dashboard.api_scenario",
                "dashboard.api_sync",
                "dashboard.api_telemetry_action_view",
                "ai_advisor.api_ai_advisor_chat",
            }

            def _reset_demo_session():
                with client.session_transaction() as sess:
                    sess.clear()
                    sess["authenticated"] = True
                    sess["user"] = "Demo Guest"
                    sess["role"] = "viewer"
                    sess["user_role"] = "viewer"
                    sess["is_demo"] = True
                    sess["universe"] = "demo"
                    sess["family_id"] = 1

            for rule in app.url_map.iter_rules():
                if rule.endpoint in exempt_from_write_lock or rule.endpoint == "static":
                    continue
                methods = set(rule.methods or [])
                write_methods = methods.intersection({"POST", "PUT", "DELETE"})
                if not write_methods:
                    continue

                test_url = rule.rule
                test_url = re.sub(r"<int:[^>]+>", "1", test_url)
                test_url = re.sub(r"<[^>]+>", "1", test_url)

                for method in write_methods:
                    _reset_demo_session()
                    req_fn = getattr(client, method.lower())
                    try:
                        resp = req_fn(test_url, json={"name": "test", "amount": 100})
                    except Exception as e:
                        rep.record_failure("fuzzing", f"Demo write to {method} {test_url} raised exception: {e}")
                        continue

                    if resp.status_code != 403:
                        rep.record_failure(
                            "fuzzing",
                            f"Demo Guest write exploit: {method} {test_url} ({rule.endpoint}) returned HTTP {resp.status_code} instead of 403 Forbidden"
                        )

            public_endpoints = {
                "auth.login_view",
                "login_view",
                "auth.features_view",
                "features_view",
                "auth.help_view",
                "help_view",
                "auth.helm_comparison_view",
                "helm_comparison_view",
                "auth.projectionlab_comparison_view",
                "projectionlab_comparison_view",
                "auth.scenario_playbooks_view",
                "scenario_playbooks_view",
                "auth.privacy_view",
                "privacy_view",
                "auth.terms_view",
                "terms_view",
                "auth.demo_view",
                "auth.exit_demo",
                "auth.api_demo_families",
                "auth.auth_status",
                "auth_google.auth_status",
                "auth.auth_passkey",
                "auth_google.google_login",
                "auth_google.google_auth_config",
                "auth_google.google_callback",
                "auth_google.verify_credential_post",
                "auth.whats_new_view",
                "dashboard.favicon_view",
                "dashboard.hvl_logo_mark_view",
                "dashboard.fo_logo_mark_view",
                "health_check",
                "sandbox.sandbox_launch_view",
                "sandbox.api_sandbox_status",
                "sandbox.api_sandbox_job_status",
                "hvl_common_ui.studio",
                "hvl_common_ui.icons_catalog",
                "static",
            }
            for rule in app.url_map.iter_rules():
                if rule.endpoint in public_endpoints:
                    continue
                if "GET" not in (rule.methods or []):
                    continue

                test_url = rule.rule
                test_url = re.sub(r"<int:[^>]+>", "1", test_url)
                test_url = re.sub(r"<[^>]+>", "1", test_url)

                try:
                    with app.test_client() as anon_client:
                        resp = anon_client.get(test_url)
                except Exception as e:
                    rep.record_failure("fuzzing", f"Anonymous probe to GET {test_url} raised exception: {e}")
                    continue

                    is_safe = (resp.status_code in (401, 403, 302))
                    if resp.status_code == 200 and resp.is_json:
                        j = resp.get_json() or {}
                        if j.get("login_required") or j.get("error") in ("Unauthorized", "Forbidden"):
                            is_safe = True
                    if not is_safe:
                        rep.record_failure(
                            "fuzzing",
                            f"Unauthenticated data leak: Anonymous GET {test_url} ({rule.endpoint}) returned HTTP {resp.status_code}"
                        )

            with client.session_transaction() as sess:
                sess.clear()
                sess["authenticated"] = True
                sess["user"] = "Alpha Tenant"
                sess["user_family_id"] = 777
                sess["family_id"] = 777
                sess["role"] = "editor"
                sess["universe"] = "public"

            test_read_endpoints = [
                "/api/dashboard",
                "/api/compensation",
                "/api/gifting",
                "/api/education",
                "/api/scenarios",
                "/api/holdings/policy",
            ]
            for ep in test_read_endpoints:
                for spoof_id in (888, 1, 999):
                    res = client.get(f"{ep}?family_id={spoof_id}")
                    if res.status_code != 200:
                        rep.record_failure("multitenancy", f"Endpoint {ep} failed with HTTP {res.status_code} for family_id=777")
                    elif res.is_json:
                        body_str = str(res.get_json() or "")
                        if DENYLIST_PATH.exists():
                            terms = [l.strip() for l in DENYLIST_PATH.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
                            for term in terms:
                                if re.search(rf"\b{re.escape(term)}\b", body_str, re.IGNORECASE):
                                    rep.record_failure("idor", f"IDOR query tampering on {ep}?family_id={spoof_id} leaked term '{term}'")

            with client.session_transaction() as sess:
                sess.clear()
                sess["authenticated"] = True
                sess["user"] = "Demo Guest (Miller)"
                sess["is_demo"] = True
                sess["universe"] = "demo"
                sess["family_id"] = 2
                sess["role"] = "viewer"

            res_miller = client.get("/api/family?family_id=3")
            if res_miller.status_code == 200 and res_miller.is_json:
                data_miller = res_miller.get_json() or {}
                fam_name = data_miller.get("family", {}).get("name", "")
                if "Chen" in fam_name:
                    rep.record_failure("idor", f"Demo IDOR leak: Persona 2 session received Persona 3 data via ?family_id=3: '{fam_name}'")

            with client.session_transaction() as sess:
                sess["family_id"] = 3
                sess["user"] = "Demo Guest (Chen)"

            res_chen = client.get("/api/family?family_id=2")
            if res_chen.status_code == 200 and res_chen.is_json:
                data_chen = res_chen.get_json() or {}
                fam_name = data_chen.get("family", {}).get("name", "")
                if "Miller" in fam_name:
                    rep.record_failure("idor", f"Demo IDOR leak: Persona 3 session received Persona 2 data via ?family_id=2: '{fam_name}'")

    except Exception as e:
        rep.record_failure("fuzzing", f"Dynamic route fuzzing threw exception: {e}")

    print("    Dynamic route fuzzing complete.")


# =========================================================================
# MAIN EXECUTION & SUMMARY
# =========================================================================
def main() -> None:
    print("=" * 70)
    print("   HVL FAMILY OFFICE: ADVERSARIAL SECURITY & DATA AUDIT")
    print("=" * 70)

    audit_database()
    audit_codebase_backdoors()
    audit_templates()
    audit_environment_and_gitignore()
    audit_client_side_assets()
    audit_data_purity_and_hardcoded_financials()
    audit_dynamic_route_fuzzing()

    print("=" * 70)
    print(f"AUDIT RESULTS: {len(failures)} FAILURES, {len(warnings)} WARNINGS")
    print("=" * 70)

    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  * {w}")

    if failures:
        print("\nFAILURES DETECTED:")
        for f in failures:
            print(f"  * {f}")
        print("\n[CONCLUSION] Audit FAILED. Correct all issues above before deploying.")
        sys.exit(1)
    else:
        print("\n[CONCLUSION] Audit PASSED with 0 security or data-leak vulnerabilities.")
        sys.exit(0)


if __name__ == "__main__":
    main()
