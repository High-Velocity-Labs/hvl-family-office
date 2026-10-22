"""
scripts/build_assets.py: Asset compilation and bundling entrypoint for HVL Family Office.
Delegates to centralized `hvl_common.ui.bundler` using `bundle_config.json`.
"""

from __future__ import annotations

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "vendor"))

from hvl_common.ui.bundler import build_bundles  # noqa: E402


def build_all() -> dict[str, int]:
    return build_bundles(BASE_DIR)


if __name__ == "__main__":
    build_all()
