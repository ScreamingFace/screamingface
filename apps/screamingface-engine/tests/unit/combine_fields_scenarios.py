"""Scenarios of the pick and merge reducers for the hash-seed test (OME-1289 E4a, unit 9; FW-3).

Test-only. Each function returns one string (the answer, then the evidence JSON) and is run in a
fresh interpreter under many ``PYTHONHASHSEED`` values by ``test_combine_fields_determinism.py``.
"""

from __future__ import annotations

import json
from typing import Any

from combine_fields_support import merge_spec, pick_spec, project_spec, step
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS

_COUNT = 12
_WORDS = ("caf\u00e9", "Caf\u00e9.", "\u4e2d\u6587", "naïve", "NAÏVE", "x")
# Members carry undeclared unicode keys (dropped by the merge) and list values that overlap.
_MEMBERS = tuple(
    json.dumps(
        {
            "answer": _WORDS[index % len(_WORDS)],
            "score": (index * 7) % 5,
            "source": f"src \U0001f600 {index}",
            "tags": [_WORDS[index % 4], _WORDS[(index + 1) % 4], f"t{index % 3}"],
            "\u00fcnused": {"k": index},
            "confidence": 0.5 if index % 3 else 0.9,
        },
        ensure_ascii=False,
    )
    for index in range(_COUNT)
)
_RULES = [
    {"field": "answer", "rule": "majority", "normalize": "text"},
    {"field": "score", "rule": "max"},
    {"field": "source", "rule": "from_member", "member": "member_5"},
    {"field": "tags", "rule": "union", "normalize": "text"},
    {"field": "summary", "rule": "model"},
]


def _bytes_of(spec: dict[str, Any], signals: dict[str, str] | None = None) -> str:
    outcome = run(
        spec_text(spec),
        context_text(list(_MEMBERS), signals),
        registry=BUILTIN_OPERATORS,
    )
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def merge_scenario() -> str:
    """Output and evidence JSON of a merge that uses all five rules."""
    return _bytes_of(merge_spec(_COUNT, _RULES), {"writer_summary": "A summary \u00e9."})


def pick_scenario() -> str:
    """Output and evidence JSON of a pick with four members tied at the top."""
    return _bytes_of(pick_spec(_COUNT, step("by_field@1", order="max")))


def projection_scenario() -> str:
    """Output and evidence JSON of the projection a writer model would read."""
    return _bytes_of(project_spec(_COUNT, "tags"))


__all__ = [
    "merge_scenario",
    "pick_scenario",
    "projection_scenario",
]
