"""
Account Synchronization, Manual Balance Sheet Accounts, Dated Balance History, and CSV Import/Export Routes.
Extracted from `routes/dashboard.py` to maintain thin, modular route handlers (<50 lines per route).
"""

from __future__ import annotations

from flask import Response, jsonify, request, session

import background_jobs
import db
import monarch_service
from routes.dashboard import dashboard_bp
from routes.helpers import (
    DB_PATH,
    editor_required,
    get_current_db_path,
    get_current_family_id,
    get_current_universe,
    login_required,
    sanitize_text,
)
import security
from ssr.dashboard import build_networth_history_payload


def _invoke_simplefin_sync(family_id: int) -> dict:
    fn = getattr(monarch_service, "trigger_simplefin_sync", None) or getattr(monarch_service, "sync_simplefin_accounts", None)
    if not fn:
        return {}
    target_db = get_current_db_path(family_id=family_id)
    try:
        return fn(family_id=family_id, db_path=target_db)
    except TypeError:
        return fn(family_id=family_id)


def _invoke_monarch_sync(family_id: int) -> dict:
    fn = getattr(monarch_service, "trigger_monarch_sync", None) or getattr(monarch_service, "sync_from_monarch", None)
    if not fn:
        return {}
    target_db = get_current_db_path(family_id=family_id)
    try:
        return fn(family_id=family_id, db_path=target_db)
    except TypeError:
        return fn(family_id=family_id)


def _run_unified_account_sync(family_id: int) -> dict:
    """Syncs all connected providers (Monarch Money and/or SimpleFIN Bridge) for the household."""
    monarch_configured = sfin_configured = False
    target_db = get_current_db_path(family_id=family_id)
    try:
        if target_db.exists() and family_id:
            creds = security.db_load_encrypted(target_db, "monarch_credentials", family_id=family_id) or {}
            sess_file = monarch_service.get_family_session_file(family_id)
            monarch_configured = bool((isinstance(creds, dict) and (creds.get("token") or creds.get("email"))) or (sess_file and sess_file.exists()))
            sfin_status = monarch_service.get_simplefin_status(family_id=family_id, db_path=target_db)
            sfin_configured = bool(isinstance(sfin_status, dict) and sfin_status.get("is_connected"))
    except Exception:
        pass

    if sfin_configured and not monarch_configured:
        return _invoke_simplefin_sync(family_id)
    if monarch_configured and not sfin_configured:
        return _invoke_monarch_sync(family_id)
    if monarch_configured and sfin_configured:
        m_res = _invoke_monarch_sync(family_id)
        if not isinstance(m_res, dict):
            m_res = {"success": False}
        if not m_res.get("simplefin_synced"):
            s_res = _invoke_simplefin_sync(family_id)
            if isinstance(s_res, dict) and s_res.get("success"):
                if not m_res.get("success"):
                    return s_res
                m_res["accounts_count"] = int(m_res.get("accounts_count", 0)) + int(s_res.get("accounts_count", 0))
                m_res["holdings_count"] = int(m_res.get("holdings_count", 0)) + int(s_res.get("holdings_count", 0))
                m_res["simplefin_synced"] = True
                m_res["providers"] = ["monarch", "simplefin"]
                m_res["message"] = f"Account sync complete! Refreshed {m_res['accounts_count']} accounts across Monarch Money & SimpleFIN."
        return m_res
    return _invoke_monarch_sync(family_id)


def _invalidate_family_forecast_cache(family_id: int) -> None:
    try:
        from forecast.cache import invalidate_family_cache
        invalidate_family_cache(family_id)
    except Exception:
        pass


def _parse_snapshot_item(item: dict) -> dict:
    try:
        balance = float(item.get("balance", 0.0) or 0.0)
    except (ValueError, TypeError):
        raise ValueError("Invalid balance amount.")
    return {
        "account_id": sanitize_text(item.get("account_id") or "", max_length=100, field_name="Account ID") or None,
        "account_name": sanitize_text(item.get("account_name") or item.get("name") or "", max_length=120, field_name="Account Name"),
        "date": sanitize_text(item.get("date") or item.get("as_of_date") or "", max_length=10, field_name="Date", required=True),
        "balance": balance,
        "role": sanitize_text(item.get("role") or "", max_length=50, field_name="Role") or "public_brokerage",
        "institution": sanitize_text(item.get("institution") or "Manual Entry", max_length=100, field_name="Institution") or "Manual Entry",
        "provider": sanitize_text(item.get("provider") or item.get("source") or "manual", max_length=30, field_name="Provider") or "manual",
    }


def _is_demo_or_readonly_beta() -> bool:
    return bool(session.get("is_demo") or (get_current_universe() == "beta" and session.get("role") != "admin"))


@dashboard_bp.route("/api/sync", methods=["POST"])
@login_required
def api_sync():
    """Triggers an on-demand sync across all connected account providers (Monarch Money and/or SimpleFIN Bridge)."""
    try:
        family_id = get_current_family_id()
        body = request.get_json(silent=True) or {}
        run_sync = background_jobs.should_run_synchronously(
            sync_param=body.get("sync", request.args.get("sync")),
            async_param=body.get("async", request.args.get("async")),
        )
        if session.get("is_demo"):
            accounts = db.accounts.list_accounts(family_id=family_id, db_path=DB_PATH) or []
            demo_res = {
                "success": True,
                "message": f"Demo Sandbox: Simulated account sync refreshed {len(accounts)} demo accounts (read-only).",
                "accounts_count": len(accounts),
            }
            if not run_sync:
                job_id = background_jobs.submit_job(
                    job_type="monarch_sync", family_id=family_id, universe=get_current_universe(), fn=lambda: demo_res
                )
                return jsonify({"success": True, "status": "processing", "job_id": job_id, "message": "Demo account sync queued in background..."})
            return jsonify(demo_res)

        from routes.helpers import is_sandbox_session
        from db.telemetry import record_portal_telemetry_event
        if is_sandbox_session():
            from hvl_common.web.rate_limit import _default_limiter
            allowed, retry_after, _ = _default_limiter.evaluate("2/hr", scope=f"sandbox_sync:{family_id}")
            if not allowed:
                record_portal_telemetry_event("sandbox", "rate_limit_hit", feature_key="monarch_sync")
                return jsonify({
                    "success": False,
                    "error": "Sandbox Mode allows up to 2 live institution syncs per hour to protect shared server limits. You can continue editing accounts manually, download your vault, or sign in for unlimited syncs.",
                    "retry_after": retry_after,
                }), 429
        record_portal_telemetry_event(get_current_universe(), "monarch_sync", feature_key=str(family_id))

        if run_sync:
            return jsonify(_run_unified_account_sync(family_id=family_id))
        job_id = background_jobs.submit_job(
            lambda: _run_unified_account_sync(family_id=family_id),
            job_type="monarch_sync", family_id=family_id, universe=get_current_universe(),
        )
        return jsonify({"success": True, "status": "processing", "job_id": job_id, "message": "Account sync started in background..."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/sync/status/<job_id>", methods=["GET"])
@login_required
def api_sync_status(job_id: str):
    """Fast (<2ms) non-blocking status lookup for a background account sync job."""
    family_id = get_current_family_id()
    clean_id = sanitize_text(job_id, max_length=64, field_name="Job ID")
    job = background_jobs.get_job(clean_id, family_id=family_id)
    if not job:
        return jsonify({"success": False, "status": "not_found", "error": "Sync job not found."}), 404
    if job["status"] == "processing":
        return jsonify({"success": True, "status": "processing", "job_id": clean_id})
    if job["status"] == "failed":
        return jsonify({"success": False, "status": "failed", "job_id": clean_id, "error": job.get("error") or "Account sync failed."}), 500
    result_payload = job.get("result") or {}
    return jsonify({**result_payload, "status": "completed", "job_id": clean_id})


@dashboard_bp.route("/api/accounts/toggle_net_worth", methods=["POST"])
@editor_required
def api_accounts_toggle_net_worth():
    """Toggles an account's includeInNetWorth flag via an atomic single-row relational update."""
    try:
        family_id = get_current_family_id()
        body = request.get_json() or {}
        account_id = sanitize_text(body.get("account_id", ""), max_length=100, field_name="Account ID")
        include = body.get("include_in_net_worth")
        if not account_id:
            return jsonify({"success": False, "error": "account_id is required."}), 400

        updated_acc = db.accounts.toggle_account_net_worth(
            family_id=family_id, account_id=account_id, include=bool(include), db_path=DB_PATH
        )
        if not updated_acc:
            return jsonify({"success": False, "error": "Account not found."}), 404

        target_name = updated_acc.get("displayName") if isinstance(updated_acc, dict) else (updated_acc or account_id)
        snapshot = monarch_service.get_financial_snapshot(family_id=family_id)
        return jsonify({
            "success": True, "message": f"Updated {target_name}: Include in Net Worth = {include}.",
            "new_true_net_worth": snapshot.get("true_net_worth"), "new_monarch_net_worth": snapshot.get("monarch_reported_net_worth"),
            "categories": snapshot.get("categories"),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/accounts/manual", methods=["POST"])
@editor_required
def api_upsert_manual_account():
    """Creates or updates a first-class manual account (manual_<hex>) in monarch_accounts and account_roles."""
    try:
        if _is_demo_or_readonly_beta():
            return jsonify({"success": False, "error": "Manual accounts cannot be modified in demo mode."}), 403
        family_id = get_current_family_id()
        body = request.get_json(silent=True) or {}
        acc_id = sanitize_text(body.get("account_id") or body.get("id") or "", max_length=100, field_name="Account ID") or None
        name = sanitize_text(body.get("name") or body.get("displayName"), max_length=120, field_name="Account Name", required=True)
        try:
            balance = float(body.get("balance", 0.0) or 0.0)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid balance amount."}), 400
        role = sanitize_text(body.get("role") or "", max_length=50, field_name="Account Role") or "public_brokerage"
        institution = sanitize_text(body.get("institution") or "Manual Entry", max_length=100, field_name="Institution") or "Manual Entry"
        as_of_date = sanitize_text(body.get("as_of_date") or body.get("date") or "", max_length=10, field_name="As of Date") or None

        acc_dict = db.accounts.upsert_manual_account(
            family_id=family_id, account_id=acc_id, display_name=name, balance=balance, role=role,
            institution_name=institution, include_in_net_worth=bool(body.get("include_in_net_worth", True)),
            as_of_date=as_of_date, db_path=DB_PATH,
        )
        _invalidate_family_forecast_cache(family_id)
        snapshot = monarch_service.get_financial_snapshot(family_id=family_id)
        return jsonify({
            "success": True, "account": acc_dict, "message": f"Saved manual account '{name}'.",
            "new_true_net_worth": snapshot.get("true_net_worth"), "categories": snapshot.get("categories"),
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/accounts/manual/<account_id>", methods=["DELETE"])
@editor_required
def api_delete_manual_account(account_id: str):
    """Deletes a manual account (manual_*) and its role override."""
    try:
        if _is_demo_or_readonly_beta():
            return jsonify({"success": False, "error": "Manual accounts cannot be deleted in demo mode."}), 403
        family_id = get_current_family_id()
        clean_id = sanitize_text(account_id, max_length=100, field_name="Account ID", required=True)
        if not clean_id.startswith("manual_"):
            return jsonify({"success": False, "error": "Only manual accounts (manual_*) can be deleted via this endpoint."}), 400
        if not db.accounts.delete_manual_account(family_id=family_id, account_id=clean_id, db_path=DB_PATH):
            return jsonify({"success": False, "error": "Manual account not found."}), 404

        _invalidate_family_forecast_cache(family_id)
        snapshot = monarch_service.get_financial_snapshot(family_id=family_id)
        return jsonify({
            "success": True, "account_id": clean_id, "message": "Manual account deleted.",
            "new_true_net_worth": snapshot.get("true_net_worth"), "categories": snapshot.get("categories"),
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/accounts/history", methods=["GET"])
@login_required
def api_get_accounts_history():
    """Returns dated balance snapshots and the rebuilt historical net worth timeline."""
    try:
        family_id = get_current_family_id()
        history = db.accounts.get_account_balance_history(family_id=family_id, db_path=DB_PATH)
        nw_payload = build_networth_history_payload(family_id=family_id)
        return jsonify({"success": True, "history": history, "historical_net_worth": nw_payload.get("historical_net_worth", [])})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/accounts/history", methods=["POST"])
@editor_required
def api_post_accounts_history():
    """Records or updates one or more historical account balance snapshots."""
    try:
        if _is_demo_or_readonly_beta():
            return jsonify({"success": False, "error": "Balance history cannot be modified in demo mode."}), 403
        family_id = get_current_family_id()
        body = request.get_json(silent=True) or {}
        raw_items = body.get("snapshots") if isinstance(body.get("snapshots"), list) else [body]
        cleaned_snapshots = [_parse_snapshot_item(item) for item in raw_items if isinstance(item, dict)]
        if not cleaned_snapshots:
            return jsonify({"success": False, "error": "No valid balance snapshots provided."}), 400

        rec_res = db.accounts.record_account_balance_snapshots(family_id=family_id, snapshots=cleaned_snapshots, db_path=DB_PATH)
        _invalidate_family_forecast_cache(family_id)
        history = db.accounts.get_account_balance_history(family_id=family_id, db_path=DB_PATH)
        nw_payload = build_networth_history_payload(family_id=family_id)
        return jsonify({
            "success": True, "recorded": rec_res, "history": history,
            "historical_net_worth": nw_payload.get("historical_net_worth", []),
            "message": f"Recorded {len(cleaned_snapshots)} balance snapshot(s).",
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/accounts/history", methods=["DELETE"])
@editor_required
def api_delete_accounts_history():
    """Deletes a specific dated balance snapshot for an account."""
    try:
        if _is_demo_or_readonly_beta():
            return jsonify({"success": False, "error": "Balance history cannot be modified in demo mode."}), 403
        family_id = get_current_family_id()
        body = request.get_json(silent=True) or {}
        account_id = sanitize_text(body.get("account_id") or request.args.get("account_id") or "", max_length=100, field_name="Account ID", required=True)
        date_str = sanitize_text(
            body.get("date") or body.get("as_of_date") or request.args.get("date") or request.args.get("as_of_date") or "",
            max_length=10, field_name="Date", required=True,
        )
        if not db.accounts.delete_account_balance_snapshot(family_id=family_id, account_id=account_id, date_str=date_str, db_path=DB_PATH):
            return jsonify({"success": False, "error": "Snapshot not found."}), 404

        _invalidate_family_forecast_cache(family_id)
        history = db.accounts.get_account_balance_history(family_id=family_id, db_path=DB_PATH)
        nw_payload = build_networth_history_payload(family_id=family_id)
        return jsonify({"success": True, "history": history, "historical_net_worth": nw_payload.get("historical_net_worth", []), "message": f"Deleted snapshot for {date_str}."})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _execute_csv_balance_import(family_id: int, clean_csv: str) -> dict:
    res = db.accounts.parse_and_import_balance_csv(family_id=family_id, csv_text=clean_csv, db_path=DB_PATH)
    _invalidate_family_forecast_cache(family_id)
    nw_payload = build_networth_history_payload(family_id=family_id)
    out = dict(res) if isinstance(res, dict) else {"imported_rows": res}
    out.setdefault("success", True)
    out["historical_net_worth"] = nw_payload.get("historical_net_worth", [])
    return out


@dashboard_bp.route("/api/accounts/import_csv", methods=["POST"])
@editor_required
def api_import_accounts_csv():
    """Imports historical or current account balances from CSV (supports async background job execution)."""
    try:
        if _is_demo_or_readonly_beta():
            return jsonify({"success": False, "error": "CSV import is disabled in demo mode."}), 403
        family_id = get_current_family_id()
        body = request.get_json(silent=True) or {}
        if "file" in request.files and request.files["file"]:
            csv_text = request.files["file"].read(2 * 1024 * 1024).decode("utf-8-sig", errors="replace")
        else:
            csv_text = body.get("csv_text") or body.get("csv") or ""
        clean_csv = sanitize_text(csv_text, max_length=500000, field_name="CSV Content", required=True, multiline=True)

        if str(body.get("async", request.args.get("async", ""))).lower() in ("1", "true", "yes"):
            job_id = background_jobs.submit_job(
                lambda: _execute_csv_balance_import(family_id, clean_csv),
                job_type="csv_balance_import", family_id=family_id, universe=get_current_universe(),
            )
            return jsonify({"success": True, "status": "processing", "job_id": job_id})
        return jsonify(_execute_csv_balance_import(family_id, clean_csv))
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/accounts/export_csv", methods=["GET"])
@login_required
def api_export_accounts_csv():
    """Exports the household's account balances and historical snapshots as a downloadable CSV."""
    try:
        family_id = get_current_family_id()
        export_fn = getattr(db.accounts, "export_balances_csv", None)
        csv_data = export_fn(family_id=family_id, db_path=DB_PATH) if callable(export_fn) else "Date,Account Name,Balance,Role,Institution,Provider\n"
        return Response(
            csv_data, mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="family_office_account_balances.csv"', "Cache-Control": "no-store"},
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
