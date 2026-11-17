"""The Candidate Result, built one marked Case at a time: held in memory, or parked on disk.

FEATURE memory fix 3 (OME-1835), unit 2. ``finalize_candidate_result`` used to take the list of
every full ``CaseResult``, so the aggregate held all of them until the result left the Engine.
Now each marked Case goes through ``CandidateResultBuilder.add`` once:

    add(case) ──► replay flag (from the FULL Case)
        held   ──► keep the Case itself                      finish_result() ──► CandidateResult
        parked ──► wire JSON (input echoed) ──► the run's Case-result store (or in memory)
               └─► keep scoring_projection(case)             finish_body()  ──► ParkedResultBody

    ParkedResultBody.case_fragments():  read the parked text ──► late accounting ──► the fragment

Think of a cloakroom again. The coat (the full Case) goes on the rack when it arrives; the
builder keeps only the ticket and a small card with what the scorer reads (the projection).
At the end, the cards are ordered, counted and scored, and the coats are brought back one at a
time while the body is written.

INVARIANT (one finalize implementation): the held and the parked path share ``_settle`` (order,
fill, tally, score) and ``_result`` (the CandidateResult and its whole-set validators). The held
path is ``finalize_candidate_result``; the parked body writes the same bytes as
``compact_json(finalize_candidate_result(...).as_payload())``.
INVARIANT (fail closed): a parked Case that cannot be read raises ``CaseResultStoreError``. A
Case that cannot be parked raises ``CaseParkingError``, never an OSError or a ValueError.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    Scorer,
    SelectedCase,
    policy_cases,
)
from screamingface_engine.benchmarks.case_result_store import (
    CaseResultStore,
    CaseResultStoreError,
)
from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    CaseId,
    CaseResult,
    Failure,
    candidate_coverage,
)
from screamingface_engine.benchmarks.definition import FailurePolicy
from screamingface_engine.benchmarks.echoed_input import echoed_input
from screamingface_engine.benchmarks.replay_stability import replay_stable_failure
from screamingface_engine.benchmarks.result_body import compact_json
from screamingface_engine.benchmarks.scoring_projection import scoring_projection
from screamingface_engine.capture_outcomes import record_case_results
from screamingface_engine.grading_accounting import (
    GradingAccountingView,
    grading_accounting_view,
    reconcile_candidate_grading_accounting,
    reconcile_case_accounting_text,
)


class CaseParkingError(RuntimeError):
    """A marked Case could not be parked in the run's Case-result store.

    WHY RuntimeError: the aggregate endpoints map OSError and ValueError to
    ``benchmark_unavailable``, and a disk or store failure must never become
    ``benchmark_unavailable``.
    """


@dataclass(frozen=True, slots=True)
class ParkedCase:
    """One position of the parked body. Exactly one of ``key`` and ``fragment`` is set.

    ``key`` when a store is bound; ``fragment`` (the compact JSON, in memory) when none is.
    ``case_id`` is the original CaseId (int or str): the grading owner key needs it as is.
    """

    case_id: CaseId
    key: str | None
    fragment: str | None


@dataclass(frozen=True, slots=True)
class ParkedResultBody:
    """A finished Candidate Result whose Cases are parked; it satisfies ``ResultBody``.

    INVARIANT: re-iterable. Each ``case_fragments()`` call reads the parked text again, so the
    body can be written twice with the same bytes.
    INVARIANT: thread-safe to write. ``accounting`` is a frozen view taken on the run loop when
    the body was finished; the writer (on the spool's worker thread) reads only that view and
    the parked text, never the run's live grading registry or request ledger.
    """

    benchmark_id: str
    case_count: int
    head_payload: dict[str, Any]
    cases: tuple[ParkedCase, ...]
    store: CaseResultStore | None
    accounting: GradingAccountingView | None = None

    def head(self) -> dict[str, Any]:
        return dict(self.head_payload)

    def case_fragments(self) -> Iterator[str]:
        # WHY None writes verbatim: today's reconcile changes nothing unless a grading registry
        # and a request ledger are both bound, and then there is no view.
        for parked in self.cases:
            text = self._text(parked)
            if self.accounting is not None:
                text = reconcile_case_accounting_text(
                    text,
                    benchmark_id=self.benchmark_id,
                    case_id=parked.case_id,
                    view=self.accounting,
                )
            yield text

    def _text(self, parked: ParkedCase) -> str:
        if parked.fragment is not None:
            return parked.fragment
        if self.store is None or parked.key is None:
            raise CaseResultStoreError(f"Case {parked.case_id!r} has no parked Case result")
        return self.store.read_text(parked.key)


@dataclass(frozen=True, slots=True)
class _Marked:
    """What the builder keeps of one marked Case: the view, the replay flag, the ticket.

    ``invalid`` is set only in parked mode, and only when the full Case breaks a CaseResult rule:
    it is the echoed-input copy today's CandidateResult gets, so ``finish_body`` raises today's
    ValidationError. A valid Case keeps nothing here, so memory stays flat.
    """

    case_id: CaseId
    view: CaseResult
    replay: bool
    key: str | None
    fragment: str | None
    invalid: CaseResult | None = None


class CandidateResultBuilder:
    """Collect marked Cases one at a time and finish them as a Candidate Result.

    Held (``parked=False``): the view is the Case itself, and ``finish_result`` returns today's
    ``CandidateResult``. Parked: the view is the scoring projection, the Case's wire JSON goes
    to ``store`` (or stays in memory when there is none), and ``finish_body`` returns a
    ``ParkedResultBody``.
    WHY no validation here: ``finalize_candidate_result`` validates its inputs first, and the
    whole-set checks run at finish, so today's error precedence holds.
    """

    def __init__(
        self,
        *,
        benchmark_id: str,
        benchmark_revision: str,
        selected_cases: Sequence[SelectedCase],
        scorer: Scorer,
        failure_policy: FailurePolicy,
        failures: Sequence[Failure] = (),
        inverted_grade: bool = False,
        parked: bool = False,
        store: CaseResultStore | None = None,
    ) -> None:
        self._benchmark_id = benchmark_id
        self._benchmark_revision = benchmark_revision
        self._selected = tuple(selected_cases)
        self._scorer = scorer
        self._failure_policy: FailurePolicy = failure_policy
        self._failures = tuple(failures)
        self._inverted_grade = inverted_grade
        self._parked = parked
        self._store = store
        self._marked: list[_Marked] = []
        self._added = 0
        self._filled: tuple[CaseResult, ...] = ()

    @property
    def added(self) -> int:
        """The number of ``add`` calls."""

        return self._added

    @property
    def filled(self) -> tuple[CaseResult, ...]:
        """The fill-in Cases (case_result_missing) of the last finish; empty before a finish."""

        return self._filled

    def add(self, case: CaseResult) -> CaseResult:
        """Take one marked Case and return its view (the Case, or its scoring projection)."""

        self._added += 1
        marked = self._mark(case)
        self._marked.append(marked)
        return marked.view

    def finish_result(self) -> CandidateResult:
        """The held CandidateResult, byte-for-byte today's ``finalize_candidate_result``."""

        if self._parked:
            raise RuntimeError("a parked CandidateResultBuilder finishes with finish_body()")
        ordered, scored = self._settle()
        views = [m.view for m in ordered]
        # FEATURE (OME-1271): this is where a Candidate result leaves the engine, so here each
        # Case's echoed input loses its pictures' base64 to their placeholders.
        # INVARIANT: after the scorer, so grading and scoring saw the real Case; a text Case's
        # input is the same string, so its result is byte-identical.
        cases = [view.model_copy(update={"input": echoed_input(view.input)}) for view in views]
        result = self._result(cases, scored, views)
        reconcile_candidate_grading_accounting(result)
        return result

    def finish_body(self) -> ParkedResultBody:
        """The parked body: the light result's head plus one parked Case per position."""

        if not self._parked:
            raise RuntimeError("a held CandidateResultBuilder finishes with finish_result()")
        ordered, scored = self._settle()
        # WHY a light result: it runs every whole-set validator once (case_count, duplicates,
        # coverage, the score and metrics rules); only its head is kept. The light result and its
        # stand-ins are locals: they never live on the builder or in the body.
        light = self._result([_stand_in(m) for m in ordered], scored, [m.view for m in ordered])
        head_payload = light.model_copy(update={"cases": []}).as_payload()
        del light
        return ParkedResultBody(
            benchmark_id=self._benchmark_id,
            case_count=len(ordered),
            head_payload=head_payload,
            cases=tuple(ParkedCase(m.case_id, m.key, m.fragment) for m in ordered),
            store=self._store,
            # WHY here: the same point as the held reconcile (every owner has registered), and
            # on the run loop, before the body goes to the spool's worker thread.
            accounting=grading_accounting_view(),
        )

    def _mark(self, case: CaseResult) -> _Marked:
        # FEATURE: OME-1775 — the replay flag is computed on the FULL Case (Attempts included);
        # the projection keeps no Attempt failures.
        replay = not replay_stable_failure(case)
        if not self._parked:
            return _Marked(case.case_id, case, replay, None, None)
        # INVARIANT: the input is echoed before parking, as finish_result echoes it; echoed_input
        # is pure, so the parked wire JSON equals the held Case's fragment.
        echoed = case.model_copy(update={"input": echoed_input(case.input)})
        key, fragment = self._park(case.case_id, echoed.model_dump(by_alias=True))
        invalid = None if _is_valid_case(case) else echoed
        return _Marked(case.case_id, scoring_projection(case), replay, key, fragment, invalid)

    def _park(self, case_id: CaseId, wire: dict[str, Any]) -> tuple[str | None, str | None]:
        if self._store is None:
            return None, compact_json(wire)
        try:
            return self._store.append(wire), None
        except UnicodeEncodeError as exc:
            raise CaseParkingError(
                f"Case {case_id!r} has text that cannot be encoded as UTF-8: {exc}"
            ) from exc
        except (OSError, CaseResultStoreError) as exc:
            raise CaseParkingError(f"Case {case_id!r} could not be parked: {exc}") from exc

    def _settle(self) -> tuple[list[_Marked], CandidateScore | None]:
        """Validate, order, fill, tally and score, in today's order."""

        selected_ids = [selected.case_id for selected in self._selected]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("selected Case sequence cannot contain duplicate case_id values")
        added_ids = [marked.case_id for marked in self._marked]
        if len(added_ids) != len(set(added_ids)):
            raise ValueError("CandidateResult cannot contain duplicate case_id values")
        unexpected = sorted(set(added_ids) - set(selected_ids), key=str)
        if unexpected:
            raise ValueError(f"CandidateResult contains unselected case_id values {unexpected!r}")
        ordered = self._ordered()
        # FEATURE: OME-1775 — R1 needs each Case's final result; every final Case result passes
        # here, once per Candidate. Unknown, retryable and time-based failures may recover on
        # replay; only positively identified deterministic failures are eligible for the
        # stored-proof check.
        record_case_results((marked.case_id, marked.replay) for marked in ordered)
        scoring_cases = policy_cases([marked.view for marked in ordered], self._failure_policy)
        scored = self._scorer(scoring_cases) if scoring_cases is not None else None
        return ordered, scored

    def _ordered(self) -> list[_Marked]:
        """The marked Cases in roll-call order; a selected Case with none gets today's fill."""

        by_id = {marked.case_id: marked for marked in self._marked}
        ordered: list[_Marked] = []
        fills: list[CaseResult] = []
        for selected in self._selected:
            marked = by_id.get(selected.case_id)
            if marked is None:
                marked = self._mark(_missing_case_result(selected))
                fills.append(marked.view)
            ordered.append(marked)
        self._filled = tuple(fills)
        return ordered

    def _result(
        self,
        cases: list[CaseResult],
        scored: CandidateScore | None,
        views: Sequence[CaseResult],
    ) -> CandidateResult:
        """Today's CandidateResult over ``cases``; coverage is counted over the scoring views.

        WHY ``views``: candidate_coverage reads only ``grade.score``, which a projection keeps,
        so the views give today's coverage in both modes.
        """

        return CandidateResult(
            benchmark_id=self._benchmark_id,
            benchmark_revision=self._benchmark_revision,
            case_count=len(cases),
            score=scored.score if scored is not None else None,
            coverage=candidate_coverage(views, len(views)),
            metrics=scored.metrics if scored is not None else {},
            cases=cases,
            failures=list(self._failures),
            inverted_grade=self._inverted_grade,
            scores=scored.scores if scored is not None else {},
        )


def _is_valid_case(case: CaseResult) -> bool:
    """True when the full Case obeys every CaseResult rule (its after-validator runs again).

    WHY: today's CandidateResult re-runs that validator on each Case it gets and lists every
    invalid one in its ValidationError. A projection cannot show which full Case was invalid,
    so the parked builder asks here, before the Case is projected.
    """

    try:
        CaseResult.model_validate(case)
    except ValidationError:
        return False
    return True


def _stand_in(marked: _Marked) -> CaseResult:
    """The Case the light result validates at this position: never the parked Case itself.

    WHY: CandidateResult runs the CaseResult after-validator on each instance, and a projection
    is not a valid Case (a scored projection has neither output nor refusal; Attempts are []).
    The stand-in keeps every fact the whole-set validators read: case_id, status, grade.score,
    failures[].case_id, stop_reason/rounds_executed. It never reaches the wire. An invalid full
    Case stands in as itself, so the light result raises today's ValidationError.
    INVARIANT: this relies on pydantic re-running only the model after-validators on an instance
    it already holds (revalidate_instances='never'); field validators do not run again (a
    projection's Failure.message is ''). If the wire models ever set revalidate_instances='always',
    this stand-in must change.
    """

    if marked.invalid is not None:
        return marked.invalid
    view = marked.view
    return view.model_copy(
        update={"output": "" if view.status == "scored" else None, "attempts": None}
    )


def _missing_case_result(selected: SelectedCase) -> CaseResult:
    """Today's fill for a selected Case that produced no Case Result."""

    return CaseResult(
        status="failed",
        case_id=selected.case_id,
        input=selected.input,
        output=None,
        finish_reason=None,
        refusal=None,
        grade=None,
        failures=[
            Failure(
                stage="aggregation",
                code="case_result_missing",
                message="the selected Case produced no Case Result",
                retryable=None,
                case_id=selected.case_id,
                metadata={},
            )
        ],
        metadata=selected.metadata,
    )


__all__ = [
    "CandidateResultBuilder",
    "CaseParkingError",
    "ParkedCase",
    "ParkedResultBody",
]
