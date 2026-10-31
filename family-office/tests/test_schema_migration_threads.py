"""Alembic's `op`/`context` proxies are process-wide, so upgrades of different databases from different threads (a
request and a background job) must not run at once (db/schema_migrations.py `_ALEMBIC_RUN_LOCK`)."""

from __future__ import annotations

import threading

from db.schema_migrations import alembic_head_revision, stamped_revision, upgrade_to_head


def test_concurrent_upgrades_of_different_databases_all_reach_head(tmp_path):
    paths = [tmp_path / f"family_{i}.db" for i in range(6)]
    start = threading.Barrier(len(paths))
    errors = []

    def upgrade(path):
        start.wait()
        try:
            upgrade_to_head(path)
        except Exception as exc:  # collected and asserted below
            errors.append(f"{path.name}: {exc!r}")

    threads = [threading.Thread(target=upgrade, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == []
    assert all(stamped_revision(p) == alembic_head_revision() for p in paths)
