"""
Pytest integration runner for Node.js clientside test suites.
"""

from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def run_node_tests(test_file: str, cwd: Optional[Path] = None) -> None:
    """
    Executes a Node.js test file using node's built-in test runner (`node --test`).
    Raises an AssertionError if the test fails, or pytest.skip if Node is unavailable.
    """
    node_bin = shutil.which("node")
    if not node_bin:
        try:
            import pytest
            pytest.skip("Node.js is not installed on this environment.")
        except ImportError:
            return

    work_dir = str(cwd) if cwd else None
    result = subprocess.run(
        [node_bin, "--test", test_file],
        capture_output=True,
        text=True,
        cwd=work_dir,
    )
    assert result.returncode == 0, (
        f"JavaScript test suite failed ({test_file}):\n"
        f"--- STDOUT ---\n{result.stdout}\n"
        f"--- STDERR ---\n{result.stderr}"
    )
