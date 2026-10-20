"""
Family Gifting Program, Annual Exclusion Headroom, and Recipient Ledger APIs.
Data-driven and multi-tenant backed by SQLite gift_recipients & gifts tables.
"""

from __future__ import annotations
from flask import Blueprint, request, jsonify

import security
import db
from db.schemas import GiftRecordSchema
from routes.helpers import login_required, editor_required, DB_PATH, get_current_family_id, sanitize_text

gifting_bp = Blueprint("gifting", __name__)


def _load_gifting_data(family_id: int):
    """Loads gifting ledger and recipient limits from relational SQLite tables."""
    recipients_map = {}
    limits = {}
    summary = {}
    yearly = {}

    if DB_PATH.exists():
        try:
            rec_rows = db.gifting.list_gift_recipients(family_id=family_id, db_path=DB_PATH)
            for r in rec_rows:
                rec_id = r["recipient_id"]
                name = r["recipient_group_name"]
                cnt = int(r["member_count"] or 1)
                recipients_map[rec_id] = name
                limits[name] = {
                    "recipient_name": name,
                    "num_people": cnt,
                    "beneficiary_count": cnt,
                    "limit_from_single_donor": cnt * 19000.0,
                    "limit_from_couple": cnt * 38000.0,
                    "joint_annual_limit": cnt * 38000.0,
                }
                summary[name] = {}

            gift_rows = db.gifting.list_gifts(family_id=family_id, db_path=DB_PATH)
            for g in gift_rows:
                rec_name = g["recipient_name"]
                if not rec_name:
                    continue
                yr = str(g["year"])
                amt = float(g["amount"])

                summary.setdefault(rec_name, {})[yr] = round(amt, 2)

                if yr not in yearly:
                    yearly[yr] = {"gifts": [], "total_given": 0.0}
                yearly[yr]["gifts"].append({
                    "recipient": rec_name,
                    "amount": round(amt, 2),
                    "date": f"{yr}-01-01",
                    "notes": g["notes"] or "",
                })
                yearly[yr][rec_name] = round(amt, 2)
                yearly[yr]["total_given"] = round(yearly[yr]["total_given"] + amt, 2)
        except Exception:
            pass

    return limits, summary, yearly


@gifting_bp.route("/api/gifting", methods=["GET"])
@login_required
def api_gifting():
    """Returns Family Gifting program ledger, recipient limits, and annual exclusion headroom."""
    try:
        family_id = get_current_family_id()
        limits, summary, yearly = _load_gifting_data(family_id)

        return jsonify({
            "success": True,
            "recipient_limits": limits,
            "summary_by_recipient": summary,
            "yearly_details": yearly,
            "annual_exclusion_2026_per_donor": 19000.0,
            "annual_exclusion_2026_couple": 38000.0,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@gifting_bp.route("/api/gifting/budget", methods=["POST"])
@editor_required
def api_gifting_update_budget():
    """Updates or budgets a gift amount for a recipient in a given year, supporting recipient renaming and inline edits."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}
        year = sanitize_text(body.get("year", "2026"), max_length=10, field_name="Year", required=True)
        recipient = sanitize_text(body.get("recipient"), max_length=100, field_name="Recipient name", required=True)
        old_recipient = sanitize_text(body.get("old_recipient", ""), max_length=100, field_name="Old recipient name")
        amount_raw = body.get("amount")
        amount = float(amount_raw) if amount_raw is not None else 0.0

        member_cnt = None
        if "beneficiary_count" in body or "num_people" in body:
            member_cnt = int(body.get("beneficiary_count") or body.get("num_people") or 1)

        if DB_PATH.exists():
            rec_res = db.gifting.upsert_gift_recipient(
                family_id=family_id,
                recipient_group_name=recipient,
                member_count=member_cnt,
                old_recipient_group_name=old_recipient,
                db_path=DB_PATH,
            )
            rec_id = rec_res.get("recipient_id")
            if rec_id and amount >= 0:
                db.gifting.record_gift(
                    family_id=family_id,
                    recipient_id=rec_id,
                    year=int(year),
                    amount=amount,
                    db_path=DB_PATH,
                )

        return jsonify({
            "success": True,
            "recipient": recipient,
            "old_recipient": old_recipient,
            "year": year,
            "amount": round(amount, 2),
            "message": f"Updated gifting budget for {recipient} ({year}) to ${amount:,.2f}"
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _resolve_source_year_gifts(summary: dict, yearly: dict, from_year: str, to_year: str) -> tuple[str, dict[str, float]]:
    if not from_year:
        possible = [
            y for y in sorted(yearly.keys(), key=lambda x: int(x) if x.isdigit() else 0, reverse=True)
            if int(y) < int(to_year) and yearly[y].get("total_given", 0) > 0
        ]
        from_year = possible[0] if possible else str(int(to_year) - 1)
    src_gifts = (yearly.get(from_year) or {}).get("gifts", [])
    recipient_amounts: dict[str, float] = {}
    if src_gifts:
        for g in src_gifts:
            recipient_amounts[g["recipient"]] = float(g.get("amount", 0.0))
    else:
        for rec, years_map in summary.items():
            if from_year in years_map and float(years_map[from_year]) > 0:
                recipient_amounts[rec] = float(years_map[from_year])
    return from_year, recipient_amounts


@gifting_bp.route("/api/gifting/copy_previous_year", methods=["POST"])
@editor_required
def api_gifting_copy_previous_year():
    """Copies all recipient gifting amounts from a prior year to the target year in a single click."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}
        to_year = str(body.get("to_year", "2027")).strip()
        from_year = str(body.get("from_year", "")).strip()

        _, summary, yearly = _load_gifting_data(family_id)
        from_year, recipient_amounts = _resolve_source_year_gifts(summary, yearly, from_year, to_year)
        if not recipient_amounts:
            return jsonify({"success": False, "error": f"No gifting records found in source year {from_year}."}), 400

        if DB_PATH.exists():
            db.gifting.copy_gifts_to_year(
                family_id=family_id, recipient_amounts=recipient_amounts, to_year=int(to_year), db_path=DB_PATH,
            )

        tot = round(sum(round(amt, 2) for amt in recipient_amounts.values()), 2)
        return jsonify({
            "success": True, "to_year": to_year, "from_year": from_year,
            "total_given": tot, "recipients_count": len(recipient_amounts),
            "message": f"Successfully auto-populated {to_year} gifting budget (${tot:,.2f}) from {from_year}.",
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@gifting_bp.route("/api/gifting/recipient", methods=["POST"])
@editor_required
def api_gifting_add_recipient():
    """Adds a new recipient unit to the family gifting program."""
    try:
        body = request.get_json() or {}
        recipient = sanitize_text(body.get("recipient"), max_length=100, field_name="Recipient name", required=True)
        cnt_val = body.get("num_people") or body.get("beneficiary_count") or 1
        try:
            member_count = max(1, int(cnt_val))
        except (ValueError, TypeError):
            member_count = 1

        relationship = sanitize_text(body.get("relationship", ""), max_length=50, field_name="Relationship")
        notes = sanitize_text(body.get("notes", ""), max_length=500, field_name="Notes", multiline=True)
        initial_amount_raw = body.get("amount") or body.get("initial_amount")
        initial_amount = float(initial_amount_raw) if initial_amount_raw is not None else 0.0
        year = sanitize_text(body.get("year", "2026"), max_length=10, field_name="Year")

        family_id = get_current_family_id()

        if DB_PATH.exists():
            rec_res = db.gifting.upsert_gift_recipient(
                family_id=family_id,
                recipient_group_name=recipient,
                member_count=member_count,
                relationship=relationship,
                notes=notes,
                db_path=DB_PATH,
            )
            rec_id = rec_res.get("recipient_id")
            if rec_id and initial_amount > 0 and year:
                db.gifting.record_gift(
                    family_id=family_id,
                    recipient_id=rec_id,
                    year=int(year),
                    amount=initial_amount,
                    notes="Initial gift allocation",
                    db_path=DB_PATH,
                )

        return jsonify({
            "success": True,
            "recipient": recipient,
            "member_count": member_count,
            "initial_amount": initial_amount,
            "message": f"Successfully added recipient '{recipient}' ({member_count} beneficiary unit)."
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@gifting_bp.route("/api/gifting/recipient", methods=["DELETE"])
@editor_required
def api_gifting_delete_recipient():
    """Deletes a recipient from a specific year or from all gifting records."""
    try:
        body = request.get_json() or {}
        recipient = sanitize_text(body.get("recipient"), max_length=100, field_name="Recipient name", required=True)
        year = sanitize_text(body.get("year", ""), max_length=10, field_name="Year")

        family_id = get_current_family_id()

        if DB_PATH.exists():
            db.gifting.delete_recipient_gifts(
                family_id=family_id,
                recipient_group_name=recipient,
                year=year if year else None,
                db_path=DB_PATH,
            )

        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

