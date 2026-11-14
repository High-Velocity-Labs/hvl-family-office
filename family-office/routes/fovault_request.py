"""
Request-side helpers shared by every `.fovault` export/restore route.

The passphrase is read from the POST body, used immediately for key derivation, and discarded.
It is never logged, stored in the session, or handed to a background job (job tickets persist).
"""

from __future__ import annotations

import logging
from typing import Any

from flask import jsonify, request, session

from db.telemetry import record_portal_telemetry_event
from routes.context import can_mutate, get_current_family_id, is_sandbox_session
from hvl_common.security import PassphraseEnvelopeError, PassphraseError
from security import fovault_passphrase
from services.fovault_service import PreparedRestore, prepare_fovault_restore

logger = logging.getLogger(__name__)

_TRUTHY = ("1", "true", "on", "yes")


def _body_field(name: str) -> str:
    """Reads a short text field from a JSON or form body (never from the URL query string)."""
    if request.is_json:
        value = (request.get_json(silent=True) or {}).get(name, "")
    else:
        value = request.form.get(name, "")
    return value if isinstance(value, str) else ""


def read_export_passphrase() -> str:
    """Returns the validated export passphrase or raises `PassphraseError`."""
    return fovault_passphrase.validate_export_passphrase(_body_field("passphrase"), _body_field("passphrase_confirm"))


def error_response(message: str, status: int = 400, **extra: Any):
    return jsonify({"success": False, "error": message, **extra}), status


def prepare_restore_from_request(raw_bytes: bytes, universe: str) -> tuple[PreparedRestore | None, Any]:
    """
    Unwraps the uploaded archive's FEK with the posted passphrase before any write or job.
    Returns `(prepared, None)` or `(None, error_response)`. The legacy option is for authenticated, non-sandbox editors only, and logged.
    """
    passphrase = _body_field("passphrase")
    allow_legacy = _body_field("allow_legacy").strip().lower() in _TRUTHY
    if allow_legacy and not (session.get("authenticated") and not is_sandbox_session() and can_mutate()):
        return None, error_response("Forbidden: Legacy import requires a signed-in editor (not an anonymous sandbox).", 403)
    try:
        prepared = prepare_fovault_restore(raw_bytes, passphrase, allow_legacy=allow_legacy)
    except fovault_passphrase.LegacyFovaultFormat as exc:
        return None, error_response(str(exc), 400, code="legacy_format", legacy_required=True)
    except PassphraseError as exc:
        return None, error_response(str(exc), 400, code="passphrase")
    except (PassphraseEnvelopeError, ValueError) as exc:
        return None, error_response(str(exc), 400)
    if prepared.legacy:
        fid = get_current_family_id()
        logger.warning("fovault legacy-format import accepted family_id=%s universe=%s", fid, universe)
        record_portal_telemetry_event(universe, "fovault_legacy_import", feature_key=str(fid))
    return prepared, None
