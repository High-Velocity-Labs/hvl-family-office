"""
scripts/audit_db_and_backdoors.py: SQLite Database, Backdoor Scan, and Environment Hygiene Audits.
Extracted from scripts/audit_security_and_data.py.
"""

from __future__ import annotations
import glob
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, List, Optional

from hvl_common.db import get_db_connection

BASE_DIR = Path(__file__).resolve().parent.parent
DENYLIST_PATH = BASE_DIR / "data" / "denylist.txt"
ENV_PATH = BASE_DIR / ".env"
GITIGNORE_PATH = BASE_DIR / ".gitignore"


def audit_database(reporter: Any) -> None:
    print("--> 1. Auditing Raw SQLite Database on Disk...")
    for bak in BASE_DIR.glob("**/*.local_bak"):
        reporter.record_failure("database", f"Unencrypted database backup found: {bak}")
    for bak in BASE_DIR.glob("**/*.bak"):
        reporter.record_failure("database", f"Unencrypted backup file found: {bak}")

    terms = []
    if DENYLIST_PATH.exists():
        terms = [l.strip() for l in DENYLIST_PATH.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]

    candidate_dbs: list[Path] = []
    for uni in ("public", "demo"):
        u_dir = BASE_DIR / "data" / uni
        if u_dir.exists():
            for p in u_dir.glob("*.db"):
                if not p.name.endswith(("_cache.db", "-wal", "-shm")):
                    candidate_dbs.append(p)
            fam_dir = u_dir / "families"
            if fam_dir.exists():
                for p in fam_dir.glob("*.db"):
                    if not p.name.endswith(("_cache.db", "-wal", "-shm")):
                        candidate_dbs.append(p)

    legacy_files = [
        BASE_DIR / "data" / "family_office.db",
        BASE_DIR / "data" / "family_office_beta.db",
        BASE_DIR / "data" / "global.db",
        BASE_DIR / "data" / "global_beta.db",
    ]
    for lf in legacy_files:
        if lf.exists() and lf not in candidate_dbs:
            candidate_dbs.append(lf)
    for f_dir in (BASE_DIR / "data" / "families", BASE_DIR / "data" / "families_beta"):
        if f_dir.exists():
            for p in f_dir.glob("*.db"):
                if not p.name.endswith(("_cache.db", "-wal", "-shm")) and p not in candidate_dbs:
                    candidate_dbs.append(p)

    if not candidate_dbs:
        print("    [INFO] No database found at data/public/ or legacy data/ (clean state).")
    else:
        for db_file in candidate_dbs:
            try:
                conn = get_db_connection(db_file)
                conn.row_factory = sqlite3.Row
            except Exception as e:
                reporter.record_warning("database", f"Could not open {db_file.name}: {e}")
                continue

            try:
                cur = conn.execute("SELECT user_id, name, email FROM users")
                for r in cur.fetchall():
                    uid = r["user_id"]
                    name = str(r["name"] or "")
                    email = str(r["email"] or "")
                    if name and not name.startswith("gAAAAA"):
                        reporter.record_failure("database", f"[{db_file.name}] users row {uid} has UNENCRYPTED plaintext name: '{name}'")
                    if email and not email.startswith("gAAAAA"):
                        reporter.record_failure("database", f"[{db_file.name}] users row {uid} has UNENCRYPTED plaintext email: '{email}'")
            except sqlite3.OperationalError:
                pass

            is_demo_db = "demo" in str(db_file) or "beta" in str(db_file)
            if not is_demo_db:
                try:
                    cur = conn.execute("SELECT comp_id, base_salary, bonus FROM compensation")
                    for r in cur.fetchall():
                        sal = str(r["base_salary"] or "")
                        if sal and not sal.startswith("gAAAAA"):
                            try:
                                float_val = float(sal)
                                if float_val > 0:
                                    reporter.record_failure("database", f"[{db_file.name}] compensation row {r['comp_id']} has UNENCRYPTED base_salary: '{sal}'")
                            except ValueError:
                                pass
                except sqlite3.OperationalError:
                    pass

            if terms:
                try:
                    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() if not r[0].startswith("sqlite_")]
                    for tbl in tables:
                        rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
                        if not rows:
                            continue
                        cols = [d[0] for d in conn.execute(f"SELECT * FROM {tbl} LIMIT 1").description]
                        for r_idx, row in enumerate(rows):
                            for c_idx, val in enumerate(row):
                                val_str = str(val or "")
                                if val_str.startswith("gAAAAA"):
                                    continue
                                for term in terms:
                                    if re.search(rf"\b{re.escape(term)}\b", val_str, re.IGNORECASE):
                                        reporter.record_failure("database", f"[{db_file.name}] Table '{tbl}', column '{cols[c_idx]}' contains denylist term '{term}': {val_str[:50]}")
                except sqlite3.OperationalError:
                    pass

            conn.close()

    candidate_cache_dbs: list[Path] = []
    for uni in ("public", "demo"):
        u_dir = BASE_DIR / "data" / uni
        if u_dir.exists():
            for p in u_dir.glob("*_cache.db"):
                candidate_cache_dbs.append(p)
            fam_dir = u_dir / "families"
            if fam_dir.exists():
                for p in fam_dir.glob("*_cache.db"):
                    candidate_cache_dbs.append(p)
    for cp in (
        BASE_DIR / "data" / "family_office_cache.db",
        BASE_DIR / "data" / "family_office_beta_cache.db",
        BASE_DIR / "data" / "cache_sandbox.db",
    ):
        if cp.exists() and cp not in candidate_cache_dbs:
            candidate_cache_dbs.append(cp)
    for f_dir in (BASE_DIR / "data" / "families", BASE_DIR / "data" / "families_beta"):
        if f_dir.exists():
            for cp in f_dir.glob("*_cache.db"):
                if cp not in candidate_cache_dbs:
                    candidate_cache_dbs.append(cp)

    for cache_db_path in candidate_cache_dbs:
        try:
            cache_conn = get_db_connection(cache_db_path)
            try:
                for r in cache_conn.execute("SELECT key, value, filename FROM Cache").fetchall():
                    if r[2] is not None:
                        reporter.record_failure("database", f"[{cache_db_path.name}] diskcache key '{r[0]}' spilled a loose file '{r[2]}' to disk")
                    blob = r[1]
                    blob_bytes = bytes(blob) if isinstance(blob, (bytes, bytearray, memoryview)) else str(blob).encode("utf-8")
                    if blob_bytes and not blob_bytes.startswith(b"gAAAAA"):
                        reporter.record_failure("database", f"[{cache_db_path.name}] diskcache key '{r[0]}' has UNENCRYPTED value blob on disk")
            except sqlite3.OperationalError:
                pass
            try:
                for r in cache_conn.execute("SELECT job_id, result_blob FROM background_jobs WHERE result_blob IS NOT NULL").fetchall():
                    blob = r[1]
                    blob_bytes = bytes(blob) if isinstance(blob, (bytes, bytearray, memoryview)) else str(blob).encode("utf-8")
                    if blob_bytes and not blob_bytes.startswith(b"gAAAAA"):
                        reporter.record_failure("database", f"[{cache_db_path.name}] background_jobs '{r[0]}' has UNENCRYPTED result_blob on disk")
            except sqlite3.OperationalError:
                pass
            cache_conn.close()
        except Exception as e:
            reporter.record_warning("database", f"Could not audit cache db {cache_db_path.name}: {e}")

    print("    Database audit complete.")


def audit_codebase_backdoors(reporter: Any) -> None:
    print("--> 2. Auditing Python Code for Backdoors and Auth Bypasses...")
    suspicious_patterns = [
        (r"FAMILY_MASTER_KEY", "Found deprecated FAMILY_MASTER_KEY backdoor reference"),
        (r"master_key\s*=", "Found master_key assignment"),
        (r"master_pass", "Found master_pass reference"),
        (r"webauthn_passkey_verified", "Found fake passkey bypass token"),
        (r"role\s*=\s*['\"]Master Admin['\"]", "Found hardcoded Master Admin role assignment"),
        (r"def\s+\w+\([^)]*family_id\s*(?::\s*int)?\s*=\s*1\b", "Hardcoded default family_id=1 in function signature (violates multi-tenant isolation)"),
        (r"DB_PATH\s*=\s*.*['\"]data[/\\\\]family_office\.db['\"]", "Hardcoded production family_office.db path (must use dynamic universe proxy)"),
        (r"(?:conn|cursor|db)\.execute\s*\(\s*f[\"']", "Potential SQL injection: unparameterized f-string query in execute()"),
        (r"(?:conn|cursor|db)\.execute\s*\(\s*[\"'].*%\s*\(", "Potential SQL injection: % string formatting in execute()"),
        (r"(?:conn|cursor|db)\.execute\s*\(\s*[\"'].*\.format\(", "Potential SQL injection: .format() in execute()"),
    ]

    py_files = []
    for pkg in ("routes", "forecast", "monarch", "equity", "ssr", "db", "services"):
        py_files.extend(glob.glob(str(BASE_DIR / pkg / "**" / "*.py"), recursive=True))
    py_files.extend(glob.glob(str(BASE_DIR / "*.py")))

    for f_str in py_files:
        p = Path(f_str)
        if p.name in ("deploy.py", "sync_db_from_remote.py", "audit_security_and_data.py", "seed_demo_families.py") or p.name.startswith("audit_"):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for pat, desc in suspicious_patterns:
            if "f-string query" in desc and p.parent.name == "db":
                continue
            matches = list(re.finditer(pat, content, re.IGNORECASE))
            for m in matches:
                start_line = content[:m.start()].count("\n") + 1
                line = content.splitlines()[start_line - 1].strip()
                if line.startswith("#") or line.startswith('"""') or line.startswith("*"):
                    continue
                reporter.record_failure("codebase", f"{p.relative_to(BASE_DIR)}:{start_line} - {desc}: '{line[:80]}'")

        if "routes" in str(p.parent):
            route_matches = list(re.finditer(r"family_id\s*=\s*1\b(?!\s*[,#])", content))
            for rm in route_matches:
                start_line = content[:rm.start()].count("\n") + 1
                line = content.splitlines()[start_line - 1].strip()
                if line.startswith("#") or line.startswith('"""') or line.startswith("*"):
                    continue
                reporter.record_failure("codebase", f"{p.relative_to(BASE_DIR)}:{start_line} - Potential hardcoded family_id=1 in route: '{line[:80]}'")

    print("    Codebase backdoor audit complete.")


def audit_environment_and_gitignore(reporter: Any) -> None:
    print("--> 4. Auditing .env and .gitignore Hygiene...")
    if ENV_PATH.exists():
        env_content = ENV_PATH.read_text(encoding="utf-8", errors="ignore")
        if "FAMILY_CHILDREN_EMAILS" in env_content:
            reporter.record_failure("environment", "Found FAMILY_CHILDREN_EMAILS in .env (personal PII leak)")
        if "FAMILY_MASTER_KEY" in env_content:
            reporter.record_failure("environment", "Found FAMILY_MASTER_KEY in .env (backdoor)")

    if GITIGNORE_PATH.exists():
        gi = GITIGNORE_PATH.read_text(encoding="utf-8")
        required_ignores = [".env", "data/", "*.db", "*.xlsx", "*.csv"]
        for req in required_ignores:
            if req not in gi:
                reporter.record_failure("gitignore", f"Missing critical exclusion '{req}' in .gitignore")
    else:
        reporter.record_failure("gitignore", "No .gitignore found!")

    print("    Environment & gitignore audit complete.")
