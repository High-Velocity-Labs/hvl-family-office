"""
Household settings on the `families` row: one plain column per setting (alembic 0010).

Each write is one `UPDATE` of only the columns it changes, so two writers of different settings never undo each
other; the `families` row then syncs to the peer database (`db.session._sync_auth_records_to_peer_db`). Reads go
through the entity cache (`db.store`, entity `family_settings`), which a write here patches in place.

The dashboard layout columns hold JSON lists of widget / chart ids, NULL until the household changes the default.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from sqlalchemy import select, text, update

from db import store as db_store
from db.models import Family
from db.session import get_orm_session, resolve_db_path

logger = logging.getLogger(__name__)

FLAG_COLUMNS = ("onboarding_completed", "onboarding_dismissed", "onboarding_wizard_dismissed")
LAYOUT_COLUMNS = ("overview_widgets", "scenarios_widgets", "collapsed_charts")
TEXT_COLUMNS = ("primary_state", "tax_filing_status")

# What a household with no `families` row reads.
_DEFAULTS: Dict[str, Any] = {
    "primary_state": "",
    "tax_filing_status": "MFJ",
    **{c: False for c in FLAG_COLUMNS},
    **{c: None for c in LAYOUT_COLUMNS},
}

# Toggles one chart id in `collapsed_charts` inside the UPDATE itself, so two charts collapsed at once both stay.
_TOGGLE_COLLAPSED_CHART = text(
    "(SELECT json_group_array(value) FROM ("
    "SELECT value FROM json_each(COALESCE(families.collapsed_charts, '[]')) WHERE value != :chart_id "
    "UNION SELECT :chart_id WHERE :collapsed ORDER BY 1))"
)


def _layout_list(raw: Optional[str], fid: int, column: str) -> Optional[List[str]]:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("families.%s of household %s is not JSON; reading the default layout", column, fid)
        return None
    if not isinstance(parsed, list):
        return None
    return [str(v).strip() for v in parsed if str(v).strip()]


def _read(path: Path, fid: int) -> Dict[str, Any]:
    cols = [getattr(Family, c) for c in (*TEXT_COLUMNS, *FLAG_COLUMNS, *LAYOUT_COLUMNS)]
    with get_orm_session(path, family_id=fid) as session:
        row = session.execute(select(*cols).where(Family.family_id == fid)).first()
    if row is None:
        return dict(_DEFAULTS)
    values = row._mapping
    out: Dict[str, Any] = {c: str(values[c] or "") for c in TEXT_COLUMNS}
    out["tax_filing_status"] = out["tax_filing_status"] or "MFJ"
    out.update({c: bool(values[c]) for c in FLAG_COLUMNS})
    out.update({c: _layout_list(values[c], fid, c) for c in LAYOUT_COLUMNS})
    return out


def get_family_settings(family_id: int = 0, db_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """The household's settings (state, filing status, onboarding flags, layout lists); defaults for no household."""
    fid = int(family_id or 0)
    if fid <= 0:
        return dict(_DEFAULTS)
    path = resolve_db_path(db_path, family_id=fid)
    return db_store.get_or_load_entity(fid, "family_settings", lambda p: _read(p, fid), db_path=path, clone=True)


def _write(fid: int, path: Path, values: Dict[str, Any]) -> Dict[str, Any]:
    def _commit() -> Dict[str, Any]:
        with get_orm_session(path, family_id=fid, commit=True) as session:
            session.execute(update(Family).where(Family.family_id == fid).values(**values))
        return _read(path, fid)

    # The other entities read from `families` (the deletion quarantine) read none of these columns.
    return db_store.write_through(
        fid,
        path,
        ("families",),
        _commit,
        {"family_settings": lambda _kept, stored: stored, "deletion_status": db_store.unchanged},
    )


def set_onboarding_flags(
    family_id: int, flags: Dict[str, bool], db_path: Optional[Union[str, Path]] = None
) -> Dict[str, Any]:
    """Sets the given onboarding flags (names in `FLAG_COLUMNS`) and returns the settings as stored."""
    fid = int(family_id or 0)
    unknown = set(flags) - set(FLAG_COLUMNS)
    if fid <= 0 or unknown or not flags:
        raise ValueError(f"onboarding flags need a household and names from {FLAG_COLUMNS}, not {sorted(unknown)}")
    return _write(fid, resolve_db_path(db_path, family_id=fid), {k: 1 if v else 0 for k, v in flags.items()})


def save_widget_layout(
    family_id: int, column: str, widget_ids: Iterable[str], db_path: Optional[Union[str, Path]] = None
) -> Dict[str, Any]:
    """Saves one dashboard's whole widget list (`overview_widgets` / `scenarios_widgets`)."""
    fid = int(family_id or 0)
    if fid <= 0 or column not in ("overview_widgets", "scenarios_widgets"):
        raise ValueError(f"a widget layout needs a household and a layout column, not {column!r}")
    ids = [str(w) for w in widget_ids]
    return _write(fid, resolve_db_path(db_path, family_id=fid), {column: json.dumps(ids)})


def set_chart_collapsed(
    family_id: int, chart_id: str, collapsed: bool, db_path: Optional[Union[str, Path]] = None
) -> Dict[str, Any]:
    """Adds or removes one chart id in `collapsed_charts` and returns the settings as stored."""
    fid = int(family_id or 0)
    c_id = str(chart_id).strip()
    if fid <= 0 or not c_id:
        raise ValueError("collapsing a chart needs a household and a chart id")
    expr = _TOGGLE_COLLAPSED_CHART.bindparams(chart_id=c_id, collapsed=1 if collapsed else 0)
    return _write(fid, resolve_db_path(db_path, family_id=fid), {"collapsed_charts": expr})


__all__ = [
    "FLAG_COLUMNS",
    "LAYOUT_COLUMNS",
    "get_family_settings",
    "save_widget_layout",
    "set_chart_collapsed",
    "set_onboarding_flags",
]
