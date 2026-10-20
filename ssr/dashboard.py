"""
SSR context assembly, fragment context builders, and dashboard balance sheet / net worth helpers.
Extracted from `routes/dashboard.py` to keep HTTP route handlers thin.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Mapping

import db
import equity_engine
import monarch_service
from routes.helpers import DB_PATH, get_current_db_path
from routes.ssr_builders import (
    build_ssr_accounts, build_ssr_arbitrage, build_ssr_college, build_ssr_compensation,
    build_ssr_equity, build_ssr_estate, build_ssr_gifting, build_ssr_holdings,
    build_ssr_overview, build_ssr_philanthropy, build_ssr_scenarios, build_ssr_settings,
    get_private_investments_data,
)
import security
from ssr.holdings import (
    _INLINE_MD_RE, INVESTMENT_POLICY_PRESETS, VALID_POLICY_PRESETS,
    _tokenize_inline_markdown, load_investment_policy_payload,
    parse_changelog_releases, save_investment_policy_payload,
)

logger = logging.getLogger(__name__)

SECTION_METADATA: dict[str, dict[str, Any]] = {
    "section-overview": {"title": "Overview & Net Worth", "slugs": ["", "overview"], "depends": ("balance_sheet", "accounts", "equity", "scenarios", "household.identity", "household.members", "onboarding.checklist")},
    "section-scenarios": {"title": "Forecasting", "slugs": ["forecasting", "scenarios"], "depends": ("balance_sheet", "accounts", "holdings", "equity", "tax_profile", "compensation", "household.members", "household.identity", "college", "philanthropy", "gifting", "estate")},
    "section-equity": {"title": "Company Equity", "slugs": ["company-equity", "equity"], "depends": ("equity", "balance_sheet", "tax_profile")},
    "section-holdings": {"title": "Investments", "slugs": ["holdings", "investments"], "depends": ("holdings", "holdings.policy", "accounts", "balance_sheet")},
    "section-arbitrage": {"title": "Multi-State Arbitrage", "slugs": ["arbitrage"], "depends": ("tax_profile", "compensation", "equity", "household.identity")},
    "section-compensation": {"title": "Compensation & Taxes", "slugs": ["compensation", "withholding", "transcripts"], "depends": ("compensation", "tax_profile", "household.members")},
    "section-philanthropy": {"title": "Philanthropy", "slugs": ["philanthropy"], "depends": ("philanthropy", "tax_profile")},
    "section-gifting": {"title": "Family Gifting", "slugs": ["gifting"], "depends": ("gifting", "household.members")},
    "section-estate": {"title": "Estate & Trusts", "slugs": ["estate"], "depends": ("estate", "balance_sheet", "gifting", "household.members", "household.identity")},
    "section-college": {"title": "Education", "slugs": ["college", "education"], "depends": ("college", "accounts", "household.members")},
    "section-accounts": {"title": "Accounts & Holdings", "slugs": ["accounts"], "depends": ("accounts", "holdings", "balance_sheet")},
    "section-settings": {"title": "Family Office Settings", "slugs": ["settings"], "depends": ("settings.invites", "household.identity")},
}

FRAGMENT_ETAG_DOMAINS: dict[str, tuple[str, ...]] = {
    slug: meta["depends"]
    for sec_id, meta in SECTION_METADATA.items()
    if "depends" in meta and sec_id not in ("section-scenarios", "section-settings")
    for slug in meta.get("slugs", [])
    if slug
}

SLUG_TO_SECTION: dict[str, str] = {
    slug: sec_id for sec_id, meta in SECTION_METADATA.items() for slug in meta["slugs"]
}

VALID_FRAGMENTS: dict[str, str] = {
    "scenarios": "components/scenarios.html", "estate": "components/estate.html",
    "philanthropy": "components/philanthropy.html", "gifting": "components/gifting.html",
    "compensation": "components/compensation.html", "college": "components/college.html",
    "arbitrage": "components/arbitrage.html", "holdings": "components/holdings_breakdown.html",
    "equity": "components/equity.html", "accounts": "components/accounts.html",
    "settings": "components/settings.html", "overview": "components/overview.html",
}


def _format_sync_timestamp(raw_sync: Any) -> tuple[str, str]:
    """Formats a raw sync timestamp into (display_str, iso_str)."""
    if not raw_sync or str(raw_sync) == "Never":
        return "Loaded from encrypted vault", ""
    raw_sync_str = str(raw_sync)
    try:
        dt = datetime.fromisoformat(raw_sync_str.replace("Z", "+00:00")).astimezone()
        return f"Last Synced: {dt.strftime('%b')} {dt.day}, {dt.year}, {dt.strftime('%I:%M %p')}", raw_sync_str
    except Exception:
        return f"Last Synced: {raw_sync_str}", raw_sync_str


def build_index_ssr_context(family_id: int, path_slug: str, query_tab: str) -> dict[str, Any]:
    """Assembles the complete SSR context dictionary for `index.html`."""
    from ssr.accounts import _resolve_provider_flags

    family_name, primary_company_name, accounts_title = "Family Office", "Company", "Accounts & Holdings"
    monarch_acc_count = simplefin_acc_count = 0

    target_db = get_current_db_path(family_id=family_id) if family_id > 0 else DB_PATH

    if target_db.exists():
        try:
            fam = security.get_family(target_db, family_id=family_id)
            if fam and fam.get("name"):
                raw_name = str(fam["name"])
                if raw_name.startswith("gAAAAA"):
                    dec_name = security.decrypt_field(raw_name, default="Family Office")
                    family_name = dec_name if dec_name and not dec_name.startswith("gAAAAA") else "Family Office"
                else:
                    family_name = raw_name
        except Exception:
            pass

    if family_id > 0:
        try:
            primary_company_name = equity_engine.get_primary_company_name(family_id=family_id) or "Company"
            accs = db.accounts.list_accounts(family_id=family_id, db_path=target_db) or []
            if accs:
                accounts_title = f"Accounts & Holdings ({len(accs)} Accounts)"
                for a in accs:
                    aid_str = str(a.get("id") or "")
                    raw_prov = str(a.get("provider") or "").lower()
                    if aid_str.startswith("sfin_") or raw_prov == "simplefin":
                        simplefin_acc_count += 1
                    elif aid_str.startswith("monarch_") or raw_prov == "monarch":
                        monarch_acc_count += 1
        except Exception:
            pass

    provider_flags = _resolve_provider_flags(
        family_id=family_id, monarch_count=monarch_acc_count, simplefin_count=simplefin_acc_count
    )

    demo_personas = []
    try:
        from routes.auth import DEMO_PERSONAS
        demo_personas = DEMO_PERSONAS
    except Exception:
        pass

    target_slug = query_tab if (query_tab and query_tab in SLUG_TO_SECTION) else path_slug
    active_section = SLUG_TO_SECTION.get(target_slug, "section-overview")
    active_section_title = SECTION_METADATA.get(active_section, {}).get("title", "Overview & Net Worth")
    if active_section == "section-accounts":
        active_section_title = accounts_title
    elif active_section == "section-equity":
        active_section_title = "Company Equity"

    ctx: dict[str, Any] = {
        "family_name": family_name, "primary_company_name": primary_company_name, "accounts_title": accounts_title,
        "demo_personas": demo_personas, "snapshot": {}, "private_investments": {}, "ssr_kpis": {},
        "ssr_scenarios": {}, "initial_scenarios": {}, "ssr_equity": {}, "ssr_holdings": {},
        "ssr_philanthropy": {}, "ssr_estate": {}, "ssr_compensation": {}, "ssr_college": {},
        "ssr_arbitrage": {}, "ssr_gifting": {}, "ssr_accounts": {}, "ssr_settings": {},
        "active_section": active_section, "active_section_title": active_section_title,
        "sync_timestamp_str": "Loaded from encrypted vault", "sync_timestamp_iso": "",
        "section_depends_map": {sec_id: list(meta["depends"]) for sec_id, meta in SECTION_METADATA.items() if "depends" in meta},
        **provider_flags,
    }

    if family_id > 0:
        try:
            ctx["ssr_settings"] = build_ssr_settings(family_id=family_id)

            if active_section in ("section-overview", "section-settings", "section-equity", "section-holdings", "section-accounts"):
                current_share_price = equity_engine.get_current_409a_price(family_id=family_id)
                snapshot = monarch_service.get_financial_snapshot(
                    share_price=current_share_price, include_wa_tax=False, family_id=family_id
                )
                private_inv = get_private_investments_data(family_id=family_id)
                ctx["snapshot"], ctx["private_investments"] = snapshot, private_inv
                if active_section in ("section-overview", "section-settings"):
                    ctx["ssr_kpis"] = build_ssr_overview(snapshot, private_inv, family_id=family_id)
                elif active_section == "section-equity":
                    ctx["ssr_equity"] = build_ssr_equity(snapshot, family_id=family_id)
                elif active_section == "section-holdings":
                    ctx["ssr_holdings"] = build_ssr_holdings(snapshot, family_id=family_id)
                elif active_section == "section-accounts":
                    ctx["ssr_accounts"] = build_ssr_accounts(snapshot, family_id=family_id)
            elif active_section == "section-scenarios":
                ctx["ssr_scenarios"], ctx["initial_scenarios"] = build_ssr_scenarios(family_id=family_id)
            elif active_section == "section-estate":
                ctx["ssr_estate"] = build_ssr_estate(family_id=family_id)
            elif active_section == "section-compensation":
                ctx["ssr_compensation"] = build_ssr_compensation(family_id=family_id)
            elif active_section == "section-college":
                ctx["ssr_college"] = build_ssr_college(family_id=family_id)
            elif active_section == "section-arbitrage":
                ctx["ssr_arbitrage"] = build_ssr_arbitrage(family_id=family_id)
            elif active_section == "section-gifting":
                ctx["ssr_gifting"] = build_ssr_gifting(family_id=family_id)
            elif active_section == "section-philanthropy":
                ctx["ssr_philanthropy"] = build_ssr_philanthropy(family_id=family_id)


            raw_sync = ctx["snapshot"].get("last_monarch_sync") if ctx["snapshot"] else None
            if not raw_sync:
                sync_meta = security.db_load_encrypted(target_db, "last_sync_metadata", family_id=family_id)
                if isinstance(sync_meta, dict):
                    raw_sync = sync_meta.get("timestamp")
            ctx["sync_timestamp_str"], ctx["sync_timestamp_iso"] = _format_sync_timestamp(raw_sync)
        except Exception as e:
            logger.warning(f"Failed to generate initial SSR snapshot for {active_section}: {e}")

    return ctx


build_dashboard_ssr_context = build_index_ssr_context


def build_fragment_ssr_context(
    fragment_name: str, family_id: int, query_args: Mapping[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    """Resolves template name and SSR context dictionary for `/fragments/<fragment_name>`."""
    tpl = VALID_FRAGMENTS.get(fragment_name)
    if not tpl:
        return None, {}

    ctx: dict[str, Any] = {"active_section": f"section-{fragment_name}"}
    if family_id <= 0:
        return tpl, ctx

    try:
        if fragment_name in ("scenarios", "forecasting"):
            scen_id_arg = query_args.get("scenario_id") or query_args.get("target_scenario_id")
            custom_scen_params = {
                k: v for k, v in query_args.items() if k not in ("scenario_id", "target_scenario_id") and v not in (None, "")
            }
            ctx["ssr_scenarios"], ctx["initial_scenarios"] = build_ssr_scenarios(
                family_id, scenario_id=scen_id_arg, custom_params=custom_scen_params
            )
        elif fragment_name in ("college", "education"):
            k12_raw = query_args.get("enable_529_k12")
            k12_arg = (str(k12_raw).lower() != "false") if k12_raw is not None else True
            ctx["ssr_college"] = build_ssr_college(family_id, horizon=query_args.get("horizon"), enable_529_k12=k12_arg)
        elif fragment_name == "compensation":
            ytd_raw, pay_raw = query_args.get("ytd_withheld"), query_args.get("remaining_paychecks")
            ctx["ssr_compensation"] = build_ssr_compensation(
                family_id, taxpayer_filter=query_args.get("taxpayer"), subtab=query_args.get("subtab"),
                ytd_withheld_override=float(ytd_raw) if (ytd_raw is not None and str(ytd_raw).strip() != "") else None,
                remaining_paychecks_override=int(pay_raw) if (pay_raw is not None and str(pay_raw).strip().isdigit()) else None,
            )
        elif fragment_name == "estate":
            sunset_raw, char_raw = query_args.get("apply_tcja_sunset"), query_args.get("charitable_pct")
            ctx["ssr_estate"] = build_ssr_estate(
                family_id, state_override=query_args.get("state"),
                apply_tcja_sunset=(str(sunset_raw).lower() == "true") if sunset_raw is not None else None,
                charitable_pct_override=float(char_raw) if char_raw is not None else None,
            )
        elif fragment_name in ("equity", "company-equity"):
            cid_raw = query_args.get("company_id")
            is_consolidated = str(cid_raw).lower() == "all"
            target_cid = int(cid_raw) if cid_raw and str(cid_raw).isdigit() else None
            include_wa = (str(query_args.get("include_wa_tax")).lower() == "true") if query_args.get("include_wa_tax") is not None else False
            mult_val = float(query_args["multiple"]) if query_args.get("multiple") else 1.0
            growth_val = float(query_args["growth_rate"]) if query_args.get("growth_rate") is not None else 0.105
            default_price = equity_engine.get_company_409a_price(family_id=family_id, company_id=target_cid)
            price_raw = query_args.get("share_price")
            share_price = float(price_raw) if price_raw else (round(default_price * mult_val, 2) if is_consolidated else default_price)
            snap = monarch_service.get_financial_snapshot(share_price=share_price, include_wa_tax=include_wa, family_id=family_id, company_id=target_cid)
            ctx["ssr_equity"] = build_ssr_equity(snap, family_id=family_id, active_company_id="all" if is_consolidated else target_cid, include_wa_tax=include_wa, multiple=mult_val, growth_rate=growth_val)
            ctx["primary_company_name"] = equity_engine.get_primary_company_name(family_id=family_id) or "Company"
        elif fragment_name in ("holdings", "investments"):
            snap = monarch_service.get_financial_snapshot(share_price=equity_engine.get_current_409a_price(family_id=family_id), include_wa_tax=False, family_id=family_id)
            drift_raw = query_args.get("drift")
            ctx["ssr_holdings"] = build_ssr_holdings(snap, family_id=family_id, preset=query_args.get("preset"), horizon=query_args.get("horizon"), drift_tolerance=float(drift_raw) if drift_raw else None)
        elif fragment_name == "arbitrage":
            hv_raw, sp_raw = query_args.get("home_value"), query_args.get("annual_spend")
            ctx["ssr_arbitrage"] = build_ssr_arbitrage(
                family_id, home_state=query_args.get("home_state"),
                home_value=float(hv_raw) if (hv_raw is not None and str(hv_raw).strip() != "") else None,
                annual_spend=float(sp_raw) if (sp_raw is not None and str(sp_raw).strip() != "") else None,
                mode=query_args.get("mode"), scenario=query_args.get("scenario"),
            )
        elif fragment_name == "gifting":
            ctx["ssr_gifting"] = build_ssr_gifting(family_id, active_year=query_args.get("year"))
        elif fragment_name == "philanthropy":
            ctx["ssr_philanthropy"] = build_ssr_philanthropy(
                family_id=family_id, active_year=query_args.get("year"), sort_key=query_args.get("sort"), sort_dir=query_args.get("dir")
            )
        elif fragment_name == "overview":
            snap = monarch_service.get_financial_snapshot(share_price=equity_engine.get_current_409a_price(family_id=family_id), include_wa_tax=False, family_id=family_id)
            priv = get_private_investments_data(family_id=family_id)
            ctx["ssr_kpis"], ctx["snapshot"], ctx["private_investments"] = build_ssr_overview(snap, priv, family_id=family_id), snap, priv
        elif fragment_name == "accounts":
            snap = monarch_service.get_financial_snapshot(share_price=equity_engine.get_current_409a_price(family_id=family_id), include_wa_tax=False, family_id=family_id)
            ssr_acc = build_ssr_accounts(snap, family_id=family_id)
            ctx["ssr_accounts"], ctx["snapshot"] = ssr_acc, snap
            target_db = get_current_db_path(family_id=family_id) if family_id > 0 else DB_PATH
            accs = db.accounts.list_accounts(family_id=family_id, db_path=target_db) or []
            ctx.update({"accounts_title": f"Accounts & Holdings ({len(accs)} Accounts)" if accs else "Accounts & Holdings", "has_monarch": ssr_acc.get("has_monarch", False), "has_simplefin": ssr_acc.get("has_simplefin", False), "has_any_sync_provider": ssr_acc.get("has_any_sync_provider", False)})
        elif fragment_name == "settings":
            ctx["ssr_settings"] = build_ssr_settings(
                family_id, active_tab=query_args.get("tab"),
                adv_search=query_args.get("adv_search") or query_args.get("search"),
                adv_page=query_args.get("adv_page") or query_args.get("page_section"),
                adv_pinned_only=query_args.get("adv_pinned_only") or query_args.get("pinned_only"),
            )
    except Exception as e:
        logger.warning(f"Error preparing SSR context for fragment {fragment_name}: {e}")

    return tpl, ctx


def build_dashboard_api_payload(family_id: int) -> dict[str, Any]:
    """Assembles the aggregated Family Office balance sheet and baseline valuation payload."""
    current_share_price = equity_engine.get_current_409a_price(family_id=family_id)
    snapshot = monarch_service.get_financial_snapshot(share_price=current_share_price, include_wa_tax=False, family_id=family_id)

    transcripts_meta = db.transcripts.get_transcripts_payload(family_id=family_id, db_path=DB_PATH) or {}
    historical_summary = transcripts_meta.get("historical_summary", {})
    safe_harbor_2026 = transcripts_meta.get("safe_harbor_2026_target")
    if safe_harbor_2026 is None:
        prior_fed = float(historical_summary.get("2025", {}).get("federal_tax_withheld", 0.0) or 0.0)
        safe_harbor_2026 = round(prior_fed * 1.10, 2) if prior_fed > 0 else 0.0

    projections = equity_engine.simulate_multi_year_projections(
        annual_growth_rate=0.08, years=5, include_wa_tax_from_year=2028,
        non_equity_net_worth=snapshot.get("non_equity_net_worth", 0.0),
        base_share_price=current_share_price, family_id=family_id,
    )

    return {
        "success": True, "snapshot": snapshot, "historical_transcripts_summary": historical_summary,
        "safe_harbor_2026_target": safe_harbor_2026, "multi_year_projections": projections,
        "spending_summary": monarch_service.get_monarch_spending_history(family_id=family_id),
        "private_investments": get_private_investments_data(family_id=family_id),
    }


def build_networth_history_payload(family_id: int, granularity: str = "auto") -> dict[str, Any]:
    """Returns historical True Net Worth curves (annual, quarterly, monthly), recommended granularity, and annual savings."""
    snapshot = monarch_service.get_financial_snapshot(family_id=family_id)
    current_true_nw = float(snapshot.get("true_net_worth", 0.0))
    equity_data = snapshot.get("company_equity") or snapshot.get("equity_company") or {}
    current_equity_net = float(equity_data.get("true_net_post_tax_value", 0.0))
    cat = snapshot.get("categories", {})
    current_cash = float(cat.get("cash_liquid", {}).get("total", 0.0))
    current_pub = float(cat.get("public_brokerage", {}).get("total", 0.0))
    current_ret = float(cat.get("retirement", {}).get("total", 0.0))
    current_re = float(cat.get("real_estate", {}).get("total", 0.0)) - abs(float(cat.get("mortgages", {}).get("total", 0.0)))

    db_history = security.db_load_encrypted(DB_PATH, "historical_net_worth", family_id=family_id)
    rebuilt_history = None
    monthly_nw: list[dict[str, Any]] = []
    quarterly_nw: list[dict[str, Any]] = []
    if family_id > 0:
        get_hist_fn = getattr(db.accounts, "get_account_balance_history", None)
        try:
            has_snapshots = bool(callable(get_hist_fn) and get_hist_fn(family_id=family_id, db_path=DB_PATH))
        except Exception:
            has_snapshots = False
        if has_snapshots or not db_history:
            rebuild_fn = getattr(db.accounts, "rebuild_historical_net_worth_from_snapshots", None)
            if callable(rebuild_fn):
                try:
                    rebuilt_history = rebuild_fn(family_id=family_id, db_path=DB_PATH, persist=False)
                except TypeError:
                    rebuilt_history = rebuild_fn(family_id=family_id, db_path=DB_PATH)
                except Exception as exc:
                    logger.debug("Could not rebuild historical_net_worth from snapshots: %s", exc)
        series_fn = getattr(db.accounts, "build_dated_net_worth_series", None)
        if callable(series_fn):
            try:
                monthly_nw = series_fn(family_id=family_id, granularity="monthly", db_path=DB_PATH)
                quarterly_nw = series_fn(family_id=family_id, granularity="quarterly", db_path=DB_PATH)
            except Exception as exc:
                logger.debug("Could not build dated net worth series: %s", exc)

    source_history = rebuilt_history if rebuilt_history else db_history
    if source_history:
        historical_nw = [dict(row) for row in source_history if isinstance(row, dict)]
        if historical_nw and historical_nw[-1].get("year") == 2026 and current_true_nw != 0:
            historical_nw[-1].update({
                "true_net_worth": round(current_true_nw), "equity_net": round(current_equity_net),
                "company_net": round(current_equity_net), "liquid_investments": round(current_cash + current_pub + current_ret),
                "real_estate": round(current_re),
            })
    elif family_id > 0 and current_true_nw != 0:
        historical_nw = [{
            "year": 2026, "true_net_worth": round(current_true_nw), "equity_net": round(current_equity_net),
            "company_net": round(current_equity_net), "liquid_investments": round(current_cash + current_pub + current_ret),
            "real_estate": round(current_re),
        }]
    else:
        historical_nw = []

    recommended_gran = "monthly" if (len(historical_nw) < 2 and len(monthly_nw) >= 2) else "annual"
    norm_gran = str(granularity or "auto").strip().lower()
    active_gran = recommended_gran if norm_gran not in ("annual", "quarterly", "monthly") else norm_gran

    return {
        "success": True, "historical_net_worth": historical_nw, "monthly_net_worth": monthly_nw,
        "quarterly_net_worth": quarterly_nw, "recommended_granularity": recommended_gran,
        "active_granularity": active_gran,
        "annual_savings_history": security.db_load_encrypted(DB_PATH, "annual_savings_history", family_id=family_id) or [],
    }

