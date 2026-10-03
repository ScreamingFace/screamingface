"""The golden of the GSM8K vote replay lane, and its evidence lock (OME-1289 E4a, EV-12).

Mental model: ``goldens.GoldenReport`` is the answer sheet of one board replay and it carries FIVE
locks (expression sha, case statuses, failure codes, coverage, score). A reducer lane needs the same
five plus one more: what the combine step read and decided for one case. This module is the answer
sheet of that lane. It does not copy the five locks. ``ReducerGolden.outcome()`` maps the golden to
a ``GoldenReport`` (``kind: "model"``, with the candidate's route as the one model), so
``goldens.compare_outcome`` runs them UNCHANGED (it never reads ``kind``). The sixth lock is
``assert_evidence_lock``.

A reducer candidate is not a ``GoldenReport`` candidate (it is a Fusion of N seeded samples with a
Vote), so the golden carries its own replay input: ``ReducerCandidateSpec``. ``build()`` rebuilds
the exact candidate the user recorded. The expression sha then proves the rebuild.

Worked example (a lane recorded with ``--samples 5``): ``candidate.build()`` is
``sf.Fusion(list(sf.samples(model, 5, temperature=0.7)), synthesizer=sf.Vote(extract=...,
normalize=...))``; the evidence lock then wants ``op_synthesis_1`` of the pinned case to hold five
member readings and to carry the same bytes as the text of the member it chose.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from screamingface.case_result import CaseStatus

from .goldens import GoldenFailure, GoldenReport

REDUCER_GOLDEN_SCHEMA: Final = "screamingface.reducer-golden.v1"

_SHA256_HEX = r"^[0-9a-f]{64}$"
_MEMBER_PREFIX: Final = "member_"
_BOARD_REFRESH_ADVICE: Final = re.compile(
    r" — re-bless this golden from its committed snapshot \(`just e2e-refresh-golden [^`]*`\)"
)
_MAX_SAMPLES: Final = 256  # sf.samples()'s own bound


class ReducerCandidateSpec(BaseModel):
    """The replay INPUT of a reducer lane: what ``build()`` turns into the recorded candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    samples: int = Field(ge=1, le=_MAX_SAMPLES)
    temperature: float | None
    extract: str = Field(min_length=1)
    normalize: str | None

    def build(self):  # -> sf.Fusion
        """Fusion of ``samples`` seeded Models of ``model`` with a ``Vote`` synthesizer."""
        import screamingface as sf

        return sf.Fusion(
            list(sf.samples(self.model, self.samples, temperature=self.temperature)),
            synthesizer=sf.Vote(extract=self.extract, normalize=self.normalize),
        )


class EvidenceLock(BaseModel):
    """The pinned combine evidence: one case, one operation, as ``to_dict()`` wrote it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    operation_id: str = "op_synthesis_1"
    combine: dict[str, Any]


class ReducerGolden(BaseModel):
    """The frozen expected outcome of one reducer-lane replay (the field docs are in goldens.py)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_: Literal["screamingface.reducer-golden.v1"] = Field(
        alias="schema", default=REDUCER_GOLDEN_SCHEMA
    )
    lane: Literal["inspect-gsm8k-vote"]
    board: Literal["inspect-gsm8k"]
    revision: str = Field(min_length=1)
    limit: int | None
    candidate: ReducerCandidateSpec
    expression_sha: str = Field(pattern=_SHA256_HEX)
    final_score: str | None
    case_count: int = Field(ge=0)
    gradeable_count: int = Field(ge=0)
    case_statuses: dict[str, CaseStatus]
    case_failures: dict[str, tuple[GoldenFailure, ...]] = {}
    evidence: EvidenceLock

    def outcome(self) -> GoldenReport:
        """The five-lock answer sheet, so ``compare_outcome`` runs unchanged."""
        return GoldenReport(
            # `models` stays empty: only `build_candidate` reads it, and a reducer lane builds its
            # candidate from `ReducerCandidateSpec`; `compare_outcome` never reads it.
            kind="model",
            board=self.board,
            revision=self.revision,
            limit=self.limit,
            expression_sha=self.expression_sha,
            final_score=self.final_score,
            case_count=self.case_count,
            gradeable_count=self.gradeable_count,
            case_statuses=self.case_statuses,
            case_failures=self.case_failures,
        )

    @model_validator(mode="after")
    def _agrees_with_the_five_lock_golden(self) -> ReducerGolden:
        # INVARIANT: the counters, the statuses and the failure map tell one story, and the
        # evidence points at a case the golden lists. GoldenReport already owns the first rule, so
        # it is asked, not copied.
        try:
            self.outcome()
        except ValidationError as exc:
            raise ValueError(_reducer_remediation(str(exc))) from exc
        if self.evidence.case_id not in self.case_statuses:
            raise ValueError(
                f"evidence pins case {self.evidence.case_id!r} that case_statuses does not list"
            )
        return self


def _reducer_remediation(message: str) -> str:
    """GoldenReport's advice names the board refresh recipe, which cannot refresh this lane."""
    return _BOARD_REFRESH_ADVICE.sub(
        " — re-record and re-bless the lane (tests/e2e/fixtures/reducer_lane.py)", message
    )


def load_reducer_golden(path: Path) -> ReducerGolden:
    """Read + validate one ``*.reducer-golden.json``; any shape problem raises at load time."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"golden file {path.name} is not valid JSON: {exc}") from exc
    try:
        return ReducerGolden.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"golden file {path.name} failed validation: {exc}") from exc


def assert_evidence_lock(golden: ReducerGolden, cases: Sequence[Any]) -> None:
    """The sixth lock: the pinned case's combine evidence, read off the replayed ``CaseResult`` s.

    Raises ``AssertionError`` naming the first thing that is wrong: the case or its combine
    evidence is missing, the evidence differs from the golden, the pinned case did not answer with
    its chosen member, the readings are not one per sample, the agreement is not in (0, 1], the
    synthesis text is not the chosen member's text byte for byte, or a member operation has no
    output (EV-H3).
    """
    lock = golden.evidence
    case = next((item for item in cases if str(item.case_id) == lock.case_id), None)
    if case is None:
        raise AssertionError(f"the replay has no case {lock.case_id!r} to read the evidence from")
    operations = {item.operation_id: item for item in case.operations or ()}
    synthesis = operations.get(lock.operation_id)
    if synthesis is None or synthesis.combine is None:
        raise AssertionError(
            f"case {lock.case_id!r} carries no combine evidence on {lock.operation_id}"
        )
    combine = synthesis.combine
    # The golden file holds JSON, so compare the JSON form (tuples become lists, as on disk).
    actual = json.loads(json.dumps(combine.to_dict()))
    if actual != lock.combine:
        raise AssertionError(
            f"combine evidence drifted on case {lock.case_id!r} (golden, actual): "
            f"{lock.combine!r} != {actual!r}"
        )
    _check_answered(combine)
    _check_readings(golden, combine)
    _check_text(operations, synthesis, combine)


def _check_answered(combine: Any) -> None:
    """The pinned case answered with a member: an abstained Case has no text to lock (F3)."""
    result = combine.result
    if result.status != "answered":
        raise AssertionError(
            f"the pinned case did not answer (result status {result.status!r}, "
            f"reason {result.reason!r})"
        )
    if combine.chosen and result.member_id != combine.chosen[0]:
        raise AssertionError(
            f"the pinned case did not answer with the chosen member "
            f"(result {result.member_id!r}, chosen {combine.chosen[0]!r})"
        )


def _check_readings(golden: ReducerGolden, combine: Any) -> None:
    samples = golden.candidate.samples
    if len(combine.members) != samples:
        raise AssertionError(
            f"expected {samples} member readings (one per sample), got {len(combine.members)}"
        )
    if combine.agreement is None or not 0 < combine.agreement <= 1:
        raise AssertionError(f"agreement must be in (0, 1], got {combine.agreement!r}")


def _check_text(operations: dict[str, Any], synthesis: Any, combine: Any) -> None:
    for index in range(1, len(combine.members) + 1):
        member = operations.get(f"op_model_{index}")
        if member is None or member.output is None:
            raise AssertionError(f"op_model_{index} carries no output (the member text is lost)")
    if not combine.chosen:
        raise AssertionError("the vote chose no member, so there is no text to compare")
    # The loop above proved op_model_1..N exist, and the SDK refuses a `chosen` outside the members.
    chosen = operations[f"op_model_{combine.chosen[0].removeprefix(_MEMBER_PREFIX)}"]
    if synthesis.output != chosen.output:
        raise AssertionError(
            "the synthesis output is not the chosen member's text verbatim: "
            f"{synthesis.output!r} != {chosen.output!r}"
        )
