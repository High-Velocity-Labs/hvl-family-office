"""
Memory probe: renders pages over and over in one process and reports how its memory moves (#2316).

Use it when the memory watchdog files a "memory creep" card for family-office. It tells a one-time warm-up step (the
first heavy render loads lazy imports, engines and caches, then memory stays flat) from a real per-request leak (memory
keeps rising with every render), and for a leak it lists the Python allocations that grew most, by traceback.

    python3 scripts/memory_probe.py                                  # 40 renders of the demo dashboard
    python3 scripts/memory_probe.py --renders 60 --path "/?demo=1" --path /fragments/scenarios

It runs the app in-process (Flask test client) on a fresh temporary data directory by default, so it seeds its own
demo universe and never touches real household data. `--data-dir` reuses a directory (e.g. one already seeded, to
leave the seeding out of the first render).
"""

from __future__ import annotations

import argparse
import gc
import os
import shutil
import subprocess
import sys
import tempfile
import tracemalloc
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DEFAULT_PATHS = ("/?demo=1",)
DEFAULT_PERSONA = "taylor"
WARMUP_RENDERS = 5  # renders before the baseline: the first ones load lazy imports, engines and caches
MIN_ROUNDS_AFTER_WARMUP = 10  # fewer rounds than this measure allocator noise, not a trend
CREEP_MB_PER_RENDER = 0.25  # steady growth past this after warm-up reads as a per-request leak


def current_rss_mb() -> float:
    """This process's resident memory in MB (`ps` works on macOS and Linux alike)."""
    out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())])
    return int(out.strip()) / 1024.0


def summarize(boot_mb: float, rss_mb: Sequence[float], warmup: int = WARMUP_RENDERS) -> Dict[str, Any]:
    """The step and the after-warm-up growth of one probe run.

    `rss_mb[i]` is the memory after render round `i`. The step is what the first round added over `boot_mb`; the
    growth is from the end of warm-up to the last round, also per round, which decides `verdict`."""
    if not rss_mb:
        return {"first_render_step_mb": 0.0, "growth_after_warmup_mb": 0.0, "mb_per_render": 0.0, "verdict": "no data"}
    base_idx = min(max(0, int(warmup)), len(rss_mb) - 1)
    rounds = len(rss_mb) - 1 - base_idx
    growth = rss_mb[-1] - rss_mb[base_idx]
    per_render = growth / rounds if rounds > 0 else 0.0
    if rounds < MIN_ROUNDS_AFTER_WARMUP:
        verdict = "too few renders"
    elif per_render > CREEP_MB_PER_RENDER:
        verdict = "creep"
    else:
        verdict = "step"
    return {
        "first_render_step_mb": round(rss_mb[0] - boot_mb, 1),
        "growth_after_warmup_mb": round(growth, 1),
        "mb_per_render": round(per_render, 3),
        "verdict": verdict,
    }


def probe(
    app: Any,
    paths: Sequence[str],
    renders: int,
    *,
    persona: str = DEFAULT_PERSONA,
    top: int = 8,
    rss_fn: Callable[[], float] = current_rss_mb,
) -> Dict[str, Any]:
    """Renders every path `renders` times on one demo session and returns the memory series, its summary and the
    allocations that grew most after warm-up (traced from the end of warm-up only, so the trace costs no warm-up)."""
    client = app.test_client()
    boot_mb = rss_fn()
    client.get(f"/demo/{persona}", follow_redirects=True)
    rss_series: List[float] = []
    statuses: List[int] = []
    snap0 = snap1 = None
    try:
        for i in range(max(1, int(renders))):
            for path in paths:
                statuses.append(client.get(path, follow_redirects=True).status_code)
            if i == WARMUP_RENDERS:
                gc.collect()
                tracemalloc.start(25)
                snap0 = tracemalloc.take_snapshot()
            rss_series.append(rss_fn())
        if snap0 is not None:
            gc.collect()
            snap1 = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()  # a failed render never leaves tracing on for the rest of the process
    growth_sites: List[Dict[str, Any]] = []
    if snap0 is not None and snap1 is not None:
        for stat in snap1.compare_to(snap0, "traceback")[: max(0, int(top))]:
            growth_sites.append({
                "kb": round(stat.size_diff / 1024.0, 1),
                "blocks": stat.count_diff,
                "where": [f"{fr.filename}:{fr.lineno}" for fr in stat.traceback][-6:],
            })
    return {
        "boot_mb": round(boot_mb, 1),
        "rss_mb": [round(v, 1) for v in rss_series],
        "statuses": sorted(set(statuses)),
        "summary": summarize(boot_mb, rss_series),
        "growth_sites": growth_sites,
    }


def _print_report(result: Dict[str, Any], paths: Sequence[str]) -> None:
    summary = result["summary"]
    print(f"paths: {', '.join(paths)}   statuses: {result['statuses']}")
    print(
        f"boot {result['boot_mb']} MB -> after first render {result['rss_mb'][0]} MB"
        f" -> last {result['rss_mb'][-1]} MB"
    )
    print(
        f"first-render step {summary['first_render_step_mb']} MB; after warm-up "
        f"{summary['growth_after_warmup_mb']} MB ({summary['mb_per_render']} MB/render): {summary['verdict']}"
    )
    print("memory per round:", " ".join(str(v) for v in result["rss_mb"]))
    for site in result["growth_sites"]:
        print(f"  +{site['kb']} KB in {site['blocks']} blocks")
        for frame in site["where"]:
            print(f"      {frame}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render pages repeatedly and report how memory moves.")
    parser.add_argument("--renders", type=int, default=40, help="render rounds (default 40)")
    parser.add_argument("--path", action="append", dest="paths", help="page to render each round (repeatable)")
    parser.add_argument("--persona", default=DEFAULT_PERSONA, help="demo persona slug for the session")
    parser.add_argument(
        "--data-dir",
        help="scratch data directory to reuse, e.g. an already seeded probe run (default: a fresh temporary one;"
        " never the real data folder: the probe writes the demo universe there)",
    )
    parser.add_argument("--top", type=int, default=8, help="allocation growth sites to list")
    args = parser.parse_args(argv)

    temp_dir = None if args.data_dir else tempfile.mkdtemp(prefix="fo_memory_probe_")
    data_dir = Path(args.data_dir or temp_dir).expanduser().resolve()
    os.environ["FAMILY_OFFICE_DATA_DIR"] = str(data_dir)
    os.environ["HVL_RATELIMIT_CACHE_DIR"] = str(data_dir / "ratelimit_cache")  # never beside the checkout
    from app import create_app  # after the data directory is set: config reads it on first use

    paths = tuple(args.paths or DEFAULT_PATHS)
    try:
        result = probe(create_app(), paths, args.renders, persona=args.persona, top=args.top)
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"data dir: {data_dir}" + (" (temporary, removed)" if temp_dir else ""))
    _print_report(result, paths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
