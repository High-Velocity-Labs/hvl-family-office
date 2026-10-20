"""
SSR view-model builder for the Family Office Settings modal & tab.
"""

from __future__ import annotations
import logging

import db
import security
from routes.helpers import DB_PATH, get_current_db_path
from ssr.formatting import fmt_currency

logger = logging.getLogger(__name__)

VALID_SETTINGS_TABS = (
    "members",
    "assumptions",
    "roles",
    "integrations",
    "monarch",
    "simplefin",
    "advisor-history",
    "security",
    "appearance",
)


def build_ssr_settings(
    family_id: int = 0,
    active_tab: str | None = None,
    adv_search: str | None = None,
    adv_page: str | None = None,
    adv_pinned_only: bool = False,
) -> dict:
    """Prepares SSR data for Settings modal/tab (members, legal profile, assumptions, account roles, monarch/simplefin status, advisor conversations)."""
    raw_tab = str(active_tab or "").strip().lower()
    if raw_tab.startswith("settings-tab-"):
        raw_tab = raw_tab[len("settings-tab-"):]
    elif raw_tab.startswith("tab-btn-"):
        raw_tab = raw_tab[len("tab-btn-"):]
    norm_tab = raw_tab if raw_tab in VALID_SETTINGS_TABS else "members"

    clean_search = str(adv_search or "").strip()
    clean_page = str(adv_page or "").strip()
    if isinstance(adv_pinned_only, bool):
        is_pinned_filter = adv_pinned_only
    else:
        is_pinned_filter = str(adv_pinned_only or "").strip().lower() in ("1", "true", "yes")

    if family_id <= 0:
        return {
            "active_tab": norm_tab,
            "adv_search": clean_search,
            "adv_page": clean_page,
            "adv_pinned_only": is_pinned_filter,
            "family_name": "Family Office",
            "support_access_enabled": False,
            "members": [],
            "assumptions": {},
            "roles": [],
            "available_roles": [],
            "children": [],
            "monarch_status": {
                "is_connected": False,
                "status_text": "Not Connected",
                "last_sync": "Never",
                "accounts_count": 0,
                "auth_mode": "None",
            },
            "simplefin_status": {
                "is_connected": False,
                "status_text": "Not Connected",
                "last_sync": "Never",
                "accounts_count": 0,
                "auth_mode": "None",
                "warnings": [],
            },
            "ai_key_status": {
                "has_custom_key": False,
                "masked_key": "",
                "has_server_key": False,
                "is_local_mode": False,
            },
            "advisor_conversations": [],
        }

    target_db = get_current_db_path(family_id=family_id) if family_id > 0 else DB_PATH
    fam = security.get_family(target_db, family_id=family_id)
    family_name = (fam.get("name") if fam else None) or "Family Office"
    support_access_enabled = bool(fam.get("support_access_enabled")) if fam else False

    members_raw = security.get_family_members(target_db, family_id=family_id) or []
    members = []
    for m in members_raw:
        members.append({
            "user_id": m.get("user_id"),
            "name": m.get("name") or "Member",
            "relationship": m.get("relationship") or "dependent",
            "birthdate": m.get("birthdate") or "",
            "role": m.get("role") or "viewer",
            "email": m.get("email") or "",
        })

    default_state = "WA"
    try:
        from flask import has_request_context, request
        if has_request_context():
            geo_hdr = (
                request.headers.get("CF-IPRegion")
                or request.headers.get("X-Geo-Region")
                or request.headers.get("X-AppEngine-Region")
                or ""
            ).strip().upper()
            if geo_hdr in ("CA", "CO", "FL", "IL", "MA", "NJ", "NV", "NY", "OR", "TX", "VA", "WA", "WY"):
                default_state = geo_hdr
    except Exception:
        pass

    assumptions = {
        "state": default_state,
        "has_saved_state": False,
        "filing_status": "MFJ",
        "annual_spending": "--",
        "annual_savings": "--",
        "retirement_age": 65,
        "inflation_rate": "2.5%",
    }
    if target_db.exists():
        try:
            hp = db.families.get_household_profile(family_id=family_id, db_path=target_db)
            if hp:
                assumptions.update({
                    "state": hp.get("state") or default_state,
                    "has_saved_state": bool(hp.get("state")),
                    "filing_status": hp.get("filing_status", "MFJ"),
                    "annual_spending": fmt_currency(float(hp["annual_spending"]), 0) if hp.get("annual_spending") is not None and float(hp["annual_spending"]) > 0 else "--",
                    "annual_savings": fmt_currency(float(hp["annual_savings"]), 0) if hp.get("annual_savings") is not None and float(hp["annual_savings"]) > 0 else "--",
                    "retirement_age": hp.get("retirement_age", 65),
                    "inflation_rate": f"{float(hp.get('inflation_rate') or 0.025) * 100:.1f}%",
                })
        except Exception:
            pass

    roles_list = []
    available_roles_list = []
    children_list = [m for m in members if m.get("relationship") in ("child", "dependent")]
    try:
        from monarch.categorizer import (
            AVAILABLE_ROLES, ROLE_ALIASES, get_family_company_names, suggest_account_role_and_beneficiary,
        )
        available_roles_list = AVAILABLE_ROLES
        accounts_list = db.accounts.list_accounts(family_id=family_id, db_path=target_db) if target_db.exists() else []
        family_comps = get_family_company_names(family_id=family_id) if accounts_list else []
        roles_map = {
            str(r["monarch_account_id"]): dict(r)
            for r in (db.families.get_account_roles(family_id=family_id, db_path=target_db) or [] if target_db.exists() else [])
            if isinstance(r, dict) or hasattr(r, "__getitem__")
        }
        for acc in accounts_list:
            aid = str(acc.get("id"))
            role_info = roles_map.get(aid, {})
            is_confirmed = bool(role_info.get("is_user_confirmed", 0))
            db_role = role_info.get("role")
            db_ben = role_info.get("beneficiary_user_id")

            if is_confirmed and db_role:
                active_role, active_ben = ROLE_ALIASES.get(db_role, db_role), db_ben
            else:
                sugg_role, sugg_ben = suggest_account_role_and_beneficiary(
                    acc, children_list, family_id=family_id, family_comps=family_comps
                )
                active_role = ROLE_ALIASES.get(db_role, db_role) if db_role else sugg_role
                active_ben = (db_ben or sugg_ben) if db_role else sugg_ben

            is_hidden_fo = bool(role_info.get("is_hidden_from_family_office", 0))

            if active_role in ("company_equity_nso", "tax_liability", "hidden_from_family_office", "manual_tax_offset"):
                is_hidden_fo = True

            balance = float(acc.get("currentBalance") or acc.get("current_balance") or acc.get("balance") or 0.0)
            display_name = acc.get("displayName") or acc.get("name") or "Account"
            institution = (
                ((acc.get("credential") or {}).get("displayName") if isinstance(acc.get("credential"), dict) else None)
                or ((acc.get("institution") or {}).get("name") if isinstance(acc.get("institution"), dict) else None)
                or "Institution"
            )
            raw_prov = str(acc.get("provider") or "").lower()
            if aid.startswith("manual_") or raw_prov == "manual":
                prov = "manual"
                source_label = "Manual"
            elif aid.startswith("sfin_") or raw_prov == "simplefin":
                prov = "simplefin"
                source_label = "SimpleFIN"
            else:
                prov = "monarch"
                source_label = "Monarch Money"

            roles_list.append({
                "account_id": aid,
                "name": display_name,
                "display_name": display_name,
                "institution": institution,
                "provider": prov,
                "source_label": source_label,
                "balance": balance,
                "balance_str": fmt_currency(balance, 2),
                "role": active_role,
                "beneficiary_user_id": active_ben,
                "is_confirmed": is_confirmed,
                "is_hidden_from_family_office": is_hidden_fo,
                "hide_from_family_office": is_hidden_fo,
            })
    except Exception as e:
        logger.warning(f"Failed to build SSR account roles: {e}")

    monarch_status = {
        "is_connected": False,
        "status_text": "Not Connected",
        "last_sync": "Never",
        "accounts_count": 0,
        "auth_mode": "None",
    }
    simplefin_status = {
        "is_connected": False,
        "status_text": "Not Connected",
        "last_sync": "Never",
        "accounts_count": 0,
        "auth_mode": "None",
        "warnings": [],
    }
    try:
        import monarch_service
        session_file = monarch_service.get_family_session_file(family_id)
        sync_meta = security.db_load_encrypted(target_db, "last_sync_metadata", family_id=family_id) or {}
        creds = security.db_load_encrypted(target_db, "monarch_credentials", family_id=family_id) or {}
        has_token = bool(creds.get("token"))
        has_session = has_token or session_file.exists()
        has_email = bool(creds.get("email"))
        has_mfa_secret = bool(creds.get("mfa_secret_key"))
        is_conn = has_session or has_token or (has_email and has_mfa_secret)
        raw_ts = sync_meta.get("timestamp")
        last_sync_str = "Never"
        if raw_ts:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                last_sync_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                last_sync_str = str(raw_ts)
        auth_mode = (
            "Automated 2FA (TOTP)"
            if has_mfa_secret
            else ("Persistent Trusted Device" if has_token else ("Active Session Pickle" if has_session else "None"))
        )
        monarch_accs = [r for r in roles_list if r.get("provider") == "monarch"]
        monarch_status = {
            "is_connected": is_conn,
            "status_text": "Connected & Operational" if is_conn else "Not Connected",
            "last_sync": last_sync_str,
            "accounts_count": len(monarch_accs) if monarch_accs else sync_meta.get("accounts_count", 0),
            "auth_mode": auth_mode,
        }
        simplefin_status = monarch_service.get_simplefin_status(family_id=family_id, db_path=target_db)
    except Exception as e:
        logger.warning(f"Failed to build SSR monarch/simplefin status: {e}")

    advisor_conversations = []
    try:
        if target_db.exists():
            convs = db.conversations.list_conversations(family_id=family_id, db_path=target_db) or []
            page_labels = {
                "section-overview": "Overview & Net Worth",
                "section-equity": "Company Equity & RSUs",
                "section-scenarios": "Forecasting & Longevity",
                "section-holdings": "Investments & IPS",
                "section-arbitrage": "Multi-State Tax Arbitrage",
                "section-withholding": "Taxes & Withholding",
                "section-philanthropy": "Philanthropy",
                "section-gifting": "Family Gifting",
                "section-college": "Education Funding",
                "section-transcripts": "IRS Transcripts",
                "section-compensation": "Career Compensation",
                "section-accounts": "Accounts & Assets",
                "section-estate": "Estate Planning",
            }
            search_q = clean_search.lower()
            for c in convs:
                p_sec = c.get("page_section") or c.get("page_context") or "section-overview"
                is_pinned = bool(c.get("is_pinned"))
                title = c.get("title") or "Untitled Conversation"
                last_msg = c.get("last_message") or ""

                if is_pinned_filter and not is_pinned:
                    continue
                if clean_page and p_sec != clean_page:
                    continue
                if search_q and search_q not in f"{title} {last_msg}".lower():
                    continue

                upd = c.get("updated_at") or ""
                upd_str = str(upd)[:16].replace("T", " ") if upd else "--"
                cid = c.get("conversation_id") or c.get("id") or ""
                advisor_conversations.append({
                    "id": cid,
                    "conversation_id": cid,
                    "title": title,
                    "last_message": last_msg,
                    "created_by": c.get("created_by") or c.get("user_name") or "Member",
                    "page_section": p_sec,
                    "page_label": page_labels.get(p_sec, p_sec or "General"),
                    "is_pinned": is_pinned,
                    "updated_at": upd_str,
                })
    except Exception as e:
        logger.warning(f"Failed to build SSR advisor conversations: {e}")

    invites_list = []
    invites_enabled = True
    can_invite_new_household = False
    is_site_admin = False
    ai_key_status = {
        "has_custom_key": False,
        "masked_key": "",
        "has_server_key": False,
        "is_local_mode": False,
    }
    try:
        import os
        from pathlib import Path
        from flask import has_request_context, session as flask_session
        from config import get_global_db_path, is_local_mode, is_site_admin_email

        local_mode = is_local_mode()
        invites_enabled = not local_mode
        active_email = ""
        is_demo = False
        active_role = "viewer"
        if has_request_context():
            active_email = str(flask_session.get("user_email") or flask_session.get("user") or "").strip().lower()
            is_demo = bool(flask_session.get("is_demo"))
            active_role = str(flask_session.get("role") or flask_session.get("user_role") or "viewer").strip().lower()
        can_invite_new_household = invites_enabled and is_site_admin_email(active_email, db_path=Path(DB_PATH))
        is_site_admin = bool(
            not is_demo
            and (
                can_invite_new_household
                or is_site_admin_email(active_email, db_path=get_global_db_path())
                or (int(family_id) == int("1") and active_role in ("admin", "editor"))
            )
        )
        if invites_enabled and DB_PATH.exists():
            invites_list = security.list_invite_tokens(Path(DB_PATH), family_id=family_id)

        custom_gemini_key = ""
        if DB_PATH.exists():
            ai_creds = security.db_load_encrypted(Path(DB_PATH), "ai_credentials", family_id=family_id)
            if isinstance(ai_creds, dict):
                custom_gemini_key = str(ai_creds.get("gemini_api_key") or "").strip()
        masked_key = f"••••{custom_gemini_key[-4:]}" if len(custom_gemini_key) >= 4 else ("••••" if custom_gemini_key else "")
        from config import get_household_ai_limits

        limits_meta = get_household_ai_limits(family_id=family_id, db_path=Path(DB_PATH) if DB_PATH.exists() else None)
        ai_key_status = {
            "has_custom_key": bool(custom_gemini_key),
            "masked_key": masked_key,
            "has_server_key": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "is_local_mode": local_mode,
            "tier": limits_meta.get("tier", "shared"),
            "rate_limit_label": limits_meta.get("rate_limit_label", "5/min · 30/hr"),
            "max_input_chars": limits_meta.get("max_input_chars", 2000),
            "shared_rate_limit_label": limits_meta.get("shared_rate_limit_label", "5/min · 30/hr"),
            "byo_rate_limit_label": limits_meta.get("byo_rate_limit_label", "30/min · 300/hr"),
            "shared_max_input_chars": limits_meta.get("shared_max_input_chars", 2000),
            "byo_max_input_chars": limits_meta.get("byo_max_input_chars", 8000),
        }
    except Exception:
        invites_list = []

    return {
        "active_tab": norm_tab,
        "adv_search": clean_search,
        "adv_page": clean_page,
        "adv_pinned_only": is_pinned_filter,
        "family_name": family_name,
        "support_access_enabled": support_access_enabled,
        "members": members,
        "invites": invites_list,
        "invites_enabled": invites_enabled,
        "can_invite_new_household": can_invite_new_household,
        "is_site_admin": is_site_admin,
        "assumptions": assumptions,
        "roles": roles_list,
        "available_roles": available_roles_list,
        "children": children_list,
        "monarch_status": monarch_status,
        "simplefin_status": simplefin_status,
        "ai_key_status": ai_key_status,
        "advisor_conversations": advisor_conversations,
    }
