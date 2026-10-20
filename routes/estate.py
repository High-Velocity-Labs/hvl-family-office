"""
HVL Family Office: Estate & Generational Wealth Blueprint.
Endpoints:
- GET /api/estate: Gathers estate tax exposure, trust vehicle sandbox, state comparisons, and next-gen inheritance waterfall.
- POST /api/estate/settings: Saves estate planning preferences (TCJA sunset toggle, charitable legacy %, selected trust vehicles).
"""

from __future__ import annotations
import json
import logging
from flask import Blueprint, request, jsonify, session

import estate_engine
from routes.helpers import (
    login_required,
    editor_required,
    DB_PATH,
    get_current_family_id,
    get_current_universe,
    sanitize_text,
)

logger = logging.getLogger(__name__)

# Ensure dynamic DB_PATH routing
estate_engine.DB_PATH = DB_PATH

estate_bp = Blueprint("estate", __name__)


def _parse_estate_overrides(args):
    state_override = args.get("state")
    if state_override:
        try:
            state_override = sanitize_text(state_override, max_length=10, field_name="State").upper()
        except ValueError:
            state_override = None
    sunset_param = args.get("apply_tcja_sunset")
    sunset_override = sunset_param.lower() in ("true", "1", "yes") if sunset_param is not None else None
    gross_estate_override = None
    if args.get("gross_estate"):
        try:
            gross_estate_override = float(args["gross_estate"])
        except (ValueError, TypeError):
            pass
    return state_override, sunset_override, gross_estate_override


@estate_bp.route("/api/estate", methods=["GET"])
@login_required
def api_get_estate_profile():
    """Returns comprehensive estate planning profile for the active family."""
    family_id = get_current_family_id()
    state_override, sunset_override, gross_estate_override = _parse_estate_overrides(request.args)
    profile = estate_engine.get_family_estate_profile(family_id=family_id)

    if state_override or (sunset_override is not None) or (gross_estate_override is not None):
        target_state = state_override or profile["state"]
        target_sunset = sunset_override if sunset_override is not None else profile["apply_tcja_sunset"]
        target_nw = gross_estate_override if gross_estate_override is not None else profile["current_net_worth"]
        profile["state"] = target_state
        profile["apply_tcja_sunset"] = target_sunset
        profile["current_net_worth"] = round(target_nw, 2)
        profile["current_estate_tax"] = estate_engine.calculate_comprehensive_estate_tax(
            gross_estate=target_nw, state=target_state, is_mfj=profile["is_mfj"], apply_tcja_sunset=target_sunset,
        )
        profile["trust_sandbox"] = estate_engine.simulate_trust_architectures(
            gross_estate=target_nw, state=target_state, is_mfj=profile["is_mfj"], apply_tcja_sunset=target_sunset,
        )

    return jsonify(profile)


@estate_bp.route("/api/estate/settings", methods=["POST"])
@editor_required
def api_update_estate_settings():
    """
    Updates estate planning preferences in household_profile.assumptions_json.
    Guarded against demo modifications.
    """
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Estate preferences cannot be changed in demo mode."}), 403

    family_id = get_current_family_id()
    data = request.get_json() or {}

    try:
        apply_tcja_sunset = bool(data.get("apply_tcja_sunset", False))
        charitable_pct = max(0.0, min(0.90, float(data.get("charitable_pct", 0.05))))
        trust_prefs = data.get("trust_preferences") or []
        if not isinstance(trust_prefs, list):
            trust_prefs = []
        sanitized_trusts = [sanitize_text(str(t), max_length=50, field_name="Trust ID") for t in trust_prefs[:10]]
        updates = {
            "apply_tcja_sunset": apply_tcja_sunset,
            "charitable_pct": charitable_pct,
            "trust_preferences": sanitized_trusts,
        }
        if DB_PATH.exists():
            import db
            updates = db.estate.merge_estate_planning_assumptions(
                family_id=family_id, updates=updates, db_path=DB_PATH,
            )
        return jsonify({"success": True, "estate_planning": updates})
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error("Error saving estate settings: %s", e)
        return jsonify({"success": False, "error": "Failed to update estate settings."}), 500


@estate_bp.route("/api/estate/audit_verify", methods=["POST"])
@editor_required
def api_verify_estate_audit_item():
    """Toggles verification status of a survivorship/readiness audit finding for the active family."""
    if session.get("is_demo") or (get_current_universe() in ("demo", "beta") and session.get("role") != "admin"):
        return jsonify({"success": False, "error": "Audit verification cannot be changed in demo mode."}), 403

    family_id = get_current_family_id()
    data = request.get_json() or {}
    try:
        finding_id = sanitize_text(str(data.get("finding_id") or ""), max_length=100, field_name="Finding ID")
        if not finding_id:
            return jsonify({"success": False, "error": "Missing finding_id."}), 400
        verified_arg = data.get("verified")
        verified_bool = bool(verified_arg) if verified_arg is not None else None
        import db
        verified_ids = db.estate.toggle_estate_audit_item(
            family_id=family_id, finding_id=finding_id, verified=verified_bool, db_path=DB_PATH,
        )
        return jsonify({
            "success": True,
            "finding_id": finding_id,
            "verified": finding_id in verified_ids,
            "verified_audit_ids": verified_ids,
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error("Error toggling estate audit verification: %s", e)
        return jsonify({"success": False, "error": "Failed to update audit verification."}), 500
