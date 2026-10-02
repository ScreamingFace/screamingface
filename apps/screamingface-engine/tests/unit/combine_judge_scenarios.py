"""Scenarios of the judge reducers for the hash-seed test (OME-1289 E4a, unit 8; FW-3).

Test-only. Each function returns one string (the answer, then the evidence JSON) and is run in a
fresh interpreter under many ``PYTHONHASHSEED`` values by ``test_combine_judge_determinism.py``.
"""

from __future__ import annotations

from typing import Literal

from combine_flow_support import judge_spec
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import canonical_json

_TEXTS = tuple(
    f"member {index}: caf\u00e9 \u4e2d\u6587 \U0001f600 {index * 7}" for index in range(1, 13)
)
# Three members share the top score; the answer must be the first of them in author order.
_TIED_SCORES = {f"member_{index}": 0.25 for index in range(1, 13)}
_TIED_SCORES.update({"member_4": 0.9, "member_8": 0.9, "member_11": 0.9})


# Twelve members whose last numbers fall into three values; the judge scores tie two tally rows.
_WEIGHT_TEXTS = tuple(
    f"member {index}: caf\u00e9 \u4e2d\u6587 {index % 3}" for index in range(1, 13)
)
_WEIGHT_SCORES = {f"member_{index}": (0.125 if index % 3 == 2 else 0.25) for index in range(1, 13)}


def _bytes_of(returns: Literal["label", "scores"], reply: str) -> str:
    spec = judge_spec(len(_TEXTS), returns)
    outcome = run(
        spec_text(spec),
        context_text(list(_TEXTS), {"judge": reply}),
        registry=BUILTIN_OPERATORS,
    )
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def scores_scenario() -> str:
    """Output and evidence JSON of a scores judge with three tied top scores."""
    reply = canonical_json(_TIED_SCORES)
    return _bytes_of("scores", reply)


def label_scenario() -> str:
    """Output and evidence JSON of a label judge."""
    return _bytes_of("label", " member_7\n")


def score_weight_scenario() -> str:
    """Output and evidence JSON of a vote weighted by ``score:judge`` whose two top rows tie."""
    spec = vote_spec(
        len(_WEIGHT_TEXTS),
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "max_weight_holder@1", "args": {}},
        weights={"signal": "score:judge"},
    )
    outcome = run(
        spec_text(spec),
        context_text(list(_WEIGHT_TEXTS), {"judge": canonical_json(_WEIGHT_SCORES)}),
        registry=BUILTIN_OPERATORS,
    )
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


__all__ = ["label_scenario", "score_weight_scenario", "scores_scenario"]
