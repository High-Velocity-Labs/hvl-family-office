"""
The shared `dashboard` Flask blueprint. Route modules (`routes/dashboard.py`, `routes/accounts.py`) register on it,
so neither has to import the other.
"""

from __future__ import annotations

from flask import Blueprint

dashboard_bp = Blueprint("dashboard", __name__)
