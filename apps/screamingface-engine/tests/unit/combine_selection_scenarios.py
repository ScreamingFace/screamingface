"""Scenarios of the rank and concat operators for the hash-seed test (OME-1289 E4a, unit 10).

Test-only. Each function returns one string (the answer, then the evidence JSON) and is run in a
fresh interpreter under many ``PYTHONHASHSEED`` values by ``test_combine_selection_determinism.py``.
"""

from __future__ import annotations

from combine_selection_support import concat_spec, rank_spec
from combine_support import context_text, run, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.ports import canonical_json

_TEXTS = tuple(
    f"member {index}: caf\u00e9 \u4e2d\u6587 \U0001f600 {index * 7}" for index in range(12)
)
_SEPARATOR = " \u2702 "
# The cut at k=5 falls inside a group of four members that share the score 0.5: the first three of
# them in author order (member_1, member_5, member_7) must be kept, whatever the hash seed.
_SCORES = {f"member_{index}": 0.1 for index in range(1, 13)}
_SCORES.update({"member_3": 0.9, "member_9": 0.8})
_SCORES.update({"member_1": 0.5, "member_5": 0.5, "member_7": 0.5, "member_10": 0.5})


def _bytes_of(spec: str, context: str) -> str:
    outcome = run(spec, context, registry=BUILTIN_OPERATORS)
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def rank_scenario() -> str:
    """Output and evidence JSON of a top 5 of 12 whose cut falls inside four tied scores."""
    context = context_text(list(_TEXTS), {"judge": canonical_json(_SCORES)})
    return _bytes_of(spec_text(rank_spec(len(_TEXTS), 5)), context)


def concat_scenario() -> str:
    """Output and evidence JSON of a labelled concat of 12 texts; one holds the separator."""
    texts = list(_TEXTS)
    texts[6] += _SEPARATOR
    spec = concat_spec(len(texts), separator=_SEPARATOR, label=True)
    return _bytes_of(spec_text(spec), context_text(texts))


__all__ = ["concat_scenario", "rank_scenario"]
