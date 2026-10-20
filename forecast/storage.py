"""
forecast/storage.py: Scenario State Persistence, Tuition Ledger & Historical Actuals.
Decouples database access and encrypted state storage from mathematical forecast engines.
"""

from __future__ import annotations
import sys
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone
import logging

import security
import monarch_service
from db.session import resolve_db_path


logger = logging.getLogger(__name__)


class _ForecastDbPathProxy:
    _override: Optional[Any] = None

    def set_override(self, path: Optional[Any]) -> None:
        self._override = path

    def _path(self) -> Path:
        if self._override is not None:
            return Path(self._override)
        try:
            from routes.helpers import get_current_db_path
            return get_current_db_path()
        except Exception:
            from config import get_db_path_for_universe
            return get_db_path_for_universe()

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return f"<ForecastDbPathProxy: {self._path()}>"

    def exists(self) -> bool:
        return self._path().exists()

    @property
    def parent(self) -> Path:
        return self._path().parent


DB_PATH = _ForecastDbPathProxy()


def get_db_path() -> Path:
    """Returns active database path, honoring any temporary forecast_engine overrides."""
    fe = sys.modules.get("forecast_engine")
    if fe and hasattr(fe, "DB_PATH") and not isinstance(fe.DB_PATH, _ForecastDbPathProxy):
        return Path(fe.DB_PATH)
    return DB_PATH._path()


from forecast.storage_education import (
    load_children_edu_reserves,
    load_children_k12_tuition,
    get_child_ledger_expense_for_year,
    child_has_tuition_ledger,
)



def load_historical_forecast_actuals(
    family_id: int = 0,
    mortgage_annual_service: float = 0.0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Loads historical net worth ribbon (2018-2025) and cash flow actuals for continuous forecasting.
    Loads encrypted actuals from database if present (keyed by 'historical_forecast_actuals').
    Never hardcodes personal financials, PII, or assumes family_id == 1.
    """
    active_db = resolve_db_path(get_db_path(), family_id=family_id)
    if not family_id or not active_db.exists():
        return [], []

    try:
        stored = security.db_load_encrypted(active_db, "historical_forecast_actuals", family_id=family_id)
        if stored and isinstance(stored, dict):
            ribbon = list(stored.get("historical_ribbon", []))
            raw_cf = stored.get("historical_cash_flow_series", [])
            m_hist_svc = round(mortgage_annual_service, 2)
            cash_flows = []
            for item in raw_cf:
                c = dict(item)
                if "mortgage_debt_service" in c and m_hist_svc > 0:
                    c["mortgage_debt_service"] = m_hist_svc
                    living = float(c.get("living_core", 0.0))
                    travel = float(c.get("travel_gogo", 0.0))
                    gifting = float(c.get("gifting", 0.0))
                    events_outflow = float(c.get("events_outflow", 0.0))
                    outflow = living + travel + gifting + events_outflow + m_hist_svc
                    c["total_outflow"] = round(outflow, 2)
                    c["net_cash_flow"] = round(float(c.get("total_inflow", 0.0)) - outflow, 2)
                cash_flows.append(c)
            return ribbon, cash_flows
    except Exception:
        pass

    return [], []


def load_scenario_state(family_id: int = 0, force_resync: bool = False, persist_repairs: bool = False) -> Dict[str, Any]:
    """Loads complete scenario and event state from normalized relational tables."""
    import db
    active_db = resolve_db_path(get_db_path(), family_id=family_id)
    if active_db.exists():
        security.init_db(active_db)
    state = db.scenarios.get_scenario_state(family_id=family_id, db_path=active_db)

    # Lazy-import event builders to avoid circular import loops
    from .presets import get_default_event_catalog, get_default_scenarios

    had_load_error = bool(isinstance(state, dict) and state.get("_load_error"))
    if not state or force_resync or not state.get("events") or not state.get("scenarios"):
        state = {
            "events": get_default_event_catalog(family_id=family_id),
            "scenarios": get_default_scenarios(family_id=family_id),
            "active_scenario_id": "scen_baseline",
            "equity_growth_preset": "moderate",
            "view_mode": "real",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if family_id and (not had_load_error or force_resync):
            security.init_db(active_db)
            db.scenarios.save_scenario_state(family_id=family_id, state=state, db_path=active_db, invalidate_cache=False)
    else:
        # Clean out legacy presets from main UI (scen_a, scen_b, scen_c, scen_d) so user only sees active scenarios
        legacy_presets = {"scen_a", "scen_b", "scen_c", "scen_d"}
        cleaned = [s for s in state.get("scenarios", []) if s.get("id") not in legacy_presets]
        if not cleaned:
            cleaned = get_default_scenarios(family_id=family_id)

        # Ensure all default events exist in state["events"] (e.g. per-child K-12 and college events)
        k12_pre = load_children_k12_tuition(family_id=family_id)
        edu_pre = load_children_edu_reserves(family_id=family_id)
        defaults = get_default_event_catalog(family_id=family_id, children_k12=k12_pre, children_edu=edu_pre)
        added = False

        # 1. Identify valid dynamic event IDs for this family from defaults
        valid_edu_ids = {
            d["id"] for d in defaults
            if d.get("category") in ("education", "college") or d["id"].startswith("evt_k12_") or d["id"].startswith("evt_college_")
        }
        valid_equity_ids = {
            d["id"] for d in defaults
            if d.get("category") in ("company_equity",)
        }

        # 2. Prune invalid/foreign child education events (from other families or deleted children)
        invalid_edu_ids = {
            e["id"] for e in state.get("events", [])
            if (
                e.get("category") in ("education", "college")
                or e.get("id", "").startswith("evt_k12_")
                or e.get("id", "").startswith("evt_college_")
                or e.get("child_user_id") is not None
                or e.get("child_name") is not None
            )
            and e.get("id") not in valid_edu_ids
        }

        # Also purge any legacy equity event or orphaned equity grants not in active family
        invalid_equity_ids = set()
        for e in state.get("events", []):
            eid = e.get("id", "")
            if eid.endswith("_exercise_custom") and eid != "evt_company_equity_exercise_custom":
                invalid_equity_ids.add(eid)
            elif eid.startswith("evt_equity_") and valid_equity_ids and eid not in valid_equity_ids:
                invalid_equity_ids.add(eid)

        invalid_event_ids = invalid_edu_ids | invalid_equity_ids

        if invalid_event_ids:
            state["events"] = [e for e in state.get("events", []) if e.get("id") not in invalid_event_ids]
            added = True

        # 3. Ensure all default events exist in state["events"] and backfill missing default icons
        existing_by_id = {e["id"]: e for e in state.get("events", []) if "id" in e}
        existing_ids = set(existing_by_id.keys())
        for d in defaults:
            if d["id"] not in existing_ids:
                state["events"].append(d)
                existing_ids.add(d["id"])
                existing_by_id[d["id"]] = d
                added = True
            else:
                ex_ev = existing_by_id[d["id"]]
                if not ex_ev.get("icon") and d.get("icon"):
                    ex_ev["icon"] = d["icon"]
                    added = True

        # 4. Prune removed/invalid event IDs from all scenarios
        for s in cleaned:
            s_evts = s.setdefault("event_ids", [])
            orig_len = len(s_evts)
            s["event_ids"] = [
                ("evt_company_equity_exercise_custom" if eid.endswith("_exercise_custom") else eid)
                for eid in s_evts
                if eid not in invalid_event_ids
            ]
            if len(s["event_ids"]) != orig_len:
                added = True

            if "added_event_ids" in s:
                orig_add_len = len(s["added_event_ids"])
                s["added_event_ids"] = [eid for eid in s["added_event_ids"] if eid not in invalid_event_ids]
                if len(s["added_event_ids"]) != orig_add_len:
                    added = True
            if "excluded_event_ids" in s:
                orig_exc_len = len(s["excluded_event_ids"])
                s["excluded_event_ids"] = [eid for eid in s["excluded_event_ids"] if eid not in invalid_event_ids]
                if len(s["excluded_event_ids"]) != orig_exc_len:
                    added = True

        # 5. Ensure baseline plan has updated per-child k12 and college events
        def_base = get_default_scenarios(family_id=family_id, children_k12=k12_pre, children_edu=edu_pre)[0]
        def_base_events = def_base.get("event_ids", [])

        baseline = next((s for s in cleaned if s.get("id") == "scen_baseline"), None)
        if baseline:
            # If the household has no children, purge generic childless baseline fallback events
            if not k12_pre and "evt_k12_education" in baseline.get("event_ids", []):
                baseline["event_ids"].remove("evt_k12_education")
                added = True
            if not edu_pre and "evt_college_undergrad" in baseline.get("event_ids", []):
                baseline["event_ids"].remove("evt_college_undergrad")
                added = True

            # If the household has no gift recipients, purge legacy fallback gifting
            has_gifting = False
            if family_id and active_db.exists():
                from db.gifting import count_gift_recipients
                has_gifting = bool(count_gift_recipients(family_id=family_id, db_path=active_db) > 0)
            if not has_gifting and "evt_family_gifting" in baseline.get("event_ids", []):
                baseline["event_ids"] = [eid for eid in baseline["event_ids"] if eid != "evt_family_gifting"]
                added = True

            # Update baseline description if it was using the default multi-outflow description
            if not k12_pre and not edu_pre and not has_gifting:
                if "per-child K-12 tuition" in baseline.get("description", ""):
                    baseline["description"] = def_base.get("description", "Current baseline trajectory without early option exercise.")
                    added = True

            for bid in def_base_events:
                if bid not in baseline.setdefault("event_ids", []):
                    baseline["event_ids"].append(bid)
                    added = True

        _legacy_scenario_colors = {
            "#3b82f6": "#1D4ED8",
            "#2563eb": "#1D4ED8",
            "#7c3aed": "#0284C7",
            "#8b5cf6": "#0284C7",
            "#a855f7": "#0D9488",
            "#06b6d4": "#0284C7",
            "#0ea5e9": "#0284C7",
            "#10b981": "#059669",
            "#22c55e": "#059669",
            "#14b8a6": "#0D9488",
            "#f59e0b": "#D97706",
            "#f97316": "#D97706",
            "#e11d48": "#059669",
            "#ef4444": "#C75D6E",
            "#f43f5e": "#C75D6E",
            "#ec4899": "#0D9488",
        }
        for s in cleaned:
            raw_c = str(s.get("color") or "").strip().lower()
            if raw_c in _legacy_scenario_colors:
                s["color"] = _legacy_scenario_colors[raw_c]
                added = True

        if added or len(cleaned) != len(state.get("scenarios", [])):
            state["scenarios"] = cleaned
            if state.get("active_scenario_id") in legacy_presets:
                state["active_scenario_id"] = "scen_baseline"
            if family_id and (added and persist_repairs):
                db.scenarios.save_scenario_state(family_id=family_id, state=state, db_path=active_db, invalidate_cache=False)
    return state


def save_scenario_state(state: Dict[str, Any], family_id: int = 0, *, invalidate_cache: bool = True) -> None:
    """Saves complete scenario and event state to normalized relational tables."""
    import db
    active_db = resolve_db_path(get_db_path(), family_id=family_id)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    if family_id:
        security.init_db(active_db)
        db.scenarios.save_scenario_state(
            family_id=family_id,
            state=state,
            db_path=active_db,
            invalidate_cache=invalidate_cache,
        )

