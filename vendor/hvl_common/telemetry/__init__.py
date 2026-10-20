"""
High Velocity Labs Zero-Cost Operational Telemetry (`hvl_common.telemetry`).
"""

from hvl_common.telemetry.middleware import register_telemetry
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
    "TelemetryStore",
    "clear_telemetry_events",
    "get_default_telemetry_db_path",
    "get_telemetry_events",
    "get_telemetry_summary",
    "record_telemetry_event",
    "register_telemetry",
    "sanitize_telemetry_detail",
    "sanitize_telemetry_path",
]
