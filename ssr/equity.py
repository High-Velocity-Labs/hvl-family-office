"""
SSR view-model builder for Company Equity, RSU Vesting, 409A FMV, and Liquidity Projections.
"""

from __future__ import annotations
from datetime import date, datetime
import logging

import equity_engine
from ssr.formatting import fmt_currency

logger = logging.getLogger(__name__)


def build_ssr_equity(
    snapshot: dict,
    family_id: int = 0,
    active_company_id: str | int | None = None,
    include_wa_tax: bool = False,
    multiple: float = 1.0,
    growth_rate: float = 0.105,
    projections: list | None = None,
) -> dict:
    """Prepares formatted strings and state for SSR Equity KPI cards, company tabs, valuation slider, graph stats, and grants table."""
    if not snapshot:
        return {}
    eq = snapshot.get("company_equity") or {}
    share_price = float(eq.get("share_price") or 0.0)

    companies = eq.get("companies") or []
    if not companies and family_id > 0:
        try:
            companies = equity_engine.load_equity_companies_summary(family_id=family_id)
        except Exception:
            companies = []

    is_consolidated = str(active_company_id).lower() == "all"
    resolved_cid: str | int = "all" if is_consolidated else (
        int(active_company_id)
        if active_company_id is not None and str(active_company_id).isdigit()
        else (eq.get("company_id") if eq.get("company_id") is not None else (companies[0]["company_id"] if companies else 1))
    )

    active_comp = None
    if not is_consolidated and companies:
        active_comp = next((c for c in companies if int(c.get("company_id", 0)) == int(resolved_cid)), companies[0])

    raw_comp_fmv = float((active_comp or (companies[0] if companies else {})).get("current_fmv") or 0.0)
    base_fmv = raw_comp_fmv or share_price
    if share_price <= 0 and raw_comp_fmv > 0:
        share_price = raw_comp_fmv

    if is_consolidated:
        net_val = float(eq.get("true_net_post_tax_value") or 0.0)
        gross_val = float(eq.get("nominal_gross_equity_value") or eq.get("total_gross_equity_value") or 0.0)
        strike_cost = float(eq.get("total_strike_cost_needed") or 0.0)
        tax_drag = float(eq.get("total_tax_drag") or 0.0)
        comp_name = "Consolidated Holdings"
        gross_label = "PORTFOLIO NOMINAL GROSS (VESTED)"
    else:
        net_val = float(
            eq.get("company_true_net_post_tax_value")
            if eq.get("company_true_net_post_tax_value") is not None
            else (eq.get("true_net_post_tax_value") or 0.0)
        )
        gross_val = float(
            eq.get("company_nominal_gross_equity_value")
            or eq.get("nominal_gross_equity_value")
            or eq.get("total_gross_equity_value")
            or 0.0
        )
        strike_cost = float(
            eq.get("company_strike_cost_needed")
            if eq.get("company_strike_cost_needed") is not None
            else (eq.get("total_strike_cost_needed") or 0.0)
        )
        tax_drag = float(
            eq.get("company_tax_drag")
            if eq.get("company_tax_drag") is not None
            else (eq.get("total_tax_drag") or 0.0)
        )
        comp_name = (active_comp and active_comp.get("company_name")) or eq.get("company_name") or "Company"
        gross_label = f"{comp_name.upper()} NOMINAL GROSS (VESTED)"

    all_grants = eq.get("grants") or []
    has_equity_data = bool(companies or all_grants or share_price > 0)

    perf_str = "--"
    perf_pct_str = "--"
    perf_mult_str = ""
    cagr_str = "--% CAGR"
    is_baseline_growth = abs(growth_rate - 0.105) < 0.001
    growth_str = (
        f"{'Baseline' if is_baseline_growth else 'Growth'}: +{growth_rate * 100:.1f}%/yr"
        if has_equity_data
        else "--"
    )
    bench_desc = ""
    benchmark_data = None
    history = eq.get("fmv_history") or []
    if not history and family_id > 0 and has_equity_data:
        try:
            history = equity_engine.get_historical_equity_fmv(
                share_price,
                family_id=family_id,
                company_id=None if is_consolidated else int(resolved_cid),
            )
        except Exception:
            history = []

    if history and history[0].get("price") and float(history[0]["price"]) > 0:
        first_price = float(history[0]["price"])
        total_pct = (share_price / first_price - 1.0) * 100.0
        mult_perf = share_price / first_price
        perf_pct_str = f"+{total_pct:,.1f}%"
        perf_mult_str = f"({mult_perf:.1f}x)"
        perf_str = f"{perf_pct_str} {perf_mult_str}"

        years_elapsed = 12.5
        first_date_str = history[0].get("date")
        if first_date_str:
            try:
                d1 = datetime.strptime(first_date_str, "%Y-%m-%d").date()
                d2 = date.today()
                years_elapsed = max(0.5, (d2 - d1).days / 365.25)
            except Exception:
                years_elapsed = 12.5

        cagr = (pow(share_price / first_price, 1.0 / years_elapsed) - 1.0) * 100.0
        cagr_str = f"+{cagr:.1f}% CAGR ({years_elapsed:.1f} yrs)"

        sp_cagr = 11.8
        vtsax_cagr = 11.5
        sp_total = (pow(1.0 + sp_cagr / 100.0, years_elapsed) - 1.0) * 100.0
        sp_mult = pow(1.0 + sp_cagr / 100.0, years_elapsed)
        vtsax_total = (pow(1.0 + vtsax_cagr / 100.0, years_elapsed) - 1.0) * 100.0
        vtsax_mult = pow(1.0 + vtsax_cagr / 100.0, years_elapsed)
        alpha = cagr - sp_cagr

        alpha_color = "var(--status-green)" if alpha >= 0 else "var(--status-red)"
        alpha_sign = "+" if alpha >= 0 else ""
        bench_desc = (
            f'<div><strong>Total Return:</strong> vs. VTSAX +{vtsax_total:,.1f}% ({vtsax_mult:.1f}x) • '
            f'S&amp;P 500 +{sp_total:,.1f}% ({sp_mult:.1f}x)</div>'
            f'<div style="margin-top: 2px;"><strong>Annualized Alpha:</strong> '
            f'<span style="color: {alpha_color}; font-weight: 600;">{alpha_sign}{alpha:.1f}%/yr</span> '
            f'excess return over S&amp;P 500</div>'
        )
        benchmark_data = {
            "vtsax_total": f"{vtsax_total:,.1f}%",
            "vtsax_mult": f"{vtsax_mult:.1f}",
            "sp_total": f"{sp_total:,.1f}%",
            "sp_mult": f"{sp_mult:.1f}",
            "cagr": f"{cagr:.1f}",
            "vtsax_cagr": f"{vtsax_cagr:.1f}",
            "alpha": f"{alpha:.1f}",
            "alpha_sign": alpha_sign,
            "alpha_color": alpha_color,
        }

    active_company_info = False
    active_company_type = "PRIVATE"
    active_company_fmv_str = f"${share_price:,.2f}" if share_price > 0 else "--"
    active_company_date_str = ""
    if is_consolidated and companies:
        active_company_info = True
    elif active_comp:
        active_company_info = True
        active_company_type = (active_comp.get("ticker_or_private") or "PRIVATE").upper()
        c_fmv = float(active_comp.get("current_fmv", share_price) or share_price or 0.0)
        active_company_fmv_str = f"${c_fmv:,.2f}"
        if active_comp.get("fmv_date"):
            active_company_date_str = f" • As of {active_comp['fmv_date']}"

    if is_consolidated:
        slider_readout_label = "PORTFOLIO VALUATION MULTIPLE:"
        display_price_str = f"{multiple:.2f}x"
        ratio_str = f"{multiple:.2f}x Baseline FMVs"
        slider_min = 0.5
        slider_max = 5.0
        slider_step = 0.05
        slider_val = multiple
        presets = [
            {"mult": 0.5, "price": "", "label": "0.5x Bear", "active": abs(multiple - 0.5) < 0.01},
            {"mult": 1.0, "price": "", "label": "1.0x Baseline FMVs", "active": abs(multiple - 1.0) < 0.01},
            {"mult": 1.5, "price": "", "label": "1.5x", "active": abs(multiple - 1.5) < 0.01},
            {"mult": 2.0, "price": "", "label": "2.0x Bull", "active": abs(multiple - 2.0) < 0.01},
            {"mult": 3.0, "price": "", "label": "3.0x", "active": abs(multiple - 3.0) < 0.01},
            {"mult": 5.0, "price": "", "label": "5.0x Strategic / IPO", "active": abs(multiple - 5.0) < 0.01},
        ]
        slider_labels = {
            "bear": "0.5x (Bear)",
            "current": "1.0x (Baseline FMVs)",
            "x2": "2.0x (Bullish)",
            "x3": "3.0x (High Growth)",
            "bull": "5.0x (Strategic / IPO)",
        }
    else:
        slider_base = base_fmv if base_fmv > 0 else 100.0
        cur_ratio = (share_price / base_fmv) if base_fmv > 0 else 1.0
        slider_readout_label = "CURRENT 409A SHARE PRICE:" if abs(cur_ratio - 1.0) < 0.01 else "SIMULATED 409A SHARE PRICE:"
        display_price_str = f"${share_price:,.2f}" if share_price > 0 else "--"
        ratio_str = f"{cur_ratio:.2f}x Baseline FMV" if share_price > 0 else "--"
        slider_min = max(1, round(slider_base * 0.5))
        slider_max = max(slider_min + 10, round(slider_base * 5.0))
        slider_step = max(0.5, round((slider_max - slider_min) / 200 * 10) / 10)
        slider_val = share_price if share_price > 0 else slider_base
        presets = [
            {"mult": 0.5, "price": f"{slider_base * 0.5:.2f}", "label": f"0.5x ({fmt_currency(slider_base * 0.5, 0)})", "active": abs(cur_ratio - 0.5) < 0.05},
            {"mult": 1.0, "price": f"{slider_base:.2f}", "label": f"Current FMV: {fmt_currency(slider_base, 2)}" if base_fmv > 0 else "Current FMV", "active": abs(cur_ratio - 1.0) < 0.05},
            {"mult": 1.5, "price": f"{slider_base * 1.5:.2f}", "label": f"1.5x ({fmt_currency(slider_base * 1.5, 0)})", "active": abs(cur_ratio - 1.5) < 0.05},
            {"mult": 2.0, "price": f"{slider_base * 2.0:.2f}", "label": f"2.0x ({fmt_currency(slider_base * 2.0, 0)})", "active": abs(cur_ratio - 2.0) < 0.05},
            {"mult": 3.0, "price": f"{slider_base * 3.0:.2f}", "label": f"3.0x ({fmt_currency(slider_base * 3.0, 0)})", "active": abs(cur_ratio - 3.0) < 0.05},
            {"mult": 5.0, "price": f"{slider_base * 5.0:.2f}", "label": f"5.0x Strategic ({fmt_currency(slider_base * 5.0, 0)})", "active": abs(cur_ratio - 5.0) < 0.05},
        ]
        slider_labels = {
            "bear": f"{fmt_currency(slider_base * 0.5, 0)} (Bear)",
            "current": f"{fmt_currency(slider_base, 2)} (409A FMV)" if base_fmv > 0 else "1.0x (409A FMV)",
            "x2": f"{fmt_currency(slider_base * 2.0, 0)} (2.0x)",
            "x3": f"{fmt_currency(slider_base * 3.0, 0)} (3.0x)",
            "bull": f"{fmt_currency(slider_base * 5.0, 0)} (Strategic / IPO)",
        }

    filtered_grants = (
        all_grants
        if is_consolidated
        else [g for g in all_grants if int(g.get("company_id") or resolved_cid or 1) == int(resolved_cid)]
    )

    grant_rows = []
    total_unvested = 0
    total_vested_options = 0
    total_owned_shares = 0
    option_grants_count = 0
    for g in filtered_grants:
        row_gtype = str(g.get("grant_type") or "").lower()
        is_rsu = row_gtype == "rsu"
        is_iso = row_gtype == "iso"
        type_badge = "RSU" if is_rsu else ("ISO" if is_iso else "NSO")
        badge_class = "badge-blue" if is_rsu else ("badge-green" if is_iso else "badge-blue")
        strike_p = float(g.get("strike_price") or 0.0)
        tot_granted = int(g.get("total_granted") or 0)
        unexercised = int(g.get("unexercised_options") or g.get("unexercised_vested") or 0)
        unvested = int(g.get("unvested_options") or g.get("unvested") or 0)
        owned = int(g.get("owned_shares") or g.get("owned_exercised") or 0)
        strike_cost_val = float(g.get("strike_cost") or 0.0)
        spread_val = float(g.get("spread") or 0.0)
        true_net_val = float(g.get("true_net_value") or 0.0)

        total_unvested += unvested
        total_vested_options += unexercised
        total_owned_shares += owned
        if not is_rsu and unexercised > 0:
            option_grants_count += 1

        grant_rows.append({
            "grant_id": g.get("grant_id"),
            "nickname": g.get("nickname") or "Grant",
            "company_name": g.get("company_name"),
            "type_badge": type_badge,
            "badge_class": badge_class,
            "grant_date": g.get("grant_date") or "--",
            "total_granted": f"{tot_granted:,}",
            "strike_str": "$0.00" if is_rsu else f"${strike_p:,.2f}",
            "unexercised": f"{unexercised:,}",
            "unvested": f"{unvested:,}",
            "vesting_completion": g.get("vesting_completion") or "Fully Vested",
            "strike_cost_str": "$0" if is_rsu else fmt_currency(strike_cost_val, 0),
            "spread_str": fmt_currency(spread_val, 0),
            "owned_str": f"{owned:,}" if owned > 0 else "--",
            "true_net_str": fmt_currency(true_net_val, 0),
        })

    if total_unvested > 0:
        unvested_badge_text = f"{total_unvested:,} Unvested Units Excluded"
        unvested_badge_class = "badge badge-orange"
    elif filtered_grants:
        unvested_badge_text = "All Grants 100% Vested"
        unvested_badge_class = "badge badge-blue"
    else:
        unvested_badge_text = "Unvested Options Excluded"
        unvested_badge_class = "badge badge-orange"

    if (total_vested_options + total_owned_shares) > 0:
        vested_shares_breakdown = f"{total_vested_options:,} Vested Options • {total_owned_shares:,} Owned Shares"
    else:
        vested_shares_breakdown = "Options + owned shares"

    if option_grants_count > 0:
        strike_grants_summary = f"Across {option_grants_count} Vested Option Grant{'s' if option_grants_count != 1 else ''}"
    else:
        strike_grants_summary = "Active Grant Strike Totals"

    if projections is None and family_id > 0:
        try:
            projections = equity_engine.simulate_multi_year_projections(
                annual_growth_rate=growth_rate,
                years=5,
                include_wa_tax_from_year=2028 if include_wa_tax else 9999,
                non_equity_net_worth=snapshot.get("non_equity_net_worth", 0.0),
                base_share_price=share_price,
                family_id=family_id,
            )
        except Exception:
            projections = []

    first_fmv = history[0] if history else None
    first_fmv_note = (first_fmv.get("notes") or "Initial recorded grant") if first_fmv else "Historical baseline"
    proj_5yr = share_price * ((1.0 + growth_rate) ** 5)
    gain_5yr_pct = (((1.0 + growth_rate) ** 5) - 1.0) * 100.0
    graph_stats = {
        "stat1_label": f"INITIAL 409A ({first_fmv.get('date') or ''}):" if first_fmv else "EARLIEST 409A RECORD:",
        "stat1_val": fmt_currency(float(first_fmv["price"]), 2) if (first_fmv and first_fmv.get("price")) else "--",
        "stat1_sub": first_fmv_note,
        "stat2_label": "SIMULATED MULTIPLE:" if is_consolidated else "CURRENT 409A FMV:",
        "stat2_val": f"{multiple:.2f}x" if is_consolidated else (fmt_currency(share_price, 2) if share_price > 0 else "--"),
        "stat2_sub": "Applied across holdings" if is_consolidated else "Verified 409A baseline",
        "stat4_val": f"+{growth_rate * 100:.1f}% / yr" if has_equity_data else "--",
        "stat4_sub": ("Forecasting Baseline" if is_baseline_growth else "Selected Scenario Rate") if has_equity_data else "No 409A data recorded",
        "stat5_val": fmt_currency(proj_5yr, 2) if share_price > 0 else "--",
        "stat5_sub": f"+{gain_5yr_pct:.1f}% gain @ +{growth_rate * 100:.1f}%/yr" if share_price > 0 else "--",
    }

    return {
        "active_company_id": resolved_cid,
        "is_consolidated": is_consolidated,
        "include_wa_tax": include_wa_tax,
        "multiple": multiple,
        "growth_rate": str(growth_rate),
        "base_fmv": base_fmv,
        "slider_readout_label": slider_readout_label,
        "net_value": fmt_currency(net_val, 0),
        "gross_value": fmt_currency(gross_val, 0),
        "gross_label": gross_label,
        "strike_cost": fmt_currency(strike_cost, 0),
        "tax_drag": fmt_currency(tax_drag, 0),
        "unvested_badge_text": unvested_badge_text,
        "unvested_badge_class": unvested_badge_class,
        "vested_shares_breakdown": vested_shares_breakdown,
        "strike_grants_summary": strike_grants_summary,
        "first_fmv_note": first_fmv_note,
        "share_price": display_price_str,
        "share_price_num": share_price,
        "ratio_str": ratio_str,
        "slider_min": slider_min,
        "slider_max": slider_max,
        "slider_step": slider_step,
        "slider_val": slider_val,
        "slider_labels": slider_labels,
        "presets": presets,
        "company_name": comp_name,
        "performance": perf_str,
        "perf_pct": perf_pct_str,
        "perf_mult": perf_mult_str,
        "cagr_badge": cagr_str,
        "growth_badge": growth_str,
        "benchmark_desc": bench_desc,
        "benchmark_data": benchmark_data,
        "companies": companies,
        "grants": all_grants,
        "grant_rows": grant_rows,
        "fmv_history": history,
        "projections": projections or [],
        "graph_stats": graph_stats,
        "active_company_info": active_company_info,
        "active_company_type": active_company_type,
        "active_company_fmv_str": active_company_fmv_str,
        "active_company_date_str": active_company_date_str,
        "equity_raw": {
            "company_id": None if is_consolidated else resolved_cid,
            "company_name": comp_name,
            "share_price": share_price,
            "base_fmv": base_fmv,
            "include_wa_millionaire_tax": include_wa_tax,
            "true_net_post_tax_value": net_val,
            "company_true_net_post_tax_value": net_val,
            "nominal_gross_equity_value": gross_val,
            "company_nominal_gross_equity_value": gross_val,
            "total_gross_equity_value": gross_val,
            "total_strike_cost_needed": strike_cost,
            "company_strike_cost_needed": strike_cost,
            "total_tax_drag": tax_drag,
            "company_tax_drag": tax_drag,
        },
    }
