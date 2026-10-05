"""Versioned JSON recovery metadata; never pickle or authentication credentials."""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime
from decimal import Decimal
from typing import Any

from screamingface._core.ports import _ResultArtifact, _RunOutcome
from screamingface._evaluation.model import (
    Candidate,
    _compiled_candidate,
    _MemberProjection,
    _with_answer_seed,
)
from screamingface.operation import OperationInfo
from screamingface.report import Usage


def candidate_data(candidate: Candidate) -> dict[str, object]:
    # WHY: excluded preflight assignments contain mappingproxy values; never deep-copy them.
    return {
        "name": candidate.name,
        "kind": candidate.kind,
        "models": candidate.models,
        "url4": candidate.url4,
        "operations": [asdict(operation) for operation in candidate.operations],
        "members": [asdict(member) for member in candidate.members],
        "answer_seed": candidate.answer_seed,
    }


def candidate_value(data: dict[str, Any]) -> Candidate:
    values = dict(data)
    seed = values.pop("answer_seed")
    values["operations"] = [OperationInfo(**v) for v in values["operations"]]
    values["members"] = [
        _MemberProjection(**{**v, "models": tuple(v["models"])}) for v in values["members"]
    ]
    values["known_operation_ids"] = tuple(
        {op.id for op in values["operations"]}
        | {member.operation_id for member in values["members"]}
    )
    candidate = _compiled_candidate(**values)
    return candidate if seed is None else _with_answer_seed(candidate, seed)


def outcome_data(outcome: _RunOutcome) -> dict[str, object]:
    # INVARIANT: large result bodies and filesystem paths are not copied into metadata.
    return {
        f.name: getattr(outcome, f.name)
        for f in fields(outcome)
        if f.name not in ("result_body", "result_path")
    }


def outcome_value(data: dict[str, Any]) -> _RunOutcome:
    values = dict(data)
    for key in ("started_at", "completed_at"):
        values[key] = datetime.fromisoformat(values[key])
    for key in ("cache_saved_cost_usd", "cache_saved_cost_archive_usd"):
        if values.get(key) is not None:
            values[key] = Decimal(values[key])
    if values["root_usage"] is not None:
        usage = values["root_usage"]
        if usage.get("cost_usd") is not None:
            usage["cost_usd"] = Decimal(usage["cost_usd"])
        values["root_usage"] = Usage(**usage)
    if values["artifact"] is not None:
        values["artifact"] = _ResultArtifact(**values["artifact"])
    return _RunOutcome(**values, result_body=None)


def json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Usage | _ResultArtifact):
        return asdict(value)
    raise TypeError(f"Unsupported recovery metadata: {type(value).__name__}")
