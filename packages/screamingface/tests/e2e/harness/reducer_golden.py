"""The golden of the GSM8K vote replay lane, and its evidence lock (OME-1289 E4a, EV-12).

Mental model: ``goldens.GoldenReport`` is the answer sheet of one board replay and it carries FIVE
locks (expression sha, case statuses, failure codes, coverage, score). A reducer lane needs the same
five plus one more: what the combine step read and decided for one case. This module is the answer
sheet of that lane. It does not copy the five locks. ``ReducerGolden.outcome()`` maps the golden to
a ``GoldenReport`` (``kind: "model"``, with the candidate's route as the one model), so
``goldens.compare_outcome`` runs them UNCHANGED (it never reads ``kind``). The sixth lock is
``assert_evidence_lock``.

Two more claims ride on the same recording (OME-1289 E4a, SG#15 and RT#16). ``SignalReplayLock``
holds the evidence of a live cost-weighted vote, and ``assert_signal_replay`` demands that the
cached replay gives the same signals, weights, tally and result (SG-D1). ``live_traces`` holds the
two live ``report-trace.v1`` documents, which ``replay_trace.trace_drift`` holds to the replay's.

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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from screamingface.case_result import CaseStatus
from screamingface.report_trace import TRACE_SCHEMA

from .goldens import GoldenFailure, GoldenReport, expression_sha

REDUCER_GOLDEN_SCHEMA: Final = "screamingface.reducer-golden.v1"

_SHA256_HEX = r"^[0-9a-f]{64}$"
_MEMBER_PREFIX: Final = "member_"
_BOARD_REFRESH_ADVICE: Final = re.compile(
    r" — re-bless this golden from its committed snapshot \(`just e2e-refresh-golden [^`]*`\)"
)
_SCRIPT: Final = "tests/e2e/fixtures/reducer_lane.py"
_MAX_SAMPLES: Final = 256  # sf.samples()'s own bound
_SIGNAL_KEY: Final = "cost_usd"
_OPERATION_ID: Final = "op_synthesis_1"
_PRICED_NOTHING: Final = (
    "the recording priced no call, so the signal replay (SG#15) would prove nothing"
)


class ReducerCandidateSpec(BaseModel):
    """The replay INPUT of a reducer lane: what ``build()`` turns into the recorded candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    samples: int = Field(ge=1, le=_MAX_SAMPLES)
    temperature: float | None
    extract: str = Field(min_length=1)
    normalize: str | None
    weights: Literal["cost_usd"] | None = None

    def build(self):  # -> sf.Fusion
        """Fusion of ``samples`` seeded Models of ``model`` with a ``Vote`` synthesizer.

        ``weights="cost_usd"`` makes it the cost-weighted vote of the SG#15 claim.
        """
        import screamingface as sf

        weights = None if self.weights is None else sf.signal(self.weights)
        return sf.Fusion(
            list(sf.samples(self.model, self.samples, temperature=self.temperature)),
            synthesizer=sf.Vote(extract=self.extract, normalize=self.normalize, weights=weights),
        )


class EvidenceLock(BaseModel):
    """The pinned combine evidence: one case, one operation, as ``to_dict()`` wrote it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    operation_id: str = "op_synthesis_1"
    combine: dict[str, Any]


class SignalReplayLock(BaseModel):
    """SG#15: the live cost-weighted vote's evidence per Case, which the replay must repeat."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    weights: Literal["cost_usd"] = "cost_usd"
    expression_sha: str = Field(pattern=_SHA256_HEX)
    combines: dict[str, dict[str, Any]]

    @field_validator("combines")
    @classmethod
    def _some_call_was_priced(
        cls, combines: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        # INVARIANT: a replay can only prove signals if the live run had a price to repeat.
        if not has_priced_signal(combines):
            raise ValueError(_PRICED_NOTHING)
        return combines


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
    signal_replay: SignalReplayLock
    live_traces: dict[Literal["vote", "signal_vote"], dict[str, Any]]

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
            raise ValueError(lane_remediation(str(exc), _SCRIPT)) from exc
        if self.evidence.case_id not in self.case_statuses:
            raise ValueError(
                f"evidence pins case {self.evidence.case_id!r} that case_statuses does not list"
            )
        return self

    @model_validator(mode="after")
    def _carries_both_live_traces(self) -> ReducerGolden:
        # INVARIANT: RT#16 compares two replays with two live traces, and each is a trace document.
        missing = {"vote", "signal_vote"} - set(self.live_traces)
        if missing:
            raise ValueError(f"live_traces lacks {', '.join(sorted(missing))}")
        for name, trace in self.live_traces.items():
            if trace.get("schema") != TRACE_SCHEMA:
                raise ValueError(f"live_traces[{name!r}] is not a {TRACE_SCHEMA} document")
        return self


def lane_remediation(message: str, script: str) -> str:
    """GoldenReport's advice names the board refresh recipe, which cannot refresh a lane.

    ``script`` is the lane's own record and bless script, e.g. ``tests/e2e/fixtures/x_lane.py``.
    """
    return _BOARD_REFRESH_ADVICE.sub(f" — re-record and re-bless the lane ({script})", message)


def load_golden[Model: BaseModel](path: Path, model: type[Model]) -> Model:
    """Read + validate one lane golden file; any shape problem raises at load time, by file name."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"golden file {path.name} is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"golden file {path.name} failed validation: {exc}") from exc


def load_reducer_golden(path: Path) -> ReducerGolden:
    """Read + validate one ``*.reducer-golden.json``; any shape problem raises at load time."""
    return load_golden(path, ReducerGolden)


def assert_evidence_lock(golden: ReducerGolden, cases: Sequence[Any]) -> None:
    """The sixth lock: the pinned case's combine evidence, read off the replayed ``CaseResult`` s.

    Raises ``AssertionError`` naming the first thing that is wrong: the case or its combine
    evidence is missing, the evidence differs from the golden, the pinned case did not answer with
    its chosen member, the readings are not one per sample, the agreement is not in (0, 1], the
    synthesis text is not the chosen member's text, character for character, or a member operation
    has no output (EV-H3).
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


def has_priced_signal(combines: Mapping[str, Mapping[str, Any]]) -> bool:
    """True when some member row of some Case holds a real number under ``signals.cost_usd``."""
    return any(
        _is_number(row.get("signals", {}).get(_SIGNAL_KEY))
        for combine in combines.values()
        for row in combine.get("members", ())
    )


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def replayed_combines(cases: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """case id -> the JSON form of the ``op_synthesis_1`` combine evidence (absent when none)."""
    return {
        str(case.case_id): json.loads(json.dumps(operation.combine.to_dict()))
        for case in cases
        for operation in case.operations or ()
        if operation.operation_id == _OPERATION_ID and operation.combine is not None
    }


def combines_drift(
    expected: Mapping[str, Mapping[str, Any]], actual: Mapping[str, Mapping[str, Any]]
) -> str | None:
    """Name the first Case whose evidence differs, or None. ``signals`` when only they moved."""
    for case_id in (*expected, *(key for key in actual if key not in expected)):
        if expected.get(case_id) != actual.get(case_id):
            return _describe_drift(case_id, expected.get(case_id), actual.get(case_id))
    return None


def _describe_drift(
    case_id: str, expected: Mapping[str, Any] | None, actual: Mapping[str, Any] | None
) -> str:
    if expected is None or actual is None:
        where = "recording" if expected is None else "replay"
        return f"case {case_id!r} is missing from the {where}"
    if _without_signals(expected) == _without_signals(actual):
        return (
            f"case {case_id!r} drifted in signals (recorded, replayed): "
            f"{_signal_rows(expected)!r} != {_signal_rows(actual)!r}"
        )
    keys = sorted(key for key in {*expected, *actual} if expected.get(key) != actual.get(key))
    return f"case {case_id!r} drifted in more than the signals (differing keys: {', '.join(keys)})"


def _signal_rows(combine: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {row["member_id"]: (row["signals"], row["weight"]) for row in combine["members"]}


def _without_signals(combine: Mapping[str, Any]) -> dict[str, Any]:
    members = [
        {key: value for key, value in row.items() if key not in ("signals", "weight")}
        for row in combine["members"]
    ]
    return {**combine, "members": members}


def assert_signal_replay(golden: ReducerGolden, rendered_url4: str, cases: Sequence[Any]) -> None:
    """SG#15: the cached replay of the cost-weighted vote repeats the live run's evidence.

    Raises ``AssertionError`` naming the first thing that is wrong: the candidate rebuilt another
    url4, or a Case's signals, weights, tally or result differ from the recorded ones (SG-D1).
    """
    lock = golden.signal_replay
    if expression_sha(rendered_url4) != lock.expression_sha:
        raise AssertionError("the signal candidate rebuilt a different url4 than the recording")
    drift = combines_drift(lock.combines, replayed_combines(cases))
    if drift is not None:
        raise AssertionError(
            f"the cached replay's signals or tally differ from the live run's (SG-D1): {drift}"
        )
