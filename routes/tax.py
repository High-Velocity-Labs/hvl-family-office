"""
Tax Planning, Multi-State Arbitrage, IRS Transcripts, and Safe Harbor Withholding APIs.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from flask import Blueprint, request, jsonify, session

import config
import db
import security
import equity_engine

logger = logging.getLogger(__name__)
from routes.helpers import (
    editor_required,
    login_required,
    DB_PATH,
    get_current_family_id,
    get_current_universe,
    sanitize_text,
)

tax_bp = Blueprint("tax", __name__)


def _sync_w2_to_compensation(result: dict, family_id: int, target_adult: str, target_db: Any) -> tuple[bool, bool, str]:
    w2_info = result.get("w2", {})
    totals_info = result.get("totals", {})
    w2_wages = float(w2_info.get("wages_box1") or totals_info.get("w2_wages") or 0.0)
    base_salary = float(w2_info.get("base_salary_and_bonus") or totals_info.get("w2_base_salary_and_bonus") or 0.0)
    employer = w2_info.get("employer") or equity_engine.get_primary_company_name(family_id=family_id) or "Primary Employer"
    has_wages = (base_salary > 0 or w2_wages > 0)
    if not has_wages:
        return False, False, employer
    try:
        from routes.compensation import save_compensation_record
        doc_label = "Form W-2 (Verified)" if result.get("doc_type") == "w2" else "IRS Transcript (W-2 Verified)"
        target_uid = None
        if target_db.exists() and target_adult:
            try:
                members = security.get_family_members(target_db, family_id=family_id)
                target_uid = next((m.get("user_id") for m in members if m.get("name", "").lower() == target_adult.lower()), None)
            except Exception:
                pass
        save_compensation_record(
            family_id=family_id, year=result["year"], company=employer,
            salary=(base_salary if base_salary > 0 else w2_wages), bonus=0.0,
            source=doc_label, user_id=target_uid, db_path=target_db,
        )
        return True, True, employer
    except Exception as e:
        logger.warning("Failed to save compensation record for family %s: %s", family_id, e)
        return False, True, employer


def _process_transcript_upload_bytes(
    pdf_bytes: bytes, family_id: int, target_adult: str, db_path: Any = None,
) -> dict:
    """Parses an uploaded IRS Transcript or Form W-2 PDF in memory and persists summary + compensation."""
    import forecast_cache
    import ingest_tax_transcripts

    target_db = db_path if db_path is not None else DB_PATH
    try:
        result = ingest_tax_transcripts.ingest_single_transcript_bytes(pdf_bytes, family_id=family_id, db_path=target_db)
    except Exception as e:
        msg = str(e)
        raise ValueError(msg if msg.startswith("Maximum of ") else f"Failed to parse document: {msg}") from e

    totals = result.get("totals", {})
    adult_summary = {
        "year": result["year"],
        "federal_tax_withheld": totals.get("federal_tax_withheld", 0.0),
        "social_security_withheld": totals.get("social_security_withheld", 0.0),
        "medicare_tax_withheld": totals.get("medicare_withheld", 0.0),
        "mortgage_interest_paid": sum(m.get("interest_paid", 0.0) for m in result.get("mortgages", [])),
        "qualified_dividends": totals.get("qualified_dividends", 0.0),
        "realized_capital_gains": totals.get("realized_capital_gains", 0.0),
        "safe_harbor_110_target": None,
    }
    db.transcripts.upsert_adult_year_summary(
        family_id=family_id, adult_name=target_adult, tax_year=int(result["year"]),
        summary_dict=adult_summary, db_path=target_db,
    )
    comp_synced, has_wages, employer = _sync_w2_to_compensation(result, family_id, target_adult, target_db)
    try:
        forecast_cache.invalidate_family_cache(family_id)
    except Exception:
        pass

    doc_kind = "Form W-2" if result.get("doc_type") == "w2" else "IRS transcript"
    tax_year = result.get("year")
    if not comp_synced and has_wages:
        message = f"Successfully parsed and encrypted {doc_kind} ({tax_year} - {employer}), but compensation sync failed."
    else:
        message = f"Successfully parsed and encrypted {doc_kind} for {tax_year} ({target_adult}). Compensation and safe harbor records updated."
    return {"success": True, "message": message, "data": result, "adult": target_adult, "compensation_synced": comp_synced}


def _resolve_upload_target_adult(family_id: int) -> str:
    target_adult = sanitize_text(request.form.get("adult", ""), max_length=100, field_name="Adult taxpayer")
    if not target_adult:
        try:
            members = security.get_family_members(DB_PATH, family_id=family_id)
            primary = next((m for m in members if m.get("relationship") in ("primary", "parent")), None)
            if primary and primary.get("name"):
                target_adult = primary["name"]
        except Exception:
            pass
    return target_adult or session.get("user") or "Primary Taxpayer"


@tax_bp.route("/api/transcripts/upload", methods=["POST"])
@editor_required
def api_transcripts_upload():
    """Parses an uploaded IRS Transcript/W-2 PDF in memory and encrypts parsed financial data into SQLite."""
    family_id = get_current_family_id()
    max_transcripts = int(getattr(config, "MAX_TAX_TRANSCRIPTS", 100))
    if DB_PATH.exists() and db.transcripts.count_transcript_records(family_id=family_id, db_path=DB_PATH) >= max_transcripts:
        return jsonify({"success": False, "error": f"Maximum of {max_transcripts} tax transcript records per household reached."}), 400

    uploaded_file = request.files.get("file") or request.files.get("transcript_pdf")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"success": False, "error": "No file uploaded."}), 400
    if not uploaded_file.filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "error": "Only IRS transcript PDF files are supported."}), 400

    pdf_bytes = uploaded_file.read()
    if not pdf_bytes:
        return jsonify({"success": False, "error": "Uploaded file is empty."}), 400

    target_adult = _resolve_upload_target_adult(family_id)
    import background_jobs
    run_sync = background_jobs.should_run_synchronously(
        sync_param=(request.args.get("sync") or request.form.get("sync")),
        async_param=(request.args.get("async") or request.form.get("async")),
    )
    if not run_sync:
        explicit_db = DB_PATH if isinstance(DB_PATH, Path) else None
        job_id = background_jobs.submit_job(
            _process_transcript_upload_bytes, pdf_bytes, family_id, target_adult, explicit_db,
            family_id=family_id, universe=get_current_universe(), job_type="transcript_upload",
        )
        return jsonify({"success": True, "status": "processing", "job_id": job_id, "adult": target_adult, "message": "Parsing and encrypting document in memory..."})

    try:
        return jsonify(_process_transcript_upload_bytes(pdf_bytes=pdf_bytes, family_id=family_id, target_adult=target_adult, db_path=DB_PATH))
    except Exception as e:
        err_msg = str(e)
        if not err_msg.startswith("Failed to parse document:") and not err_msg.startswith("Maximum of "):
            err_msg = f"Failed to parse document: {err_msg}"
        return jsonify({"success": False, "error": err_msg}), 400



@tax_bp.route("/api/transcripts/status/<job_id>", methods=["GET"])
@login_required
def api_transcripts_status(job_id: str):
    """Fast (<2ms) non-blocking status lookup for a background transcript/W-2 upload job."""
    import background_jobs
    family_id = get_current_family_id()
    clean_id = sanitize_text(job_id, max_length=64, field_name="Job ID")
    job = background_jobs.get_job(clean_id, family_id=family_id)
    if not job:
        return jsonify({"success": False, "status": "not_found", "error": "Transcript job not found."}), 404

    if job["status"] == "processing":
        return jsonify({
            "success": True,
            "status": "processing",
            "job_id": clean_id,
        })

    if job["status"] == "failed":
        return jsonify({
            "success": False,
            "status": "failed",
            "job_id": clean_id,
            "error": job.get("error") or "Failed to parse document.",
        }), 400

    result_payload = job.get("result") or {}
    return jsonify({
        **result_payload,
        "status": "completed",
        "job_id": clean_id,
    })


@tax_bp.route("/api/tax/checklist", methods=["GET"])
@login_required
def api_tax_checklist():
    """Returns auto-derived tax season document checklist merged with saved completion statuses."""
    family_id = get_current_family_id()
    year_arg = request.args.get("year", "2025")
    tax_year = int(year_arg) if str(year_arg).isdigit() else 2025
    from services.tax_checklist_service import get_tax_document_checklist
    return jsonify(get_tax_document_checklist(family_id=family_id, tax_year=tax_year, db_path=DB_PATH))


@tax_bp.route("/api/tax/checklist", methods=["POST"])
@editor_required
def api_tax_checklist_update():
    """Cycles or updates the readiness status of an expected tax season document."""
    family_id = get_current_family_id()
    data = request.get_json(silent=True) or {}
    item_id = sanitize_text(str(data.get("item_id") or ""), max_length=64, field_name="Item ID")
    status_raw = sanitize_text(str(data.get("status") or "cycle"), max_length=32, field_name="Status")
    if not item_id:
        return jsonify({"success": False, "error": "Missing item_id parameter."}), 400
    year_arg = data.get("tax_year", 2025)
    tax_year = int(year_arg) if str(year_arg).isdigit() else 2025
    from services.tax_checklist_service import update_tax_document_status
    res = update_tax_document_status(
        db_path=DB_PATH, family_id=family_id, item_id=item_id, status=status_raw, tax_year=tax_year
    )
    return jsonify(res)


@tax_bp.route("/api/tax/core_burn_calibration", methods=["GET"])
@login_required
def api_tax_core_burn_calibration():
    """Returns steady-state core burn calibrated against Monarch Money spending minus mortgage & tuition."""
    family_id = get_current_family_id()
    from services.tax_checklist_service import compute_monarch_core_burn_calibration
    return jsonify(compute_monarch_core_burn_calibration(family_id=family_id, db_path=DB_PATH))


@tax_bp.route("/api/tax/apply_core_burn", methods=["POST"])
@editor_required
def api_tax_apply_core_burn():
    """Applies calibrated Monarch core living burn to household baseline planning assumptions."""
    family_id = get_current_family_id()
    from services.tax_checklist_service import compute_monarch_core_burn_calibration
    calib = compute_monarch_core_burn_calibration(family_id=family_id, db_path=DB_PATH)
    burn_val = calib["calibrated_core_burn"]
    req_data = request.get_json(silent=True) or {}
    if "annual_spend" in req_data:
        try:
            burn_val = max(0.0, float(req_data["annual_spend"]))
        except (TypeError, ValueError):
            pass
    db.families.update_household_assumptions_key(
        family_id=family_id, section_key="annual_spend", section_value=burn_val, db_path=DB_PATH
    )
    try:
        from db import store
        store.notify_family_mutation(family_id, domains=["balance_sheet", "scenarios"], db_path=DB_PATH)
    except Exception:
        pass
    msg = f"Applied calibrated core burn (${burn_val:,.0f}) to baseline plan." if burn_val > 0 else "Updated baseline assumptions."
    return jsonify({"success": True, "annual_spend": burn_val, "calibration": calib, "message": msg})

