"""The conftest sweep deletes data dirs that crashed or killed test sessions left in the temp dir, and nothing else."""

from __future__ import annotations
import os
import subprocess
import sys
import time

from conftest import _DATA_DIR_PREFIX, _OWNER_PID_FILE, _sweep_dead_session_data_dirs


def _dead_pid() -> int:
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    return finished.pid


def _make_dir(root, name, owner_pid=None, age_seconds=0):
    leftover = root / f"{_DATA_DIR_PREFIX}{name}"
    leftover.mkdir()
    if owner_pid is not None:
        (leftover / _OWNER_PID_FILE).write_text(str(owner_pid))
    stamp = time.time() - age_seconds
    os.utime(leftover, (stamp, stamp))
    return leftover


def test_sweep_removes_only_dirs_whose_session_is_gone(tmp_path):
    crashed = _make_dir(tmp_path, "crashed", owner_pid=_dead_pid())
    running = _make_dir(tmp_path, "running", owner_pid=os.getpid())
    old_unowned = _make_dir(tmp_path, "old", age_seconds=2 * 24 * 3600)
    new_unowned = _make_dir(tmp_path, "new")
    unrelated = tmp_path / "other_tool_dir"
    unrelated.mkdir()

    _sweep_dead_session_data_dirs(tmp_path)

    assert not crashed.exists()
    assert not old_unowned.exists()
    assert running.exists()
    assert new_unowned.exists()
    assert unrelated.exists()
