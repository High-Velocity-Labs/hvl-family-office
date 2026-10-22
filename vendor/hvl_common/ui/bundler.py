"""
hvl_common.ui.bundler: Pure Python Asset Compilation and Bundling Pipeline.
Standardizes concatenation and bundling of CSS and JavaScript assets across
all High Velocity Labs applications without requiring Node.js, npm, or webpack.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_FILENAME = "bundle_config.json"


def bundle_css_files(output_path: Path, source_paths: list[Path], project_name: str = "HVL") -> int:
    """Concatenates CSS files into a single bundle with source markers."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = [f"/* {project_name} Consolidated CSS Bundle: {output_path.name} */\n"]
    for src in source_paths:
        if not src.exists():
            raise FileNotFoundError(f"Missing CSS source: {src}")
        content = src.read_text(encoding="utf-8")
        parts.append(f"\n/* --- Source: {src.name} --- */\n")
        parts.append(content)
    output_path.write_text("\n".join(parts), encoding="utf-8")
    return output_path.stat().st_size


def bundle_js_files(output_path: Path, source_paths: list[Path], project_name: str = "HVL") -> int:
    """Concatenates JS files into a single bundle with defensive semicolon boundaries."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = [f"/* {project_name} Consolidated JS Bundle: {output_path.name} */\n"]
    for src in source_paths:
        if not src.exists():
            raise FileNotFoundError(f"Missing JS source: {src}")
        content = src.read_text(encoding="utf-8")
        parts.append(f"\n/* --- Source: {src.name} --- */\n;\n")
        parts.append(content)
        parts.append("\n;\n")
    output_path.write_text("".join(parts), encoding="utf-8")
    return output_path.stat().st_size


def build_bundles(
    project_root: Path | str,
    config_path: Path | str | None = None,
    silent: bool = False,
) -> dict[str, int]:
    """
    Reads bundle_config.json from project_root (or config_path) and compiles
    all declared CSS and JS bundles. Returns a dict mapping bundle filename to byte size.
    """
    root = Path(project_root).resolve()
    cfg_file = Path(config_path).resolve() if config_path else root / DEFAULT_CONFIG_FILENAME
    if not cfg_file.exists():
        if not silent:
            print(f"[BUNDLER] No '{DEFAULT_CONFIG_FILENAME}' found in {root}. Skipping bundle compilation.")
        return {}

    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to parse {cfg_file}: {e}") from e

    out_rel = cfg.get("output_dir", "static/vendor")
    out_dir = root / out_rel
    out_dir.mkdir(parents=True, exist_ok=True)
    project_name = cfg.get("project_name", root.name.replace("-", " ").title())

    results: dict[str, int] = {}

    # Compile CSS bundles
    css_targets = cfg.get("css", {})
    for out_name, src_list in css_targets.items():
        sources = [root / p for p in src_list]
        out_file = out_dir / out_name
        size = bundle_css_files(out_file, sources, project_name=project_name)
        results[out_name] = size

    # Compile JS bundles
    js_targets = cfg.get("js", {})
    for out_name, src_list in js_targets.items():
        sources = [root / p for p in src_list]
        out_file = out_dir / out_name
        size = bundle_js_files(out_file, sources, project_name=project_name)
        results[out_name] = size

    if not silent:
        print(f"[BUNDLER] Compiled {len(results)} bundles for {project_name} -> {out_dir.relative_to(root)}:")
        for name, sz in results.items():
            kb = round(sz / 1024, 1)
            print(f"  • {name}: {sz:,} bytes ({kb} KB)")

    return results


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    build_bundles(target)
