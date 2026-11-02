"""
SSR Builders for the Forecasting Event Shelf, Timeline Pin Lanes, Scrubber Inspector,
and Year-by-Year Spend-Down Schedule.
"""

from __future__ import annotations
from typing import Any, Dict, List

from ssr.formatting import fmt_currency, fmt_short_currency
from ssr.plan_year import plan_start_year


def cat_badge(cat: str) -> str:
    if cat in ("college", "education", "grad_school", "new_child", "superfund_529"):
        return "badge-blue"
    if cat in ("real_estate", "home_renovation", "home_sale", "sabbatical"):
        return "badge-orange"
    if cat in ("lifestyle", "travel_surge", "wedding", "vehicle_purchase"):
        return "badge-pink"
    if cat in ("debt_payoff", "refinance", "company_equity", "equity", "capital_inflow", "custom_spike", "windfall", "income_change", "rental_income", "deferred_comp", "roth_conversion"):
        return "badge-green"
    if cat in ("eldercare", "parent_care", "state_relocation", "ltc_insurance"):
        return "badge-teal"
    if cat in ("gifting", "gifting_throughline", "philanthropy_daf", "child_home_gift", "pe_capital_call"):
        return "badge-purple"
    if cat in ("capital_outflow", "withdrawal", "angel_investment", "marital_settlement"):
        return "badge-red"
    return "badge-blue"


def cat_border(cat: str) -> str:
    borders = {
        "company_equity": "var(--chart-emerald)",
        "equity": "var(--chart-emerald)",
        "roth_conversion": "var(--chart-sapphire)",
        "lifestyle": "var(--accent-amber)",
        "travel_surge": "var(--accent-amber)",
        "wedding": "var(--accent-amber)",
        "vehicle_purchase": "var(--status-red)",
        "real_estate": "var(--chart-amber)",
        "home_renovation": "var(--chart-amber)",
        "home_sale": "var(--chart-amber)",
        "sabbatical": "var(--brand-primary)",
        "income_change": "var(--brand-primary)",
        "rental_income": "var(--chart-emerald)",
        "deferred_comp": "var(--chart-emerald)",
        "debt_payoff": "var(--status-green)",
        "refinance": "var(--status-green)",
        "education": "var(--chart-cerulean)",
        "college": "var(--chart-cerulean)",
        "grad_school": "var(--chart-cerulean)",
        "new_child": "var(--status-green)",
        "superfund_529": "var(--chart-cerulean)",
        "gifting": "var(--chart-sapphire)",
        "gifting_throughline": "var(--chart-sapphire)",
        "philanthropy_daf": "var(--chart-sapphire)",
        "child_home_gift": "var(--chart-sapphire)",
        "pe_capital_call": "var(--chart-emerald)",
        "eldercare": "var(--status-green)",
        "parent_care": "var(--status-green)",
        "state_relocation": "var(--status-green)",
        "ltc_insurance": "var(--status-green)",
        "capital_inflow": "var(--chart-emerald)",
        "windfall": "var(--chart-emerald)",
        "capital_outflow": "var(--status-red)",
        "withdrawal": "var(--status-red)",
        "angel_investment": "var(--status-red)",
        "marital_settlement": "var(--status-red)",
        "custom_spike": "var(--chart-slate)",
        "other": "var(--chart-slate)",
    }
    return borders.get(cat or "other", "var(--chart-slate)")


def cat_theme(cat: str) -> Dict[str, str]:
    border = cat_border(cat)
    return {
        "bg": f"color-mix(in srgb, {border} 92%, transparent)",
        "border": border,
        "text": "var(--text-on-brand)",
    }


def build_events_and_timeline_shelf(
    sim: Dict[str, Any],
    card: Dict[str, Any],
    cur_scen: Dict[str, Any],
) -> Dict[str, Any]:
    """Computes active events, event shelf items, and multi-lane timeline pins."""
    start_year = plan_start_year(sim)
    catalog = {e.get("id"): e for e in sim.get("events_catalog", []) if isinstance(e, dict)}
    raw_events = card.get("events_details") or [catalog[eid] for eid in cur_scen.get("event_ids", []) if eid in catalog]
    active_events: List[Dict[str, Any]] = []
    for e in raw_events:
        if not isinstance(e, dict):
            continue
        ey = e.get("year")
        eend = e.get("end_year")
        time_range = f" ({ey}{f'–{eend}' if eend and eend > ey else ''})" if ey else ""
        amt = e.get("amount")
        amt_str = f": ${round(float(amt) / 1000.0):,}k/yr" if amt else ""
        cat = e.get("category") or "other"
        en = str(e.get("name") or "")
        active_events.append({
            **e,
            "category": cat,
            "icon": e.get("icon") or "",
            "cat_badge": cat_badge(cat),
            "border_color": cat_border(cat),
            "tooltip": f"{en}{time_range}{amt_str}",
            "short_name": f"{en[:13]}…" if len(en) > 14 else en,
        })

    milestones = sim.get("milestones") or []
    in_view_milestones = [m for m in milestones if 2018 <= (m.get("year") or 0) <= 2060]
    cat_active_events = [catalog[eid] for eid in cur_scen.get("event_ids", []) if eid in catalog]
    in_view_events = [
        e for e in cat_active_events
        if (e.get("end_year") or e.get("year") or start_year) >= 2018 and (e.get("year") or start_year) <= 2060
    ]
    shelf_total_count = len(milestones) + len(cat_active_events)
    shelf_in_view_count = len(in_view_milestones) + len(in_view_events)

    shelf_items: List[Dict[str, Any]] = []
    for m in in_view_milestones:
        myr = int(m.get("year") or start_year)
        shelf_items.append({
            "type": "milestone",
            "category": m.get("category") or "other",
            "icon": "",
            "year": myr,
            "end_year": myr,
            "label": m.get("label") or "",
            "is_duration": False,
            "border_color": "var(--accent-orange)",
        })
    for e in in_view_events:
        start_y = int(e.get("year") or start_year)
        end_y = int(e.get("end_year") or start_y)
        ecat = e.get("category") or "other"
        shelf_items.append({
            "type": "event",
            "category": ecat,
            "icon": e.get("icon") or "",
            "year": start_y,
            "end_year": end_y,
            "label": e.get("name") or "",
            "is_duration": end_y > start_y,
            "border_color": cat_border(ecat),
        })
    shelf_items.sort(key=lambda x: (x["year"], 0 if x["type"] == "milestone" else 1))

    # Compute timeline event pins & lanes (matching scrubber.js:216-308)
    min_year = 2018
    max_year = 2060
    year_span = max(1, max_year - min_year)
    track_width = 800
    px_per_year = max(10.0, track_width / year_span)
    pill_years_buffer = max(1.8, 120.0 / px_per_year)
    category_priority = {
        "education": 1,
        "college": 2,
        "grad_school": 2,
        "new_child": 2,
        "superfund_529": 2,
        "real_estate": 3,
        "home_renovation": 3,
        "home_sale": 3,
        "company_equity": 4,
        "roth_conversion": 4,
        "debt_payoff": 5,
        "refinance": 6,
        "sabbatical": 6,
        "income_change": 6,
        "state_relocation": 6,
        "lifestyle": 7,
        "wedding": 7,
        "vehicle_purchase": 7,
        "eldercare": 8,
        "ltc_insurance": 8,
        "gifting": 9,
        "philanthropy_daf": 9,
        "child_home_gift": 9,
        "pe_capital_call": 9,
        "marital_settlement": 9,
        "other": 10,
    }
    visible_events = [
        e for e in cat_active_events
        if isinstance(e, dict) and ((e.get("end_year") or e.get("year") or start_year) >= min_year and (e.get("year") or start_year) <= max_year)
    ]

    def _pin_sort_key(ev: dict):
        sy = int(ev.get("year") or start_year)
        ey = int(ev.get("end_year") or sy)
        dur = ey - sy
        prio = category_priority.get(ev.get("category") or "", 10)
        return (prio, sy, dur)

    sorted_pins = sorted(visible_events, key=_pin_sort_key)
    lane_ends: List[float] = []
    timeline_pins: List[Dict[str, Any]] = []
    lane_height = 21
    lane_gap = 4
    for ev in sorted_pins:
        sy = int(ev.get("year") or start_year)
        ey = int(ev.get("end_year") or sy)
        is_dur = ey > sy
        occ_end = (ey + 0.5) if is_dur else (sy + pill_years_buffer)
        assigned_lane = -1
        for l_idx, l_end in enumerate(lane_ends):
            if l_end <= sy:
                assigned_lane = l_idx
                lane_ends[l_idx] = occ_end
                break
        if assigned_lane == -1:
            assigned_lane = len(lane_ends)
            lane_ends.append(occ_end)
        vis_start = max(min_year, sy)
        vis_end = min(max_year, ey)
        pct_start = ((vis_start - min_year) / year_span) * 100.0
        pct_end = ((vis_end - min_year) / year_span) * 100.0
        width_pct = max(5.0, pct_end - pct_start) if is_dur else 0.0
        top_offset = assigned_lane * (lane_height + lane_gap) + 2
        cat = ev.get("category") or "other"
        theme = cat_theme(cat)
        en = str(ev.get("name") or "")
        base_label = en.split("(")[0].strip()
        yr_label = f"{sy}–{ey}" if is_dur else str(sy)
        short_label = f"{base_label} ({yr_label})"
        timeline_pins.append({
            "id": ev.get("id") or "",
            "name": en,
            "short_label": short_label,
            "start_year": sy,
            "end_year": ey,
            "is_duration": is_dur,
            "pct_start": f"{pct_start:.4f}",
            "width_pct": f"{width_pct:.4f}",
            "top_offset": top_offset,
            "bg": theme["bg"],
            "border": theme["border"],
            "text": theme["text"],
            "category": cat,
            "icon": ev.get("icon") or "",
            "tooltip": f"{en} ({yr_label}): Click to inspect Year {sy}",
        })
    total_lanes = max(2, len(lane_ends))
    timeline_track_height_px = total_lanes * (lane_height + lane_gap) + 4

    m_now = next((m for m in milestones if m.get("year") == start_year), None)
    inspector_milestone_label = (m_now.get("label") if m_now and m_now.get("label") else "Present Pivot")

    return {
        "catalog": catalog,
        "active_events": active_events,
        "shelf_total_count": shelf_total_count,
        "shelf_in_view_count": shelf_in_view_count,
        "shelf_items": shelf_items,
        "timeline_pins": timeline_pins,
        "timeline_track_height_px": timeline_track_height_px,
        "inspector_milestone_label": inspector_milestone_label,
    }


def build_schedule_and_inspector(
    sim: Dict[str, Any],
    cur_scen: Dict[str, Any],
    active_scen_id: str,
    p_name: str,
    s_name: str,
) -> Dict[str, Any]:
    """Computes the start-year scrubber inspector metrics."""
    start_year = plan_start_year(sim)
    active_sched = (
        (sim.get("scenario_schedules") or {}).get(active_scen_id)
        or sim.get("active_schedule")
        or []
    )
    active_cfs = (
        (sim.get("scenario_cash_flows") or {}).get(active_scen_id)
        or sim.get("active_cash_flow_series")
        or []
    )
    cur_row = (
        next((r for r in active_sched if r.get("year") == start_year), None)
        or (active_sched[0] if active_sched else (cur_scen.get("schedule") or [{}])[0])
    )
    cur_cf = next((c for c in active_cfs if c.get("year") == start_year), None) or {}
    cur_nw_val = cur_row.get("total_net_worth")
    cur_inflow_val = cur_cf.get("total_inflow") or cur_row.get("yearly_inflow") or 0
    cur_outflow_val = cur_cf.get("total_outflow") or cur_row.get("yearly_outflow") or 0
    inspector_nw = fmt_short_currency(cur_nw_val) if cur_nw_val is not None else "--"
    inspector_inflow = f"+{fmt_short_currency(cur_inflow_val)}"
    inspector_outflow = f"-{fmt_short_currency(cur_outflow_val)}"
    inspector_ages = f"Ages: {p_name} {cur_row.get('age_primary') or cur_row.get('age') or 45} / {s_name} {cur_row.get('age_spouse') or 45}"

    return {
        "inspector_nw": inspector_nw,
        "inspector_inflow": inspector_inflow,
        "inspector_outflow": inspector_outflow,
        "inspector_ages": inspector_ages,
    }


def build_schedule_rows(schedule: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Formats one plan's year-by-year spend-down schedule for the schedule table (loaded on demand)."""
    schedule_rows: List[Dict[str, Any]] = []
    for row in schedule:
        p_a = row.get("age_primary") or row.get("primary_age") or "--"
        s_a = row.get("age_spouse") or row.get("spouse_age") or "--"
        is_ret = bool(row.get("is_fully_retired"))
        is_part = bool(row.get("is_partially_retired"))
        evs = [str(e) for e in (row.get("events_occurred") or [])]
        net_draw = float(row.get("net_portfolio_draw") or 0.0)
        growth = float(row.get("investment_growth") or 0.0)
        growth_sign = "+" if growth >= 0 else ""
        surv = float(row.get("joint_survival_prob") or 1.0)

        schedule_rows.append({
            "year": row.get("year"),
            "ages": f"{p_a} / {s_a}",
            "is_retired": is_ret,
            "is_partially_retired": is_part,
            "starting_liquid": fmt_currency(float(row.get("starting_liquid") or 0.0), 0),
            "growth": f"{growth_sign}{fmt_currency(growth, 0)}",
            "inflows": fmt_currency(float(row.get("yearly_inflow") or 0.0), 0),
            "living_spending": fmt_currency(float(row.get("living_spending") or 0.0), 0),
            "events": evs,
            "net_draw": net_draw,
            "net_draw_str": fmt_currency(net_draw, 0),
            "ending_nw": fmt_currency(float(row.get("total_net_worth") or 0.0), 0),
            "survival_odds": f"{surv * 100:.0f}%",
        })

    return schedule_rows
