"""
Level 0 & Level 4 Static / Syntax & Theme Guardrail Tests.

Validates that:
1. All static JavaScript files under static/js/ pass Node.js syntax parsing (`node --check`).
2. All Jinja2-rendered inline scripts across public, authenticated, and fragment views
   pass Node.js syntax parsing, ensuring dynamic interpolation never breaks script evaluation.
3. Post-v0.2.0 UI templates strictly enforce CSS custom property design tokens for status colors
   rather than hardcoded hex colors, and leverage SVG sprites / standard tokens.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from app import app

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_JS_DIR = BASE_DIR / "static" / "js"

V030_TEMPLATES = [
    "templates/login.html",
    "templates/components/bug_reporter_modal.html",
    "templates/admin_bugs.html",
    "templates/components/onboarding_wizard.html",
    "templates/components/settings/_household_access.html",
]

DISALLOWED_STATUS_HEX = ["#10B981", "#EF4444", "#DC2626", "#B91C1C", "#F59E0B"]

ALL_FRAGMENTS = [
    "overview",
    "scenarios",
    "equity",
    "holdings",
    "compensation",
    "estate",
    "college",
    "philanthropy",
    "arbitrage",
    "gifting",
    "accounts",
    "settings",
]


@pytest.fixture
def auth_client() -> Any:
    """Provides an authenticated editor client for full page and fragment rendering."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["universe"] = "test"
        sess["family_id"] = 1
        sess["user_email"] = "test@example.com"
        sess["role"] = "editor"
        sess["is_demo"] = False
    return client


def _check_js_syntax_with_node(file_path: Path | str) -> subprocess.CompletedProcess[str]:
    """Runs `node --check` against a JavaScript file path."""
    return subprocess.run(
        ["node", "--check", str(file_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_all_static_js_files_pass_node_syntax_check() -> None:
    """Verifies that every JavaScript source file under static/js/ passes Node.js syntax validation."""
    js_files = sorted(STATIC_JS_DIR.rglob("*.js"))
    assert js_files, f"Expected static .js files under {STATIC_JS_DIR}, none found"

    def _validate(p: Path) -> tuple[Path, subprocess.CompletedProcess[str]]:
        return p, _check_js_syntax_with_node(p)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_validate, js_files))

    errors: list[str] = [
        f"{rel.relative_to(BASE_DIR)}: {proc.stderr.strip()}"
        for rel, proc in results
        if proc.returncode != 0
    ]
    assert not errors, "JavaScript syntax errors detected in static assets:\n" + "\n".join(errors)


def test_rendered_inline_scripts_pass_node_syntax_check(auth_client: Any) -> None:
    """
    Extracts all inline <script> snippets across unauthenticated, authenticated, and fragment endpoints,
    validating that Jinja interpolation generates syntactically valid JavaScript.
    """
    unauthenticated_client = app.test_client()
    unauth_routes = ["/login", "/help", "/features"]
    auth_routes = ["/", "/admin/bugs"]
    fragment_routes = [f"/fragments/{name}" for name in ALL_FRAGMENTS]

    script_regex = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)
    type_regex = re.compile(r"""type=["']([^"']+)["']""", re.IGNORECASE)

    extracted_snippets: list[tuple[str, str]] = []

    for route in unauth_routes:
        resp = unauthenticated_client.get(route)
        if resp.status_code in (200, 302):
            html = resp.get_data(as_text=True)
            for match in script_regex.finditer(html):
                attrs, body = match.group(1), match.group(2).strip()
                if "src=" in attrs:
                    continue
                type_m = type_regex.search(attrs)
                if type_m and type_m.group(1).lower() in ("application/json", "importmap", "text/template", "application/ld+json"):
                    continue
                if body:
                    extracted_snippets.append((route, body))

    for route in auth_routes + fragment_routes:
        resp = auth_client.get(route)
        if resp.status_code in (200, 302):
            html = resp.get_data(as_text=True)
            for match in script_regex.finditer(html):
                attrs, body = match.group(1), match.group(2).strip()
                if "src=" in attrs:
                    continue
                type_m = type_regex.search(attrs)
                if type_m and type_m.group(1).lower() in ("application/json", "importmap", "text/template", "application/ld+json"):
                    continue
                if body:
                    extracted_snippets.append((route, body))

    assert extracted_snippets, "Expected inline scripts to be discovered in rendered templates, found none."

    syntax_failures: list[str] = []
    for route, code in extracted_snippets:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name
        try:
            res = _check_js_syntax_with_node(tmp_path)
            if res.returncode != 0:
                syntax_failures.append(f"Route '{route}' inline script syntax error:\n{res.stderr.strip()}\nCode:\n{code[:200]}...")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    assert not syntax_failures, "Rendered inline script syntax validation failed:\n" + "\n\n".join(syntax_failures)


def test_v030_templates_enforce_theme_tokens_and_svg_sprites() -> None:
    """
    Enforces design system tokens across post-v0.2.0 templates by asserting they do NOT
    contain hardcoded status hex values (#10B981, #EF4444, #DC2626, #B91C1C, #F59E0B)
    in inline style attributes or <style> tags.
    """
    hex_pattern = re.compile(r"#(?:10B981|EF4444|DC2626|B91C1C|F59E0B)\b", re.IGNORECASE)
    style_attr_pattern = re.compile(r"""style=["']([^"']*)["']""", re.IGNORECASE)
    style_tag_pattern = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)

    violations: list[str] = []

    for rel_path in V030_TEMPLATES:
        file_path = BASE_DIR / rel_path
        assert file_path.is_file(), f"Target template file does not exist: {rel_path}"
        content = file_path.read_text(encoding="utf-8")

        for match in style_attr_pattern.finditer(content):
            style_str = match.group(1)
            found = hex_pattern.findall(style_str)
            if found:
                violations.append(f"{rel_path}: inline style contains hardcoded status hex {found}: '{style_str}'")

        for match in style_tag_pattern.finditer(content):
            css_body = match.group(1)
            found = hex_pattern.findall(css_body)
            if found:
                violations.append(f"{rel_path}: <style> block contains hardcoded status hex {found}")

    assert not violations, "Found prohibited hardcoded status hex colors in post-v0.2.0 templates:\n" + "\n".join(violations)


def test_all_ui_controls_and_css_variables_resolve_via_arch_gate() -> None:
    """
    Delegates directly to the consolidated arch_gate.py CSS index check to verify that:
    1. Every var(--...) reference in templates/**/*.html, static/js/**/*.js, and static/css/**/*.css
       resolves to a defined CSS custom property in theme.css or app stylesheets.
    2. Every <button> and <select> with a class="..." attribute in HTML templates or JS template
       literals includes at least one defined CSS class from our stylesheets (preventing unstyled
       hallucinated classes like 'btn-pill' or 'select select-sm').
    """
    arch_gate = Path.home() / ".gemini" / "config" / "skills" / "hvl-architecture-audit" / "scripts" / "arch_gate.py"
    if not arch_gate.is_file():
        pytest.skip("Global arch_gate.py not present")

    res = subprocess.run(
        ["python3", str(arch_gate), "--repo", str(BASE_DIR), "--structural-all"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"arch_gate.py structural/CSS check failed:\n{res.stdout}\n{res.stderr}"

