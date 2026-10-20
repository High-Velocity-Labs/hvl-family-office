#!/usr/bin/env python3
"""
Migration script: Single monolithic SQLite to Multi-Tenant Database-Per-Family Architecture.

Decomposes monolithic SQLite files into:
1. data/{universe}/global.db (e.g. data/public/global.db, data/demo/global.db):
   Global directory & authentication tables:
   - users, families, account_roles, qr_sessions, _schema_migrations, alembic_version
2. data/{universe}/families/{family_id}.db:
   Self-contained per-family databases with dedicated domain tables + family auth records:
   - household_profile, compensation, equity_companies, equity_grants, fmv_history,
     estate_profiles, gift_recipients, gifts, philanthropy_budgets, philanthropy_donations,
     tuition, tuition_year_records, monarch_accounts, monarch_holdings, forecast_scenarios,
     forecast_events, forecast_settings, tax_transcript_meta, tax_transcript_records,
     advisor_conversations, advisor_messages, family_encrypted_store, family_state_versions,
     families (scoped), users (scoped), account_roles (scoped), _schema_migrations, alembic_version.

INVARIANTS:
- Non-destructive: source database files are NEVER deleted and remain as archives.
- Idempotent: safe to run multiple times without duplicating or corrupting data.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Set

# Ensure project root in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config

logger = logging.getLogger("migrate_to_family_dbs")

GLOBAL_TABLES: List[str] = [
    "_schema_migrations",
    "alembic_version",
    "families",
    "users",
    "account_roles",
    "qr_sessions",
]

DOMAIN_TABLES: List[str] = [
    "household_profile",
    "compensation",
    "equity_companies",
    "equity_grants",
    "fmv_history",
    "estate_profiles",
    "gift_recipients",
    "gifts",
    "philanthropy_budgets",
    "philanthropy_donations",
    "tuition",
    "tuition_year_records",
    "monarch_accounts",
    "monarch_holdings",
    "forecast_scenarios",
    "forecast_events",
    "forecast_settings",
    "tax_transcript_meta",
    "tax_transcript_records",
    "advisor_conversations",
    "advisor_messages",
    "family_encrypted_store",
    "family_state_versions",
]

META_TABLES_FOR_FAMILY: List[str] = [
    "_schema_migrations",
    "alembic_version",
    "families",
    "users",
    "account_roles",
]


def _enable_wal(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA busy_timeout = 30000;")


def _get_existing_tables(conn: sqlite3.Connection) -> Set[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return {r[0] for r in cur.fetchall()}


def _replicate_table_schema(src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection, table_name: str) -> None:
    """Replicates table and index definitions from src_conn to dst_conn using IF NOT EXISTS."""
    tbl_row = src_conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (table_name,)).fetchone()
    if not tbl_row or not tbl_row[0]:
        return
    sql = tbl_row[0].strip()
    if "CREATE TABLE IF NOT EXISTS" not in sql:
        sql = sql.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
    dst_conn.execute(sql)

    idx_rows = src_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name = ? AND sql IS NOT NULL",
        (table_name,),
    ).fetchall()
    for (idx_sql,) in idx_rows:
        if not idx_sql:
            continue
        cleaned = idx_sql.strip()
        if "CREATE INDEX IF NOT EXISTS" not in cleaned and "CREATE UNIQUE INDEX IF NOT EXISTS" not in cleaned:
            if "CREATE UNIQUE INDEX" in cleaned:
                cleaned = cleaned.replace("CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX IF NOT EXISTS", 1)
            else:
                cleaned = cleaned.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1)
        try:
            dst_conn.execute(cleaned)
        except Exception as e:
            logger.debug("Index creation notice on %s: %s", table_name, e)


def _copy_table_rows(
    src_conn: sqlite3.Connection,
    dst_conn: sqlite3.Connection,
    table_name: str,
    where_clause: str = "",
    params: tuple = (),
) -> int:
    """Copies rows matching where_clause from src_conn to dst_conn with INSERT OR REPLACE."""
    query = f"SELECT * FROM {table_name}"
    if where_clause:
        query += f" WHERE {where_clause}"

    src_cur = src_conn.execute(query, params)
    rows = src_cur.fetchall()
    if not rows:
        return 0

    cols = [c[1] for c in src_conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
    col_str = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    insert_sql = f"INSERT OR REPLACE INTO {table_name} ({col_str}) VALUES ({placeholders})"

    delete_query = f"DELETE FROM {table_name}"
    if where_clause:
        delete_query += f" WHERE {where_clause}"
    dst_conn.execute(delete_query, params)

    dst_conn.executemany(insert_sql, rows)
    return len(rows)


def migrate_database(
    src_db: Path,
    universe: str = "public",
    target_dir: Optional[Path] = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Decomposes a single monolithic SQLite file into global.db and per-family DBs.
    Fully idempotent; does not delete src_db.
    """
    if universe == "beta":
        universe = "demo"

    src_path = Path(src_db)
    if not src_path.exists():
        if verbose:
            print(f"[SKIP] Source database does not exist: {src_path}")
        return {"status": "skipped", "reason": "source_not_found", "src_db": str(src_path)}

    if target_dir is not None:
        td = Path(target_dir)
        td.mkdir(parents=True, exist_ok=True)
        if (td / universe).exists() or not (td / f"global_{universe}.db").exists():
            u_dir = td / universe if universe in ("demo", "public", "sandbox", "test") else td
            u_dir.mkdir(parents=True, exist_ok=True)
            global_db_path = u_dir / "global.db"
        else:
            global_db_path = td / (f"global_{universe}.db" if universe != "public" else "global.db")
    else:
        global_db_path = config.get_global_db_path(universe)

    if verbose:
        print(f"[START] Migrating {src_path.name} (universe={universe}) -> {global_db_path.name} & per-family DBs")

    report: Dict[str, Any] = {
        "status": "success",
        "universe": universe,
        "src_db": str(src_path),
        "global_db": str(global_db_path),
        "families_migrated": {},
        "global_tables_migrated": {},
    }

    if dry_run:
        with sqlite3.connect(str(src_path)) as src_conn:
            tables = _get_existing_tables(src_conn)
            fams = [r[0] for r in src_conn.execute("SELECT DISTINCT family_id FROM families").fetchall()] if "families" in tables else []
            report["dry_run"] = True
            report["available_tables"] = sorted(tables)
            report["family_ids"] = fams
            if verbose:
                print(f"[DRY-RUN] Found {len(tables)} tables and {len(fams)} families: {fams}")
        return report

    # 1. Migrate Global Tables to global.db
    global_db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(src_path)) as src_conn, sqlite3.connect(str(global_db_path)) as g_conn:
        _enable_wal(src_conn)
        _enable_wal(g_conn)
        src_tables = _get_existing_tables(src_conn)

        for tbl in GLOBAL_TABLES:
            if tbl in src_tables:
                _replicate_table_schema(src_conn, g_conn, tbl)
                count = _copy_table_rows(src_conn, g_conn, tbl)
                report["global_tables_migrated"][tbl] = count
                if verbose:
                    print(f"  [GLOBAL] {tbl}: {count} rows")
        g_conn.commit()

        # Discover distinct family IDs
        family_ids: List[int] = []
        if "families" in src_tables:
            family_ids = [int(r[0]) for r in src_conn.execute("SELECT DISTINCT family_id FROM families ORDER BY family_id ASC").fetchall()]

        # Check domain tables for any orphan family IDs
        for dt in DOMAIN_TABLES:
            if dt in src_tables:
                cols = {c[1] for c in src_conn.execute(f"PRAGMA table_info({dt})").fetchall()}
                if "family_id" in cols:
                    orphan_fids = [int(r[0]) for r in src_conn.execute(f"SELECT DISTINCT family_id FROM {dt} WHERE family_id IS NOT NULL").fetchall()]
                    for ofid in orphan_fids:
                        if ofid not in family_ids:
                            family_ids.append(ofid)

        family_ids.sort()

    # 2. Migrate Each Family to data/families/{family_id}.db
    for fid in family_ids:
        if target_dir is not None:
            td = Path(target_dir)
            if (td / universe).exists() or not (td / f"families_{universe}").exists():
                u_dir = td / universe if universe in ("demo", "public", "sandbox", "test") else td
                fam_dir = u_dir / "families"
            else:
                fam_dir = td / (f"families_{universe}" if universe != "public" else "families")
            fam_dir.mkdir(parents=True, exist_ok=True)
            fam_db_path = fam_dir / f"{fid}.db"
        else:
            fam_db_path = config.get_family_db_path(fid, universe=universe)
        fam_db_path.parent.mkdir(parents=True, exist_ok=True)
        fam_report: Dict[str, int] = {}

        with sqlite3.connect(str(src_path)) as src_conn, sqlite3.connect(str(fam_db_path)) as f_conn:
            _enable_wal(src_conn)
            _enable_wal(f_conn)
            src_tables = _get_existing_tables(src_conn)

            # Replicate and populate Meta & Auth Tables for this family
            for mt in META_TABLES_FOR_FAMILY:
                if mt in src_tables:
                    _replicate_table_schema(src_conn, f_conn, mt)
                    if mt in ("_schema_migrations", "alembic_version"):
                        cnt = _copy_table_rows(src_conn, f_conn, mt)
                    else:
                        cnt = _copy_table_rows(src_conn, f_conn, mt, where_clause="family_id = ?", params=(fid,))
                    fam_report[mt] = cnt

            # Replicate and populate Domain Tables
            for dt in DOMAIN_TABLES:
                if dt in src_tables:
                    _replicate_table_schema(src_conn, f_conn, dt)
                    if dt == "fmv_history":
                        # fmv_history is linked via company_id
                        cnt = _copy_table_rows(
                            src_conn,
                            f_conn,
                            dt,
                            where_clause="company_id IN (SELECT company_id FROM equity_companies WHERE family_id = ?)",
                            params=(fid,),
                        )
                    else:
                        cnt = _copy_table_rows(src_conn, f_conn, dt, where_clause="family_id = ?", params=(fid,))
                    fam_report[dt] = cnt

            f_conn.commit()

        report["families_migrated"][fid] = fam_report
        if verbose:
            total_records = sum(fam_report.values())
            print(f"  [FAMILY {fid}] Migrated into {fam_db_path.name}: {total_records} total records across {len(fam_report)} tables")

    if verbose:
        print(f"[COMPLETE] Migration finished for universe={universe}. Total families: {len(family_ids)}")

    return report


def migrate_all(dry_run: bool = False, verbose: bool = True) -> Dict[str, Any]:
    """Migrates all discovered monolithic databases in data/ directory."""
    results: Dict[str, Any] = {}
    universe_map = {
        "public": config.get_db_path_for_universe("public"),
        "demo": config.get_db_path_for_universe("demo"),
        "test": config.get_db_path_for_universe("test"),
    }

    for universe, db_path in universe_map.items():
        if db_path.exists():
            res = migrate_database(db_path, universe=universe, dry_run=dry_run, verbose=verbose)
            results[universe] = res

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate HVL Family Office from monolithic DB to DB-per-family architecture.")
    parser.add_argument("--universe", choices=["public", "demo", "beta", "test", "all"], default="all", help="Target universe to migrate (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and report tables and families without writing")
    parser.add_argument("--verbose", action="store_true", default=True, help="Print detailed progress logs")
    args = parser.parse_args()

    target_universe = "demo" if args.universe == "beta" else args.universe
    if target_universe == "all":
        migrate_all(dry_run=args.dry_run, verbose=args.verbose)
    else:
        db_path = config.get_db_path_for_universe(target_universe)
        migrate_database(db_path, universe=target_universe, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
