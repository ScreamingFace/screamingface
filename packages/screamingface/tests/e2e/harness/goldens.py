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
3. **coverage** — the REPORT'S OWN coverage figure must equal what the golden's
   counters imply (``gradeable_count / case_count``). Stage 2 already pins the raw
   statuses, so this stage deliberately checks the one thing statuses cannot see: the
   report's independently derived aggregation. Matching statuses with a contradicting
   coverage figure means the SDK's aggregation math drifted — a different bug than a
   replay drift, named separately.
4. **score** — last, the final score, compared as DECIMAL STRINGS. The SDK reports a
   float; ``canonical_score`` renders it as the shortest round-trip decimal (`repr`), so
   the golden holds ``"0.5"``, not a float that two JSON writers could disagree about.

Worked example: golden ``final_score="0.5"``, ``case_statuses={"c1": "scored",
"c2": "refused"}``, so ``case_count=2`` and ``gradeable_count=1`` (only ``c1`` carries a
grade). A run whose expression drifted fails at stage 1 even if it also scored 0.0; a
run with the right expression but ``c1: "failed"`` fails at stage 2; only a run clean
through stages 1–3 can ever fail on the score.

Deliberately absent: progress or stream fields (``extra="forbid"`` enforces it), floats
anywhere in the file, and timestamps/run ids (nondeterministic by nature).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# The SDK's OWN status vocabulary — imported, not mirrored, so it cannot drift
# (owner review finding on OME-961).
from screamingface.case_result import CaseStatus

GOLDEN_SCHEMA: Final = "screamingface.golden-report.v1"

_SHA256_HEX = r"^[0-9a-f]{64}$"

_GRADEABLE: Final = "scored"

#: The SDK rounds its coverage figure to 4 places (``report._coverage``); the stage-3
#: compare rounds identically so the two sides speak the same precision.
_COVERAGE_PLACES: Final = 4


class GoldenMismatch(AssertionError):
    """One staged comparison failed; ``stage`` names which rung of the ladder."""

    def __init__(self, stage: Literal["expression", "cases", "coverage", "score"], message: str):
        self.stage = stage
        super().__init__(message)


class GoldenReport(BaseModel):
    """The frozen expected outcome of one board replay.

    ``models`` and ``limit`` are the replay INPUTS (which candidate to build, how many
    cases to select) — without them a golden could not be re-run; everything else is
    the expected OUTPUT.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_: str = Field(alias="schema", default=GOLDEN_SCHEMA)
    board: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    models: tuple[str, ...] = ()
    limit: int | None = None
    expression_sha: str = Field(pattern=_SHA256_HEX)
    final_score: str | None
    case_count: int = Field(ge=0)
    gradeable_count: int = Field(ge=0)
    case_statuses: dict[str, CaseStatus]

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
    """What one fresh replay actually produced — the four facts the ladder checks.

    ``coverage`` is the report's OWN aggregated figure (``CandidateResult.coverage``),
    passed through rather than re-derived from ``case_statuses`` — that independence is
    what makes stage 3 a real check instead of a restatement of stage 2.
    """

    rendered_url4: str
    final_score: float | None
    case_statuses: dict[str, str]
    coverage: float


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
    Stage 2 — case statuses. Stage 3 — the report's own coverage figure against the
    golden's counters. Stage 4 — score as decimal strings.
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
    # Stage 3 — deliberately NOT re-counting actual.case_statuses (stage 2 pinned those
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
