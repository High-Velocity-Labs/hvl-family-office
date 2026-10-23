"""
Shared Progressive Web App (PWA) Manifest, Service Worker Route Registration,
and VAPID Public Key Helpers (`hvl_common.web.pwa`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, Response, make_response, send_from_directory

from hvl_common.ui.blueprint import STATIC_DIR


def get_vapid_public_key() -> str:
    """Returns the configured W3C Web Push VAPID public key from environment."""
    return os.environ.get("VAPID_PUBLIC_KEY", "").strip()


def build_pwa_manifest(
    *,
    name: str,
    short_name: str,
    description: str = "",
    theme_color: str = "#0f172a",
    background_color: str = "#0f172a",
    start_url: str = "/",
    icons: list[dict[str, str]] | None = None,
    icon_prefix: str = "hvl-logo",
    orientation: str = "portrait-primary",
) -> dict[str, Any]:
    """Builds the canonical W3C Web App Manifest dictionary for iOS/iPadOS/Android standalone PWAs."""
    clean_prefix = (icon_prefix or "hvl-logo").strip().strip("/")
    resolved_icons = (
        list(icons)
        if icons is not None
        else [
            {
                "src": f"/common/{clean_prefix}-mark.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            },
            {
                "src": f"/common/{clean_prefix}-120.png",
                "sizes": "120x120",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": f"/common/{clean_prefix}-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ]
    )
    return {
        "name": str(name or "High Velocity Labs"),
        "short_name": str(short_name or name or "HVL"),
        "description": str(description or ""),
        "start_url": str(start_url or "/"),
        "display": "standalone",
        "background_color": str(background_color or "#0f172a"),
        "theme_color": str(theme_color or "#0f172a"),
        "orientation": str(orientation or "portrait-primary"),
        "icons": resolved_icons,
    }


def _resolve_sw_directory_and_file(sw_path: Path | str | None) -> tuple[str, str]:
    """Resolves the directory and filename for the Service Worker script."""
    if sw_path is not None:
        p = Path(sw_path).resolve()
        if p.is_dir():
            return str(p), "sw.js"
        if p.exists():
            return str(p.parent), p.name
    return str(STATIC_DIR), "sw.js"


def register_hvl_pwa_routes(
    app: Flask,
    *,
    name: str,
    short_name: str,
    description: str = "",
    icon_prefix: str = "hvl-logo",
    theme_color: str = "#0f172a",
    background_color: str = "#0f172a",
    start_url: str = "/",
    orientation: str = "portrait-primary",
    icons: list[dict[str, str]] | None = None,
    sw_path: Path | str | None = None,
) -> None:
    """Registers `GET /manifest.json` and `GET /sw.js` on a Flask application."""
    manifest_payload = build_pwa_manifest(
        name=name,
        short_name=short_name,
        description=description,
        theme_color=theme_color,
        background_color=background_color,
        start_url=start_url,
        icons=icons,
        icon_prefix=icon_prefix,
        orientation=orientation,
    )
    existing_rules = {rule.rule for rule in app.url_map.iter_rules()}

    if "/manifest.json" not in existing_rules:
        def hvl_pwa_manifest() -> Response:
            resp = make_response(json.dumps(manifest_payload, indent=2), 200)
            resp.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
            return resp

        app.add_url_rule(
            "/manifest.json",
            endpoint="hvl_pwa_manifest",
            view_func=hvl_pwa_manifest,
            methods=["GET"],
        )

    if "/sw.js" not in existing_rules:
        sw_dir, sw_file = _resolve_sw_directory_and_file(sw_path)

        def hvl_pwa_service_worker() -> Response:
            resp = make_response(
                send_from_directory(sw_dir, sw_file, mimetype="application/javascript")
            )
            resp.headers["Service-Worker-Allowed"] = "/"
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        app.add_url_rule(
            "/sw.js",
            endpoint="hvl_pwa_service_worker",
            view_func=hvl_pwa_service_worker,
            methods=["GET"],
        )


__all__ = [
    "build_pwa_manifest",
    "get_vapid_public_key",
    "register_hvl_pwa_routes",
]
