"""
Background job lifecycle as an explicit finite state machine.

    queued -> processing -> completed
       |          |
       +----------+----> failed

`completed` and `failed` are terminal. Pollers keep one stable public vocabulary
(`processing` | `completed` | `failed`): both `queued` and `processing` surface as `processing`,
and the precise lifecycle state is exposed as the record's `phase`.
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Dict, FrozenSet

QUEUED = "queued"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"

ACTIVE_STATES: FrozenSet[str] = frozenset({QUEUED, PROCESSING})
TERMINAL_STATES: FrozenSet[str] = frozenset({COMPLETED, FAILED})

_ALLOWED: Dict[str, FrozenSet[str]] = {
    QUEUED: frozenset({PROCESSING, FAILED}),
    PROCESSING: frozenset({COMPLETED, FAILED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
}


class IllegalJobTransition(ValueError):
    """Raised when a job is moved along an edge the lifecycle FSM does not allow."""


def require_transition(job_id: str, prev: str, new: str) -> None:
    if prev not in _ALLOWED:
        raise IllegalJobTransition(f"Job {job_id}: unknown state {prev!r}")
    if new not in _ALLOWED:
        raise IllegalJobTransition(f"Job {job_id}: unknown target state {new!r}")
    if new not in _ALLOWED[prev]:
        raise IllegalJobTransition(f"Job {job_id}: illegal transition {prev} -> {new}")


def public_status(state: str) -> str:
    """Maps a lifecycle state to the status string pollers have always seen."""
    return PROCESSING if state in ACTIVE_STATES else state


_boot_ids: Dict[int, str] = {}
_boot_lock = threading.Lock()


def process_boot_id() -> str:
    """
    Identifies this process incarnation. Keyed by pid so a forked gunicorn worker (preload_app)
    gets its own id rather than inheriting the master's.
    """
    pid = os.getpid()
    with _boot_lock:
        boot = _boot_ids.get(pid)
        if boot is None:
            boot = uuid.uuid4().hex
            _boot_ids[pid] = boot
        return boot
