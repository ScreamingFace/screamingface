"""Which Run each Candidate of a transport's evaluations belongs to (E5 P1 spec R1, R2, R8, D7).

FEATURE: first-class Runs (OME-1785). Both transports hold one `RunBindings`: `register` keeps
what `POST /runs` answered, every start of a bound Candidate carries `X-SF-Run` and
`X-SF-Run-Candidate`, a `run_canceled` refusal stops the Run's remaining starts, and an abort
cancels the aborted evaluation's Run.

AIDEV-NOTE: keyed by `id(candidate)`, as the transport's result contexts are: the runner hands the
transport the same Candidate objects it registered. A threading lock, never held across an
`await`, so the async twin may use it too.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from screamingface._engine import runs
from screamingface._environment import SDK_PACKAGE_ROOT
from screamingface._evaluation.model import Candidate
from screamingface._version import resolve_version
from screamingface.errors import ExecutionError
from screamingface.warnings import EvaluationWarning

RUN_HEADER = "X-SF-Run"
CANDIDATE_HEADER = "X-SF-Run-Candidate"
RUN_CANCELED = "run_canceled"
#: The Engine's refusals of a start that names a Run (spec §4.1).
START_REFUSALS = frozenset({runs.RUN_NOT_FOUND, RUN_CANCELED, "candidate_already_started"})


@dataclass(frozen=True, slots=True)
class _Binding:
    # WHY the key too: with a result store, the evaluation's manifest is keyed by the Run's id,
    # or by this key when the Run was not registered (D8).
    client_key: str
    run_id: str | None
    index: int


def run_request(
    client_key: str, benchmark: str, case_count: int, candidates: tuple[Candidate, ...]
) -> runs.RunRequest:
    return runs.RunRequest(
        client_key=client_key,
        benchmark=benchmark,
        case_count=case_count,
        candidates=tuple(candidate.name for candidate in candidates),
        client_version=resolve_version(),
    )


def new_client_key() -> str:
    """A fresh key for every evaluate, saved or not (spec §4.1)."""
    return uuid4().hex


class RunBindings:
    def __init__(self) -> None:
        self._lock = Lock()
        self._bindings: dict[int, _Binding] = {}
        self._canceled: set[str] = set()

    def register(
        self,
        client_key: str,
        result: runs.RunRecord | runs.Unavailable,
        candidates: tuple[Candidate, ...],
    ) -> str | None:
        """Bind ``candidates`` to the registered Run and return its id; or, when `POST /runs`
        failed, give the one notice and return None (D7)."""
        run_id = result.id if isinstance(result, runs.RunRecord) else None
        if isinstance(result, runs.Unavailable):
            warnings.warn(
                "This evaluation was not recorded as a Run, so `sf.runs` will not list it: "
                f"{result.reason}. It runs as before.",
                EvaluationWarning,
                skip_file_prefixes=(SDK_PACKAGE_ROOT,),
            )
        with self._lock:
            for index, candidate in enumerate(candidates):
                self._bindings[id(candidate)] = _Binding(client_key, run_id, index)
        return run_id

    def report_id(self, candidate: Candidate) -> str | None:
        """The id the evaluation's local manifest is keyed by, if ``candidate`` was registered."""
        binding = self._bindings.get(id(candidate))
        return None if binding is None else binding.run_id or binding.client_key

    def headers(self, candidate: Candidate) -> Mapping[str, str]:
        binding = self._bindings.get(id(candidate))
        if binding is None or binding.run_id is None:
            return {}
        return {RUN_HEADER: binding.run_id, CANDIDATE_HEADER: str(binding.index)}

    def refuse_if_canceled(self, candidate: Candidate) -> None:
        """Refuse a start under a Run already refused as canceled, before it mints anything.

        WHY: a cancel from another notebook stops this Client's remaining starts (spec D12);
        the Engine would refuse each of them anyway.
        """
        binding = self._bindings.get(id(candidate))
        with self._lock:
            canceled = binding is not None and binding.run_id in self._canceled
        if canceled:
            raise canceled_error()

    def note_refusal(self, candidate: Candidate, exc: ExecutionError) -> None:
        binding = self._bindings.get(id(candidate))
        if exc.code == RUN_CANCELED and binding is not None and binding.run_id is not None:
            with self._lock:
                self._canceled.add(binding.run_id)

    def forget(self, candidates: tuple[Candidate, ...]) -> None:
        with self._lock:
            for candidate in candidates:
                self._bindings.pop(id(candidate), None)

    def to_cancel(self, candidates: tuple[Candidate, ...]) -> tuple[str, ...]:
        """The Runs of ``candidates`` an abort cancels, each once (spec R8). They count as
        canceled from here: their later starts are refused before they mint anything."""
        with self._lock:
            bindings = [self._bindings.get(id(candidate)) for candidate in candidates]
            run_ids = {b.run_id for b in bindings if b is not None and b.run_id is not None}
            run_ids -= self._canceled
            self._canceled |= run_ids
            return tuple(run_ids)


def canceled_error() -> ExecutionError:
    return ExecutionError(
        "The Run was canceled, so this Candidate did not start",
        code=RUN_CANCELED,
        status=409,
        permanent=True,
    )


__all__ = [
    "CANDIDATE_HEADER",
    "RUN_HEADER",
    "START_REFUSALS",
    "RunBindings",
    "canceled_error",
    "new_client_key",
    "run_request",
]
