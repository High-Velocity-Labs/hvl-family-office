"""The bug report's server version line carries the app's real asset version."""

from __future__ import annotations

import app as app_module
from services.bug_reporter_manifests import _resolve_app_version


def test_report_version_carries_nonempty_server_asset_version(monkeypatch):
    monkeypatch.setattr(app_module, "ASSET_VERSION", "abc12345-1700000000")
    assert "(abc12345)" in _resolve_app_version()


def test_report_version_with_real_asset_version_has_sha():
    assert app_module.ASSET_VERSION
    sha = app_module.ASSET_VERSION.split("-")[0]
    assert f"({sha})" in _resolve_app_version()
