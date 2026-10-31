"""Jinja filters shared by templates that render server-side what the browser used to format."""

from __future__ import annotations

from routes.fragments import ui_fragments_bp
from ssr.formatting import fmt_short_currency


@ui_fragments_bp.app_template_filter("fmt_short_currency")
def fmt_short_currency_filter(value: object) -> str:
    return fmt_short_currency(value)
