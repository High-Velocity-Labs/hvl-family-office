"""
Education, 529 Asset Tracking, Superfunding Limits, and Private School Tuition APIs.
Data-driven and multi-tenant backed by SQLite users & tuition tables.
"""

from __future__ import annotations

import traceback
from flask import Blueprint, jsonify, request

import db
from routes.helpers import (
    DB_PATH,
    editor_required,
    get_current_family_id,
    login_required,
    sanitize_text,
)

education_bp = Blueprint("education", __name__)

from db.education import parse_grade_index as _parse_grade_index


def _load_tuition_records(family_id: int, children: list):
    """Loads tuition records from relational SQLite table or falls back to encrypted store."""
    return db.education.load_tuition_records(family_id=family_id, children=children, db_path=DB_PATH)


@education_bp.route("/api/college", methods=["GET"])
@education_bp.route("/api/education", methods=["GET"])
@login_required
def api_college():
    """Returns education and 529 asset tracking dynamically driven by family children in the database."""
    try:
        family_id = get_current_family_id()
        payload = db.education.build_college_education_payload(family_id=family_id, db_path=DB_PATH)
        return jsonify(payload)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@education_bp.route("/api/education/tuition", methods=["POST"])
@education_bp.route("/api/education/tuition/save", methods=["POST"])
@editor_required
def api_edit_tuition():
    """Adds or edits a private school tuition year record."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}
        year = sanitize_text(body.get("school_year"), max_length=20, field_name="School year", required=True)
        notes = sanitize_text(body.get("notes", ""), max_length=500, field_name="Notes", multiline=True)

        if "-" not in year:
            return jsonify({"success": False, "error": "Valid school year required (e.g. 2026-2027)."}), 400

        db.education.save_tuition_year_entry(
            family_id=family_id,
            year=year,
            notes=notes,
            body=body,
            db_path=DB_PATH,
        )
        return jsonify({"success": True, "message": f"Successfully updated tuition for {year}."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@education_bp.route("/api/education/tuition/<school_year>", methods=["DELETE"])
@education_bp.route("/api/education/tuition/delete", methods=["DELETE"])
@editor_required
def api_delete_tuition(school_year=None):
    """Deletes a private school tuition record by school year."""
    try:
        family_id = get_current_family_id()
        if not school_year:
            body = request.get_json(silent=True) or {}
            school_year = sanitize_text(
                body.get("school_year") or request.args.get("school_year"),
                max_length=20,
                field_name="School year",
                required=True,
            )

        deleted_tuition = 0
        if DB_PATH.exists():
            try:
                deleted_tuition = db.education.delete_tuition_by_year(
                    family_id=family_id, school_year=school_year, db_path=DB_PATH
                )
            except Exception:
                pass

        deleted_year_rec = db.education.delete_tuition_year_record(
            family_id=family_id,
            school_year=school_year,
            db_path=DB_PATH,
        )
        if not deleted_tuition and not deleted_year_rec:
            return jsonify({"success": False, "error": f"Year {school_year} not found."}), 404

        return jsonify({"success": True, "message": f"Deleted tuition record for {school_year}."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
