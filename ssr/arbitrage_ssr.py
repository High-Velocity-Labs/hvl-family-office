"""
SSR view-model builder for Multi-State Tax Arbitrage.
"""

from __future__ import annotations

import logging

import db
import monarch_service
import security
import tax_engine
from routes.helpers import DB_PATH
from ssr.formatting import fmt_currency, fmt_short_currency

logger = logging.getLogger(__name__)


def build_ssr_arbitrage(
    family_id: int,
    home_state: str | None = None,
    home_value: float | None = None,
    annual_spend: float | None = None,
    mode: str | None = None,
    scenario: str | None = None,
) -> dict:
    """Prepares SSR data for Multi-State Tax Arbitrage (spending history table, benchmarks, presets, and initial state cards)."""
    if family_id <= 0:
        return {}
    try:
        data = monarch_service.get_monarch_spending_history(family_id=family_id) or {}
        history = data.get("spending_history") or {}
        benchmarks = data.get("benchmarks") or {}

        active_mode = "tax_only" if str(mode or "").strip().lower() == "tax_only" else "comprehensive"
        active_scenario = "liquidity" if str(scenario or "").strip().lower() == "liquidity" else "recurring"
        is_comp = active_mode == "comprehensive"
        is_liq = active_scenario == "liquidity"

        default_state = "WA"
        db_spend = float(benchmarks.get("recommended_budget") or benchmarks.get("baseline") or 0.0)
        db_home_value, db_salary, db_spread, db_cap_gains = 0.0, 0.0, 0.0, 0.0

        if DB_PATH.exists():
            try:
                hp = db.families.get_household_profile(family_id=family_id, db_path=DB_PATH)
                if hp:
                    if hp.get("state"):
                        default_state = str(hp["state"]).strip().upper()
                    if hp.get("annual_spending"):
                        db_spend = float(hp["annual_spending"])
            except Exception:
                pass
            try:
                members = security.get_family_members(DB_PATH, family_id=family_id)
                primary_user = next((m for m in members if m.get("relationship") == "primary"), None)
                primary_uid = primary_user.get("user_id") if primary_user else None
                comp_rows = db.compensation.list_compensation_records(family_id=family_id, user_id=primary_uid, db_path=DB_PATH)
                if comp_rows:
                    tot_sal = float(comp_rows[0].get("salary", 0.0) or 0.0) + float(comp_rows[0].get("bonus", 0.0) or 0.0)
                    if tot_sal > 0:
                        db_salary = tot_sal
            except Exception:
                pass
            try:
                snapshot = monarch_service.get_financial_snapshot(family_id=family_id)
                db_home_value = float((snapshot.get("categories") or {}).get("real_estate", {}).get("total", 0.0) or 0.0)
                company_eq = snapshot.get("company_equity") or {}
                db_spread = float(company_eq.get("total_taxable_spread", 0.0) or 0.0)
                db_cap_gains = max(0.0, float(company_eq.get("total_gross_equity_value", 0.0) or 0.0) - db_spread)
            except Exception:
                pass

        raw_state_options = [
            ("WA", "Washington (WA - 0% Income / 7% Cap Gains)"), ("CA", "California (CA - 13.3% Top Bracket)"),
            ("NY", "New York (NY - 10.9% Top Bracket)"), ("OR", "Oregon (OR - 9.9% Top Bracket)"),
            ("NV", "Nevada (NV - 0% Income & Gains)"), ("TX", "Texas (TX - 0% Income & Gains)"),
            ("FL", "Florida (FL - 0% Income & Gains)"), ("WY", "Wyoming (WY - 0% Income & Gains)"),
        ]
        valid_state_codes = {code for code, _ in raw_state_options}
        if home_state and str(home_state).strip():
            cand_state = str(home_state).strip().upper()
            if cand_state in valid_state_codes:
                default_state = cand_state

        state_options = [{"code": code, "label": label, "selected": (code == default_state)} for code, label in raw_state_options]

        presets = []
        for bkey, blabel in (
            ("actual_2025", "2025 Actual"), ("annualized_2026", "2026 Annualized"),
            ("three_year_average", "3-Yr Average"), ("actual_2024", "2024 Actual"), ("baseline", "Baseline"),
        ):
            if benchmarks.get(bkey):
                v = round(float(benchmarks[bkey]))
                presets.append({"label": f"{blabel} ({fmt_short_currency(v)})", "value": v, "spend": v})

        has_custom_spend = annual_spend is not None and float(annual_spend) > 0
        target_preset_spend = float(annual_spend) if has_custom_spend else db_spend

        active_found = False
        for p in presets:
            if abs(p["spend"] - target_preset_spend) < 1000 and not active_found:
                p["is_active"], active_found = True, True
            else:
                p["is_active"] = False
        if not active_found and presets and not has_custom_spend:
            presets[0]["is_active"] = True

        active_preset = next((p for p in presets if p.get("is_active")), None)
        effective_home_value = float(home_value) if (home_value is not None and float(home_value) > 0) else (db_home_value if db_home_value > 0 else 0.0)
        effective_spend = float(annual_spend) if has_custom_spend else (float(active_preset["value"]) if (active_preset and db_spend <= 0) else (db_spend if db_spend > 0 else 0.0))

        arb_result = tax_engine.compare_state_tax_arbitrage(
            ordinary_spread=db_spread if is_liq else 0.0,
            capital_gains=db_cap_gains if is_liq else 0.0,
            base_w2_salary=db_salary,
            home_value=effective_home_value,
            annual_household_spend=effective_spend,
            home_state=default_state,
        )

        states = arb_result.get("states") or []
        home_code = arb_result.get("home_state") or default_state or "WA"
        max_savings, winner_code = float("-inf"), ""
        for s in states:
            is_home_state = bool(s.get("is_home_state")) or s.get("state_code") == home_code
            sav_5yr = float(s.get("savings_5yr_vs_home") if s.get("savings_5yr_vs_home") is not None else (s.get("savings_5yr_vs_wa_2028") or 0.0))
            sav_1yr = float(s.get("savings_vs_home", 0.0) or 0.0)
            sav = sav_5yr if is_comp else (sav_1yr if is_liq else sav_1yr * 5.0)
            if not is_home_state and sav > max_savings:
                max_savings, winner_code = sav, s.get("state_code") or ""

        state_cards = []
        for s in states:
            s_code = s.get("state_code") or ""
            is_home = bool(s.get("is_home_state")) or s_code == home_code
            is_winner = s_code == winner_code and max_savings > 0
            comp_1yr = float(s.get("comprehensive_1yr_cost") or 0.0)
            total_tax = float(s.get("total_state_tax") or 0.0)
            primary_cost = comp_1yr if is_comp else total_tax
            primary_label = "1-YEAR TOTAL LIFESTYLE COST" if is_comp else "ANNUAL STATE TAX LIABILITY"
            eff_rate = float(s.get("effective_state_rate") or 0.0) * 100.0
            sav_5yr = float(s.get("savings_5yr_vs_home") if s.get("savings_5yr_vs_home") is not None else (s.get("savings_5yr_vs_wa_2028") or 0.0))
            sav_1yr = float(s.get("savings_vs_home", 0.0) or 0.0)
            savings_vs_home = sav_5yr if is_comp else (sav_1yr if is_liq else sav_1yr * 5.0)
            savings_label = "Baseline Residence" if is_home else (f"5-Yr vs {home_code}:" if is_comp else (f"Tax Delta vs {home_code}:" if is_liq else f"5-Yr Tax vs {home_code}:"))
            badge_class = "badge-blue" if is_home else ("badge-green" if s_code == winner_code else ("badge-orange" if s_code in ("CA", "NY") else "badge-green"))
            savings_color = "var(--text-muted)" if is_home else ("var(--status-green)" if savings_vs_home > 0 else "var(--status-red)")
            savings_val_str = "Current State" if is_home else f"{'+' if savings_vs_home > 0 else ''}{fmt_short_currency(savings_vs_home)}"
            ordinary_tax = float(s.get("ordinary_income_tax") or total_tax or 0.0)
            cap_gains_tax = float(s.get("capital_gains_tax") or 0.0)
            state_cards.append({
                "state_code": s_code, "state_name": s.get("state_name") or s_code, "notes": s.get("notes") or "",
                "is_home": is_home, "is_winner": is_winner, "is_comp": is_comp, "is_liq": is_liq,
                "badge_class": badge_class, "primary_label": primary_label,
                "primary_cost_str": fmt_currency(primary_cost, 0),
                "primary_cost_color": "var(--status-green)" if total_tax == 0 else "var(--text-primary)",
                "state_tax_str": fmt_currency(total_tax, 0),
                "state_tax_color": "var(--status-green)" if total_tax == 0 else "var(--accent-orange)",
                "eff_rate_str": f"{eff_rate:.2f}%",
                "prop_tax_str": f"{fmt_currency(float(s.get('annual_property_tax') or 0.0), 0)}/yr",
                "living_cost_str": f"{fmt_currency(float(s.get('annual_living_cost') or 0.0), 0)}/yr",
                "recurring_cost_str": f"{fmt_currency(float(s.get('annual_recurring_cost') or 0.0), 0)}/yr",
                "ordinary_tax_str": fmt_currency(ordinary_tax, 0), "cap_gains_tax_str": fmt_currency(cap_gains_tax, 0),
                "liquidity_tax_str": "$0 (100% Tax Free)" if total_tax == 0 else fmt_currency(total_tax, 0),
                "liquidity_tax_color": "var(--accent-emerald)" if total_tax == 0 else "var(--accent-danger)",
                "savings_label": savings_label, "savings_color": savings_color, "savings_val_str": savings_val_str,
            })

        rows = []
        for yr in sorted(history.keys(), key=lambda y: int(y) if str(y).isdigit() else 0, reverse=True):
            item = history[yr]
            if not item:
                continue
            is_partial = bool(item.get("is_partial"))
            days = item.get("days_recorded") or (283 if is_partial else 365)
            top_drivers = ", ".join(f"{name} ({fmt_short_currency(amt)})" for name, amt in item["top_categories"][:4]) if item.get("top_categories") else "--"
            pace_val = item.get("annualized_non_housing_living") or item.get("non_housing_living_expenses") or 0.0
            rows.append({
                "year_label": f"{item.get('year', yr)}{' YTD' if is_partial else ''}",
                "badge_color": "badge-orange" if is_partial else ("badge-green" if str(yr) == "2025" else "badge-blue"),
                "badge_text": f"{round(days / 30.4)} mos" if is_partial else "Full Year",
                "total_outflow": fmt_currency(item.get("total_expenses") or 0, 0),
                "housing": fmt_currency(item.get("housing_expenses") or 0, 0),
                "gifts": fmt_currency(item.get("gifts_and_donations") or 0, 0),
                "living": fmt_currency(item.get("non_housing_living_expenses") or 0, 0),
                "annualized_living": f"{fmt_currency(pace_val, 0)} / yr",
                "top_drivers": top_drivers,
            })

        return {
            "default_state": default_state, "state_options": state_options,
            "home_value": int(round(effective_home_value)) if effective_home_value > 0 else "",
            "annual_spend": int(round(effective_spend)) if effective_spend > 0 else "",
            "active_mode": active_mode, "active_scenario": active_scenario, "is_comp": is_comp, "is_liq": is_liq,
            "presets": presets, "spending_rows": rows, "state_cards": state_cards,
            "recurring_btn_label": f"Recurring Year ({fmt_short_currency(db_salary)} W-2)" if db_salary > 0 else "Recurring Year (W-2 Only)",
            "liquidity_btn_label": f"+ Major Liquidity (+{fmt_short_currency(db_spread)} Options)" if db_spread > 0 else "+ Major Liquidity (Options Spread)",
            "base_salary_short": fmt_short_currency(db_salary),
            "total_liq_income_short": fmt_short_currency(db_salary + db_spread),
            "ordinary_spread_short": fmt_short_currency(db_spread),
            "cap_gains_short": fmt_short_currency(db_cap_gains),
            "arbitrage_raw": arb_result,
        }
    except Exception as e:
        logger.warning(f"Failed to generate SSR arbitrage data: {e}")
        return {}


__all__ = ["build_ssr_arbitrage"]
