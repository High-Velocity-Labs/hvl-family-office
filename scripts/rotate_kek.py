"""
Zero-Downtime Key Encryption Key (KEK) Rotation Utility (`MultiFernet`).

Re-encrypts every tenant's Data Encryption Key (`families.encryption_key_enc`)
under a new primary root KEK in a single atomic transaction per SQLite database,
without needing to touch or re-encrypt any row-level financial or PII records.

Usage:
    python scripts/rotate_kek.py --generate --update-env
    python scripts/rotate_kek.py --new-key <BASE64_FERNET_KEY> --db-path data/family_office.db
    python scripts/rotate_kek.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from cryptography.fernet import Fernet, MultiFernet
from dotenv import set_key

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if (BASE_DIR / "vendor").exists() and str(BASE_DIR / "vendor") not in sys.path:
    sys.path.append(str(BASE_DIR / "vendor"))

from hvl_common.db import get_db_connection
import security


def default_database_paths() -> List[Path]:
    """Returns existing default database files (`family_office.db` and `family_office_beta.db`)."""
    candidates = [
        BASE_DIR / "data" / "family_office.db",
        BASE_DIR / "data" / "family_office_beta.db",
    ]
    existing = [p for p in candidates if p.exists()]
    return existing or [candidates[0]]


def rotate_databases(
    db_paths: Sequence[Union[str, Path]],
    new_key: Optional[Union[bytes, str]] = None,
    old_keys: Optional[Sequence[Union[bytes, str]]] = None,
    dry_run: bool = False,
    update_env: bool = False,
    env_file: Optional[Path] = None,
    key_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Rotates family DEKs across one or more SQLite databases using `MultiFernet`.
    If `dry_run=True`, verifies that all existing `encryption_key_enc` tokens can be
    decrypted and rotated without committing writes.
    """
    current_raw = security.get_or_create_key()
    current_keys = security._parse_fernet_keys(current_raw)

    if new_key is not None:
        parsed_new = security._parse_fernet_keys(new_key)
        if not parsed_new:
            raise ValueError("Invalid --new-key provided")
        primary_key = parsed_new[0]
    else:
        primary_key = current_keys[0]

    prior_keys: List[bytes] = []
    if old_keys is not None:
        for k in old_keys:
            for pk in security._parse_fernet_keys(k):
                if pk != primary_key and pk not in prior_keys:
                    prior_keys.append(pk)
    else:
        for pk in current_keys:
            if pk != primary_key and pk not in prior_keys:
                prior_keys.append(pk)

    all_keys = [primary_key, *prior_keys]
    multi = MultiFernet([Fernet(k) for k in all_keys])

    results_by_db: Dict[str, Any] = {}
    total_rotated = 0

    for raw_path in db_paths:
        path_obj = Path(raw_path)
        if not path_obj.exists():
            results_by_db[str(path_obj)] = {"rotated_count": 0, "family_ids": [], "skipped": True}
            continue

        if dry_run:
            security.init_db(path_obj)
            fids: List[int] = []
            with get_db_connection(path_obj, timeout=30.0) as conn:
                rows = conn.execute(
                    "SELECT family_id, encryption_key_enc FROM families ORDER BY family_id ASC"
                ).fetchall()
                for row in rows:
                    fid = int(row[0])
                    enc_dek = row[1]
                    if not enc_dek:
                        continue
                    # Verify decryption and rotation succeed without writing
                    _ = multi.rotate(str(enc_dek).encode("utf-8"))
                    fids.append(fid)
            res = {"rotated_count": len(fids), "family_ids": fids, "dry_run": True}
        else:
            res = security.rotate_family_keys(
                path_obj,
                new_kek=primary_key,
                old_keks=prior_keys,
            )

        results_by_db[str(path_obj)] = res
        total_rotated += int(res.get("rotated_count", 0))

    combined_key_str = ",".join(k.decode("utf-8") for k in all_keys)

    if update_env and not dry_run:
        target_env = env_file or security.ENV_FILE
        target_key_file = key_file or security.KEY_FILE
        target_env.touch(exist_ok=True)
        set_key(str(target_env), "APP_ENCRYPTION_KEY", combined_key_str)
        target_key_file.parent.mkdir(parents=True, exist_ok=True)
        target_key_file.write_bytes(combined_key_str.encode("utf-8"))
        os.environ["APP_ENCRYPTION_KEY"] = combined_key_str
        security._clear_security_caches()

    return {
        "primary_key": primary_key.decode("utf-8"),
        "active_keyring": combined_key_str,
        "total_rotated": total_rotated,
        "databases": results_by_db,
        "dry_run": dry_run,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rotate the root Key Encryption Key (KEK) across HVL Family Office databases using MultiFernet."
    )
    parser.add_argument(
        "--db-path",
        action="append",
        dest="db_paths",
        help="Path to SQLite database file (can be specified multiple times; defaults to public + beta DBs).",
    )
    parser.add_argument(
        "--new-key",
        dest="new_key",
        default=None,
        help="New primary 32-byte URL-safe base64 Fernet key.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate a fresh cryptographically secure Fernet key as the new primary KEK.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify DEK decryption and rotation without modifying databases or .env.",
    )
    parser.add_argument(
        "--update-env",
        action="store_true",
        help="Persist '<new_key>,<old_key>' to .env and .mm/.secret.key after rotation.",
    )

    args = parser.parse_args(argv)
    db_paths = [Path(p) for p in args.db_paths] if args.db_paths else default_database_paths()

    new_key: Optional[bytes] = None
    if args.new_key:
        new_key = args.new_key.strip().encode("utf-8")
    elif args.generate:
        new_key = Fernet.generate_key()

    summary = rotate_databases(
        db_paths=db_paths,
        new_key=new_key,
        dry_run=args.dry_run,
        update_env=args.update_env,
    )

    mode = "DRY-RUN" if args.dry_run else "ROTATED"
    print(f"[{mode}] Total family DEKs processed: {summary['total_rotated']}")
    for db_str, info in summary["databases"].items():
        print(f"  - {db_str}: {info.get('rotated_count', 0)} families ({info.get('family_ids', [])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
