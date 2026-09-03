"""Golden reports and the compare-order contract (OME-961, parent R11).

Mental model: a golden is the frozen answer sheet for one board replay — what the
pipeline scored the last time a human blessed it. Comparing a fresh run against it is a
STAGED walk, and THE ORDER IS THE CONTRACT:

1. **expression** — sha256 of the currently rendered url4 expression must equal the
   recorded ``expression_sha``. A mismatch means the experiment itself changed, so every
   downstream number measures something else; the failure says "expression changed,
   goldens stale" and deliberately says nothing about scores.
2. **cases** — the per-case status map (``scored`` / ``refused`` / ``failed``) must
   match. Statuses drifting with the expression intact means the replay itself broke.
3. **codes** — the per-case failure map (``stage`` + ``code`` for every case that
   carries a failure) must match (OME-1094). Five rubric failure reasons all spell
   ``failed``; this rung is what makes a reclassification (``incomplete_verdicts`` →
   ``case_error``) fail by name instead of hiding behind an unchanged status word.
4. **coverage** — the REPORT'S OWN coverage figure must equal what the golden's
   counters imply (``gradeable_count / case_count``). Stage 2 already pins the raw
   statuses, so this stage deliberately checks the one thing statuses cannot see: the
   report's independently derived aggregation. Matching statuses with a contradicting
   coverage figure means the SDK's aggregation math drifted — a different bug than a
   replay drift, named separately.
5. **score** — last, the final score, compared as DECIMAL STRINGS. The SDK reports a
   float; ``canonical_score`` renders it as the shortest round-trip decimal (`repr`), so
   the golden holds ``"0.5"``, not a float that two JSON writers could disagree about.

Worked example: golden ``final_score="0.5"``, ``case_statuses={"c1": "scored",
"c2": "failed"}``, ``case_failures={"c2": [{"stage": "grading", "code":
"incomplete_verdicts"}]}``, so ``case_count=2`` and ``gradeable_count=1`` (only ``c1``
carries a grade). A run whose expression drifted fails at stage 1 even if it also
scored 0.0; a run with the right expression but ``c1: "failed"`` fails at stage 2; a
run where ``c2`` still fails but now as ``case_error`` fails at stage 3; only a run
clean through stages 1–4 can ever fail on the score.

Deliberately absent: progress or stream fields (``extra="forbid"`` enforces it), floats
anywhere in the file, and timestamps/run ids (nondeterministic by nature).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# The SDK's OWN status vocabulary — imported, not mirrored, so it cannot drift
# (owner review finding on OME-961). Same rule for the failure-stage vocabulary
# (OME-1094): ``FailureStage`` lives in the SDK's report primitives.
from screamingface._report_primitives import FailureStage
from screamingface.case_result import CaseResult, CaseStatus

GOLDEN_SCHEMA: Final = "screamingface.golden-report.v1"

_SHA256_HEX = r"^[0-9a-f]{64}$"

_GRADEABLE: Final = "scored"
_FAILED: Final = "failed"

#: The SDK rounds its coverage figure to 4 places (``report._coverage``); the stage-3
#: compare rounds identically so the two sides speak the same precision.
_COVERAGE_PLACES: Final = 4


class GoldenMismatch(AssertionError):
    """One staged comparison failed; ``stage`` names which rung of the ladder."""

    def __init__(
        self,
        stage: Literal["expression", "cases", "codes", "coverage", "score"],
        message: str,
    ):
        self.stage = stage
        super().__init__(message)


class GoldenFailure(BaseModel):
    """One pinned failure on one case: WHY it failed (``code``) and WHERE (``stage``).

    The message is deliberately absent — it is prose the engine may reword freely;
    the code is the published vocabulary a researcher acts on (retry / raise a budget
    / report a broken benchmark), so the code is what the golden freezes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: FailureStage
    code: str = Field(min_length=1)


class GoldenReport(BaseModel):
    """The frozen expected outcome of one board replay.

    ``kind``, ``models``, ``recipe``, ``synthesizer`` and ``limit`` are the replay
    INPUTS (which candidate to build, how many cases to select) — without them a
    golden could not be re-run; everything else is the expected OUTPUT. For
    ``kind: "model"`` (the default — every golden blessed before OME-978) the
    candidate is ``models[0]``; for ``kind: "fusion"`` the candidate is the recipe
    named ``recipe`` with ``models`` as its ordered members and ``synthesizer`` as
    the model that merges them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_: str = Field(alias="schema", default=GOLDEN_SCHEMA)
    board: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    kind: Literal["model", "fusion"] = "model"
    recipe: str | None = None
    models: tuple[str, ...] = ()
    synthesizer: str | None = None
    limit: int | None = None
    expression_sha: str = Field(pattern=_SHA256_HEX)
    final_score: str | None
    case_count: int = Field(ge=0)
    gradeable_count: int = Field(ge=0)
    case_statuses: dict[str, CaseStatus]
    #: Per-case failures, keyed like ``case_statuses``, for every case that carries
    #: any (OME-1094). Absent in goldens blessed before the codes rung — those load
    #: only if no case failed, so an all-scored golden never needs a replay to be
    #: re-blessed and a golden with a status-only failed case refuses at load.
    case_failures: dict[str, tuple[GoldenFailure, ...]] = {}

    @model_validator(mode="after")
    def _failures_agree_with_statuses(self) -> GoldenReport:
        # INVARIANT: the failure map and the status map tell one story. A scored case
        # carries no failure (the SDK's own contract); a failed case MUST name its
        # reason — a failed case pinned by status alone is exactly the hole this
        # rung closes, so it is refused rather than tolerated.
        for case in self.case_failures:
            if case not in self.case_statuses:
                raise ValueError(
                    f"case_failures pins case {case!r} that case_statuses does not list"
                )
        for case, entries in self.case_failures.items():
            if self.case_statuses[case] == _GRADEABLE and entries:
                raise ValueError(
                    f"case {case!r} is '{_GRADEABLE}' but case_failures pins a failure for it"
                )
        for case, status in self.case_statuses.items():
            if status == _FAILED and not self.case_failures.get(case):
                raise ValueError(
                    f"case {case!r} is '{_FAILED}' but case_failures pins no failure code "
                    f"for it — re-bless this golden from its committed snapshot "
                    f"(`just e2e-refresh-golden {self.board}`)"
                )
        return self

    @model_validator(mode="after")
    def _fusion_lineup_is_complete(self) -> GoldenReport:
        # INVARIANT: a fusion golden must be re-runnable — recipe name, ≥2 members
        # and the synthesizer are its replay inputs, so a hole here refuses at load.
        if self.kind == "fusion":
            if not self.recipe:
                raise ValueError("a fusion golden requires its recipe name")
            if not self.synthesizer:
                raise ValueError("a fusion golden requires its synthesizer route")
            if len(self.models) < 2:
                raise ValueError(
                    f"a fusion golden lists its member routes in order — got "
                    f"{len(self.models)}, need at least 2 members"
                )
        return self

    @model_validator(mode="after")
    def _counters_agree_with_statuses(self) -> GoldenReport:
        # Validation on read: the counters are DERIVED truth. A golden whose counters
        # disagree with its own statuses was hand-edited and must be refused.
        scored = sum(1 for status in self.case_statuses.values() if status == _GRADEABLE)
        if self.case_count != len(self.case_statuses):
            raise ValueError(
                f"case_count={self.case_count} but case_statuses lists "
                f"{len(self.case_statuses)} cases"
            )
        if self.gradeable_count != scored:
            raise ValueError(
                f"gradeable_count={self.gradeable_count} but case_statuses holds "
                f"{scored} '{_GRADEABLE}' cases"
            )
        if self.schema_ != GOLDEN_SCHEMA:
            raise ValueError(f"unknown golden schema: {self.schema_!r}")
        return self


@dataclass(frozen=True, slots=True)
class ActualOutcome:
    """What one fresh replay actually produced — the five facts the ladder checks.

    ``coverage`` is the report's OWN aggregated figure (``CandidateResult.coverage``),
    passed through rather than re-derived from ``case_statuses`` — that independence is
    what makes the coverage stage a real check instead of a restatement of the
    statuses stage. ``case_failures`` comes from ``failure_map`` (the same reader the
    bless tool authors the golden with); it defaults to "nothing failed" so a replay
    whose cases all scored needs no extra plumbing.
    """

    rendered_url4: str
    final_score: float | None
    case_statuses: dict[str, str]
    coverage: float
    case_failures: Mapping[str, tuple[GoldenFailure, ...]] = field(default_factory=dict)


def failure_map(cases: Iterable[CaseResult]) -> dict[str, tuple[GoldenFailure, ...]]:
    """Read every case's pinned failures off the SDK ``CaseResult`` values.

    ONE reader for both sides — the bless tool authors the golden through it and
    ``test_boards`` builds the actual outcome through it — so the golden and the
    compare can never disagree about how a failure is spelled. Cases with no
    failures are absent (not an empty tuple), matching the golden's on-disk shape.
    """
    return {
        str(case.case_id): tuple(
            GoldenFailure(stage=failure.stage, code=failure.code) for failure in case.failures
        )
        for case in cases
        if case.failures
    }


def _spell_failures(entries: tuple[GoldenFailure, ...] | None) -> tuple[str, ...] | None:
    """``("grading:incomplete_verdicts",)`` — the human-readable form for a drift message."""
    return None if entries is None else tuple(f"{entry.stage}:{entry.code}" for entry in entries)


def build_candidate(golden: GoldenReport):  # -> sf.Model | sf.Fusion
    """The golden's replay INPUT, rebuilt: the exact candidate the bless ran.

    ``kind: "model"`` → ``sf.Model(models[0])`` (the pre-OME-978 behaviour, pinned);
    ``kind: "fusion"`` → ``sf.Fusion(models, name=recipe, synthesizer=synthesizer)``
    with the members in the golden's recorded order — member order is part of the
    rendered url4 expression, so reordering would fail the expression rung, not
    silently reshuffle the run.
    """
    import screamingface as sf

    if golden.kind == "fusion":
        # The validator guarantees recipe + synthesizer + ≥2 members on this branch.
        return sf.Fusion(
            list(golden.models),
            name=golden.recipe,
            synthesizer=golden.synthesizer or "",
        )
    if len(golden.models) != 1:
        raise ValueError(
            f"golden for '{golden.board}' names {len(golden.models)} models; a "
            f"'model' golden replays exactly one candidate model"
        )
    return sf.Model(golden.models[0])


def canonical_score(score: float | None) -> str | None:
    """One float, one string: the shortest decimal that round-trips (`repr`).

    ``canonical_score(0.5) == "0.5"``; ``None`` (no gradeable case) stays ``None``.
    Both the golden author and the compare use THIS function, so the two sides can
    never disagree about how a float is spelled.
    """
    return None if score is None else repr(score)


def expression_sha(rendered_url4: str) -> str:
    """sha256 hex of the rendered url4 expression — the R11 link value."""
    return hashlib.sha256(rendered_url4.encode("utf-8")).hexdigest()


def compare_outcome(golden: GoldenReport, actual: ActualOutcome) -> None:
    """Walk the staged ladder; raise ``GoldenMismatch`` at the FIRST rung that fails.

    Stage 1 — expression: a drifted expression is reported as stale goldens and the
    message never mentions a number, because none of the numbers are comparable.
    Stage 2 — case statuses. Stage 3 — per-case failure codes, compared as a whole
    map so a swapped, added or vanished failure is all the same drift. Stage 4 — the
    report's own coverage figure against the golden's counters. Stage 5 — score as
    decimal strings.
    """
    actual_sha = expression_sha(actual.rendered_url4)
    if actual_sha != golden.expression_sha:
        raise GoldenMismatch(
            "expression",
            f"expression changed, goldens stale: recorded expression_sha "
            f"{golden.expression_sha[:12]}… but the currently rendered expression hashes "
            f"to {actual_sha[:12]}…; re-record the {golden.board} fixtures before "
            f"trusting any comparison",
        )
    if actual.case_statuses != golden.case_statuses:
        drifted = {
            case: (golden.case_statuses.get(case), actual.case_statuses.get(case))
            for case in golden.case_statuses.keys() | actual.case_statuses.keys()
            if golden.case_statuses.get(case) != actual.case_statuses.get(case)
        }
        raise GoldenMismatch("cases", f"case statuses drifted (golden, actual): {drifted}")
    # Stage 3 — failure codes. Statuses matched, so every drift here is a case that
    # failed for a DIFFERENT REASON than the blessed run — the reclassification the
    # status word cannot see (OME-1094).
    actual_failures = dict(actual.case_failures)
    if actual_failures != golden.case_failures:
        drifted_codes = {
            case: (
                _spell_failures(golden.case_failures.get(case)),
                _spell_failures(actual_failures.get(case)),
            )
            for case in golden.case_failures.keys() | actual_failures.keys()
            if golden.case_failures.get(case) != actual_failures.get(case)
        }
        raise GoldenMismatch("codes", f"failure codes drifted (golden, actual): {drifted_codes}")
    # Stage 4 — deliberately NOT re-counting actual.case_statuses (stage 2 pinned those
    # exactly; a re-count could never fire). The report's own aggregated figure is the
    # independent fact: it must equal what the golden's counters imply.
    expected_coverage = (
        1.0
        if golden.case_count == 0
        else round(golden.gradeable_count / golden.case_count, _COVERAGE_PLACES)
    )
    if round(actual.coverage, _COVERAGE_PLACES) != expected_coverage:
        raise GoldenMismatch(
            "coverage",
            f"the report's coverage figure contradicts its own case statuses: golden "
            f"counters imply {expected_coverage}, the report says "
            f"{round(actual.coverage, _COVERAGE_PLACES)} — an aggregation drift, not a "
            f"replay drift",
        )
    actual_score = canonical_score(actual.final_score)
    if actual_score != golden.final_score:
        raise GoldenMismatch(
            "score",
            f"final score drifted: golden {golden.final_score!r}, actual {actual_score!r}",
        )


def load_golden(path: Path) -> GoldenReport:
    """Read + validate one ``*.golden.json``; any shape problem raises at load time."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"golden file {path.name} is not valid JSON: {exc}") from exc
    try:
        return GoldenReport.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"golden file {path.name} failed validation: {exc}") from exc
