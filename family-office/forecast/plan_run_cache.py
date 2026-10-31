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

Entries live in process memory (a bounded LRU) as pickles, so callers can never mutate a cached run, and a deploy or
worker restart starts empty.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pickle
import threading
from typing import Any, Dict, Mapping, Optional

import cachetools

# Bump when a change to the simulation code must not reuse runs computed before it in a live process.
RUN_SCHEMA = "plan-run-1"

_RUNS: cachetools.LRUCache = cachetools.LRUCache(maxsize=256)
_LOCK = threading.Lock()


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


def get(key: str) -> Optional[Dict[str, Any]]:
    """A private copy of the cached run under `key`, or None."""
    with _LOCK:
        blob = _RUNS.get(key)
    return pickle.loads(blob) if blob is not None else None


def put(key: str, run: Dict[str, Any]) -> None:
    """Caches a copy of `run`; later changes to the caller's objects do not reach the cache."""
    blob = pickle.dumps(run, protocol=pickle.HIGHEST_PROTOCOL)
    with _LOCK:
        _RUNS[key] = blob


def clear() -> None:
    """Empties the cache (tests)."""
    with _LOCK:
        _RUNS.clear()
