"""Fixtures V and W of the consistency-value PRD §3 (E4b part 7, unit 2). Test-only.

Spec and context builders for a combine step that declares a consistency source: the spec entry
with its ``match`` steps, and the context ``samples`` key (one url4 broadcast rows text per
member). The expected records are hand-computed in the PRD, never copied from the code's output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from combine_golden_support import builtin_vote_spec
from combine_signal_support import argmax_spec
from combine_support import run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import CombineOutcome

type Samples = Mapping[str, Mapping[int, str]]

V_ENTRY: dict[str, Any] = {
    "source": "consistency",
    "n": 4,
    "temperature": 1.0,
    "match": {
        "extract": {"op": "last_number@1", "args": {}},
        "normalize": {"op": "numeric@1", "args": {}},
    },
}
W_ENTRY: dict[str, Any] = {
    "source": "consistency",
    "n": 3,
    "temperature": 1.0,
    "match": {
        "extract": {"op": "last_line@1", "args": {}},
        "normalize": {"op": "text@1", "args": {}},
    },
}
V_OUTPUTS: dict[str, str] = {"member_1": "so 12", "member_2": "it is 12", "member_3": "maybe 7"}
V_SAMPLES: dict[str, dict[int, str]] = {
    "member_1": {1: "12", 2: "12", 3: "7", 4: "twelve"},
    "member_2": {1: "12", 3: "x 12"},
    "member_3": {},
}
W_OUTPUTS: dict[str, str] = {"member_1": "B", "member_2": "C", "member_3": "A"}
W_SAMPLES: dict[str, dict[int, str]] = {
    "member_1": {1: "A", 2: "B", 3: "b"},
    "member_2": {1: "A", 2: "A", 3: "c d"},
    "member_3": {1: "a", 2: "A.", 3: "A"},
}
V_TALLY: list[dict[str, Any]] = [
    {"value": "12", "score": 2.0, "holders": ["member_1", "member_2"]},
    {"value": "7", "score": 1.0, "holders": ["member_3"]},
]
V_RECORD: list[dict[str, Any]] = [
    {"member_id": "member_1", "matched": 2, "succeeded": 4, "failed": 0},
    {"member_id": "member_2", "matched": 2, "succeeded": 2, "failed": 2},
    {"member_id": "member_3", "matched": None, "succeeded": 0, "failed": 4},
]
V_NO_VOTES_RECORD: list[dict[str, Any]] = [
    {"member_id": "member_1", "matched": None, "succeeded": 4, "failed": 0},
    {"member_id": "member_2", "matched": None, "succeeded": 2, "failed": 2},
    {"member_id": "member_3", "matched": None, "succeeded": 0, "failed": 4},
]
W_RECORD: list[dict[str, Any]] = [
    {"member_id": "member_1", "matched": 2, "succeeded": 3, "failed": 0},
    {"member_id": "member_2", "matched": 0, "succeeded": 3, "failed": 0},
    {"member_id": "member_3", "matched": 3, "succeeded": 3, "failed": 0},
]


def v_spec(**overrides: Any) -> dict[str, Any]:
    """Fixture V: ``builtin_vote_spec(3)`` (last_number, numeric, mode, first_holder) + ``cons``."""
    spec: dict[str, Any] = {**builtin_vote_spec(3), "signals": {"cons": V_ENTRY}}
    spec.update(overrides)
    return spec


def w_spec() -> dict[str, Any]:
    """Fixture W: a pick by the max of ``cons`` (no extract); match ``last_line@1``, ``text@1``."""
    return {**argmax_spec(3, "cons", "max"), "signals": {"cons": W_ENTRY}}


def rows(texts: Mapping[int, str]) -> str:
    """One member's sample panel as url4 writes it: a row per answered sample, in dict order."""
    return json.dumps(
        [
            {"source_position": j, "source_name": f"sample_{j}", "result": text}
            for j, text in texts.items()
        ]
    )


def member_panel(texts: Mapping[int, str]) -> str:
    """A quorum ``panel``: a row per member that answered (1-based positions)."""
    return json.dumps(
        [
            {"source_position": k, "source_name": f"member_{k}", "result": text}
            for k, text in texts.items()
        ]
    )


def context(
    *,
    outputs: Mapping[str, str] | None = None,
    panel: str | None = None,
    samples: Samples | None = None,
) -> str:
    """A combine context in the SDK key order (P9): ``outputs`` or ``panel``, then ``samples``.
    ``samples`` None leaves the key out."""
    body: dict[str, Any] = {"input": "q"}
    if outputs is not None:
        body["outputs"] = dict(outputs)
    if panel is not None:
        body["panel"] = panel
    if samples is not None:
        body["samples"] = {member: rows(texts) for member, texts in samples.items()}
    return json.dumps(body)


def outcome(spec: Mapping[str, Any], context_text: str) -> CombineOutcome:
    """Run the pure combine core with the built-in operators."""
    return run(spec_text(spec), context_text, registry=BUILTIN_OPERATORS)


def wire(result: CombineOutcome) -> dict[str, Any]:
    """The evidence as the JSON wire (aliases, in field order)."""
    return result.evidence.model_dump(mode="json", by_alias=True)


__all__ = [
    "V_ENTRY",
    "V_NO_VOTES_RECORD",
    "V_OUTPUTS",
    "V_RECORD",
    "V_SAMPLES",
    "V_TALLY",
    "W_ENTRY",
    "W_OUTPUTS",
    "W_RECORD",
    "W_SAMPLES",
    "context",
    "member_panel",
    "outcome",
    "rows",
    "v_spec",
    "w_spec",
    "wire",
]
