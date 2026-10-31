"""
High Velocity Labs Shared Web Middleware, Rate Limiting & Background Jobs (`hvl_common.web`).
"""

from hvl_common.web.bugs import (
    GENERIC_WORDS,
    NON_MONETARY_KEYS,
    anonymize_structure,
    scrub_explanatory_text,
)
from hvl_common.web.jobs import (
    JobManager,
    cleanup_old_jobs,
    get_job,
    should_run_synchronously,
    submit_job,
)
from hvl_common.web.lifecycle import create_hvl_lifecycle_blueprint
from hvl_common.web.notifications import (
    create_notifications_blueprint,
    dispatch_web_push,
    get_merged_notifications,
    notify_and_push_member,
    render_notifications_fragment_response,
)
from hvl_common.web.push_routes import register_push_routes
from hvl_common.web.pwa import (
    build_pwa_manifest,
    get_vapid_public_key,
    register_hvl_pwa_routes,
)
from hvl_common.web.rate_limit import (
    RateLimiter,
    parse_rate_limits,
    rate_limit,
    reset_rate_limits,
)
from hvl_common.web.security import (
    apply_hvl_security_headers,
    apply_hvl_session_config,
    check_csrf_origin,
    compute_asset_version,
    get_site_admin_emails,
    is_verified_site_admin,
    require_site_admin,
)
from hvl_common.web.siri import MAX_USER_MESSAGE_CHARS, create_siri_blueprint

__all__ = [
    "GENERIC_WORDS",
    "JobManager",
    "MAX_USER_MESSAGE_CHARS",
    "NON_MONETARY_KEYS",
    "RateLimiter",
    "anonymize_structure",
    "apply_hvl_security_headers",
    "apply_hvl_session_config",
    "build_pwa_manifest",
    "check_csrf_origin",
    "cleanup_old_jobs",
    "compute_asset_version",
    "create_hvl_lifecycle_blueprint",
    "create_notifications_blueprint",
    "create_siri_blueprint",
    "dispatch_web_push",
    "get_job",
    "get_merged_notifications",
    "get_site_admin_emails",
    "get_vapid_public_key",
    "is_verified_site_admin",
    "notify_and_push_member",
    "parse_rate_limits",
    "rate_limit",
    "register_hvl_pwa_routes",
    "register_push_routes",
    "render_notifications_fragment_response",
    "require_site_admin",
    "reset_rate_limits",
    "scrub_explanatory_text",
    "should_run_synchronously",
    "submit_job",
]
