# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Specification for HVL Family Office Local Desktop App (Windows .exe & macOS .app).
Bundles Flask templates, static assets, Alembic configs and revisions, and hvl_common from the sibling `common/` of the monorepo.
"""

from pathlib import Path
import sys

SPEC_DIR = Path(SPECPATH).resolve()
ROOT_DIR = SPEC_DIR.parent

datas = [
    (str(ROOT_DIR / "templates"), "templates"),
    (str(ROOT_DIR / "static"), "static"),
    (str(ROOT_DIR / "alembic"), "alembic"),
    (str(ROOT_DIR / "alembic.ini"), "."),
]

COMMON_DIR = ROOT_DIR.parent / "common"
if not (COMMON_DIR / "hvl_common").is_dir():
    raise SystemExit(f"{COMMON_DIR / 'hvl_common'} is missing: build from a monorepo checkout (family-office/ beside common/).")
datas.append((str(COMMON_DIR / "hvl_common"), "hvl_common"))

hiddenimports = [
    "waitress",
    "sqlalchemy.dialects.sqlite",
    "cryptography.hazmat.primitives.kdf.pbkdf2",
    "hvl_common",
    "hvl_common.auth",
    "hvl_common.db",
    "hvl_common.security",
    "hvl_common.web",
]

a = Analysis(
    [str(ROOT_DIR / "desktop_app.py")],
    pathex=[str(ROOT_DIR), str(COMMON_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

_ICON_ICNS = SPEC_DIR / "app_icon.icns"
_ICON_ICO = SPEC_DIR / "app_icon.ico"
_EXE_ICON = str(_ICON_ICNS if sys.platform == "darwin" and _ICON_ICNS.exists() else (_ICON_ICO if _ICON_ICO.exists() else "")) or None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HVL-Family-Office",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=_EXE_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HVL-Family-Office",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="HVL Family Office.app",
        icon=str(_ICON_ICNS) if _ICON_ICNS.exists() else None,
        bundle_identifier="dev.highvelocitylabs.familyoffice",
        info_plist={
            "CFBundleName": "HVL Family Office",
            "CFBundleDisplayName": "HVL Family Office",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
