"""
Authentication, Demo Persona, Beta Gate, and Universe Switching Helpers.
"""

from __future__ import annotations

from typing import Any
from flask import request, session

DEMO_PERSONAS = [
    {
        "id": 1,
        "slug": "jones",
        "name": "The Jones Family",
        "tag": "Tech + Doctor (SF)",
        "location": "San Francisco, CA",
        "description": "Dual high-earners in SF, 3 kids (College/HS/Grade), NSO grants, high CA state tax",
    },
    {
        "id": 2,
        "slug": "miller",
        "name": "The Miller Family",
        "tag": "FIRE Early Retired (WA)",
        "location": "Seattle, WA",
        "description": "Zero W-2 salary, $6.5M liquid index portfolio, 0% WA tax, Roth conversion ladder",
    },
    {
        "id": 3,
        "slug": "chen",
        "name": "The Chen Family",
        "tag": "Startup Founder (NYC)",
        "location": "New York, NY",
        "description": "Series A founder, ISO / AMT planning, Tribeca condo, toddler 529 superfund",
    },
    {
        "id": 4,
        "slug": "ramirez",
        "name": "The Ramirez Family",
        "tag": "Teacher & Electrician (TX)",
        "location": "Austin, TX",
        "description": "High school teacher + master electrician, $150k HHI, home & auto loan, Texas 529s for 2 kids",
    },
    {
        "id": 5,
        "slug": "taylor",
        "name": "The Taylor Family",
        "tag": "Nurse & Operations (OH)",
        "location": "Columbus, OH",
        "description": "Registered nurse + warehouse supervisor, $126k HHI, student loans, building 401(k) & emergency fund",
    },
    {
        "id": 6,
        "slug": "foster",
        "name": "The Foster Family",
        "tag": "Single Mom & PT (CO)",
        "location": "Denver, CO",
        "description": "Solo pediatric physical therapist, 1 child (age 12), Head of Household, Colorado 529, 403(b) & Roth IRA",
    },
]


def _resolve_persona_id(val: Any) -> int:
    """Maps a slug or numeric ID to a valid demo persona family_id (1..7)."""
    if val is None:
        return 1
    s = str(val).strip().lower()
    if s in ("1", "jones", "jones_sf"):
        return 1
    if s in ("2", "miller", "miller_fire", "fire"):
        return 2
    if s in ("3", "chen", "chen_founder", "founder"):
        return 3
    if s in ("4", "ramirez", "teacher", "electrician"):
        return 4
    if s in ("5", "taylor", "nurse", "logistics"):
        return 5
    if s in ("6", "foster", "single", "single_parent"):
        return 6
    if s in ("7", "empty", "blank", "new"):
        return 7
    try:
        n = int(s)
        if 1 <= n <= 7:
            return n
    except ValueError:
        pass
    return 1


import threading

_VERIFIED_DEMO_DB_STATE: tuple[str, float] | None = None
_DEMO_DB_LOCK = threading.Lock()


def ensure_demo_database() -> None:
    """Ensures demo database exists and is seeded with all demo personas."""
    global _VERIFIED_DEMO_DB_STATE
    try:
        import db
        from config import get_family_db_path, get_global_db_path
        demo_db = get_global_db_path("demo")
        fam_db = get_family_db_path(1, universe="demo")
        if demo_db.exists() and fam_db.exists() and _VERIFIED_DEMO_DB_STATE == (str(demo_db), demo_db.stat().st_mtime):
            return
        with _DEMO_DB_LOCK:
            if demo_db.exists() and fam_db.exists() and _VERIFIED_DEMO_DB_STATE == (str(demo_db), demo_db.stat().st_mtime):
                return
            if not fam_db.exists() or not db.families.is_demo_database_seeded(demo_db):
                from scripts.seed_demo_families import seed_all_demo_families
                demo_db.parent.mkdir(parents=True, exist_ok=True)
                seed_all_demo_families(demo_db, verbose=False)
            if demo_db.exists():
                _VERIFIED_DEMO_DB_STATE = (str(demo_db), demo_db.stat().st_mtime)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not auto-seed demo database: %s", e)



def _is_site_admin_request() -> bool:
    """Returns True if the current session or verified admin gate cookie belongs to a Site Administrator."""
    import config
    remote_ip = str(request.remote_addr or "")
    host_str = str(request.host or "")
    if remote_ip.startswith("192.168.") or ":5001" in host_str or config.is_local_mode():
        if not session.get("is_demo"):
            return True
    if _resolve_verified_admin_email():
        return True
    global_db = config.get_global_db_path("public")
    prev_email = str(session.get("prev_user_email") or "").strip().lower()
    if prev_email and config.is_site_admin_email(prev_email, db_path=global_db):
        return True
    if not session.get("authenticated") or session.get("is_demo"):
        return False
    active_email = str(session.get("user_email") or "").strip().lower()
    active_role = str(session.get("user_role") or session.get("role") or "viewer").lower()
    family_id = int(session.get("user_family_id") or session.get("family_id") or 0)
    universe = str(session.get("universe") or "public")
    return bool(
        config.is_site_admin_email(active_email, db_path=global_db)
        or (family_id == int("1") and active_role in ("admin", "editor") and (universe == "public" or session.get("user_family_id") == int("1")))
    )


def _resolve_verified_admin_email() -> str:
    """Returns the verified site administrator email from the active session or cross-subdomain gate cookie, or `""`."""
    import config
    from hvl_common.security import ADMIN_GATE_COOKIE_NAME, unwrap_admin_gate_token

    global_db = config.get_global_db_path("public")
    if session.get("authenticated") and not session.get("is_demo"):
        active_email = str(session.get("user_email") or "").strip().lower()
        active_role = str(session.get("role") or session.get("user_role") or "viewer").lower()
        family_id = int(session.get("family_id") or session.get("user_family_id") or 0)
        if active_email and (
            config.is_site_admin_email(active_email, db_path=global_db)
            or (family_id == int("1") and active_role in ("admin", "editor"))
        ):
            return active_email

    gate_cookie = request.cookies.get(ADMIN_GATE_COOKIE_NAME, "")
    if gate_cookie:
        email = unwrap_admin_gate_token(gate_cookie, config.get_admin_gate_secret_keys())
        if email and (
            config.is_site_admin_email(email, db_path=global_db)
            or not config.get_site_admin_emails(db_path=global_db)
        ):
            return email
    return ""


def is_beta_gate_authorized() -> bool:
    """Returns True if the current request is authorized to access `finances-beta`."""
    import config
    remote_ip = str(request.remote_addr or "")
    if remote_ip in ("127.0.0.1", "::1") or remote_ip.startswith("192.168.") or config.is_local_mode():
        return True
    return bool(_resolve_verified_admin_email())


def maybe_attach_admin_gate_cookie(response: Any) -> Any:
    """Attaches/refreshes the cross-subdomain `hvl_beta_admin` cookie for verified Site Administrators."""
    if not _is_site_admin_request():
        return response
    active_email = str(session.get("user_email") or "").strip().lower()
    if not active_email:
        return response
    import config
    from hvl_common.security import ADMIN_GATE_COOKIE_NAME, wrap_admin_gate_token

    existing = request.cookies.get(ADMIN_GATE_COOKIE_NAME, "")
    if existing and _resolve_verified_admin_email() == active_email:
        return response

    keys = config.get_admin_gate_secret_keys()
    if not keys:
        return response
    token = wrap_admin_gate_token(active_email, keys[0])
    if not token:
        return response
    host = (request.host or "").split(":", 1)[0].strip().lower()
    cookie_domain = ".highvelocitylabs.dev" if host.endswith("highvelocitylabs.dev") else None
    is_sec = bool(request.is_secure or request.headers.get("X-Forwarded-Proto") == "https")
    response.set_cookie(
        ADMIN_GATE_COOKIE_NAME,
        token,
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=is_sec,
        samesite="Lax",
        domain=cookie_domain,
    )
    return response


def _normalize_target_universe(raw_uni: str) -> str:
    try:
        import config
        if hasattr(config, "normalize_universe"):
            return config.normalize_universe(raw_uni)
    except Exception:
        pass
    return "demo" if raw_uni == "beta" else ("public" if raw_uni in ("dev", "") else raw_uni)


def _apply_universe_switch_session(target_universe: str, body: dict, own_fid: int) -> tuple[dict, int]:
    from config import get_global_db_path
    import db

    req_fid_raw = body.get("family_id")
    support_mode = bool(body.get("support_mode", False))
    if target_universe == "public":
        req_fid = int(req_fid_raw) if req_fid_raw is not None else own_fid
        if support_mode or (req_fid_raw is not None and req_fid != own_fid):
            target_db = get_global_db_path("public")
            if not db.families.is_support_access_enabled(family_id=req_fid, db_path=target_db):
                return {"success": False, "error": "Support access is locked for this household."}, 403
            target_family_id = req_fid
        else:
            target_family_id = own_fid
        session["is_demo"] = False
        session["role"] = session.get("user_role", "admin")
    else:
        target_family_id = int(req_fid_raw) if req_fid_raw is not None else _resolve_persona_id(None)
        target_db = get_global_db_path(target_universe)
        if target_db.exists():
            fam_rec = db.families.get_family(family_id=target_family_id, db_path=target_db)
            if fam_rec is not None and not fam_rec.get("support_access_enabled", True):
                return {"success": False, "error": "Support access is locked for this household."}, 403
        as_viewer = body.get("as_viewer")
        session["is_demo"] = (target_universe == "demo" and bool(as_viewer)) if as_viewer is not None else (target_universe == "demo")
        session["role"] = "viewer" if session["is_demo"] else "admin"

    session["universe"] = target_universe
    session["family_id"] = target_family_id
    return {"success": True, "universe": target_universe, "family_id": target_family_id, "role": session["role"]}, 200
