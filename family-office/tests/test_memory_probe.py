"""`scripts/memory_probe.py`: tells a one-time warm-up step from a per-request leak (#2316)."""

from __future__ import annotations

from app import create_app
from scripts import memory_probe


def test_flat_after_first_render_is_a_step():
    series = [160.0] + [161.0] * 39
    summary = memory_probe.summarize(120.0, series)
    assert summary["first_render_step_mb"] == 40.0
    assert summary["growth_after_warmup_mb"] == 0.0
    assert summary["verdict"] == "step"


def test_steady_rise_per_render_is_creep():
    series = [160.0 + i * 1.0 for i in range(40)]
    summary = memory_probe.summarize(120.0, series)
    assert summary["mb_per_render"] == 1.0
    assert summary["verdict"] == "creep"


def test_too_few_renders_reaches_no_verdict():
    assert memory_probe.summarize(100.0, [150.0 + i for i in range(8)])["verdict"] == "too few renders"
    assert memory_probe.summarize(100.0, [])["verdict"] == "no data"


def test_probe_renders_and_reports_the_series():
    ticks = iter(range(1000))

    def fake_rss() -> float:
        return 100.0 + next(ticks)

    renders = memory_probe.WARMUP_RENDERS + memory_probe.MIN_ROUNDS_AFTER_WARMUP + 1
    result = memory_probe.probe(create_app(), ["/login"], renders, rss_fn=fake_rss, top=3)
    assert result["statuses"] == [200]
    assert len(result["rss_mb"]) == renders
    assert result["summary"]["verdict"] == "creep"  # the fake memory rises 1 MB per round
    assert len(result["growth_sites"]) <= 3
