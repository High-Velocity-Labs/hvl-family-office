"""
Shared Siri & Apple Shortcuts Voice Webhook Blueprint (`hvl_common.web.siri`).

Provides `create_siri_blueprint` with Bearer token authentication, session-backed
token minting/revocation, rate-limit hooks, and non-blocking `submit_job` background
execution with `/api/siri/jobs/<job_id>` polling.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from flask import Blueprint, current_app, has_app_context, jsonify, request, session

from hvl_common.web.jobs import get_job, should_run_synchronously, submit_job

MAX_USER_MESSAGE_CHARS = 2000


def _extract_bearer_token(data: dict[str, Any] | None = None) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split("Bearer ", 1)[1].strip()
    if isinstance(data, dict) and data.get("token"):
        return str(data.get("token") or "").strip()
    return str(request.args.get("token") or "").strip()


def _authenticate_siri_caller(
    authenticate_token_fn: Callable[[str], dict[str, Any] | None],
    data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, Any]:
    raw_token = _extract_bearer_token(data)
    if not raw_token:
        if (
            session.get("is_demo")
            or session.get("role") == "viewer"
            or session.get("universe") == "demo"
        ):
            return None, (
                jsonify({
                    "success": False,
                    "error": "Forbidden: Demo or viewer sessions cannot invoke Siri webhook.",
                    "reply": "Forbidden: Demo or viewer sessions cannot invoke Siri webhook.",
                }),
                403,
            )
        return None, (
            jsonify({
                "success": False,
                "error": "Unauthorized: Missing Siri token.",
                "reply": "Unauthorized: Missing Siri token.",
            }),
            401,
        )
    member = authenticate_token_fn(raw_token)
    if not member:
        return None, (
            jsonify({
                "success": False,
                "error": "Unauthorized: Invalid or revoked Siri token.",
                "reply": "Unauthorized: Invalid or revoked Siri token.",
            }),
            401,
        )
    return member, None


def _check_session_user(
    get_current_user_fn: Callable[[], dict[str, Any] | None],
) -> tuple[dict[str, Any] | None, Any]:
    user = get_current_user_fn() if get_current_user_fn is not None else None
    if isinstance(user, dict) and (
        user.get("is_demo") or str(user.get("role") or "").strip().lower() == "viewer"
    ):
        return None, (jsonify({"success": False, "error": "Read-only session cannot modify Siri keys."}), 403)
    if (
        session.get("is_demo")
        or session.get("role") == "viewer"
        or session.get("universe") == "demo"
    ):
        return None, (jsonify({"success": False, "error": "Read-only session cannot modify Siri keys."}), 403)
    if not isinstance(user, dict):
        return None, (jsonify({"success": False, "error": "Authentication required."}), 401)
    email = str(user.get("email") or "").strip()
    if not email or email == "unseeded@localhost" or user.get("is_authenticated") is False:
        return None, (jsonify({"success": False, "error": "Authentication required."}), 401)
    return user, None


def _evaluate_rate_limit(
    rate_limit_fn: Callable[..., Any] | None,
    member: dict[str, Any],
    prompt: str,
) -> Any:
    if rate_limit_fn is None:
        return None
    try:
        params = list(inspect.signature(rate_limit_fn).parameters.values())
        res = rate_limit_fn(member, prompt) if len(params) >= 2 else rate_limit_fn(member)
    except TypeError:
        res = rate_limit_fn(member)
    if isinstance(res, tuple) and len(res) >= 1 and isinstance(res[0], bool):
        if not res[0]:
            msg = str(res[1] if len(res) > 1 and res[1] else "Rate limit exceeded.")
            return jsonify({"success": False, "error": msg, "reply": msg}), 429
        return None
    return res


def create_siri_blueprint(
    *,
    authenticate_token_fn: Callable[[str], dict[str, Any] | None],
    mint_token_fn: Callable[[dict[str, Any]], str],
    revoke_token_fn: Callable[[dict[str, Any]], bool],
    get_current_user_fn: Callable[[], dict[str, Any] | None],
    execute_siri_turn_fn: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    rate_limit_fn: Callable[..., Any] | None = None,
    open_url: str = "/",
    async_jobs_enabled: bool = True,
    cache_db_path_fn: Callable[[], Any] | Any = None,
    max_chars_fn: Callable[[dict[str, Any]], int] | int = MAX_USER_MESSAGE_CHARS,
    blueprint_name: str = "siri",
    url_prefix: str = "/api/siri",
) -> Blueprint:
    """Creates a shared Flask Blueprint for `/api/siri` voice turns, async jobs, and token management."""
    bp = Blueprint(blueprint_name, __name__, url_prefix=url_prefix)

    def _resolve_db_path() -> Any:
        return cache_db_path_fn() if callable(cache_db_path_fn) else cache_db_path_fn

    @bp.route("", methods=["POST"])
    def handle_siri_turn():
        data = request.get_json(silent=True) or {}
        member, auth_err = _authenticate_siri_caller(authenticate_token_fn, data)
        if auth_err is not None or member is None:
            return auth_err

        prompt = (
            str(data.get("text") or data.get("prompt") or "").strip()
            or str(request.form.get("text") or request.form.get("prompt") or "").strip()
        )
        if not prompt:
            return jsonify({"success": False, "reply": "I'm listening. What would you like to do?"}), 200

        max_chars = int(max_chars_fn(member) if callable(max_chars_fn) else (max_chars_fn or MAX_USER_MESSAGE_CHARS))
        if len(prompt) > max_chars:
            msg = f"Prompt exceeds {max_chars} character limit."
            return jsonify({"success": False, "error": msg, "reply": msg}), 400

        limited = _evaluate_rate_limit(rate_limit_fn, member, prompt)
        if limited is not None:
            return limited

        run_turn = lambda: execute_siri_turn_fn(member, prompt, data)
        is_testing = bool(current_app.config.get("TESTING")) if has_app_context() else False
        sync_flag = data.get("sync", False) if is_testing else False
        run_sync = (not async_jobs_enabled) or should_run_synchronously(
            data,
            sync_param=True if (is_testing and "sync" not in data) else sync_flag,
        )
        if not run_sync:
            hh_id = int(member.get("household_id") or member.get("family_id") or 0)
            job_id = submit_job(
                run_turn,
                job_type="siri_turn",
                family_id=hh_id,
                initial_meta={"owner_email": str(member.get("email") or "").strip().lower()},
                cache_db_path=_resolve_db_path(),
            )
            return jsonify({
                "success": True,
                "status": "processing",
                "job_id": job_id,
                "poll_url": f"{url_prefix}/jobs/{job_id}",
            })

        result = run_turn() or {}
        return jsonify({
            "success": bool(result.get("success", True)),
            "reply": str(result.get("reply") or "Done."),
            "intent": str(result.get("intent") or "turn"),
            "imessage_handoff": result.get("imessage_handoff", []),
            "open_url": str(result.get("open_url") if result.get("open_url") is not None else open_url),
        })

    @bp.route("/jobs/<string:job_id>", methods=["GET"])
    def get_siri_job_status(job_id: str):
        member, auth_err = _authenticate_siri_caller(authenticate_token_fn)
        if auth_err is not None or member is None:
            return auth_err

        hh_id = int(member.get("household_id") or member.get("family_id") or 0)
        job = get_job(
            job_id.strip()[:64],
            family_id=hh_id if hh_id > 0 else None,
            cache_db_path=_resolve_db_path(),
        )
        if not job:
            return jsonify({"success": False, "error": "Siri job not found"}), 404
        job_owner = str(job.get("owner_email") or "").strip().lower()
        caller_email = str(member.get("email") or "").strip().lower()
        if job_owner and caller_email and job_owner != caller_email:
            return jsonify({"success": False, "error": "Siri job not found"}), 404

        status = str(job.get("status") or "processing")
        if status == "completed":
            res = job.get("result")
            out = dict(res) if isinstance(res, dict) else {"success": True, "reply": str(res or "Done.")}
            out.setdefault("success", True)
            out.update({"job_id": job_id, "status": "completed"})
            return jsonify(out)
        if status == "failed":
            return jsonify({
                "success": False,
                "status": "failed",
                "job_id": job_id,
                "error": job.get("error") or "Siri job failed",
            })
        return jsonify({"success": True, "status": "processing", "job_id": job_id})

    @bp.route("/mint-token", methods=["POST"])
    def mint_token():
        user, err = _check_session_user(get_current_user_fn)
        if err is not None or user is None:
            return err
        token = mint_token_fn(user)
        return jsonify({
            "success": True,
            "token": token,
            "siri_token": token,
            "email": user["email"],
            "endpoint": url_prefix,
        })

    @bp.route("/revoke-token", methods=["POST", "DELETE"])
    @bp.route("/token", methods=["DELETE"])
    def revoke_token():
        user, err = _check_session_user(get_current_user_fn)
        if err is not None or user is None:
            return err
        revoked = bool(revoke_token_fn(user))
        return jsonify({"success": True, "revoked": revoked, "email": user["email"]})

    return bp


__all__ = [
    "MAX_USER_MESSAGE_CHARS",
    "create_siri_blueprint",
]
