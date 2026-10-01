"""Scenarios of the pick and merge reducers for the hash-seed test (OME-1289 E4a, unit 9; FW-3).

Test-only. Each function returns one string (the answer, then the evidence JSON) and is run in a
fresh interpreter under many ``PYTHONHASHSEED`` values by ``test_combine_fields_determinism.py``.
"""

from __future__ import annotations

import json
from typing import Any

from combine_support import context_text, run, spec_text, vote_spec

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


def _step(op_id: str, **args: Any) -> dict[str, Any]:
    return {"op": op_id, "args": args}


def _bytes_of(spec: dict[str, Any], signals: dict[str, str] | None = None) -> str:
    outcome = run(
        spec_text(spec),
        context_text(list(_MEMBERS), signals),
        registry=BUILTIN_OPERATORS,
    )
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def merge_scenario() -> str:
    """Output and evidence JSON of a merge that uses all five rules."""
    spec = vote_spec(
        _COUNT,
        reducer="merge",
        extract=_step("json_object@1"),
        normalize=None,
        reduce=_step("field_rules@1", fields=_RULES),
        select=_step("built@1"),
    )
    return _bytes_of(spec, {"writer_summary": "A summary \u00e9."})


def pick_scenario() -> str:
    """Output and evidence JSON of a pick with four members tied at the top."""
    spec = vote_spec(
        _COUNT,
        reducer="pick",
        extract=_step("json_field@1", path="confidence"),
        normalize=_step("numeric@1"),
        reduce=_step("values@1", field="confidence"),
        select=_step("by_field@1", order="max"),
    )
    return _bytes_of(spec)


def projection_scenario() -> str:
    """Output and evidence JSON of the projection a writer model would read."""
    spec = vote_spec(
        _COUNT,
        reducer="project",
        extract=_step("json_object@1"),
        normalize=None,
        reduce=_step("project_field@1", field="tags"),
        select=_step("built@1"),
    )
    return _bytes_of(spec)


__all__ = [
    "merge_scenario",
    "pick_scenario",
    "projection_scenario",
]
