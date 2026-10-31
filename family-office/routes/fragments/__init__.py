"""
F-UI-4 server-rendered HTML fragments (htmx targets) that used to be built as strings in the browser.
Every submodule in this package adds its routes to `ui_fragments_bp`; they are imported here so one registration covers all.
"""

from __future__ import annotations

import importlib
import pkgutil

from flask import Blueprint

ui_fragments_bp = Blueprint("ui_fragments", __name__)

for _mod in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_mod.name}")
