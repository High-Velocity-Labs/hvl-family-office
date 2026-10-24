"""
db/scenarios.py: Normalized SQLAlchemy 2.0 ORM repository for forecast scenarios, events, and active settings.
Operates on `ForecastSettings`, `ForecastScenario`, and `ForecastEvent` with transparent `TypeDecorator`
encryption and automatic `after_commit` cache invalidation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, select, text

from db.models import ForecastEvent, ForecastScenario, ForecastSettings
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)


def get_scenario_state(
    family_id: int = 0,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Loads `{"active_scenario_id": ..., "comparison_scenario_id": ..., "scenarios": [...], "events": [...]}`
    from `forecast_settings`, `forecast_scenarios`, and `forecast_events`.
    Returns `None` if no scenarios exist yet for the family.
    """
    if not family_id:
        return None
    path = resolve_db_path(db_path, family_id=family_id)
    if not path.exists():
        return None

    try:
        with get_orm_session(path, family_id=family_id) as session:
            s_rows = session.scalars(
                select(ForecastScenario)
                .where(ForecastScenario.family_id == family_id)
                .order_by(ForecastScenario.sort_order.asc(), text("rowid ASC"))
            ).all()
            if not s_rows:
                return None

            settings_row = session.get(ForecastSettings, family_id)
            e_rows = session.scalars(
                select(ForecastEvent)
                .where(ForecastEvent.family_id == family_id)
                .order_by(ForecastEvent.sort_order.asc(), text("rowid ASC"))
            ).all()

            scenarios: List[Dict[str, Any]] = []
            top_meta: Dict[str, Any] = {}
            for sr in s_rows:
                if not sr.name_enc and not sr.payload_enc:
                    continue
                scen: Dict[str, Any] = (
                    dict(sr.payload_enc) if isinstance(sr.payload_enc, dict) else {}
                )
                if "_top_meta" in scen and isinstance(scen["_top_meta"], dict):
                    top_meta.update(scen.pop("_top_meta"))
                scen["id"] = str(sr.scenario_id)
                if sr.name_enc:
                    scen["name"] = str(sr.name_enc)
                elif not scen.get("name"):
                    scen["name"] = "Baseline Plan" if sr.is_baseline else str(sr.scenario_id)
                if sr.description_enc:
                    scen["description"] = str(sr.description_enc)
                scen["is_baseline"] = bool(sr.is_baseline)
                scen["color"] = str(sr.color or scen.get("color") or "#3b82f6")
                if isinstance(sr.overrides_enc, dict) and sr.overrides_enc:
                    scen["overrides"] = dict(sr.overrides_enc)
                elif "overrides" not in scen or not isinstance(
                    scen.get("overrides"), dict
                ):
                    scen["overrides"] = {}
                scenarios.append(scen)

            if not scenarios:
                logger.warning(
                    "Forecast scenario rows for family %s could not be decrypted with active key.",
                    family_id,
                )
                return {"_load_error": True, "scenarios": [], "events": []}

            events: List[Dict[str, Any]] = []
            for er in e_rows:
                if not er.name_enc and not er.payload_enc:
                    continue
                evt: Dict[str, Any] = (
                    dict(er.payload_enc) if isinstance(er.payload_enc, dict) else {}
                )
                evt["id"] = str(er.event_id)
                evt["scenario_id"] = str(er.scenario_id or "baseline")
                if er.name_enc:
                    evt["name"] = str(er.name_enc)
                elif not evt.get("name"):
                    evt["name"] = str(er.event_id)
                evt["type"] = str(er.event_type or evt.get("type") or "expense")
                evt["amount"] = float(er.amount_enc or 0.0)
                evt["start_year"] = int(er.start_year or evt.get("start_year") or 2026)
                evt["end_year"] = int(
                    er.end_year or evt.get("end_year") or evt["start_year"]
                )
                evt["enabled"] = bool(er.enabled)
                events.append(evt)

            active_id = (
                str(settings_row.active_scenario_id)
                if settings_row and settings_row.active_scenario_id
                else "scen_baseline"
            )
            comp_id = settings_row.comparison_scenario_id if settings_row else None

            res: Dict[str, Any] = {
                "active_scenario_id": active_id,
                "comparison_scenario_id": comp_id,
                "equity_growth_preset": top_meta.get(
                    "equity_growth_preset", "moderate"
                ),
                "view_mode": top_meta.get("view_mode", "real"),
                "scenarios": scenarios,
                "events": events,
            }
            for k, v in top_meta.items():
                if k not in res:
                    res[k] = v
            return res
    except Exception as e:
        logger.warning(
            "Error reading forecast scenario tables for family %s: %s", family_id, e
        )
        return {"_load_error": True, "scenarios": [], "events": []}


def save_scenario_state(
    family_id: int = 0,
    state: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
    *,
    invalidate_cache: bool = True,
) -> None:
    """Atomically persists scenario state into `forecast_settings`, `forecast_scenarios`, and `forecast_events`."""
    if not family_id or not isinstance(state, dict):
        return

    import config

    scenarios_list = [s for s in (state.get("scenarios") or []) if isinstance(s, dict)]
    events_list = [e for e in (state.get("events") or []) if isinstance(e, dict)]

    active_id = str(state.get("active_scenario_id") or "scen_baseline")
    comp_id = state.get("comparison_scenario_id")
    comp_id_str = str(comp_id) if comp_id else None
    top_meta = {
        k: v
        for k, v in state.items()
        for _ in (0,)
        if k
        not in ("scenarios", "events", "active_scenario_id", "comparison_scenario_id")
    }

    with get_orm_session(
        db_path,
        family_id=family_id,
        commit=True,
        invalidate_cache=invalidate_cache,
    ) as session:
        if invalidate_cache:
            if len(scenarios_list) > config.MAX_SCENARIOS:
                existing_scen_ids = set(
                    session.scalars(
                        select(ForecastScenario.scenario_id).where(ForecastScenario.family_id == family_id)
                    ).all()
                )
                incoming_scen_ids = [
                    str(scen.get("id") or f"scen_{idx}") for idx, scen in enumerate(scenarios_list)
                ]
                if not existing_scen_ids or len(scenarios_list) > len(existing_scen_ids) or any(sid not in existing_scen_ids for sid in incoming_scen_ids):
                    raise ValueError(f"Maximum of {config.MAX_SCENARIOS} scenarios per household reached.")

            if len(events_list) > config.MAX_FORECAST_EVENTS:
                existing_evt_ids = set(
                    session.scalars(
                        select(ForecastEvent.event_id).where(ForecastEvent.family_id == family_id)
                    ).all()
                )
                incoming_evt_ids = [
                    str(evt.get("id") or f"evt_{idx}") for idx, evt in enumerate(events_list)
                ]
                if not existing_evt_ids or len(events_list) > len(existing_evt_ids) or any(eid not in existing_evt_ids for eid in incoming_evt_ids):
                    raise ValueError(f"Maximum of {config.MAX_FORECAST_EVENTS} forecast events per household reached.")

        session.merge(
            ForecastSettings(
                family_id=family_id,
                active_scenario_id=active_id,
                comparison_scenario_id=comp_id_str,
            )
        )
        session.execute(
            delete(ForecastScenario).where(ForecastScenario.family_id == family_id)
        )
        session.execute(
            delete(ForecastEvent).where(ForecastEvent.family_id == family_id)
        )

        scen_by_id: Dict[str, ForecastScenario] = {}
        for idx, scen in enumerate(scenarios_list):
            if not isinstance(scen, dict):
                continue
            scen_copy = dict(scen)
            if idx == 0 and top_meta:
                scen_copy["_top_meta"] = top_meta
            sid = str(scen_copy.get("id") or f"scen_{idx}")
            name = str(scen_copy.get("name") or sid)
            desc = str(scen_copy.get("description") or "")
            is_base = (
                1
                if scen_copy.get("is_baseline")
                or sid in ("baseline", "scen_baseline")
                else 0
            )
            color = str(scen_copy.get("color") or "#3b82f6")
            overrides = (
                scen_copy.get("overrides")
                if isinstance(scen_copy.get("overrides"), dict)
                else {}
            )
            if "spending_guardrail_mode" in scen_copy:
                gm = scen_copy["spending_guardrail_mode"]
                if gm in (None, "", "inherit"):
                    scen_copy["spending_guardrail_mode"] = None
                    overrides.pop("spending_guardrail_mode", None)
                else:
                    norm_gm = str(gm).lower().strip()
                    norm_val = norm_gm if norm_gm in ("moderate", "aggressive") else "off"
                    if not is_base and scen_copy.get("parent_id") and norm_val == "off" and "spending_guardrail_mode" not in overrides:
                        scen_copy["spending_guardrail_mode"] = None
                    else:
                        scen_copy["spending_guardrail_mode"] = norm_val
            scen_by_id[sid] = ForecastScenario(
                family_id=family_id,
                scenario_id=sid,
                name_enc=name,
                description_enc=desc,
                is_baseline=is_base,
                color=color,
                overrides_enc=overrides,
                payload_enc=scen_copy,
                sort_order=idx,
            )
        if scen_by_id:
            session.add_all(scen_by_id.values())

        evt_by_id: Dict[str, ForecastEvent] = {}
        for idx, evt in enumerate(state.get("events") or []):
            if not isinstance(evt, dict):
                continue
            eid = str(evt.get("id") or f"evt_{idx}")
            sid = str(evt.get("scenario_id") or "baseline")
            name = str(evt.get("name") or eid)
            etype = str(evt.get("type") or "expense")
            amt = float(evt.get("amount", 0.0) or 0.0)
            start_yr = int(evt.get("start_year", 2026) or 2026)
            end_yr = int(evt.get("end_year", start_yr) or start_yr)
            enabled = 1 if evt.get("enabled", True) else 0
            evt_by_id[eid] = ForecastEvent(
                family_id=family_id,
                event_id=eid,
                scenario_id=sid,
                name_enc=name,
                event_type=etype,
                amount_enc=amt,
                start_year=start_yr,
                end_year=end_yr,
                enabled=enabled,
                payload_enc=evt,
                sort_order=idx,
            )
        if evt_by_id:
            session.add_all(evt_by_id.values())
