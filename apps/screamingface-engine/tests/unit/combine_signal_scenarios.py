"""Scenarios of the signal reducers for the hash-seed test (OME-1289 E4a, unit 10E).

Test-only. Each function returns one string (the answer, then the evidence JSON) and is run in a
fresh interpreter under many ``PYTHONHASHSEED`` values by ``test_combine_signal_determinism.py``.
Every scenario reads a ``field:`` signal, so no accounting reader is needed in the subprocess.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from combine_signal_support import argmax_spec, filter_spec, rank_signal_spec
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import canonical_json

_NOTE = "caf\u00e9 \u4e2d\u6587 \U0001f600"
# The best score 0.9 is held by six members (member_2, 4, 5, 7, 9 and 10): the first in author
# order wins.
_TIES = [0.5, 0.9, 0.1, 0.9, 0.9, 0.2, 0.9, 0.3, 0.9, 0.9]
# The cut at k=3 falls inside four members that share 0.7: the first one in author order is kept.
_CUT = [0.7, 0.95, 0.7, 0.2, 0.7, 0.9, 0.7, 0.1]
_CONFIDENCE = [0.9, 0.2, 0.9, 0.6, 0.59, 0.61, 0.9, 0.1, 0.6]


def _texts(values: list[float], name: str) -> list[str]:
    return [canonical_json({name: value, "note": _NOTE}) for value in values]


def _bytes_of(spec: Mapping[str, Any], texts: list[str]) -> str:
    outcome = run(spec_text(spec), context_text(texts), registry=BUILTIN_OPERATORS)
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def argmax_scenario() -> str:
    """Output and evidence JSON of an argmax whose best score is held by six members."""
    return _bytes_of(argmax_spec(len(_TIES), "field:s", "max"), _texts(_TIES, "s"))


def rank_scenario() -> str:
    """Output and evidence JSON of a top 3 by a signal whose cut falls inside four tied scores."""
    return _bytes_of(rank_signal_spec(len(_CUT), 3, "field:s", "max"), _texts(_CUT, "s"))


def threshold_scenario() -> str:
    """Output and evidence JSON of a threshold filter with members exactly at the limit."""
    args = {"key": "field:confidence", "cmp": "ge", "value": 0.6}
    return _bytes_of(filter_spec(len(_CONFIDENCE), args), _texts(_CONFIDENCE, "confidence"))


def pattern_scenario() -> str:
    """Output and evidence JSON of a pattern filter over mixed case and unicode text."""
    texts = [f"{_NOTE} ANSWER: {index}" for index in range(3)]
    texts += ["answer: 9", "no marker", "ANSWER: x"] + [f"{_NOTE} ANSWER: 7"] * 3
    spec = filter_spec(len(texts), {"pattern": "ANSWER: [0-9]+", "ignore_case": True})
    return _bytes_of(spec, texts)


__all__ = ["argmax_scenario", "pattern_scenario", "rank_scenario", "threshold_scenario"]
