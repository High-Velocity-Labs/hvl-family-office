"""
forecast/plan_run_cache.py: Each plan's forecast run, cached under a digest of every input to that run.

The household forecast cache (forecast/cache.py) is tied to the household's state version, and every save bumps it,
so switching one overlay off reran every plan. A plan's own run (its year-by-year simulation and its earliest-
sustainable-retirement search) is a pure function of the keyword arguments the orchestrator passes: the household
context it gets carries everything else the simulation needs, the tuition ledger included (loaded), so nothing is
read from the database during the run (tests/test_plan_run_cache.py holds this). So each run is keyed by a SHA-256
of those arguments alone. A changed input is a new key and nothing here is ever invalidated; the same inputs give
the same run for any household, so a hit is correct by construction. Toggling a plan back to an earlier state finds
its earlier runs.

Entries live in `hvl_common.db.TwoTierCache`'s L1 memory only, as pickles (so callers can never mutate a cached run,
and the byte bound counts each run's exact size), bounded by count and bytes; a deploy or worker restart starts empty.
A run is computed once per key: concurrent forecasts asking for the same run wait for it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pickle
from typing import Any, Callable, Dict, Mapping

from hvl_common.db import TwoTierCache

# Bump when a change to the simulation code must not reuse runs computed before it in a live process.
RUN_SCHEMA = "plan-run-1"

_RUNS = TwoTierCache(max_l1_entries=256, max_l1_bytes=64 * 1024 * 1024)


_PRIMITIVES = (bool, int, float, str, type(None))


def _canonical_key(key: Any) -> str:
    """A mapping key as a string that keeps its type (`1` and `"1"` stay distinct)."""
    if isinstance(key, _PRIMITIVES) or (isinstance(key, tuple) and all(isinstance(k, _PRIMITIVES) for k in key)):
        return repr(key)
    raise TypeError(f"plan run input key of type {type(key).__name__} has no canonical form")


def _canonical(value: Any) -> Any:
    """A JSON-stable form of a run input (dataclasses as dicts, mappings keyed by typed strings), complete: every
    value it keeps is the input's own, so two inputs share a form only when they are equal."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, Mapping):
        return {_canonical_key(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_canonical(v) for v in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, _PRIMITIVES):
        return value
    # A repr could leave out state and let two different inputs share a key; a new input type must say how it hashes.
    raise TypeError(f"plan run input of type {type(value).__name__} has no canonical form")


def run_key(run_inputs: Mapping[str, Any]) -> str:
    """The key of one plan's run: a digest of its exact inputs."""
    raw = json.dumps({"schema": RUN_SCHEMA, "run": _canonical(run_inputs)}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_or_run(key: str, run_fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """A private copy of the run cached under `key`, else `run_fn()`'s run, cached (a copy: later changes to the
    caller's objects do not reach the cache). The key is the run's inputs, so the stamp is empty."""
    blob = _RUNS.get_or_load(
        "plan_run", key, lambda: pickle.dumps(run_fn(), protocol=pickle.HIGHEST_PROTOCOL), stamp_fn=lambda: ()
    )
    return pickle.loads(blob)


def clear() -> None:
    """Empties the cache (tests)."""
    _RUNS.clear_l1()
