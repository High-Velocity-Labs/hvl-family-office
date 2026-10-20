"""
Philanthropy, Donor-Advised Fund (DAF) Contributions, and Charitable Giving APIs.
"""

from __future__ import annotations
from flask import Blueprint, request, jsonify

import db
from routes.helpers import login_required, editor_required, DB_PATH, get_current_family_id, sanitize_text

philanthropy_bp = Blueprint("philanthropy", __name__)


@philanthropy_bp.route("/api/philanthropy", methods=["GET"])
@login_required
def api_philanthropy():
    """Returns DAF contribution ledger, charities, and appreciated stock tax savings."""
    try:
        family_id = get_current_family_id()
        data = db.philanthropy.get_philanthropy_payload(family_id=family_id, db_path=DB_PATH) or {}
        return jsonify({
            "success": True,
            "total_lifetime_charity": data.get("total_lifetime_charity", 0.0),
            "lifetime_history": data.get("lifetime_history", []),
            "donations_by_year": data.get("donations_by_year", {}),
            "annual_budgets": data.get("annual_budgets", {}),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@philanthropy_bp.route("/api/philanthropy/budget", methods=["POST"])
@editor_required
def api_philanthropy_update_budget():
    """Updates the annual charitable giving / DAF budget target for a given year."""
    try:
        body = request.get_json() or {}
        year = sanitize_text(body.get("year", "2026"), max_length=10, field_name="Year", required=True)
        budget = float(body.get("budget", 0.0))

        if budget < 0:
            return jsonify({"success": False, "error": "Positive budget amount required."}), 400

        family_id = get_current_family_id()
        db.philanthropy.set_year_budget(
            family_id=family_id,
            tax_year=int(year),
            budget_amount=round(budget, 2),
            db_path=DB_PATH,
        )

        return jsonify({
            "success": True,
            "year": year,
            "budget": round(budget, 2),
            "message": f"Updated {year} philanthropic giving budget to ${budget:,.2f}"
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def normalize_grant_date(date_str: str) -> str:
    """Normalizes various user date inputs (MM/DD/YYYY, YYYY-MM-DD, etc.) into YYYY-MM-DD."""
    if not date_str:
        return ""
    d_clean = date_str.strip()
    parts_dash = d_clean.split("-")
    if len(parts_dash) == 3 and len(parts_dash[0]) == 4:
        try:
            return f"{int(parts_dash[0]):04d}-{int(parts_dash[1]):02d}-{int(parts_dash[2]):02d}"
        except Exception:
            pass
    parts_slash = d_clean.split("/")
    if len(parts_slash) == 3 and len(parts_slash[2]) == 4:
        try:
            return f"{int(parts_slash[2]):04d}-{int(parts_slash[0]):02d}-{int(parts_slash[1]):02d}"
        except Exception:
            pass
    return d_clean


@philanthropy_bp.route("/api/philanthropy/grant", methods=["POST"])
@editor_required
def api_philanthropy_add_grant():
    """Adds a new charitable grant / DAF contribution to the encrypted ledger."""
    try:
        body = request.get_json() or {}
        year = sanitize_text(body.get("year", "2026"), max_length=10, field_name="Year", required=True)
        org = sanitize_text(body.get("organization"), max_length=150, field_name="Organization", required=True)
        amount = float(body.get("amount", 0.0))
        date_str = normalize_grant_date(sanitize_text(body.get("date", ""), max_length=30, field_name="Date"))
        desc = sanitize_text(body.get("description", ""), max_length=500, field_name="Description", multiline=True)

        if amount <= 0:
            return jsonify({"success": False, "error": "Valid positive amount is required."}), 400

        family_id = get_current_family_id()
        new_grant = {
            "organization": org,
            "amount": round(amount, 2),
            "date": date_str,
            "description": desc,
        }
        db.philanthropy.add_donation(
            family_id=family_id,
            tax_year=int(year),
            donation=new_grant,
            db_path=DB_PATH,
        )
        data = db.philanthropy.get_philanthropy_payload(family_id=family_id, db_path=DB_PATH) or {}
        d_by_year = data.get("donations_by_year", {})
        year_total = float((d_by_year.get(year) or {}).get("total", round(amount, 2)))
        total_lifetime = float(data.get("total_lifetime_charity", year_total))

        return jsonify({
            "success": True,
            "message": f"Successfully recorded {org} (${amount:,.2f}) for {year}.",
            "grant": new_grant,
            "year_total": year_total,
            "total_lifetime_charity": total_lifetime
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@philanthropy_bp.route("/api/philanthropy/grant", methods=["DELETE"])
@editor_required
def api_philanthropy_delete_grant():
    """Removes a charitable grant from the encrypted ledger."""
    try:
        body = request.get_json() or {}
        year = str(body.get("year", "2026")).strip()
        index = body.get("index")

        family_id = get_current_family_id()
        data_before = db.philanthropy.get_philanthropy_payload(family_id=family_id, db_path=DB_PATH) or {}
        d_by_year_before = data_before.get("donations_by_year", {})
        if year not in d_by_year_before or "donations" not in d_by_year_before[year]:
            return jsonify({"success": False, "error": f"No grants found for year {year}."}), 404

        donations_before = d_by_year_before[year]["donations"]
        if index is None or index < 0 or index >= len(donations_before):
            return jsonify({"success": False, "error": "Invalid grant index."}), 400

        removed = db.philanthropy.delete_donation_by_index(
            family_id=family_id,
            tax_year=int(year),
            index=int(index),
            db_path=DB_PATH,
        )
        if not removed:
            return jsonify({"success": False, "error": "Invalid grant index."}), 400

        data = db.philanthropy.get_philanthropy_payload(family_id=family_id, db_path=DB_PATH) or {}
        d_by_year = data.get("donations_by_year", {})
        year_total = float((d_by_year.get(year) or {}).get("total", 0.0))
        total_lifetime = float(data.get("total_lifetime_charity", 0.0))

        return jsonify({
            "success": True,
            "message": f"Removed grant to {removed.get('organization')}.",
            "year_total": year_total,
            "total_lifetime_charity": total_lifetime
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@philanthropy_bp.route("/api/philanthropy/grant", methods=["PUT"])
@editor_required
def api_philanthropy_edit_grant():
    """Updates an existing charitable grant (past, current, or future)."""
    try:
        body = request.get_json() or {}
        year = sanitize_text(body.get("year", "2026"), max_length=10, field_name="Year", required=True)
        index = body.get("index")
        org = sanitize_text(body.get("organization"), max_length=150, field_name="Organization", required=True)
        amount = float(body.get("amount", 0.0))
        date_str = normalize_grant_date(sanitize_text(body.get("date", ""), max_length=30, field_name="Date"))
        desc = sanitize_text(body.get("description", ""), max_length=500, field_name="Description", multiline=True)
        if amount <= 0:
            return jsonify({"success": False, "error": "Valid positive amount is required."}), 400

        family_id = get_current_family_id()
        d_by_year_before = (db.philanthropy.get_philanthropy_payload(family_id=family_id, db_path=DB_PATH) or {}).get("donations_by_year", {})
        if year not in d_by_year_before or "donations" not in d_by_year_before[year]:
            return jsonify({"success": False, "error": f"No grants found for year {year}."}), 404

        donations_before = d_by_year_before[year]["donations"]
        if index is None or index < 0 or index >= len(donations_before):
            return jsonify({"success": False, "error": "Invalid grant index."}), 400

        updated_grant = {"organization": org, "amount": round(amount, 2), "date": date_str, "description": desc}
        res = db.philanthropy.update_donation_by_index(
            family_id=family_id, tax_year=int(year), index=int(index), donation=updated_grant, db_path=DB_PATH,
        )
        if not res:
            return jsonify({"success": False, "error": "Invalid grant index."}), 400

        data = db.philanthropy.get_philanthropy_payload(family_id=family_id, db_path=DB_PATH) or {}
        year_total = float(((data.get("donations_by_year") or {}).get(year) or {}).get("total", round(amount, 2)))
        total_lifetime = float(data.get("total_lifetime_charity", year_total))
        return jsonify({
            "success": True, "message": f"Successfully updated grant to {org} ({year}).",
            "grant": updated_grant, "year_total": year_total, "total_lifetime_charity": total_lifetime,
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


