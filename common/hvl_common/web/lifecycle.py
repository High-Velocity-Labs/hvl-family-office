"""
Shared HVL Lifecycle Health & Version Blueprint.
Registers /health, /api/health, /healthz, and /api/version endpoints.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Callable

from flask import Blueprint, jsonify


def _is_hex_sha(value: str) -> bool:
    return len(value) == 40 and all(ch in "0123456789abcdef" for ch in value)


def _read_startup_git_sha(base_dir: Path | str | None = None) -> str:
    """Reads the deployed 40-char git SHA once at startup from `.deploy_commit_sha` / `.public_commit_sha` or git."""
    roots: list[Path] = []
    if base_dir is not None:
        roots.append(Path(base_dir).resolve())
    try:
        roots.append(Path.cwd().resolve())
    except OSError:  # OS boundary: deleted or inaccessible working directory falls back to module parent paths
        pass
    here = Path(__file__).resolve()
    roots.extend(here.parents[:4])

    seen_dirs: set[Path] = set()
    for directory in roots:
        if directory in seen_dirs:
            continue
        seen_dirs.add(directory)
        for marker in (".deploy_commit_sha", ".public_commit_sha"):
            marker_path = directory / marker
            try:
                if marker_path.is_file():
                    sha = marker_path.read_text(encoding="utf-8").strip().lower()
                    if _is_hex_sha(sha):
                        return sha
            except OSError:  # filesystem boundary: unreadable marker file falls back to next candidate
                continue

    git_cwds: list[str | None] = [str(Path(base_dir).resolve())] if base_dir is not None else [None, str(here.parent)]
    for cwd in git_cwds:
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):  # process boundary: missing git or non-repo dir returns ""
            continue
        sha = (res.stdout or "").strip().lower()
        if res.returncode == 0 and _is_hex_sha(sha):
            return sha
    return ""


def create_hvl_lifecycle_blueprint(
    service_name: str | Callable[[], str],
    *,
    is_beta_fn: Callable[[], bool] | None = None,
    asset_version_fn: Callable[[], str] | str | None = None,
    git_sha_fn: Callable[[], str] | str | None = None,
) -> Blueprint:
    """Creates a Flask Blueprint registering /health, /api/health, /healthz, and /api/version."""
    bp = Blueprint("hvl_lifecycle", __name__)
    startup_git_sha = _read_startup_git_sha() if git_sha_fn is None else ""

    @bp.route("/health", methods=["GET", "HEAD"])
    @bp.route("/api/health", methods=["GET", "HEAD"])
    @bp.route("/healthz", methods=["GET", "HEAD"])
    @bp.route("/api/version", methods=["GET", "HEAD"])
    def lifecycle_status():
        resolved_service = str(
            service_name() if callable(service_name) else service_name
        )
        resolved_beta = (
            bool(is_beta_fn()) if callable(is_beta_fn) else bool(is_beta_fn)
        )
        if asset_version_fn is None:
            resolved_version = ""
        elif callable(asset_version_fn):
            resolved_version = str(asset_version_fn() or "")
        else:
            resolved_version = str(asset_version_fn)

        if git_sha_fn is None:
            resolved_git_sha = startup_git_sha
        elif callable(git_sha_fn):
            resolved_git_sha = str(git_sha_fn() or "")
        else:
            resolved_git_sha = str(git_sha_fn)

        return jsonify({
            "status": "ok",
            "service": resolved_service,
            "app": resolved_service.removesuffix("-beta"),
            "beta_instance": resolved_beta,
            "is_beta": resolved_beta,
            "version": resolved_version,
            "git_sha": resolved_git_sha,
        })

    return bp
