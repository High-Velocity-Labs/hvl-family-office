"""The Flask app is built by `wsgi.py` (what gunicorn loads), never as a side effect of importing `app`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask

import app as app_module
from wsgi import app as wsgi_app


def test_importing_app_module_builds_no_app():
    assert not hasattr(app_module, "app")
    assert callable(app_module.create_app)


def test_wsgi_exposes_the_served_app_and_create_app_builds_a_fresh_one():
    assert isinstance(wsgi_app, Flask)
    other = app_module.create_app()
    assert isinstance(other, Flask) and other is not wsgi_app
