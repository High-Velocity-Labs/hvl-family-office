"""SSR builders raise on a failed section to the route error handler; they never render a blank section."""

import pytest

import ssr.planning as planning
import ssr.widgets_charts as widgets_charts


class _LedgerDown(RuntimeError):
    pass


class _StrictLedger:
    """Stateful double: records calls and raises on every load, as a broken ledger would."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise _LedgerDown("gifting ledger unavailable")


def test_gifting_failure_raises_instead_of_empty_section(monkeypatch):
    ledger = _StrictLedger()
    monkeypatch.setattr(planning, "load_gifting_data", ledger)
    with pytest.raises(_LedgerDown):
        planning.build_ssr_gifting(family_id=7)
    assert ledger.calls == 1


def test_collapsed_chart_read_failure_raises(monkeypatch):
    def _boom(*args, **kwargs):
        raise _LedgerDown("family read failed")

    monkeypatch.setattr(widgets_charts.family_settings, "get_family_settings", _boom)
    with pytest.raises(_LedgerDown):
        widgets_charts.get_collapsed_charts(family_id=7)
