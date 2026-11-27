"""C2, C5 and C6 read one Router vocabulary (Unit 5.2).

FEATURE: Router Recipe extension. The C2 reader (`world.router_spec`), the C5 codec
(`router_decision`) and the pure C6 policy (`world.routing_policy`) take their binding, revision,
strict-model and selector-evidence rules from `router_vocabulary`, so the three cannot drift.

INVARIANT: a selector reading the C5 record refuses is invalid evidence for the C6 policy too,
so a decision never stands on evidence its record could not hold.
INVARIANT: a score row the C5 record refuses is invalid evidence at DECIDE, read before the policy:
a permanent `router_evidence_invalid` draft, never an exception out of the step.
"""

from __future__ import annotations

import json
from typing import Literal

import pytest
from pydantic import ValidationError
from router_join_support import draft
from router_support import accepted, fixed_definition, scores, text

from screamingface_engine import router_decision, router_vocabulary
from screamingface_engine.router_vocabulary import Parse, SelectorRecord
from screamingface_engine.world import router_spec
from screamingface_engine.world.routing_policy import (
    ROUTER_EVIDENCE_INVALID,
    PolicyFailure,
    PolicyRule,
    SelectorEvidence,
    decide,
)

_LABELS = ("code", "math")
_REFUSED = [
    pytest.param("llm", ("code",), (), "unparsed", id="unparsed-names-a-label"),
    pytest.param("llm", (), ("x",), "unparsed", id="unparsed-keeps-unknown"),
    pytest.param("llm", ("code",), ("x",), "ok", id="ok-keeps-unknown"),
    pytest.param("llm", (), ("x", "x"), "unrecognized", id="unknown-twice"),
    pytest.param("llm", ("code", "code"), (), "ok", id="label-twice"),
    pytest.param("llm", (), (), "unrecognized", id="unrecognized-without-unknown"),
    pytest.param("regex", (), (), "unparsed", id="regex-unparsed"),
    pytest.param("regex", (), ("x",), "unrecognized", id="regex-unrecognized"),
    pytest.param("llm", (), (), "no_match", id="llm-no-match"),
]
_ACCEPTED = [
    pytest.param("llm", ("code",), (), "ok", id="llm-ok"),
    pytest.param("llm", (), (), "unparsed", id="llm-unparsed"),
    pytest.param("llm", ("math",), ("x",), "unrecognized", id="llm-unrecognized-with-label"),
    pytest.param("regex", ("code", "math"), (), "ok", id="regex-ok"),
    pytest.param("regex", (), (), "no_match", id="regex-no-match"),
]


def _record(source: str, labels: tuple[str, ...], unknown: tuple[str, ...], parse: str) -> None:
    SelectorRecord.model_validate(
        {"source": source, "labels": labels, "unknown": unknown, "parse": parse}
    )


_Source = Literal["llm", "regex"]


def _invalid(
    source: _Source, labels: tuple[str, ...], unknown: tuple[str, ...], parse: Parse
) -> bool:
    evidence = SelectorEvidence(source, labels, unknown, parse)
    result = decide(
        PolicyRule("router-policy", "exact", "all"), evidence, labels=_LABELS, has_default=True
    )
    return result.failure == PolicyFailure("decide", ROUTER_EVIDENCE_INVALID, True)


@pytest.mark.parametrize(("source", "labels", "unknown", "parse"), _REFUSED)
def test_a_reading_the_record_refuses_is_invalid_evidence_for_the_policy(
    source: _Source, labels: tuple[str, ...], unknown: tuple[str, ...], parse: Parse
) -> None:
    with pytest.raises(ValidationError):
        _record(source, labels, unknown, parse)

    assert _invalid(source, labels, unknown, parse)


@pytest.mark.parametrize(("source", "labels", "unknown", "parse"), _ACCEPTED)
def test_a_reading_the_record_holds_is_evidence_the_policy_reads(
    source: _Source, labels: tuple[str, ...], unknown: tuple[str, ...], parse: Parse
) -> None:
    _record(source, labels, unknown, parse)

    assert not _invalid(source, labels, unknown, parse)


def test_a_label_no_candidate_has_is_invalid_for_the_policy_only() -> None:
    _record("llm", ("other",), (), "ok")

    assert _invalid("llm", ("other",), (), "ok")


def test_the_c2_reader_and_the_c5_codec_share_one_vocabulary() -> None:
    for name in ("RouterBinding", "Revision", "REVISION_SCHEME", "SCORES_CONTRACT"):
        shared = getattr(router_vocabulary, name)
        assert getattr(router_spec, name) is shared
        assert getattr(router_decision, name, shared) is shared
    assert issubclass(router_spec.RouterSpec, router_vocabulary.StrictModel)


# --- C5 score rows at DECIDE -------------------------------------------------------------------

_VALID = scores(general=0.1, code=0.8, math=0.1)


def _with_row(row: object) -> str:
    """The valid scores answer with ``row`` appended."""
    document = json.loads(_VALID)
    document["scores"].append(row)
    return text(document)


@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param(_with_row({"label": ["code"], "score": 0.5}), id="list-label"),
        pytest.param(_with_row({"label": {"code": 1}, "score": 0.5}), id="object-label"),
        pytest.param(_with_row({"label": 7, "score": 0.5}), id="number-label"),
        pytest.param(_with_row({"label": "", "score": 0.5}), id="empty-label"),
        pytest.param(_with_row({"label": "x" * 65, "score": 0.5}), id="label-over-64-bytes"),
        pytest.param(_with_row({"label": "code", "score": True}), id="bool-score"),
        pytest.param(_with_row({"label": "code", "score": "0.5"}), id="string-score"),
        pytest.param(_with_row({"label": "code", "score": 10**400}), id="huge-integer-score"),
        pytest.param(_VALID.replace("0.8", "1e400"), id="overflowing-float-score"),
    ],
)
def test_a_score_row_the_record_refuses_is_invalid_evidence_at_decide(evidence: str) -> None:
    admit = accepted(fixed_definition())

    decided = json.loads(draft(admit, evidence))

    # WHY the reference: a score above one was invalid evidence already; a malformed row reads
    # the same permanent draft, with no evidence, reason or selection.
    assert decided == json.loads(draft(admit, scores(general=0.1, code=1.5, math=0.1)))
    assert decided["failure"] == {
        "phase": "decide",
        "code": "router_evidence_invalid",
        "permanent": True,
    }
