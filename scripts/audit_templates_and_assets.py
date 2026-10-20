"""
scripts/audit_templates_and_assets.py: Template Authenticity, Client Assets, and Data Purity Audits.
Extracted from scripts/audit_security_and_data.py.
"""

from __future__ import annotations
import glob
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DENYLIST_PATH = BASE_DIR / "data" / "denylist.txt"


def audit_templates(reporter: Any) -> None:
    print("--> 3. Auditing HTML Templates for Insecure Inputs & Fake UI Controls...")
    html_files = glob.glob(str(BASE_DIR / "templates" / "**" / "*.html"), recursive=True)

    insecure_input_patterns = [
        (r'name=["\'](?:master|secret|pin)["\']', "Insecure manual PIN/secret form input found"),
        (r'id=["\'](?:input-mobile-secret|input-secret)["\']', "Manual mobile secret input found"),
        (r'Master Passphrase', "Found user-facing 'Master Passphrase' text"),
        (r'Sign in with Passkey', "Found un-enrolled/fake 'Sign in with Passkey' button"),
        (r'\|\s*safe\b', "Unsafe HTML rendering: found '| safe' filter in Jinja template"),
    ]

    for f_str in html_files:
        p = Path(f_str)
        rel_path = str(p.relative_to(BASE_DIR))
        if "features.html" in rel_path or "login.html" in rel_path:
            continue

        content = p.read_text(encoding="utf-8", errors="ignore")
        for pat, desc in insecure_input_patterns:
            matches = list(re.finditer(pat, content, re.IGNORECASE))
            for m in matches:
                line_no = content[:m.start()].count("\n") + 1
                reporter.record_failure("templates", f"{rel_path}:{line_no} - {desc}")

        statutory_and_benchmarks = {
            "$0", "$10,000", "$35,000", "$38,000", "$40,000", "$48,000", "$75,000", "$85,000", "$90,000",
            "$95,000", "$144,000", "$150k", "$150,000", "$250k", "$250,000", "$1M", "$2M", "$2.5M",
            "$7M", "$7.0M", "$13.61M", "$14M", "$14.0M", "$27M", "$27.2M", "$27.22M", "$1,000,000",
        }
        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("<!--") or stripped.startswith("//") or "{{" in line:
                pass
            else:
                if re.search(r'class=["\'][^"\']*kpi-value[^"\']*["\'][^>]*>\s*(?:\+|-)?\$0(?:\.00)?\s*<', line):
                    reporter.record_failure("templates", f"{rel_path}:{line_no} - Found hardcoded '$0' in kpi-value element (must use SSR or generic placeholder): '{stripped[:70]}'")
                if re.search(r'id=["\'](?:stat-|holdings-kpi-|inspector-|badge-)[^"\']*["\'][^>]*>\s*(?:\+|-)?(?:[^<]*:\s*)?\$0(?:\.00)?\s*<', line):
                    reporter.record_failure("templates", f"{rel_path}:{line_no} - Found hardcoded '$0' in stat/badge element (must use SSR or generic placeholder): '{stripped[:70]}'")

                for m in re.finditer(r'(\$[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?[kKmMbB]?)', line):
                    val = m.group(1)
                    if val not in statutory_and_benchmarks and any(tag in line for tag in ("id=", "class=", "<td", "<option", "<strong")):
                        reporter.record_failure("templates", f"{rel_path}:{line_no} - Found suspicious hardcoded financial figure '{val}' in template: '{stripped[:70]}'")

                for pm in re.finditer(r'placeholder=["\'][^"\']*?\b([1-9]\d{4,})\b[^"\']*["\']', line):
                     raw_num = int(pm.group(1))
                     if raw_num % 5000 != 0:
                         reporter.record_failure("templates", f"{rel_path}:{line_no} - Found non-round numeric placeholder '{raw_num}' in template: '{stripped[:70]}'")

        for line_no, line in enumerate(content.splitlines(), start=1):
            for tag in re.finditer(r"<(?:input|textarea)\b[^>]*>", line, re.IGNORECASE):
                tag_str = tag.group(0).lower()
                if any(skip in tag_str for skip in ['type="hidden"', 'type="checkbox"', 'type="number"', 'type="date"', 'type="color"', 'type="radio"', 'type="range"', 'type="button"', 'type="submit"', 'type="file"']):
                    continue
                if "maxlength" not in tag_str:
                    reporter.record_failure("templates", f"{rel_path}:{line_no} - Missing maxlength on text input/textarea: '{tag.group(0)[:70]}'")

    print("    Template audit complete.")


def audit_client_side_assets(reporter: Any) -> None:
    print("--> 5. Auditing JavaScript & CSS Assets for Secret Leaks & Dangerous Sinks...")
    static_files = glob.glob(str(BASE_DIR / "static" / "**" / "*.*"), recursive=True)
    terms = []
    if DENYLIST_PATH.exists():
        terms = [l.strip() for l in DENYLIST_PATH.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]

    dangerous_patterns = [
        (r"\beval\s*\(", "Dangerous JavaScript eval() execution sink found"),
        (r"\bdocument\.write\s*\(", "Dangerous JavaScript document.write() sink found"),
        (r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", "Embedded private key found in client asset"),
        (r"AIza[0-9A-Za-z-_]{35}", "Hardcoded Google API key found in client asset"),
    ]

    for f_str in static_files:
        p = Path(f_str)
        if p.suffix not in (".js", ".css", ".html"):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for pat, desc in dangerous_patterns:
            matches = list(re.finditer(pat, content))
            for m in matches:
                line_no = content[:m.start()].count("\n") + 1
                reporter.record_failure("assets", f"{p.relative_to(BASE_DIR)}:{line_no} - {desc}")

        for term in terms:
            prefix = r"(?<![a-zA-Z0-9])" if term and term[0].isalnum() else ""
            suffix = r"(?![a-zA-Z0-9])" if term and term[-1].isalnum() else ""
            rx = re.compile(rf"{prefix}{re.escape(term)}{suffix}", re.IGNORECASE)
            if rx.search(content):
                reporter.record_failure("assets", f"{p.relative_to(BASE_DIR)} contains denylist term '{term}'")

    print("    Client-side asset audit complete.")


def audit_data_purity_and_hardcoded_financials(reporter: Any) -> None:
    print("--> 6. Auditing Codebase for Hardcoded Personal Financials & PII Strings...")

    scan_files = []
    for pkg in ("routes", "forecast", "monarch", "equity", "ssr", "db", "services"):
        scan_files.extend(glob.glob(str(BASE_DIR / pkg / "**" / "*.py"), recursive=True))
    scan_files.extend(glob.glob(str(BASE_DIR / "*.py")))
    scan_files.extend(glob.glob(str(BASE_DIR / "templates" / "**" / "*.html"), recursive=True))
    scan_files.extend(glob.glob(str(BASE_DIR / "static" / "js" / "**" / "*.js"), recursive=True))

    terms = []
    if DENYLIST_PATH.exists():
        terms = [l.strip() for l in DENYLIST_PATH.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]

    banned_engine_fallback_patterns = [
        (r"primary_earned_income\s*=\s*[1-9]\d*(?:\.\d+)?", "Hardcoded non-zero default primary_earned_income fallback in forecast engine"),
        (r"spouse_earned_income\s*=\s*[1-9]\d*(?:\.\d+)?", "Hardcoded non-zero default spouse_earned_income fallback in forecast engine"),
        (r"living_core\s*=\s*max\(\s*[1-9]\d*(?:\.\d+)?\s*,", "Unconditional hardcoded floor on living_core in forecast waterfall"),
        (r"gifting_layer\s*=\s*[1-9]\d*(?:\.\d+)?", "Hardcoded non-zero default gifting_layer fallback in forecast waterfall"),
        (r"prior_ordinary_income\s*=\s*[1-9]\d*(?:\.\d+)?", "Hardcoded prior_ordinary_income in option tax calculation"),
        (r'"recommended_budget"\s*:\s*[1-9]\d*(?:\.\d+)?', "Hardcoded non-zero fallback recommended_budget for unseeded household"),
    ]

    for f_str in scan_files:
        p = Path(f_str)
        if p.name.startswith("audit_") or p.name in ("deploy.py", "sync_db_from_remote.py", "ingest_tax_transcripts.py", "ingest_new_spreadsheets.py"):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for term in terms:
            prefix = r"(?<![a-zA-Z0-9])" if term and term[0].isalnum() else ""
            suffix = r"(?![a-zA-Z0-9])" if term and term[-1].isalnum() else ""
            rx = re.compile(rf"{prefix}{re.escape(term)}{suffix}", re.IGNORECASE)
            if rx.search(content):
                for line_no, line in enumerate(content.splitlines(), start=1):
                    if rx.search(line):
                        reporter.record_failure("denylist", f"{p.relative_to(BASE_DIR)}:{line_no} contains denylist term '{term}': '{line.strip()[:80]}'")

        if p.suffix == ".py":
            for pat, desc in banned_engine_fallback_patterns:
                for m in re.finditer(pat, content):
                    line_no = content[:m.start()].count("\n") + 1
                    line = content.splitlines()[line_no - 1].strip()
                    if not line.startswith("#"):
                        reporter.record_failure("codebase", f"{p.relative_to(BASE_DIR)}:{line_no} - {desc}: '{line[:80]}'")

    print("    Data purity & hardcoded financials audit complete.")
