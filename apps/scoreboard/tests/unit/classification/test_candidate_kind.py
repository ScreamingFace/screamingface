"""`classify_candidate_kind` (OME-1852): the Pareto chart's circle/square verdict.

FEATURE: a leaderboard row's composition type, read only from `metadata.candidate_kind` — the
Client's own declaration (`packages/screamingface/.../leaderboards.py`'s `_submission`) — never
inferred from `spec_id` or `ran_with_providers` length.
"""

from __future__ import annotations

import pytest

from scoreboard.classification.candidate_kind import classify_candidate_kind


def test_a_declared_model_classifies_as_model() -> None:
    assert classify_candidate_kind({"candidate_kind": "model"}) == "model"


def test_a_declared_fusion_classifies_as_fusion() -> None:
    assert classify_candidate_kind({"candidate_kind": "fusion"}) == "fusion"


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"candidate_kind": None},
        {"candidate_kind": ""},
        {"candidate_kind": 42},
        {"candidate_kind": ["fusion"]},
        # The Client's own compiler emits these three further kinds (candidate.py's
        # `_CandidateKind`), and the chart draws exactly two shapes — neither is a fusion.
        {"candidate_kind": "pipeline"},
        {"candidate_kind": "corrective_loop"},
        {"candidate_kind": "self_corrective"},
        # A kind the compiler might add later must read the same way as one it has never named.
        {"candidate_kind": "mixture_of_agents"},
    ],
)
def test_anything_but_the_two_known_kinds_is_unknown_never_fusion(metadata: object) -> None:
    assert classify_candidate_kind(metadata) == "unknown"  # type: ignore[arg-type]


def test_reads_metadata_without_mutating_it() -> None:
    metadata = {"candidate_kind": "fusion", "run_id": "r1"}
    before = dict(metadata)

    classify_candidate_kind(metadata)

    assert metadata == before
