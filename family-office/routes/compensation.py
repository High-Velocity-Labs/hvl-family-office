"""
Historical and Projected Career Compensation APIs (2000 to present).
Backed by relational SQLite compensation table with encrypted store fallback.
"""

from __future__ import annotations
from typing import Any, Optional
from flask import Blueprint, request, jsonify

import config
import security
from services import equity_engine
import db
from db.schemas import CompensationRecordSchema
from services.compensation_records import load_compensation_records
from routes.context import login_required, editor_required, DB_PATH, get_current_family_id, sanitize_text

compensation_bp = Blueprint("compensation", __name__)


@compensation_bp.route("/api/compensation", methods=["GET"])
@login_required
def api_compensation():
    """Returns historical career compensation history (2000 to present), optionally filtered by user_id."""
    try:
        family_id = get_current_family_id()
        user_id_arg = request.args.get("user_id")
        user_id = int(user_id_arg) if user_id_arg and user_id_arg.isdigit() else None
        history, primary_years, primary_comp, adults = load_compensation_records(family_id, DB_PATH, user_id=user_id)
        return jsonify({
            "success": True,
            "history": history,
            "adults": adults,
            "primary_company": primary_comp,
            "primary_company_years": primary_years,
            "company_years": primary_years,
            "user_id": user_id,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _resolve_default_compensation_user_id(target_db: Any, family_id: int, user_id: Optional[int]) -> int:
    if user_id is not None:
        return user_id
    if target_db.exists():
        try:
            members = security.get_family_members(target_db, family_id=family_id)
            prim = next((m for m in members if str(m.get("relationship") or "").lower() == "primary"), None)
            if prim and prim.get("user_id") is not None:
                return int(prim["user_id"])
        except Exception:
            pass
    return 1


def save_compensation_record(
    family_id: int, year: int, company: str, salary: float, bonus: float,
    source: str = "Manual Entry", user_id: Optional[int] = None,
    original_year: Optional[int] = None, original_company: str = "", db_path: Any = None,
) -> dict:
    """Helper to upsert compensation record into SQLite relational table."""
    target_db = db_path or DB_PATH
    default_company = equity_engine.get_primary_company_name(family_id=family_id)
    company = sanitize_text(company or default_company, max_length=100, field_name="Company name") or default_company
    salary, bonus = float(salary or 0.0), float(bonus or 0.0)
    source = sanitize_text(source or "Manual Entry", max_length=100, field_name="Source") or "Manual Entry"
    resolved_uid = _resolve_default_compensation_user_id(target_db, family_id, user_id)

    if target_db.exists():
        db.compensation.upsert_compensation_record(
            family_id=family_id, year=year, company=company, salary=salary, bonus=bonus,
            source=source, user_id=resolved_uid, original_year=original_year,
            original_company=original_company, db_path=target_db,
        )

    record_entry = {
        "year": year, "user_id": resolved_uid, "company": company,
        "salary": salary, "bonus": bonus, "total_compensation": round(salary + bonus, 2), "source": source,
    }
    history_reloaded, _, _, _ = load_compensation_records(family_id, DB_PATH)
    return {
        "success": True,
        "message": f"Compensation record for {year} ({company}) successfully saved.",
        "record": record_entry,
        "history": history_reloaded,
    }


@compensation_bp.route("/api/compensation", methods=["POST"])
@compensation_bp.route("/api/compensation/save", methods=["POST"])
@editor_required
def api_compensation_save():
    """Adds or updates a career compensation record in SQLite."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}
        year_val = body.get("year")
        if not year_val:
            return jsonify({"success": False, "error": "Year is required."}), 400

        schema = CompensationRecordSchema.from_dict(body)
        res = save_compensation_record(
            family_id=family_id,
            year=schema.year,
            company=schema.company,
            salary=schema.salary,
            bonus=schema.bonus,
            source=schema.source,
            user_id=schema.user_id,
            original_year=schema.original_year,
            original_company=schema.original_company,
        )
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@compensation_bp.route("/api/compensation/<int:year>", methods=["DELETE"])
@compensation_bp.route("/api/compensation/delete", methods=["DELETE"])
@editor_required
def api_compensation_delete(year: Optional[int] = None):
    """Deletes a career compensation record by year, optionally filtered by company."""
    try:
        family_id = get_current_family_id()
        body = request.get_json(silent=True) or {}
        if year is None:
            year = int(body.get("year") or request.args.get("year") or 0)
        company_filter = (body.get("company") or request.args.get("company") or "").strip().lower()

        if DB_PATH.exists() and year:
            db.compensation.delete_compensation_record_by_year(
                family_id=family_id,
                year=year,
                company_filter=company_filter or None,
                db_path=DB_PATH,
            )

        history_reloaded, _, _, _ = load_compensation_records(family_id, DB_PATH)

        return jsonify({"success": True, "message": f"Deleted compensation record for {year}.", "history": history_reloaded})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@compensation_bp.route("/api/compensation/upload_w2", methods=["POST"])
@editor_required
def api_compensation_upload_w2():
    """Alias for /api/transcripts/upload to ingest W-2 / Transcripts directly from compensation view."""
    family_id = get_current_family_id()
    max_records = int(getattr(config, "MAX_COMPENSATION_RECORDS", 200))
    if DB_PATH.exists():
        current_records = db.compensation.list_compensation_records(
            family_id=family_id, db_path=DB_PATH
        )
        if len(current_records) >= max_records:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Maximum of {max_records} compensation records per household reached.",
                    }
                ),
                400,
            )

    from routes.tax import api_transcripts_upload
    return api_transcripts_upload()

