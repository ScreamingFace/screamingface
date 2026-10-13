"""All scenarios for the deterministic hash-seed tests (OME-1289 E4a; FW-3).

Test-only. Each function returns one string (the answer, then the evidence JSON). These are run in
fresh interpreters under many PYTHONHASHSEED values by test_combine_determinism.py.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from combine_fields_support import merge_spec, pick_spec, project_spec, step
from combine_flow_support import judge_spec
from combine_selection_support import concat_spec, rank_spec
from combine_signal_support import argmax_spec, filter_spec, rank_signal_spec
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import canonical_json

# --- Core vote and signal scenarios --------------------------------------------------------

_BODY = """
import json

from combine_support import context_text, run, spec_text, vote_spec


def _wire(evidence) -> str:
    # The wire form: the model dumped by alias, then written the way the envelope encoder writes.
    return json.dumps(evidence.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"))

_WORDS = ["\\u00c9", "stra\\u00dfe", "\\u00e9", "STRASSE", "x", "y", "x", "y",
          "\\u4e16\\u754c", "k", "\\u4e16\\u754c", "z"]


def scenario() -> str:
    texts = [f"the answer is {word}" for word in _WORDS]
    outcome = run(spec_text(vote_spec(12)), context_text(texts))
    return outcome.output + "\\n" + _wire(outcome.evidence)
"""

_SIGNAL_BODY = """
import json

from combine_support import context_text, run, spec_text, vote_spec


def _wire(evidence) -> str:
    return json.dumps(evidence.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"))

_WORDS = ["\\u00c9", "stra\\u00dfe", "\\u00e9", "STRASSE", "x", "y", "x", "y",
          "\\u4e16\\u754c", "k", "\\u4e16\\u754c", "z"]
_WEIGHTS = [2, 1.5, 2, 1.5, 1, 1, 0.5, 2, True, -1, "0.5", 1.5]


def _reader(sources):
    return {
        member: {"cost_usd": None if index % 5 == 0 else (index % 3) * 0.25}
        for index, member in enumerate(sorted(sources))
    }


def scenario() -> str:
    texts = [json.dumps({"w": w, "x": word}) for w, word in zip(_WEIGHTS, _WORDS)]
    weighted = vote_spec(
        12,
        weights={"signal": "field:w"},
        reduce={"op": "fake_weighted@1", "args": {}},
    )
    lenient = vote_spec(12, weights={"signal": "field:w"})
    first = run(spec_text(lenient), context_text(texts))
    sources = {f"member_{i}": {"model_1": {"path": "/provider/alpha", "params": ""}}
               for i in range(1, 13)}
    scored = vote_spec(
        12,
        reduce={"op": "fake_signal_score@1", "args": {"key": "cost_usd", "order": "min"}},
        select={"op": "fake_best@1", "args": {}},
    )
    second = run(spec_text(scored), context_text(texts, sources=sources), accounting=_reader)
    parts = [
        first.output + "\\n" + _wire(first.evidence),
        second.output + "\\n" + _wire(second.evidence),
    ]
    try:
        run(spec_text(weighted), context_text(texts))
    except Exception as exc:
        parts.append(type(exc).__name__)
    return "\\n".join(parts)
"""


def core_scenario() -> str:
    """Output and evidence JSON of a vote with unicode ties."""
    namespace: dict[str, Any] = {}
    exec(_BODY, namespace)
    return namespace["scenario"]()


def core_signal_scenario() -> str:
    """Output and evidence JSON of a vote with signal weights."""
    namespace: dict[str, Any] = {}
    exec(_SIGNAL_BODY, namespace)
    return namespace["scenario"]()


# --- Fields scenarios ----------------------------------------------------------------------

_FIELDS_COUNT = 12
_FIELDS_WORDS = ("café", "Café.", "中文", "naïve", "NAÏVE", "x")
# Members carry undeclared unicode keys (dropped by the merge) and list values that overlap.
_FIELDS_MEMBERS = tuple(
    json.dumps(
        {
            "answer": _FIELDS_WORDS[index % len(_FIELDS_WORDS)],
            "score": (index * 7) % 5,
            "source": f"src \U0001f600 {index}",
            "tags": [_FIELDS_WORDS[index % 4], _FIELDS_WORDS[(index + 1) % 4], f"t{index % 3}"],
            "ünused": {"k": index},
            "confidence": 0.5 if index % 3 else 0.9,
        },
        ensure_ascii=False,
    )
    for index in range(_FIELDS_COUNT)
)
_FIELDS_RULES = [
    {"field": "answer", "rule": "majority", "normalize": "text"},
    {"field": "score", "rule": "max"},
    {"field": "source", "rule": "from_member", "member": "member_5"},
    {"field": "tags", "rule": "union", "normalize": "text"},
    {"field": "summary", "rule": "model"},
]


def _fields_bytes_of(spec: dict[str, Any], signals: dict[str, str] | None = None) -> str:
    outcome = run(
        spec_text(spec),
        context_text(list(_FIELDS_MEMBERS), signals),
        registry=BUILTIN_OPERATORS,
    )
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def merge_scenario() -> str:
    """Output and evidence JSON of a merge that uses all five rules."""
    return _fields_bytes_of(
        merge_spec(_FIELDS_COUNT, _FIELDS_RULES), {"writer_summary": "A summary é."}
    )


def pick_scenario() -> str:
    """Output and evidence JSON of a pick with four members tied at the top."""
    return _fields_bytes_of(pick_spec(_FIELDS_COUNT, step("by_field@1", order="max")))


def projection_scenario() -> str:
    """Output and evidence JSON of the projection a writer model would read."""
    return _fields_bytes_of(project_spec(_FIELDS_COUNT, "tags"))


# --- Judge scenarios -----------------------------------------------------------------------

_JUDGE_TEXTS = tuple(f"member {index}: café 中文 \U0001f600 {index * 7}" for index in range(1, 13))
# Three members share the top score; the answer must be the first of them in author order.
_JUDGE_TIED_SCORES = {f"member_{index}": 0.25 for index in range(1, 13)}
_JUDGE_TIED_SCORES.update({"member_4": 0.9, "member_8": 0.9, "member_11": 0.9})

# Twelve members whose last numbers fall into three values; the judge scores tie two tally rows.
_JUDGE_WEIGHT_TEXTS = tuple(f"member {index}: café 中文 {index % 3}" for index in range(1, 13))
_JUDGE_WEIGHT_SCORES = {
    f"member_{index}": (0.125 if index % 3 == 2 else 0.25) for index in range(1, 13)
}


def _judge_bytes_of(returns: Literal["label", "scores"], reply: str) -> str:
    spec = judge_spec(len(_JUDGE_TEXTS), returns)
    outcome = run(
        spec_text(spec),
        context_text(list(_JUDGE_TEXTS), {"judge": reply}),
        registry=BUILTIN_OPERATORS,
    )
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def scores_scenario() -> str:
    """Output and evidence JSON of a scores judge with three tied top scores."""
    reply = canonical_json(_JUDGE_TIED_SCORES)
    return _judge_bytes_of("scores", reply)


def label_scenario() -> str:
    """Output and evidence JSON of a label judge."""
    return _judge_bytes_of("label", " member_7\n")


def score_weight_scenario() -> str:
    """Output and evidence JSON of a vote weighted by ``score:judge`` whose two top rows tie."""
    spec = vote_spec(
        len(_JUDGE_WEIGHT_TEXTS),
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "max_weight_holder@1", "args": {}},
        weights={"signal": "score:judge"},
    )
    outcome = run(
        spec_text(spec),
        context_text(list(_JUDGE_WEIGHT_TEXTS), {"judge": canonical_json(_JUDGE_WEIGHT_SCORES)}),
        registry=BUILTIN_OPERATORS,
    )
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


# --- Selection scenarios -------------------------------------------------------------------

_SELECTION_TEXTS = tuple(f"member {index}: café 中文 \U0001f600 {index * 7}" for index in range(12))
_SELECTION_SEPARATOR = " ✂ "
# The cut at k=5 falls inside a group of four members that share the score 0.5: the first three of
# them in author order (member_1, member_5, member_7) must be kept, whatever the hash seed.
_SELECTION_SCORES = {f"member_{index}": 0.1 for index in range(1, 13)}
_SELECTION_SCORES.update({"member_3": 0.9, "member_9": 0.8})
_SELECTION_SCORES.update({"member_1": 0.5, "member_5": 0.5, "member_7": 0.5, "member_10": 0.5})


def _selection_bytes_of(spec: str, context: str) -> str:
    outcome = run(spec, context, registry=BUILTIN_OPERATORS)
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def rank_selection_scenario() -> str:
    """Output and evidence JSON of a top 5 of 12 whose cut falls inside four tied scores."""
    context = context_text(list(_SELECTION_TEXTS), {"judge": canonical_json(_SELECTION_SCORES)})
    return _selection_bytes_of(spec_text(rank_spec(len(_SELECTION_TEXTS), 5)), context)


def concat_scenario() -> str:
    """Output and evidence JSON of a labelled concat of 12 texts; one holds the separator."""
    texts = list(_SELECTION_TEXTS)
    texts[6] += _SELECTION_SEPARATOR
    spec = concat_spec(len(texts), separator=_SELECTION_SEPARATOR, label=True)
    return _selection_bytes_of(spec_text(spec), context_text(texts))


# --- Signal scenarios ----------------------------------------------------------------------

_SIGNAL_NOTE = "café 中文 \U0001f600"
# The best score 0.9 is held by six members (member_2, 4, 5, 7, 9 and 10): the first in author
# order wins.
_SIGNAL_TIES = [0.5, 0.9, 0.1, 0.9, 0.9, 0.2, 0.9, 0.3, 0.9, 0.9]
# The cut at k=3 falls inside four members that share 0.7: the first one in author order is kept.
_SIGNAL_CUT = [0.7, 0.95, 0.7, 0.2, 0.7, 0.9, 0.7, 0.1]
_SIGNAL_CONFIDENCE = [0.9, 0.2, 0.9, 0.6, 0.59, 0.61, 0.9, 0.1, 0.6]


def _signal_texts(values: list[float], name: str) -> list[str]:
    return [canonical_json({name: value, "note": _SIGNAL_NOTE}) for value in values]


def _signal_bytes_of(spec: Mapping[str, Any], texts: list[str]) -> str:
    outcome = run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def argmax_scenario() -> str:
    """Output and evidence JSON of an argmax whose best score is held by six members."""
    return _signal_bytes_of(
        argmax_spec(len(_SIGNAL_TIES), "field:s", "max"), _signal_texts(_SIGNAL_TIES, "s")
    )


def rank_signal_scenario() -> str:
    """Output and evidence JSON of a top 3 by a signal whose cut falls inside four tied scores."""
    return _signal_bytes_of(
        rank_signal_spec(len(_SIGNAL_CUT), 3, "field:s", "max"), _signal_texts(_SIGNAL_CUT, "s")
    )


def threshold_scenario() -> str:
    """Output and evidence JSON of a threshold filter with members exactly at the limit."""
    args = {"key": "field:confidence", "cmp": "ge", "value": 0.6}
    return _signal_bytes_of(
        filter_spec(len(_SIGNAL_CONFIDENCE), args), _signal_texts(_SIGNAL_CONFIDENCE, "confidence")
    )


def pattern_scenario() -> str:
    """Output and evidence JSON of a pattern filter over mixed case and unicode text."""
    texts = [f"{_SIGNAL_NOTE} ANSWER: {index}" for index in range(3)]
    texts += ["answer: 9", "no marker", "ANSWER: x"] + [f"{_SIGNAL_NOTE} ANSWER: 7"] * 3
    spec = filter_spec(len(texts), {"pattern": "ANSWER: [0-9]+", "ignore_case": True})
    return _signal_bytes_of(spec, texts)


__all__ = [
    "argmax_scenario",
    "concat_scenario",
    "core_scenario",
    "core_signal_scenario",
    "label_scenario",
    "merge_scenario",
    "pattern_scenario",
    "pick_scenario",
    "projection_scenario",
    "rank_selection_scenario",
    "rank_signal_scenario",
    "score_weight_scenario",
    "scores_scenario",
    "threshold_scenario",
]
