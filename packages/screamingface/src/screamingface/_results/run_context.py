"""What the Client sends with a Run so its Report can be rebuilt anywhere (E5 P2 spec D9b).

FEATURE: a detached Run (OME-1837). STORY: as a researcher who reattaches from another machine,
the Report I get is the one the machine that started the Run would have built.

The Engine keeps the context unread, beside the Run, and serves it back to the Run's owner. It
holds the benchmark, the selection and each compiled Candidate without its url4 and seed; the
Candidate's start, which the Run also keeps, holds those and the start's flags.

INVARIANT: ``evaluation_from_context(run_context(e, cs), starts_of(cs))`` gives back ``e``'s
benchmark, selection and models, and ``cs`` themselves.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, NoReturn

from screamingface._engine.runs import StartRequest
from screamingface._evaluation.model import (
    Candidate,
    _compiled_evaluation,
    _Evaluation,
    _with_capture,
    _with_replay_frozen_copy,
    _without_cache,
)
from screamingface._results.codec import candidate_data, candidate_value, json_default
from screamingface.discovery import BenchmarkInfo
from screamingface.errors import ExecutionError

SCHEMA = "screamingface.run-context.v1"
#: What a raw-URL4 or replay evaluation is called before it runs: in the progress output, and as
#: its Run's benchmark, with 0 (unknown) Cases (E5 P1 spec D8).
URL4_RUN_LABEL = "URL4 replay"
#: Held by the Candidate's start, so kept out of the context.
_IN_THE_START = ("url4", "answer_seed")


def run_context(evaluation: _Evaluation | None, candidates: Sequence[Candidate]) -> str:
    """``evaluation`` is None for a raw-url4 or replay evaluation: its context is its Candidates."""
    described = [
        {key: value for key, value in candidate_data(c).items() if key not in _IN_THE_START}
        for c in candidates
    ]
    if evaluation is None:
        return json.dumps(
            {"schema": SCHEMA, "benchmark": None, "candidates": described},
            default=json_default,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return json.dumps(
        {
            "schema": SCHEMA,
            "benchmark": asdict(evaluation.benchmark),
            "limit": evaluation.limit,
            "case_count": evaluation.case_count,
            "selected_cases": (
                None if evaluation.selected_cases is None else list(evaluation.selected_cases)
            ),
            "required_models": list(evaluation.required_models),
            "candidates": described,
        },
        default=json_default,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def evaluation_from_context(
    context: str, starts: Sequence[StartRequest]
) -> tuple[_Evaluation | None, tuple[Candidate, ...]]:
    """The evaluation and its Candidates, from the Run's context and its Candidates' starts;
    the evaluation is None for a raw-url4 or replay Run, which has no benchmark."""
    try:
        value = json.loads(context)
        if not isinstance(value, dict) or value.get("schema") != SCHEMA:
            _invalid()
        described = value["candidates"]
        if not isinstance(described, list) or len(described) != len(starts):
            _invalid()
        candidates = tuple(
            _candidate(data, start) for data, start in zip(described, starts, strict=True)
        )
        if value["benchmark"] is None:
            return None, candidates
        selected = value["selected_cases"]
        evaluation = _compiled_evaluation(
            benchmark=BenchmarkInfo(**value["benchmark"]),
            limit=value["limit"],
            case_count=value["case_count"],
            candidates=candidates,
            required_models=tuple(value["required_models"]),
            selected_cases=None if selected is None else tuple(selected),
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise _invalid_error() from exc
    return evaluation, candidates


def _candidate(data: Mapping[str, Any], start: StartRequest) -> Candidate:
    candidate = candidate_value({**data, "url4": start.url4, "answer_seed": start.answer_seed})
    if start.capture:
        candidate = _with_capture(candidate)
    if not start.use_cache:
        candidate = _without_cache(candidate)
    if start.replay_frozen_copy is not None:
        candidate = _with_replay_frozen_copy(candidate, start.replay_frozen_copy)
    return candidate


def _invalid() -> NoReturn:
    raise _invalid_error()


def _invalid_error() -> ExecutionError:
    return ExecutionError(
        "The Run's context is not one this Client can read",
        code="run_context_invalid",
        permanent=True,
        hint="Open the Run with the screamingface version that started it.",
    )


__all__ = ["SCHEMA", "evaluation_from_context", "run_context"]
