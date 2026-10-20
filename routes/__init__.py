"""
Routes Package Initialization.
Aggregates and registers all modular Flask Blueprints.
"""

from __future__ import annotations
from flask import Flask

from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.equity import equity_bp
from routes.tax import tax_bp
from routes.philanthropy import philanthropy_bp
from routes.gifting import gifting_bp
from routes.education import education_bp
from routes.compensation import compensation_bp
from routes.family import family_bp
from routes.scenarios import scenarios_bp
from routes.settings import settings_bp
from routes.ai_advisor import ai_advisor_bp
from routes.estate import estate_bp
from routes.desktop import desktop_bp
from routes.sandbox import sandbox_bp
from routes.bugs import bugs_bp

__all__ = [
    "auth_bp",
    "dashboard_bp",
    "equity_bp",
    "tax_bp",
    "philanthropy_bp",
    "gifting_bp",
    "education_bp",
    "compensation_bp",
    "family_bp",
    "scenarios_bp",
    "settings_bp",
    "ai_advisor_bp",
    "estate_bp",
    "desktop_bp",
    "sandbox_bp",
    "bugs_bp",
    "register_blueprints",
]


def register_blueprints(app: Flask) -> None:
    """Registers all application blueprints on the provided Flask app instance."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(equity_bp)
    app.register_blueprint(tax_bp)
    app.register_blueprint(philanthropy_bp)
    app.register_blueprint(gifting_bp)
    app.register_blueprint(education_bp)
    app.register_blueprint(compensation_bp)
    app.register_blueprint(family_bp)
    app.register_blueprint(scenarios_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(ai_advisor_bp)
    app.register_blueprint(estate_bp)
    app.register_blueprint(desktop_bp)
    app.register_blueprint(sandbox_bp)
    app.register_blueprint(bugs_bp)

    @app.context_processor
    def _inject_sandbox_template_context():
        from routes.helpers import is_sandbox_session, get_current_family_id
        from routes.sandbox import get_resumable_sandbox_lease
        from services.sandbox_service import get_sandbox_lease_info
        is_sb = is_sandbox_session()
        fid = get_current_family_id() if is_sb else 0
        lease = get_sandbox_lease_info(fid) if (is_sb and fid > 0) else None
        _, _, resumable_lease = get_resumable_sandbox_lease()
        return {
            "is_sandbox": is_sb,
            "sandbox_lease": lease,
            "resumable_sandbox_lease": lease or resumable_lease,
        }
