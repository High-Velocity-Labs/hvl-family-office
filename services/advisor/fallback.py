"""
Deterministic rule-based fiduciary fallback engine for the AI Financial Advisor.
Executes when GEMINI_API_KEY is unset or during offline/test runs, providing
structured, data-grounded responses across all 11 dashboard tabs.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import estate_engine
import forecast_engine
from services.advisor.context import _format_off_topic_refusal, _is_off_topic_query
from services.advisor.fallback_helpers import _DISCLAIMER_SUFFIX, _render_extended_tab_fallback
from services.advisor.tools_tabs import get_scenarios_and_forecast_plan

logger = logging.getLogger(__name__)


def _generate_rule_based_response(
    prompt: str,
    ctx: Dict[str, Any],
    history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """High-fidelity deterministic advisor fallback across all 11 dashboard tabs."""
    if _is_off_topic_query(prompt, history=history):
        return _format_off_topic_refusal(ctx)

    p_lower = (prompt or "").lower()
    if history and len(prompt.split()) <= 10:
        past_user_queries = [t.get("content", "") for t in history if t.get("role") == "user"]
        if past_user_queries:
            p_lower = (past_user_queries[-1] + " " + prompt).lower()

    tab = ctx.get("active_tab", "").lower()
    inv_pol = ctx.get("investment_policy", {})
    preset_id = inv_pol.get("anchor_preset", "core_satellite")
    drift = int(inv_pol.get("drift_tolerance", 0.05) * 100)
    rationale = inv_pol.get("deviations_rationale", "")
    eq = ctx.get("equity", {})
    nw = ctx.get("net_worth_snapshot", {})
    family_name = ctx.get("family_name", "Family")
    state = ctx.get("state", "WA")
    spending = ctx.get("annual_spending", 250000.0)
    net_worth = nw.get("net_worth", 0.0)
    fam_id = int(ctx.get("family_id") or 0)

    preset_names = {
        "core_satellite": "Core & Satellite (50/20/15/5/10)",
        "boglehead_80_20": "Classic Three-Fund (80/20)",
        "all_equity_90_10": "Aggressive All-Equity (90/10)",
        "boglehead_90_10": "Aggressive All-Equity (90/10)",
        "glidepath_60_40": "Age-Based Glidepath (60/40)",
        "boglehead_60_40": "Age-Based Glidepath (60/40)",
        "core_four_reit": "Core Four with Real Estate REITs (48/24/20/8)",
    }
    preset_name = preset_names.get(preset_id, preset_id.replace("_", " ").title())

    # Check extended tabs first when specific keywords or active tab match
    ext_reply = _render_extended_tab_fallback(p_lower, tab, fam_id, family_name, state)
    if ext_reply:
        return ext_reply

    # 1. Holdings / Allocation / Policy / Deviation inquiries
    if any(k in p_lower for k in ("allocation", "holdings", "policy", "deviation", "boglehead", "preset", "rebalance", "portfolio")) or "holdings" in tab:
        rebal_steps = inv_pol.get("rebalance_action_steps") or []
        rebal_md = "\n".join(f"- {s}" for s in rebal_steps[:4]) if rebal_steps else "- Portfolio is balanced within your declared drift band."
        return (
            f"### 📊 Strategic Investment & Allocation Review for {family_name}\n\n"
            f"**Active Policy Anchor:** **{preset_name}**  \n"
            f"**Rebalancing Drift Tolerance:** ±{drift}%  \n"
            f"**Declared Deviation Rationale:**  \n"
            f'> *"{rationale or "Adhering to baseline benchmark without custom deviations."}"*\n\n'
            f"---\n\n"
            f"#### 1. Strategic Alignment & Rebalancing Action Plan\n"
            f"Your portfolio is modeled against the **{preset_name}** framework:\n"
            f"{rebal_md}\n\n"
            f"#### 2. Strategic Action Items\n"
            f"1. **Maintain Tax-Free Rebalancing:** Execute allocation adjustments within deferred accounts or by routing new savings rather than selling appreciated taxable lots.\n"
            f"2. **Review Cash Reserves:** Ensure 12–24 months of core living expenses (${spending:,.0f}/yr) remain in liquid money market instruments or short Treasuries.\n"
            f"3. **Audit Annual Drift:** If your active equity or satellite holdings breach the **±{drift}%** band, rebalance proportionally back toward {preset_name}."
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 2. Equity, RSUs, NSOs, or Stock valuation inquiries
    if any(k in p_lower for k in ("equity", "rsu", "nso", "iso", "stock", "grant", "409a", "strike", "option")) or "equity" in tab:
        comp_name = eq.get("company_name", "Primary Company")
        share_price = eq.get("share_price", 0.0)
        gross_val = eq.get("total_gross_equity_value", 0.0)
        net_val = eq.get("true_net_post_tax_value", 0.0)
        strike_req = eq.get("total_strike_cost_needed", 0.0)
        grants = eq.get("grants", [])
        nso_count = eq.get("nso_count", 0)
        rsu_count = eq.get("rsu_count", 0)

        grants_bullets = []
        for g in grants[:5]:
            gt = g.get("grant_type", "NSO")
            stk = "$0.00" if gt == "RSU" else f"${g.get('strike_price', 0):,.2f}"
            grants_bullets.append(
                f"- **{g.get('nickname')}** ({gt}): {g.get('unexercised_options', 0):,} vested units @ {stk} strike -> Net est: **${g.get('true_net_value', 0):,.0f}**"
            )

        return (
            f"### 🚀 Equity & Compensation Assessment: {comp_name}\n\n"
            f"**Current 409A Share Price:** **${share_price:,.2f}**  \n"
            f"**Total Position (Vested):** **${gross_val:,.0f} Gross** | **${net_val:,.0f} True Post-Tax Net**  \n"
            f"**Grant Structure:** {len(grants)} grants ({nso_count} NSO, {rsu_count} RSU)\n\n"
            f"---\n\n"
            f"#### 1. Grant Composition & Mechanics\n"
            f"{chr(10).join(grants_bullets) if grants_bullets else '- No active vested grants recorded.'}\n\n"
            f"- **Non-Qualified Stock Options (NSOs):** Require **${strike_req:,.0f}** in aggregate strike exercise capital. When exercised, the spread (FMV minus strike) is taxed as ordinary income.\n"
            f"- **Restricted Stock Units (RSUs):** Possess **$0.00 strike cost**. Upon vesting, 100% of the Fair Market Value is treated as taxable compensation income.\n\n"
            f"#### 2. Risk & Liquidity Recommendations\n"
            f"1. **Concentration Risk:** Company stock represents ${net_val:,.0f} of ${net_worth:,.0f} net worth. Systematically trim vested RSUs and NSOs at liquidity windows to fund your **{preset_name}** liquid index allocations.\n"
            f"2. **Exercise Strategy:** For NSOs, evaluate cashless exercise during secondary buybacks to fund tax withholdings and avoid out-of-pocket cash drain."
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 3. Monte Carlo, Sequence-of-Returns, Crash Stress Testing & Bear Market inquiries
    if any(k in p_lower for k in ("monte carlo", "stress test", "crash", "2008", "1929", "stagflation", "dot com", "dotcom", "sequence of returns", "bear market", "drawdown", "percentile")):
        try:
            mc = forecast_engine.run_monte_carlo_simulation(family_id=fam_id, trials=1000)
            if mc.get("success"):
                rate100 = mc.get("success_rate_age_100", 0.0)
                rate90 = mc.get("success_rate_age_90", 0.0)
                med_term = mc.get("median_terminal_wealth", 0.0)
                p10_term = mc.get("p10_terminal_wealth", 0.0)
                p_stats = mc.get("portfolio_stats", {})
                exp_ret = p_stats.get("expected_return", 0.0) * 100
                p_vol = p_stats.get("volatility", 0.0) * 100
                st_map = mc.get("stress_tests", {})
                st_bullets = [
                    f"- **{st.get('name')}:** {'✅ Solvency Preserved' if st.get('survived') else '⚠️ Depleted Before Age 100'} | Max Drawdown: **{st.get('max_drawdown_pct')}%** | Trough: **${st.get('trough_net_worth', 0):,.0f}** ({st.get('trough_year')}) | Terminal: **${st.get('terminal_net_worth', 0):,.0f}**"
                    for st in st_map.values()
                ]
                return (
                    f"### 🎲 Stochastic Monte Carlo & Sequence-of-Returns Audit for {family_name}\n\n"
                    f"**1,000-Trial Solvency Probability (Age 100):** **{rate100}%**  \n"
                    f"**Solvency Probability through Age 90:** **{rate90}%**  \n"
                    f"**Portfolio Risk Profile:** **σ = {p_vol:.1f}% / yr** volatility | **+{exp_ret:.1f}% / yr** weighted expected return\n\n"
                    f"---\n\n"
                    f"#### 1. Stochastic Percentile Distribution\n"
                    f"- **Median Terminal Wealth (50th Percentile):** **${med_term:,.0f}** at Age 100.\n"
                    f"- **Downside Floor (10th Percentile Bear Sequence):** **${p10_term:,.0f}** remaining capital.\n\n"
                    f"#### 2. Historical Sequence-of-Returns Crisis Replays\n"
                    f"{chr(10).join(st_bullets)}"
                    f"{_DISCLAIMER_SUFFIX}"
                )
        except Exception as e:
            logger.warning("Monte carlo execution error in advisor: %s", e)

    # 4. Life Events & Scenario Modeling (e.g., personal assistant, vacation, travel, sabbatical)
    if any(k in p_lower for k in ("event", "events", "assistant", "nanny", "vacation", "galapagos", "travel", "sabbatical", "lifestyle")):
        scen_info = get_scenarios_and_forecast_plan(family_id=fam_id, scenario_name=prompt)
        active_plan = scen_info.get("active_plan_name", "Baseline Plan")
        events = scen_info.get("active_life_events") or []
        catalog = scen_info.get("all_household_events_catalog") or []
        ev_lines = [
            f"- **{e.get('name')}** ({e.get('year_str') or e.get('year')}): {e.get('amount_str') or e.get('amount')} ({e.get('type_label') or e.get('category')})"
            for e in (events if events else catalog)[:6]
        ]
        return (
            f"### 🗓️ Scenario Life Events Analysis for {family_name}\n\n"
            f"**Target Plan:** **{active_plan}** | **Net Worth at 65:** **{scen_info.get('net_worth_age_65', '--')}** | **Solvency:** **{scen_info.get('solvency_status', '--')}**\n\n"
            f"---\n\n"
            f"#### 1. Modeled Life Events\n"
            f"{chr(10).join(ev_lines) if ev_lines else '- No scheduled life events in this scenario.'}\n\n"
            f"#### 2. Quantitative Modeling\n"
            f"To simulate or save custom life events (such as vacations, sabbaticals, or household staffing), you can manage them directly via `manage_scenario_life_event`."
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 5. Forecasting / Retirement / FIRE / Scenarios inquiries
    if any(k in p_lower for k in ("forecast", "retire", "fire", "spending", "burn", "simulation", "safe withdrawal", "scenario")) or "scenarios" in tab:
        swr = (spending / net_worth * 100) if net_worth > 0 else 0.0
        scen_info = get_scenarios_and_forecast_plan(family_id=fam_id, scenario_name=prompt)
        scorecard = scen_info.get("scenarios_scorecard") or []
        sc_lines = [
            f"- **{s.get('name')}**: Retire {s.get('retirement_ages')} | Spend {s.get('annual_spend')} | NW @ 65: **{s.get('nw_65')}** | NW @ 95: **{s.get('nw_95')}** ({s.get('solvency')})"
            for s in scorecard[:4]
        ]
        return (
            f"### 📈 Multi-Decade Wealth & Longevity Forecast for {family_name}\n\n"
            f"**Estimated Total Net Worth:** **${net_worth:,.0f}** | **Active Plan:** **{scen_info.get('active_plan_name', 'Baseline Plan')}**  \n"
            f"**Annual Household Spending:** **${spending:,.0f} / year** | **Implied Withdrawal Rate:** **{swr:.2f}%**\n\n"
            f"---\n\n"
            f"#### 1. Saved Scenarios Scorecard\n"
            f"{chr(10).join(sc_lines) if sc_lines else '- Baseline longevity trajectory active.'}\n\n"
            f"#### 2. Wealth & Solvency Analysis\n"
            f"- **Sustainable Withdrawal Rate:** Your current burn rate of **{swr:.2f}%** is {'well within' if swr <= 4.0 else 'above'} the classical 3.5%–4.0% safe withdrawal threshold."
            f"{_DISCLAIMER_SUFFIX}"
        )

    # 6. Estate Tax, Generational Wealth, Trusts & Inheritance inquiries
    if any(k in p_lower for k in ("estate", "inheritance", "trust", "slat", "idgt", "grat", "ilit", "death tax", "sunset", "heir", "children")) or "estate" in tab:
        try:
            ep = estate_engine.get_family_estate_profile(family_id=fam_id)
            cur_tax = ep.get("current_estate_tax", {})
            tot_tax = cur_tax.get("total_estate_tax", 0.0)
            fed_tax = cur_tax.get("federal_estate_tax", 0.0)
            state_tax = cur_tax.get("state_estate_tax", 0.0)
            eff_rate = cur_tax.get("effective_tax_rate", 0.0)
            net_heirs = cur_tax.get("net_estate_to_heirs", 0.0)
            sandbox = ep.get("trust_sandbox", {})
            max_shield = sandbox.get("max_potential_tax_savings", 0.0)
            return (
                f"### 🏛️ Estate Tax & Wealth Preservation Audit for {family_name}\n\n"
                f"**Projected Gross Estate:** **${cur_tax.get('gross_estate', net_worth):,.0f}**  \n"
                f"**Combined Estate Tax Liability:** **${tot_tax:,.0f}** (Effective Rate: **{eff_rate:.1f}%**)  \n"
                f"- **Federal Estate Tax (40%):** **${fed_tax:,.0f}** | **{state} State Estate Tax:** **${state_tax:,.0f}**  \n"
                f"**Net Wealth Transferred to Next-Gen:** **${net_heirs:,.0f}** | **Max Potential Tax Shielded (SLAT/IDGT/ILIT):** **${max_shield:,.0f}**"
                f"{_DISCLAIMER_SUFFIX}"
            )
        except Exception as e:
            logger.warning("Estate calculation error in advisor: %s", e)

    # 7. General / Default response
    return (
        f"### ✨ AI Financial Advisor Briefing for {family_name}\n\n"
        f"Welcome to your family office advisory portal. I have live tool access across all tabs: Balance Sheet Accounts, Investments & IPS, Company Equity, Multi-Scenario Forecasting, Compensation & Safe Harbor, Multi-State Tax Arbitrage, Education 529s, Philanthropy & DAFs, Family Gifting, and Estate Planning.\n\n"
        f"---\n\n"
        f"#### Current Family Highlights\n"
        f"- **Net Worth:** **${net_worth:,.0f}** across liquid cash, investments, real estate, and company equity.\n"
        f"- **Investment Policy Statement:** Anchored to **{preset_name}** with a ±{drift}% rebalancing tolerance.\n"
        f"- **Declared Policy Rationale:** *\"{rationale or 'Standard index allocation.'}\"*\n"
        f"- **Equity Holdings:** {eq.get('company_name', 'Company')} shares at **${eq.get('share_price', 0):,.2f}** 409A valuation ({eq.get('nso_count', 0)} NSO, {eq.get('rsu_count', 0)} RSU grants)."
        f"{_DISCLAIMER_SUFFIX}"
    )


__all__ = [
    "_DISCLAIMER_SUFFIX",
    "_generate_rule_based_response",
    "_render_extended_tab_fallback",
]
