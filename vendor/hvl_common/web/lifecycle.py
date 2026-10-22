"""
Shared HVL Lifecycle Health & Version Blueprint.
Registers /health, /api/health, /healthz, and /api/version endpoints.
"""

from __future__ import annotations

from typing import Callable

from flask import Blueprint, jsonify


def create_hvl_lifecycle_blueprint(
    service_name: str | Callable[[], str],
    *,
    is_beta_fn: Callable[[], bool] | None = None,
    asset_version_fn: Callable[[], str] | str | None = None,
) -> Blueprint:
    """Creates a Flask Blueprint registering /health, /api/health, /healthz, and /api/version."""
    bp = Blueprint("hvl_lifecycle", __name__)

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

        return jsonify({
            "status": "ok",
            "service": resolved_service,
            "app": resolved_service.removesuffix("-beta"),
            "beta_instance": resolved_beta,
            "is_beta": resolved_beta,
            "version": resolved_version,
        })

    return bp
