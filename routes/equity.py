"""
Equity Engine & 409A Grants Management APIs.
Data-driven and multi-tenant backed by SQLite equity_companies, equity_grants, and fmv_history tables.
Exposes generic /api/equity/... endpoints.
"""

from __future__ import annotations
import time
from flask import Blueprint, request, jsonify

import config
import security
import equity_engine
import db
from hvl_common.web import rate_limit
from routes.helpers import login_required, editor_required, DB_PATH, get_current_family_id, sanitize_text

equity_bp = Blueprint("equity", __name__)
rate_limit("120/min")(equity_bp)


def _get_or_create_primary_company(conn_or_none, family_id: int):
    """Fetches the primary company record or creates a default one if none exists."""
    return db.equity.get_or_create_primary_company(family_id=family_id, db_path=DB_PATH)


@equity_bp.route("/api/equity/fmv", methods=["POST"])
@editor_required
def api_equity_fmv():
    """Sets or records Fair Market Value on a given date for a specific or primary equity company."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}
        price = float(body.get("price", 0.0))
        date_str = sanitize_text(body.get("effective_date"), max_length=30, field_name="Effective date", required=True)
        notes = sanitize_text(body.get("notes", "409A Valuation"), max_length=250, field_name="Valuation notes")
        target_cid = body.get("company_id")

        if price <= 0:
            return jsonify({"success": False, "error": "Valid share price > 0 is required."}), 400

        cid = None
        cname = "Company"

        if DB_PATH.exists():
            cid, cname = db.equity.record_fmv_valuation(
                family_id=family_id,
                price=price,
                valuation_date=date_str,
                notes=notes,
                company_id=target_cid,
                db_path=DB_PATH,
            )

        fmv_history = equity_engine.get_historical_equity_fmv(price, family_id=family_id, company_id=cid or target_cid)

        return jsonify({
            "success": True,
            "message": f"Successfully updated 409A FMV to ${price:,.2f} as of {date_str}.",
            "price": price,
            "effective_date": date_str,
            "fmv_history": fmv_history
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


def _persist_equity_grant_to_db(
    family_id: int, body: dict, nickname: str, grant_type: str, strike: float,
    qty: float, vested: float, unvested: float, grant_date: str, fully_vested_date: str,
) -> tuple[Any, Any, Any]:
    if not DB_PATH.exists():
        return None, None, None
    new_cname = sanitize_text(body.get("new_company_name", ""), max_length=100, field_name="Company name")
    new_fmv = float(body.get("new_company_fmv") or 10.0)
    target_cid = body.get("company_id")
    created_company_id = None
    cid = None
    if new_cname:
        cid = db.equity.create_company(
            family_id=family_id, company_name=new_cname, current_fmv=new_fmv, fmv_date=grant_date, db_path=DB_PATH,
        )
        created_company_id = cid
    elif target_cid and str(target_cid).isdigit():
        cid = int(target_cid)
    if not cid:
        cid, _, _, _ = db.equity.get_or_create_primary_company(family_id=family_id, db_path=DB_PATH)
    db_grant_id = db.equity.insert_grant(
        family_id=family_id, company_id=cid, grant_label=nickname, grant_type=grant_type,
        strike_price=strike, shares_granted=qty, shares_vested=vested, shares_unvested=unvested,
        grant_date=grant_date, fully_vested_date=fully_vested_date, db_path=DB_PATH,
    )
    return db_grant_id, created_company_id, cid


@equity_bp.route("/api/equity/grant", methods=["POST"])
@editor_required
def api_equity_grant():
    """Adds a new equity grant with grant date and fully vested date."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}
        nickname = sanitize_text(body.get("nickname") or body.get("grant_label"), max_length=100, field_name="Grant nickname", required=True)
        grant_date = sanitize_text(body.get("grantDate") or body.get("grant_date"), max_length=30, field_name="Grant date", required=True)
        fully_vested_date = sanitize_text(body.get("fullyVestedDate") or body.get("fully_vested_date", ""), max_length=30, field_name="Fully vested date")
        qty = float(body.get("quantityGranted") or body.get("shares_granted") or 0.0)
        strike = float(body.get("strikePrice") or body.get("strike_price") or 0.0)
        unvested = float(body.get("unvestedQuantity") or body.get("shares_unvested") or 0.0)
        grant_type = sanitize_text(body.get("grantType") or body.get("grant_type") or "nso", max_length=20, field_name="Grant type").lower()
        if grant_type == "rsu":
            strike = 0.0
        if qty <= 0:
            return jsonify({"success": False, "error": "Total granted quantity must be > 0."}), 400

        vested = max(0.0, qty - unvested)
        db_grant_id, created_company_id, cid = _persist_equity_grant_to_db(
            family_id, body, nickname, grant_type, strike, qty, vested, unvested, grant_date, fully_vested_date
        )
        grant_id = str(db_grant_id) if db_grant_id else str(int(time.time() * 1000))
        current_price = equity_engine.get_company_409a_price(family_id=family_id, company_id=cid)
        new_grant = {
            "id": grant_id, "grantNickname": nickname, "grantDate": grant_date, "fullyVestedDate": fully_vested_date,
            "grantType": grant_type, "quantityGranted": qty, "strikePrice": strike, "vestedQuantity": vested,
            "unvestedQuantity": unvested, "exercisedQuantity": 0.0, "soldQuantity": 0.0,
            "unexercisedVested": vested, "currentValue": round(qty * current_price, 2),
        }
        return jsonify({
            "success": True, "message": f"Successfully added grant {nickname}.",
            "grant": new_grant, "company_id": created_company_id,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@equity_bp.route("/api/equity/company", methods=["POST"])
@editor_required
def api_add_equity_company():
    """Registers a new private equity company holding with initial 409A valuation."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}
        cname = sanitize_text(body.get("company_name"), max_length=100, field_name="Company name", required=True)
        fmv = float(body.get("current_fmv") or body.get("price") or 10.0)
        fmv_date = sanitize_text(body.get("fmv_date") or body.get("effective_date", "2026-01-01"), max_length=30, field_name="FMV date")
        ticker = sanitize_text(body.get("ticker_or_private", "private"), max_length=20, field_name="Ticker / status")

        cid = None
        if DB_PATH.exists():
            cid = db.equity.create_company(
                family_id=family_id,
                company_name=cname,
                current_fmv=fmv,
                fmv_date=fmv_date,
                ticker_or_private=ticker,
                db_path=DB_PATH,
            )

        return jsonify({
            "success": True,
            "company_id": cid,
            "company_name": cname,
            "current_fmv": fmv,
            "message": f"Successfully registered company {cname}."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@equity_bp.route("/api/equity/grant/<grant_id>", methods=["DELETE"])
@editor_required
def api_delete_equity_grant(grant_id):
    """Deletes an equity grant by grant ID or label."""
    try:
        family_id = get_current_family_id()
        if not grant_id:
            return jsonify({"success": False, "error": "Grant ID is required."}), 400

        if DB_PATH.exists():
            db.equity.delete_grant(family_id=family_id, grant_id_or_label=grant_id, db_path=DB_PATH)

        return jsonify({
            "success": True,
            "message": f"Successfully deleted grant {grant_id}."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@equity_bp.route("/api/equity/grant/<grant_id>", methods=["PUT", "POST"])
@editor_required
def api_update_equity_grant(grant_id):
    """Updates an existing equity grant's terms, vesting schedule, and owned shares."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}

        nickname = sanitize_text(body.get("nickname") or body.get("grant_label"), max_length=100, field_name="Grant nickname", required=True)
        grant_date = sanitize_text(body.get("grantDate") or body.get("grant_date", ""), max_length=30, field_name="Grant date")
        fully_vested_date = sanitize_text(body.get("fullyVestedDate") or body.get("fully_vested_date", ""), max_length=30, field_name="Fully vested date")
        qty = float(body.get("quantityGranted") or body.get("shares_granted") or 0.0)
        strike = float(body.get("strikePrice") or body.get("strike_price") or 0.0)
        unvested = float(body.get("unvestedQuantity") or body.get("shares_unvested") or 0.0)
        vested = float(body.get("vestedQuantity") or body.get("shares_vested") or max(0.0, qty - unvested))
        owned = float(body.get("ownedShares") or body.get("shares_exercised") or 0.0)
        cost_basis = float(body.get("costBasis") or body.get("cost_basis") or 0.0)
        grant_type = sanitize_text(body.get("grantType") or body.get("grant_type") or "nso", max_length=20, field_name="Grant type").lower()
        if grant_type == "rsu":
            strike = 0.0

        target_cid = body.get("company_id")
        new_cid = int(target_cid) if target_cid and str(target_cid).isdigit() else None

        if DB_PATH.exists():
            db.equity.update_grant(
                family_id=family_id,
                grant_id_or_label=grant_id,
                grant_label=nickname,
                grant_type=grant_type,
                company_id=new_cid,
                strike_price=strike,
                shares_granted=qty,
                shares_vested=vested,
                shares_unvested=unvested,
                shares_exercised=owned,
                cost_basis=cost_basis,
                grant_date=grant_date,
                fully_vested_date=fully_vested_date,
                db_path=DB_PATH,
            )

        return jsonify({
            "success": True,
            "message": f"Successfully updated grant {nickname}."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

