"""Shared helpers for the reducer-slot tests (not a test module; OME-1289)."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.operators import _OperatorCatalog, decode_operator_catalog
from screamingface.reducer import Reducer, _ReducerKind, _ReducerName, _Step, _Steps


def _entry(name: str, version: int, stage: str) -> dict[str, object]:
    return {
        "id": f"{name}@{version}",
        "name": name,
        "version": version,
        "stage": stage,
        "args_schema": {},
        "summary": f"{name} v{version}.",
    }


OPERATOR_WIRE: dict[str, object] = {
    "object": "list",
    "data": [
        _entry("boxed", 1, "extract"),
        _entry("first_holder", 1, "select"),
        _entry("last_line", 1, "extract"),
        _entry("last_number", 1, "extract"),
        _entry("last_number", 2, "extract"),
        _entry("median", 1, "reduce"),
        _entry("mode", 1, "reduce"),
        _entry("numeric", 1, "normalize"),
        _entry("text", 1, "normalize"),
        _entry("value", 1, "select"),
    ],
}


def fixture_operators() -> _OperatorCatalog:
    return decode_operator_catalog(OPERATOR_WIRE)


def operators_response(etag: str = '"v1"', max_age: int = 300) -> httpx.Response:
    return httpx.Response(
        200,
        json=OPERATOR_WIRE,
        headers={"ETag": etag, "Cache-Control": f"public, max-age={max_age}, must-revalidate"},
    )


@dataclass(frozen=True, slots=True, init=False)
class FixtureVote(Reducer):
    """A vote-shaped reducer defined by the tests (the real Vote is a later unit)."""

    name: str
    extract: str
    normalize: str | None
    weights: tuple[float, ...] | None
    extract_args: Mapping[str, object] | None

    def __init__(
        self,
        *,
        extract: str = "last_number",
        normalize: str | None = "numeric",
        weights: tuple[float, ...] | None = None,
        extract_args: Mapping[str, object] | None = None,
    ) -> None:
        object.__setattr__(self, "name", "vote")
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "normalize", normalize)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "extract_args", extract_args)

    @property
    def _reducer(self) -> _ReducerName:
        return "vote"

    @property
    def _kind(self) -> _ReducerKind:
        return "answer"

    def _steps(self) -> _Steps:
        return _Steps(
            extract=_Step(self.extract, self.extract_args),
            normalize=None if self.normalize is None else _Step(self.normalize),
            reduce=_Step("mode"),
            select=_Step("first_holder"),
        )

    def _weights(self) -> tuple[float, ...] | None:
        return self.weights

    def _check_members(self, count: int) -> None:
        if self.weights is not None and len(self.weights) != count:
            raise ValueError(f"{self.name} has {len(self.weights)} weights for {count} members")

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> FixtureVote:
        extract = spec["extract"]
        normalize = spec["normalize"]
        weights = spec["weights"]
        assert isinstance(extract, Mapping)
        return cls(
            extract=str(extract["op"]),
            normalize=None if normalize is None else str(normalize["op"]),  # type: ignore[index]
            weights=None if weights is None else tuple(weights.values()),  # type: ignore[attr-defined]
            extract_args=extract["args"] or None,  # type: ignore[arg-type]
        )

    def __repr__(self) -> str:
        arguments = [f"extract={self.extract!r}", f"normalize={self.normalize!r}"]
        if self.weights is not None:
            arguments.append(f"weights={self.weights!r}")
        if self.extract_args:
            arguments.append(f"extract_args={dict(self.extract_args)!r}")
        return f"FixtureVote({', '.join(arguments)})"

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False)
class FixtureJudgeish(Reducer):
    """A judge-shaped reducer: no extract or normalize step (valid for the Engine's judge rule).

    It keeps the base-class defaults for weights and member checks.
    """

    name: str

    def __init__(self) -> None:
        object.__setattr__(self, "name", "judge")

    @property
    def _reducer(self) -> _ReducerName:
        return "judge"

    @property
    def _kind(self) -> _ReducerKind:
        return "answer"

    def _steps(self) -> _Steps:
        return _Steps(reduce=_Step("median"), select=_Step("value"))

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> FixtureJudgeish:
        del spec
        return cls()

    def __repr__(self) -> str:
        return "FixtureJudgeish()"

    __hash__: ClassVar[Any] = None


def reducer_fusion(**kw: Any) -> sf.Fusion:
    return sf.Fusion(["provider/a", "provider/b", "provider/c"], synthesizer=FixtureVote(**kw))


def compiled_vote_url4() -> str:
    return compile_candidate(reducer_fusion(), operators=fixture_operators()).url4


def evidence_wire(member_count: int = 3, **overrides: Any) -> dict[str, Any]:
    ids = [f"member_{index}" for index in range(1, member_count + 1)]
    wire: dict[str, Any] = {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "vote",
        "operators": ["last_number@1", "numeric@1", "mode@1", "first_holder@1"],
        "members": [
            {
                "member_id": member,
                "raw": "12",
                "value": "12",
                "status": "answered",
                "reason": None,
                "signals": {},
                "weight": 1.0,
                "score": 1.0,
            }
            for member in ids
        ],
        "tally": [{"value": "12", "score": float(member_count), "holders": list(ids)}],
        "judge": None,
        "fields": None,
        "chosen": ["member_1"],
        "built": False,
        "agreement": 1.0,
        "tie": False,
        "median": None,
        "presentation_order": None,
        "separator_collision": None,
        "signal": None,
        "result": {"member_id": "member_1", "value": "12", "status": "answered", "reason": None},
        "dropped": 0,
        "finish_reason": "stop",
    }
    wire.update(copy.deepcopy(overrides))
    return wire
