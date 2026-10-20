"""
Net worth series reconstruction, linear interpolation, and snapshot evaluation helpers.
Extracted from db/balance_history.py for modularity.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from db.balance_history_csv import normalize_date_str
from db.session import resolve_db_path


def interpolate_account_balance_at_date(
    acc_dates_map: Dict[str, float],
    target_date_str: str,
) -> float:
    """
    Computes an account's balance at `target_date_str` (`YYYY-MM-DD`) using:
    1. Exact match if `target_date_str` exists in `acc_dates_map`.
    2. Linear interpolation if snapshots exist both `<= target_date_str` and `>= target_date_str`.
    3. Carry-forward of the latest snapshot `<= target_date_str` if no future snapshot exists.
    4. `0.0` if no snapshot exists on or before `target_date_str`.
    """
    if not acc_dates_map:
        return 0.0
    if target_date_str in acc_dates_map:
        return float(acc_dates_map[target_date_str])

    prev_d = max((d for d in acc_dates_map.keys() if d <= target_date_str), default=None)
    if prev_d is None:
        return 0.0

    next_d = min((d for d in acc_dates_map.keys() if d >= target_date_str), default=None)
    if next_d is None or next_d == prev_d:
        return float(acc_dates_map[prev_d])

    try:
        t_ord = date.fromisoformat(target_date_str).toordinal()
        p_ord = date.fromisoformat(prev_d).toordinal()
        n_ord = date.fromisoformat(next_d).toordinal()
        span = max(1, n_ord - p_ord)
        frac = (t_ord - p_ord) / float(span)
        v_prev = float(acc_dates_map[prev_d])
        v_next = float(acc_dates_map[next_d])
        return v_prev + frac * (v_next - v_prev)
    except Exception:
        return float(acc_dates_map[prev_d])


def _load_snapshot_eval_context(
    family_id: int,
    path: Path,
) -> tuple[Dict[int, Dict[str, Any]], Dict[str, Dict[str, float]], Dict[str, Dict[str, float]], Dict[str, str], float]:
    """Loads seeded annual rows, raw & effective balance history maps, categorized account buckets, and live equity."""
    from db import accounts as db_accounts
    from db.balance_history import load_balance_history_map, load_roles_map_for_path
    from monarch.categorizer import categorize_account, is_account_hidden_from_family_office
    import security

    seeded_list = security.db_load_encrypted(path, "historical_net_worth", family_id=family_id) or []
    existing_by_year: Dict[int, Dict[str, Any]] = {}
    if isinstance(seeded_list, list):
        for item in seeded_list:
            if isinstance(item, dict) and item.get("year") is not None:
                try:
                    existing_by_year[int(item["year"])] = dict(item)
                except (ValueError, TypeError):
                    pass

    history_map = load_balance_history_map(family_id=family_id, db_path=path)
    accounts = db_accounts.list_accounts(family_id=family_id, db_path=path)
    roles_cache = load_roles_map_for_path(family_id, path)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    effective_history: Dict[str, Dict[str, float]] = {aid: dict(dmap) for aid, dmap in history_map.items()}
    acc_by_id: Dict[str, Dict[str, Any]] = {}
    for acc in accounts:
        aid = str(acc.get("id") or "")
        if not aid:
            continue
        acc_by_id[aid] = acc
        if aid not in effective_history:
            as_of = normalize_date_str(acc.get("as_of_date")) or today_str
            effective_history[aid] = {as_of: float(acc.get("currentBalance", acc.get("balance", 0.0)) or 0.0)}

    excluded_roles = {"education_529", "education_530a", "company_equity_nso", "tax_liability", "hidden_from_family_office"}
    acc_bucket: Dict[str, str] = {}
    for aid in effective_history.keys():
        acc_obj = acc_by_id.get(aid)
        if acc_obj is not None:
            cat = categorize_account(acc_obj, family_id=family_id, roles_cache=roles_cache, family_comps=[])
            is_fo_hidden = is_account_hidden_from_family_office(aid, cat, family_id=family_id, roles_cache=roles_cache)
            inc_nw = (
                acc_obj.get("includeInNetWorth", True) is not False
                and acc_obj.get("includeBalanceInNetWorth", True) is not False
                and not is_fo_hidden
                and cat not in excluded_roles
            )
            if inc_nw:
                acc_bucket[aid] = cat
        else:
            role_entry = roles_cache.get(aid)
            cat = role_entry[0] if role_entry else "cash_liquid"
            is_fo_hidden = role_entry[1] if role_entry else False
            if not is_fo_hidden and cat not in excluded_roles:
                acc_bucket[aid] = cat

    live_equity_net = 0.0
    try:
        if path == resolve_db_path(None, family_id=family_id):
            import equity_engine
            eq_sim = equity_engine.simulate_valuation_scenario(family_id=family_id)
            live_equity_net = float(eq_sim.get("true_net_post_tax_value", 0.0) or 0.0)
    except Exception:
        pass

    return existing_by_year, history_map, effective_history, acc_bucket, live_equity_net


def _sum_buckets_at_date(
    acc_bucket: Dict[str, str],
    effective_history: Dict[str, Dict[str, float]],
    eval_date_str: str,
    yr_prefix: Optional[str] = None,
) -> tuple[float, float, float]:
    """Evaluates (liquid_inv, real_estate_net, non_equity_nw) across categorized accounts at `eval_date_str`."""
    liquid_inv = 0.0
    real_estate_net = 0.0
    non_equity_nw = 0.0
    for aid, cat in acc_bucket.items():
        dmap = effective_history.get(aid) or {}
        if not dmap:
            continue
        if yr_prefix:
            in_year_dates = [d for d in dmap.keys() if d.startswith(yr_prefix)]
            bal = float(dmap[max(in_year_dates)]) if in_year_dates else interpolate_account_balance_at_date(dmap, eval_date_str)
        else:
            bal = interpolate_account_balance_at_date(dmap, eval_date_str)

        if cat in ("cash_liquid", "public_brokerage", "retirement"):
            liquid_inv += bal
            non_equity_nw += bal
        elif cat == "real_estate":
            real_estate_net += bal
            non_equity_nw += bal
        elif cat == "mortgages":
            mort_val = -abs(bal) if bal > 0 else bal
            real_estate_net += mort_val
            non_equity_nw += mort_val
        elif cat == "credit_cards":
            non_equity_nw += (-abs(bal) if bal > 0 else bal)
        else:
            non_equity_nw += bal
    return liquid_inv, real_estate_net, non_equity_nw


def rebuild_historical_net_worth_from_snapshots(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
    persist: bool = True,
) -> List[Dict[str, Any]]:
    """
    Computes the yearly Net Worth Over Time series from `"account_balance_history"`
    using Carry-Forward and Linear Interpolation across sync/entry gaps.
    """
    if not family_id or family_id <= 0:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    import security
    existing_by_year, history_map, effective_history, acc_bucket, live_equity_net = _load_snapshot_eval_context(family_id, path)

    snapshot_years = {
        int(d[:4]) for acc_d in history_map.values() for d in acc_d.keys() if len(d) >= 4 and d[:4].isdigit()
    }
    if not snapshot_years:
        return [existing_by_year[y] for y in sorted(existing_by_year.keys())] if existing_by_year else []

    current_year = datetime.now(timezone.utc).year
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    min_snap_year = min(snapshot_years)
    max_snap_year = max(max(snapshot_years), current_year)

    result_by_year: Dict[int, Dict[str, Any]] = {
        yr: seeded_row
        for yr, seeded_row in existing_by_year.items()
        if yr < min_snap_year and not seeded_row.get("from_snapshots")
    }

    for yr in range(min_snap_year, max_snap_year + 1):
        yr_prefix = f"{yr:04d}-"
        target_eval_date = today_str if yr == current_year else f"{yr:04d}-12-31"
        liquid_inv, real_estate_net, non_equity_nw = _sum_buckets_at_date(
            acc_bucket, effective_history, target_eval_date, yr_prefix=yr_prefix
        )
        prev_seeded = existing_by_year.get(yr) or {}
        eq_val = (
            live_equity_net
            if (yr == current_year and live_equity_net > 0)
            else float(prev_seeded.get("equity_net", prev_seeded.get("company_net", 0.0)) or 0.0)
        )
        true_nw = non_equity_nw + eq_val
        result_by_year[yr] = {
            "year": yr,
            "true_net_worth": round(true_nw),
            "equity_net": round(eq_val),
            "company_net": round(eq_val),
            "liquid_investments": round(liquid_inv),
            "real_estate": round(real_estate_net),
            "from_snapshots": True,
        }

    final_series = [result_by_year[y] for y in sorted(result_by_year.keys())]
    if persist:
        try:
            security.db_save_encrypted(path, "historical_net_worth", "balance_history", final_series, family_id=family_id)
        except Exception:
            pass
    return final_series


def build_dated_net_worth_series(
    family_id: int = 0,
    granularity: str = "auto",
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """
    Builds a chronological Net Worth Over Time series at `"annual"`, `"quarterly"`, `"monthly"`,
    or `"auto"` granularity using per-account Carry-Forward and Linear Interpolation.
    """
    if not family_id or family_id <= 0:
        return []
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return []

    norm_gran = str(granularity or "auto").strip().lower()
    if norm_gran not in ("annual", "quarterly", "monthly", "auto"):
        norm_gran = "auto"

    existing_by_year, history_map, effective_history, acc_bucket, live_equity_net = _load_snapshot_eval_context(family_id, path)
    now_utc = datetime.now(timezone.utc)
    current_year = now_utc.year
    today_str = now_utc.strftime("%Y-%m-%d")

    all_snap_dates = sorted({d for acc_d in history_map.values() for d in acc_d.keys() if len(d) >= 7})
    snapshot_years = {int(d[:4]) for d in all_snap_dates if d[:4].isdigit()}
    snapshot_months = {d[:7] for d in all_snap_dates if len(d) >= 7}
    min_snap_yr = min(snapshot_years) if snapshot_years else current_year
    seeded_prior_years = {
        yr for yr, row in existing_by_year.items()
        if yr < min_snap_yr and not row.get("from_snapshots")
    }
    distinct_years = snapshot_years | seeded_prior_years

    eff_gran = "monthly" if (norm_gran == "auto" and len(distinct_years) < 2 and (len(snapshot_months) >= 2 or len(all_snap_dates) >= 2)) else (norm_gran if norm_gran != "auto" else "annual")

    if eff_gran == "annual":
        annual_rows = rebuild_historical_net_worth_from_snapshots(family_id=family_id, db_path=path)
        out_annual: List[Dict[str, Any]] = []
        for r in annual_rows:
            row_copy = dict(r)
            yr = int(row_copy.get("year") or current_year)
            row_copy.setdefault("period", f"{yr:04d}")
            row_copy.setdefault("date", today_str if yr == current_year else f"{yr:04d}-12-31")
            out_annual.append(row_copy)
        return out_annual

    use_seeded_interp = len(all_snap_dates) < 2 and len(existing_by_year) >= 2
    if use_seeded_interp:
        min_yr = max(min(existing_by_year.keys()), current_year - 3)
        max_yr = max(max(existing_by_year.keys()), current_year)
        min_date_str = f"{min_yr:04d}-01-31"
        max_date_str = today_str if max_yr == current_year else f"{max_yr:04d}-12-31"
    elif not all_snap_dates:
        if not existing_by_year:
            return []
        min_date_str = f"{min(existing_by_year.keys()):04d}-12-31"
        max_date_str = max(f"{max(existing_by_year.keys()):04d}-12-31", today_str)
    else:
        min_date_str = min(all_snap_dates)
        max_date_str = max(all_snap_dates)

    start_yr, start_mo = int(min_date_str[:4]), int(min_date_str[5:7])
    end_yr, end_mo = int(max_date_str[:4]), int(max_date_str[5:7])

    periods: List[tuple[str, str, int]] = []
    if eff_gran == "monthly":
        yr, mo = start_yr, start_mo
        while (yr, mo) <= (end_yr, end_mo):
            last_day = calendar.monthrange(yr, mo)[1]
            periods.append((f"{yr:04d}-{mo:02d}", f"{yr:04d}-{mo:02d}-{last_day:02d}", yr))
            yr, mo = (yr + 1, 1) if mo == 12 else (yr, mo + 1)
        if len(periods) < 2 and len(all_snap_dates) >= 2:
            periods = [(d, d, int(d[:4])) for d in all_snap_dates]
    else:
        start_q, end_q = (start_mo - 1) // 3 + 1, (end_mo - 1) // 3 + 1
        yr, q = start_yr, start_q
        while (yr, q) <= (end_yr, end_q):
            q_end_mo = q * 3
            last_day = calendar.monthrange(yr, q_end_mo)[1]
            periods.append((f"{yr:04d}-Q{q}", f"{yr:04d}-{q_end_mo:02d}-{last_day:02d}", yr))
            yr, q = (yr + 1, 1) if q == 4 else (yr, q + 1)

    if use_seeded_interp:
        nw_dmap = {f"{y:04d}-12-31": float(r.get("true_net_worth", 0.0) or 0.0) for y, r in existing_by_year.items()}
        eq_dmap = {f"{y:04d}-12-31": float(r.get("equity_net", r.get("company_net", 0.0)) or 0.0) for y, r in existing_by_year.items()}
        liq_dmap = {f"{y:04d}-12-31": float(r.get("liquid_investments", 0.0) or 0.0) for y, r in existing_by_year.items()}
        re_dmap = {f"{y:04d}-12-31": float(r.get("real_estate", 0.0) or 0.0) for y, r in existing_by_year.items()}
        return [
            {
                "period": label,
                "date": eval_date_str,
                "year": yr,
                "true_net_worth": round(interpolate_account_balance_at_date(nw_dmap, eval_date_str)),
                "equity_net": round(interpolate_account_balance_at_date(eq_dmap, eval_date_str)),
                "company_net": round(interpolate_account_balance_at_date(eq_dmap, eval_date_str)),
                "liquid_investments": round(interpolate_account_balance_at_date(liq_dmap, eval_date_str)),
                "real_estate": round(interpolate_account_balance_at_date(re_dmap, eval_date_str)),
            }
            for label, eval_date_str, yr in periods
        ]

    series: List[Dict[str, Any]] = []
    for label, eval_date_str, yr in periods:
        liquid_inv, real_estate_net, non_equity_nw = _sum_buckets_at_date(
            acc_bucket, effective_history, eval_date_str, yr_prefix=None
        )
        prev_seeded = existing_by_year.get(yr) or {}
        eq_val = (
            live_equity_net
            if (yr == current_year and live_equity_net > 0)
            else float(prev_seeded.get("equity_net", prev_seeded.get("company_net", 0.0)) or 0.0)
        )
        true_nw = non_equity_nw + eq_val
        series.append({
            "period": label,
            "date": eval_date_str,
            "year": yr,
            "true_net_worth": round(true_nw),
            "equity_net": round(eq_val),
            "company_net": round(eq_val),
            "liquid_investments": round(liquid_inv),
            "real_estate": round(real_estate_net),
        })
    return series
