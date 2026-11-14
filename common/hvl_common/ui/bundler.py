"""
hvl_common.ui.bundler: Pure Python Asset Compilation and Bundling Pipeline.
Standardizes concatenation and bundling of CSS and JavaScript assets across
all High Velocity Labs applications without requiring Node.js, npm, or webpack.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_CONFIG_FILENAME = "bundle_config.json"

HVL_CSS_SCOPES: dict[str, tuple[str, ...]] = {
    "core": ("theme.css", "components.css", "cards.css", "forms.css", "scrollbars.css"),
    "subnav": ("subnav.css",),
    "sidebar": ("sidebar.css",),
    "modal": ("modal-dialog.css", "settings-modal.css"),
    "chat": ("chat-drawer.css",),
    "notifications": ("notifications-drawer.css",),
}

HVL_JS_SCOPES: dict[str, tuple[str, ...]] = {
    "htmx": ("htmx.min.js", "htmx_config.js", "idiomorph-ext.min.js"),
    "core": ("utils.js",),
    "subnav": ("subnav.js",),
    "modal": ("modal-dialog.js", "bug-reporter.js"),
    "chat": ("marked.min.js", "chat-drawer.js", "chat-attachments.js"),
    "notifications": ("notifications-drawer.js", "device-integrations.js"),
    "toast": ("toast.js",),
    "signals": ("version_pill.js", "reactive-signals.js"),
}


def _parse_scope_names(
    scopes: str | Iterable[str] | None,
    valid_scopes: dict[str, tuple[str, ...]],
) -> list[str]:
    if scopes is None:
        return []
    raw_items = [s.strip() for s in scopes.split(",")] if isinstance(scopes, str) else [str(s).strip() for s in scopes]
    resolved: list[str] = []
    for item in raw_items:
        key = item[5:] if item.startswith("@hvl:") else item
        for candidate in (list(valid_scopes) if key == "all" else ([key] if key in valid_scopes else [])):
            if candidate not in resolved:
                resolved.append(candidate)
    return resolved


def resolve_hvl_css_files(
    scopes: str | Iterable[str] | None = None,
    *,
    subnav: bool = True,
    sidebar: bool = True,
    modal: bool = True,
    chat: bool = True,
    notifications: bool = True,
) -> list[str]:
    """Return deduplicated HVL shared CSS filenames in canonical order."""
    if scopes is not None:
        active_scopes = _parse_scope_names(scopes, HVL_CSS_SCOPES)
    else:
        flags = (("core", True), ("subnav", subnav), ("sidebar", sidebar), ("modal", modal), ("chat", chat), ("notifications", notifications))
        active_scopes = [name for name, enabled in flags if enabled]

    files: list[str] = []
    for scope_name in active_scopes:
        for fname in HVL_CSS_SCOPES.get(scope_name, ()):
            if fname not in files:
                files.append(fname)
    return files


def resolve_hvl_js_files(
    scopes: str | Iterable[str] | None = None,
    *,
    htmx: bool = True,
    subnav: bool = True,
    modal: bool = True,
    chat: bool = True,
    notifications: bool = True,
    toast: bool = True,
    signals: bool = False,
) -> list[str]:
    """Return deduplicated HVL shared JS filenames in canonical order (with marked.min.js before chat-drawer.js)."""
    if scopes is not None:
        active_scopes = _parse_scope_names(scopes, HVL_JS_SCOPES)
        files: list[str] = []
        for scope_name in active_scopes:
            for fname in HVL_JS_SCOPES.get(scope_name, ()):
                if fname not in files:
                    files.append(fname)
    else:
        files = []
        if htmx:
            files.extend(HVL_JS_SCOPES["htmx"])
        if chat:
            files.append("marked.min.js")
        if subnav:
            files.extend(HVL_JS_SCOPES["subnav"])
        files.extend(HVL_JS_SCOPES["core"])
        if modal:
            files.extend(HVL_JS_SCOPES["modal"])
        if chat:
            files.extend(f for f in HVL_JS_SCOPES["chat"] if f != "marked.min.js")
        if notifications:
            files.extend(HVL_JS_SCOPES["notifications"])
        if toast:
            files.extend(HVL_JS_SCOPES["toast"])
        if signals:
            files.extend(HVL_JS_SCOPES["signals"])

    if "marked.min.js" in files and "chat-drawer.js" in files:
        if files.index("marked.min.js") > files.index("chat-drawer.js"):
            files.remove("marked.min.js")
            files.insert(files.index("chat-drawer.js"), "marked.min.js")
    return files


def _resolve_hvl_static_dir(project_root: Path) -> Path:
    """`@hvl:` scopes come from the installed hvl_common (`-e ../common`), the same code the app's tests run against."""
    return Path(__file__).resolve().parent / "static"


def _inside(base: Path, rel: str, *also: Path) -> Path:
    """`base / rel`, refused unless it resolves inside `base` (or one of `also`): bundle_config.json may come from an
    unreviewed commit, and an absolute or `../` path would let a deploy write (or bundle and upload) any file."""
    path = (base / rel).resolve()
    if not any(path.is_relative_to(d.resolve()) for d in (base, *also)):
        raise ValueError(f"bundle path {rel!r} leaves {base}")
    return path


def _expand_bundle_sources(
    project_root: Path,
    src_list: list[str],
    scopes_map: dict[str, tuple[str, ...]],
) -> list[Path]:
    hvl_static = _resolve_hvl_static_dir(project_root)
    paths: list[Path] = []
    seen: set[Path] = set()
    for entry in src_list:
        if entry.startswith("@hvl:"):
            scope_key = entry[5:].strip()
            if scope_key == "all":
                fnames = [f for group in scopes_map.values() for f in group]
            elif scope_key in scopes_map:
                fnames = list(scopes_map[scope_key])
            else:
                raise ValueError(f"Unknown @hvl bundle scope: {entry}")
            target_paths = [(hvl_static / fname).resolve() for fname in fnames]
        else:
            # sources may also come from the sibling common/ (`../common/hvl_common/ui/static/...`), never elsewhere
            target_paths = [_inside(project_root, entry, project_root.parent / "common")]
        for p in target_paths:
            if p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


def _compact_css_for_bundle(content: str) -> str:
    """Packs non-empty CSS lines into compact lines (~320 chars) so .min.css bundles stay <350 lines."""
    non_empty = [line.strip() for line in content.splitlines() if line.strip()]
    out_lines: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in non_empty:
        if cur_len + len(line) + 1 > 320 and cur:
            out_lines.append(" ".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += len(line) + 1
    if cur:
        out_lines.append(" ".join(cur))
    return "\n".join(out_lines)


CSS_IMPORT_RE = re.compile(r"""^\s*@import\s+(?:url\(\s*)?["']?([^"')\s;]+)["']?\s*\)?[^;]*;\s*$""")


def _drop_bundled_imports(src: Path, content: str, bundled: set[Path]) -> str:
    """A browser ignores an @import that is not at the top of a stylesheet, so inside a bundle it would silently
    drop whatever it imports (and the cascade order the separate file had). An @import of a file this bundle already
    holds is removed; any other @import fails the build, so the file gets listed in bundle_config.json instead."""
    kept: list[str] = []
    for line in content.splitlines():
        m = CSS_IMPORT_RE.match(line)
        if not m:
            kept.append(line)
            continue
        target = m.group(1)
        if target.startswith("/common/"):
            resolved = (_resolve_hvl_static_dir(src) / target[len("/common/") :]).resolve()
        else:
            resolved = (src.parent / target).resolve()
        if resolved not in bundled:
            raise ValueError(f"{src}: @import {target} is not in this bundle; list it in bundle_config.json instead")
    return "\n".join(kept)


def bundle_css_files(output_path: Path, source_paths: list[Path], project_name: str = "HVL") -> int:
    """Concatenates CSS files into a single bundle with source markers."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = [f"/* {project_name} Consolidated CSS Bundle: {output_path.name} */"]
    bundled = {src.resolve() for src in source_paths}
    for src in source_paths:
        if not src.exists():
            raise FileNotFoundError(f"Missing CSS source: {src}")
        parts.append(f"/* --- Source: {src.name} --- */")
        content = _drop_bundled_imports(src, src.read_text(encoding="utf-8"), bundled)
        parts.append(_compact_css_for_bundle(content))
    output_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return output_path.stat().st_size


def bundle_js_files(output_path: Path, source_paths: list[Path], project_name: str = "HVL") -> int:
    """Concatenates JS files into a single bundle with defensive semicolon boundaries."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = [f"/* {project_name} Consolidated JS Bundle: {output_path.name} */\n"]
    for src in source_paths:
        if not src.exists():
            raise FileNotFoundError(f"Missing JS source: {src}")
        parts.append(f"\n/* --- Source: {src.name} --- */\n;\n")
        parts.append(src.read_text(encoding="utf-8"))
        parts.append("\n;\n")
    output_path.write_text("".join(parts), encoding="utf-8")
    return output_path.stat().st_size


def build_bundles(
    project_root: Path | str,
    config_path: Path | str | None = None,
    silent: bool = False,
) -> dict[str, int]:
    """Reads bundle_config.json and compiles all declared CSS and JS bundles."""
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

    out_dir = _inside(root, cfg.get("output_dir", "static/dist"))
    out_dir.mkdir(parents=True, exist_ok=True)
    project_name = cfg.get("project_name", root.name.replace("-", " ").title())
    results: dict[str, int] = {}

    for out_name, src_list in cfg.get("css", {}).items():
        sources = _expand_bundle_sources(root, src_list, HVL_CSS_SCOPES)
        results[out_name] = bundle_css_files(_inside(out_dir, out_name), sources, project_name=project_name)

    for out_name, src_list in cfg.get("js", {}).items():
        sources = _expand_bundle_sources(root, src_list, HVL_JS_SCOPES)
        results[out_name] = bundle_js_files(_inside(out_dir, out_name), sources, project_name=project_name)

    if not silent:
        print(f"[BUNDLER] Compiled {len(results)} bundles for {project_name} -> {out_dir.relative_to(root)}:")
        for name, sz in results.items():
            print(f"  • {name}: {sz:,} bytes ({round(sz / 1024, 1)} KB)")
    return results


if __name__ == "__main__":
    build_bundles(sys.argv[1] if len(sys.argv) > 1 else ".")
