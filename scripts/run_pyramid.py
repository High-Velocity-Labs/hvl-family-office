#!/usr/bin/env python3
"""
HVL Family Office — 7-Level Testing Pyramid Runner (`scripts/run_pyramid.py`)

Runs the codebase health & verification pyramid on demand or before public release:
  Level 0: Static AST, Architecture, Security & Theme Token Guardrails
  Level 1: Engine Unit Tests (Tax, Monte Carlo, RSU Equity, Estate, W-2, Allocations)
  Level 2: Backend Invariants (DB-per-Family, AES-256-GCM Crypto, .fovault, Auth & Roles)
  Level 3: HTTP Services (`GET`/`POST` Contracts & Dynamic `app.url_map` Auth Guardrails)
  Level 3.5: SSR & Hydration Parity (Seeded, Empty Household, Full-Page & Standalone SSR)
  Level 4: Frontend JavaScript (Node Syntax Check + JSDOM Logic & User Event Simulation)
  Level 5: Viewport Overflow & Browser Interactions (Headless Chrome Desktop & Mobile)

Parallel Execution & Complete Data Isolation:
  By default, when running multiple levels, each level executes concurrently in its own
  process with a dedicated temporary `FAMILY_OFFICE_DATA_DIR` sandbox cloned from baseline.
  No two parallel levels ever share a SQLite `.db`, `-wal`, or `-shm` file.

Usage:
  python3 scripts/run_pyramid.py                 # Run all levels in parallel
  python3 scripts/run_pyramid.py --fast          # Run Levels 0–4 in parallel (skip headless Chrome)
  python3 scripts/run_pyramid.py --serial        # Run levels sequentially one after another
  python3 scripts/run_pyramid.py --level 5       # Run only a specific level (0, 1, 2, 3, 3.5, 4, 5)
  python3 scripts/run_pyramid.py --level ssr     # Alias support: static, unit, backend, http, ssr, js, overflow
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

LEVEL_ALIASES: Dict[str, str] = {
    "0": "0", "static": "0", "guardrails": "0",
    "1": "1", "unit": "1", "engines": "1",
    "2": "2", "backend": "2", "invariants": "2",
    "3": "3", "http": "3", "api": "3",
    "3.5": "3.5", "ssr": "3.5",
    "4": "4", "js": "4", "frontend": "4", "jsdom": "4",
    "5": "5", "overflow": "5", "viewport": "5", "layout": "5",
}


def get_pyramid_levels() -> List[Tuple[str, str, List[List[str]]]]:
    """Returns ordered (level_id, level_name, commands) definitions."""
    arch_gate = Path.home() / ".gemini/config/skills/hvl-architecture-audit/scripts/arch_gate.py"
    level_0_cmds = [
        [PYTHON, "scripts/audit_security_and_data.py"],
        [PYTHON, "-m", "pytest", "-q", "--tb=short", "--no-header",
         "tests/test_guardrails.py", "tests/test_js_and_theme_guardrails.py"],
    ]
    if arch_gate.exists():
        level_0_cmds.insert(0, [PYTHON, str(arch_gate), "--repo", str(REPO_ROOT), "--all"])

    return [
        (
            "0",
            "Static AST, Security & Theme Guardrails",
            level_0_cmds,
        ),
        (
            "1",
            "Engine Unit Tests (Tax, MC, Equity, Estate, W-2)",
            [[
                PYTHON, "-m", "pytest", "-q", "--tb=short", "--no-header",
                "tests/test_engines.py",
                "tests/test_async_tax_and_mc.py",
                "tests/test_rsu_equity.py",
                "tests/test_estate.py",
                "tests/test_w2_parsing.py",
                "tests/test_allocation_presets.py",
            ]],
        ),
        (
            "2",
            "Backend Invariants (DB Isolation, Crypto, .fovault, Roles)",
            [[
                PYTHON, "-m", "pytest", "-q", "--tb=short", "--no-header",
                "tests/test_sandbox_universe.py",
                "tests/test_family_dbs.py",
                "tests/test_alembic_security_telemetry.py",
                "tests/test_auth_google.py",
                "tests/test_auth_google_invites.py",
                "tests/test_security_access.py",
                "tests/test_demo_universe.py",
                "tests/test_forecast_cache.py",
                "tests/test_local_desktop.py",
            ]],
        ),
        (
            "3",
            "HTTP Services (GET/POST Contracts & Dynamic url_map Auth)",
            [[
                PYTHON, "-m", "pytest", "-q", "--tb=short", "--no-header",
                "tests/test_api_endpoints.py",
                "tests/test_accounts_and_onboarding.py",
                "tests/test_scenarios_and_family.py",
                "tests/test_bug_reporter.py",
                "tests/test_ai_advisor.py",
                "tests/test_version_pill.py",
            ]],
        ),
        (
            "3.5",
            "SSR & Hydration Parity (Seeded, Empty Household & Full-Page)",
            [[
                PYTHON, "-m", "pytest", "-q", "--tb=short", "--no-header",
                "tests/test_ssr_parity.py",
                "tests/test_ssr_and_routes_coverage.py",
            ]],
        ),
        (
            "4",
            "Frontend JS (Syntax Gate + JSDOM Logic & User Events)",
            [[
                PYTHON, "-m", "pytest", "-q", "--tb=short", "--no-header",
                "tests/test_javascript_harness.py",
                "tests/test_js_and_theme_guardrails.py",
            ]],
        ),
        (
            "5",
            "Viewport Overflow & Browser Interactions (Desktop + Mobile)",
            [[
                PYTHON, "-m", "pytest", "-q", "--tb=short", "--no-header",
                "tests/test_layout_overflow.py",
            ]],
        ),
    ]


def run_level(
    level_id: str,
    title: str,
    commands: List[List[str]],
    capture: bool = False,
) -> Tuple[str, str, bool, float, str]:
    """Executes all commands for a level inside an isolated temporary data directory."""
    start = time.time()
    logs: List[str] = []
    if not capture:
        print(f"\n━━━ [Level {level_id}] {title} ━━━", flush=True)

    with tempfile.TemporaryDirectory(prefix=f"fo_pyramid_l{level_id.replace('.', '_')}_") as tmp_data_dir:
        tmp_path = Path(tmp_data_dir)
        mm_dir = tmp_path / ".mm"
        mm_dir.mkdir(parents=True, exist_ok=True)
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        import security_crypto
        root_key = security_crypto.get_or_create_key()
        (mm_dir / ".secret.key").write_bytes(root_key)
        for key_file in (".secret.key", ".env"):
            src_key = REPO_ROOT / key_file
            if src_key.exists():
                import shutil
                shutil.copy2(src_key, tmp_path / key_file)
        import shutil
        src_data = REPO_ROOT / "data"
        for sub_uni in ("public", "demo"):
            src_uni = src_data / sub_uni
            if src_uni.exists():
                shutil.copytree(
                    src_uni,
                    tmp_path / sub_uni,
                    ignore=shutil.ignore_patterns("*-wal", "*-shm", "*_cache.db*"),
                    dirs_exist_ok=True,
                )

        for cmd in commands:
            filtered_cmd = [
                arg for arg in cmd
                if not (arg.startswith("tests/") and not (REPO_ROOT / arg).exists())
            ]
            env = os.environ.copy()
            env["PAGER"] = "cat"
            # audit_security_and_data.py inspects the real repo data/ directory;
            # all pytest suites get their own isolated FAMILY_OFFICE_DATA_DIR sandbox.
            if "audit_security_and_data.py" not in " ".join(filtered_cmd):
                env["FAMILY_OFFICE_DATA_DIR"] = tmp_data_dir

            if capture:
                res = subprocess.run(
                    filtered_cmd,
                    cwd=str(REPO_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                if res.stdout:
                    logs.append(res.stdout.strip())
            else:
                res = subprocess.run(filtered_cmd, cwd=str(REPO_ROOT), env=env)

            if res.returncode != 0:
                elapsed = time.time() - start
                out_text = "\n".join(logs) if logs else f"Failed command: {' '.join(filtered_cmd)}"
                return level_id, title, False, elapsed, out_text

    elapsed = time.time() - start
    return level_id, title, True, elapsed, "\n".join(logs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the HVL Family Office 7-Level Testing Pyramid.")
    parser.add_argument(
        "--level", "-l",
        action="append",
        help="Run specific level(s): 0/static, 1/unit, 2/backend, 3/http, 3.5/ssr, 4/js, 5/overflow",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run Levels 0–4 only (skip Level 5 headless browser overflow checks).",
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="Run levels sequentially instead of in parallel.",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="Max parallel level workers (default: 4).",
    )
    args = parser.parse_args()

    all_levels = get_pyramid_levels()
    selected_ids = None
    if args.level:
        selected_ids = set()
        for raw in args.level:
            for token in raw.split(","):
                key = token.strip().lower()
                if key not in LEVEL_ALIASES:
                    print(f"Unknown level '{token}'. Valid: {', '.join(sorted(set(LEVEL_ALIASES.keys())))}")
                    return 2
                selected_ids.add(LEVEL_ALIASES[key])

    target_levels = [
        (lid, title, cmds)
        for lid, title, cmds in all_levels
        if (selected_ids is None or lid in selected_ids) and not (args.fast and lid == "5")
    ]

    overall_start = time.time()
    results_map: Dict[str, Tuple[str, str, bool, float, str]] = {}

    use_parallel = not args.serial and len(target_levels) > 1
    if use_parallel:
        print(f"Running {len(target_levels)} pyramid levels in parallel (max_workers={args.workers}, isolated DB sandboxes)...", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            future_to_lid = {
                pool.submit(run_level, lid, title, cmds, True): lid
                for lid, title, cmds in target_levels
            }
            for fut in as_completed(future_to_lid):
                lid, title, ok, elapsed, output = fut.result()
                results_map[lid] = (lid, title, ok, elapsed, output)
                badge = "PASS" if ok else "FAIL"
                print(f"  [{badge}] Level {lid:<4} — {title} ({elapsed:.1f}s)", flush=True)
                if not ok and output:
                    print(f"\n--- Level {lid} Failure Output ---\n{output}\n----------------------------", flush=True)
    else:
        for lid, title, cmds in target_levels:
            res = run_level(lid, title, cmds, capture=False)
            results_map[lid] = res
            if not res[2]:
                break

    ordered_results = [results_map[lid] for lid, _, _ in target_levels if lid in results_map]
    total_elapsed = time.time() - overall_start
    sum_cpu_time = sum(r[3] for r in ordered_results)

    print("\n" + "═" * 76)
    print(f"{'LEVEL':<8} {'SUITE DESCRIPTION':<48} {'STATUS':<8} {'TIME':>8}")
    print("─" * 76)
    all_passed = True
    for lid, title, ok, elapsed, _ in ordered_results:
        status_str = "PASS" if ok else "FAIL"
        if not ok:
            all_passed = False
        print(f"{lid:<8} {title[:47]:<48} {status_str:<8} {elapsed:>7.1f}s")
    print("═" * 76)
    print(f"Wall Time: {total_elapsed:.1f}s (Cumulative Suite Time: {sum_cpu_time:.1f}s) | Overall: {'PASSED' if all_passed else 'FAILED'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
