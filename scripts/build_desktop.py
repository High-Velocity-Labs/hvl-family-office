#!/usr/bin/env python3
"""
Cross-Platform Desktop Installer Builder for HVL Family Office.
Builds standalone application bundles using PyInstaller:
- macOS:   dist/HVL Family Office.app and dist/HVL-Family-Office-macOS.dmg
- Windows: dist/HVL-Family-Office/HVL-Family-Office.exe (and Setup.exe if Inno Setup is installed)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SPEC_FILE = BASE_DIR / "packaging" / "family_office.spec"
DIST_DIR = BASE_DIR / "dist"


def build_desktop_bundle() -> int:
    if not SPEC_FILE.exists():
        print(f"[ERROR] Spec file not found: {SPEC_FILE}")
        return 1

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_FILE)]
    print(f"--> Running PyInstaller: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode != 0:
        return res.returncode

    if sys.platform == "darwin":
        app_bundle = DIST_DIR / "HVL Family Office.app"
        dmg_out = DIST_DIR / "HVL-Family-Office-macOS.dmg"
        if app_bundle.exists() and shutil.which("hdiutil"):
            if dmg_out.exists():
                dmg_out.unlink()
            print(f"--> Creating macOS disk image: {dmg_out}")
            subprocess.run(
                [
                    "hdiutil",
                    "create",
                    "-volname",
                    "HVL Family Office",
                    "-srcfolder",
                    str(app_bundle),
                    "-ov",
                    "-format",
                    "UDZO",
                    str(dmg_out),
                ],
                check=False,
            )
    elif sys.platform == "win32":
        iscc = shutil.which("iscc")
        if not iscc:
            default_iscc = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
            if default_iscc.exists():
                iscc = str(default_iscc)
        iss_file = BASE_DIR / "packaging" / "installer_windows.iss"
        if iscc and iss_file.exists():
            print("--> Compiling Windows Setup.exe with Inno Setup...")
            subprocess.run([iscc, str(iss_file)], cwd=str(BASE_DIR / "packaging"), check=False)

    print(f"--> Build complete! Artifacts in {DIST_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build_desktop_bundle())
