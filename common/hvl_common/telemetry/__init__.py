"""
High Velocity Labs Zero-Cost Operational Telemetry (`hvl_common.telemetry`).
"""

from hvl_common.telemetry.middleware import register_telemetry
from hvl_common.telemetry.portal import (
    VALID_PORTAL_UNIVERSES,
    compute_request_session_hash,
    ensure_portal_telemetry_table,
    get_portal_telemetry_counts,
    normalize_portal_universe,
    record_portal_telemetry_event,
    resolve_telemetry_audience,
)
from hvl_common.telemetry.store import (
    EVENT_ERROR_500,
    EVENT_JOB_ERROR,
    EVENT_RATE_LIMIT,
    EVENT_SLOW_REQUEST,
    VALID_EVENT_TYPES,
    TelemetryStore,
    clear_telemetry_events,
    get_default_telemetry_db_path,
    get_telemetry_events,
    get_telemetry_summary,
    record_telemetry_event,
    sanitize_telemetry_detail,
    sanitize_telemetry_path,
)

__all__ = [
    "EVENT_ERROR_500",
    "EVENT_JOB_ERROR",
    "EVENT_RATE_LIMIT",
    "EVENT_SLOW_REQUEST",
    "VALID_EVENT_TYPES",
    "VALID_PORTAL_UNIVERSES",
    "TelemetryStore",
    "clear_telemetry_events",
    "compute_request_session_hash",
    "ensure_portal_telemetry_table",
    "get_default_telemetry_db_path",
    "get_portal_telemetry_counts",
    "get_telemetry_events",
    "get_telemetry_summary",
    "normalize_portal_universe",
    "record_portal_telemetry_event",
    "record_telemetry_event",
    "register_telemetry",
    "resolve_telemetry_audience",
    "sanitize_telemetry_detail",
    "sanitize_telemetry_path",
]
