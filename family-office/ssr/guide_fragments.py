"""View-model for the page-guide drawer: resolves a section id (with aliases) to its catalog entry;
the author-written markup strings are marked trusted (Markup) here so templates never need `| safe`."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from ssr.guide_content import GUIDE_DATA

DEFAULT_SECTION = "section-scenarios"
SECTION_ALIASES = {"section-withholding": "section-compensation", "section-transcripts": "section-compensation"}


def build_guide_vm(section_id: str) -> dict[str, Any]:
    """Returns the catalog entry for `section_id`, falling back to the forecasting guide for unknown sections."""
    resolved = SECTION_ALIASES.get(section_id, section_id)
    if resolved not in GUIDE_DATA:
        resolved = DEFAULT_SECTION
    entry = GUIDE_DATA[resolved]
    model = entry["mentalModel"]
    return {
        "section_id": resolved,
        **entry,
        "mentalModel": {**model, "text": Markup(model["text"])},
        "steps": [{**step, "text": Markup(step["text"])} for step in entry.get("steps", [])],
        "calculations": [Markup(rule) for rule in entry.get("calculations", [])],
    }
