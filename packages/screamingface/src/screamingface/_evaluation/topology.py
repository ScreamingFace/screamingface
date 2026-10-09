"""Versioned, inert Recipe topology carried by newly compositional Candidate URL4."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

from url4 import Expression, Node, Source, Text, src

from screamingface.fusion import _quorum

_SCHEMA = "screamingface.recipe.v1"
_SOURCE_NAME = "_sf_recipe"
# A corrective loop nests its whole gated chain as one inner expression bound
# under loop_candidate (OME-796); everything else stays model_N / synthesis_N.
_BINDING = re.compile(r"(?:model|synthesis)_\d+|loop_candidate")
type _TopologyKind = Literal["model", "fusion", "pipeline", "corrective_loop", "self_corrective"]
type _OperationRole = Literal["model", "synthesis"]


@dataclass(frozen=True, slots=True)
class _RecipeTopology:
    """One public Recipe node mapped to its executable result binding."""

    kind: _TopologyKind
    name: str
    binding: str
    named: bool = False
    role: _OperationRole | None = None
    members: tuple[_RecipeTopology, ...] = ()
    synthesizer: _RecipeTopology | None = None
    stages: tuple[_RecipeTopology, ...] = ()
    quorum: int | Literal["all"] = "all"
    optional_members: bool = False
    # Corrective-loop identity (OME-796): the judge role, the cost cap, the
    # check route compiled against (carries the benchmark revision), and the
    # loop protocol revision — run records self-describe with no new mechanism.
    judge: _RecipeTopology | None = None
    max_rounds: int | None = None
    check_route: str | None = None
    protocol: str | None = None


@dataclass(frozen=True, slots=True)
class _TopologyBinding:
    """One executable model call: its leaf node plus both dependency notions."""

    node: _RecipeTopology
    context_dependencies: tuple[str, ...]
    operation_dependencies: tuple[str, ...]


def _topology_bindings(value: _RecipeTopology) -> dict[str, _TopologyBinding]:
    """One walk of a Recipe topology, shared by every consumer.

    Think of it as the topology's dependency rulebook evaluated once: each model
    leaf gets its binding plus TWO dependency tuples, because the same tree carries
    two distinct notions —

    - ``context_dependencies``: which earlier bindings this call's rendered context
      references (a Fusion synthesizer reads the upstream input AND every member's
      answer, deduplicated in that order). Replay validation compares these against
      the ``$``-references parsed out of the executable calls.
    - ``operation_dependencies``: the operation DAG's edges as the compiler records
      them (a Fusion synthesizer depends only on its members — the upstream edge is
      already carried by each member).

    Worked example — ``pipeline(model_1, fusion(members=[model_2], synth))`` where
    the synthesizer executes as ``synthesis_1``: ``model_2`` has context AND
    operation deps ``("model_1",)`` (fusion members inherit the pipeline stage
    input), while ``synthesis_1`` has context deps ``("model_1", "model_2")`` but
    operation deps ``("model_2",)`` only.

    INVARIANT: a new Recipe kind extends THIS walker (one branch), never a fork —
    replay decoding and validation must agree by construction.
    """

    return _TopologyWalker().walk(value)


class _TopologyWalker:
    """Resolve model leaves and their two dependency projections."""

    def __init__(self) -> None:
        self._selected: dict[str, _TopologyBinding] = {}

    def walk(self, value: _RecipeTopology) -> dict[str, _TopologyBinding]:
        self._visit(value, (), ())
        return self._selected

    def _visit(
        self,
        node: _RecipeTopology,
        context: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> None:
        if node.kind == "model":
            self._model(node, context, operations)
        elif node.kind == "pipeline":
            self._pipeline(node, context, operations)
        elif node.kind == "self_corrective":
            self._visit(node.members[0], context, operations)
        elif node.kind == "corrective_loop":
            self._corrective(node, context, operations)
        else:
            self._fusion(node, context, operations)

    def _model(
        self,
        node: _RecipeTopology,
        context: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> None:
        entry = _TopologyBinding(node, context, operations)
        previous = self._selected.setdefault(node.binding, entry)
        if previous != entry:
            raise ValueError("Evaluation URL4 has conflicting Recipe topology metadata")

    def _pipeline(
        self,
        node: _RecipeTopology,
        context: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> None:
        stage_context, stage_operations = context, operations
        for stage in node.stages:
            self._visit(stage, stage_context, stage_operations)
            stage_context = (stage.binding,)
            stage_operations = (stage.binding,)

    def _corrective(
        self,
        node: _RecipeTopology,
        context: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> None:
        for member in node.members:
            self._visit(member, context, operations)
        assert node.judge is not None
        self._visit_reducer(node.judge, node.members, context)

    def _fusion(
        self,
        node: _RecipeTopology,
        context: tuple[str, ...],
        operations: tuple[str, ...],
    ) -> None:
        for member in node.members:
            self._visit(member, context, operations)
        assert node.synthesizer is not None
        self._visit_reducer(node.synthesizer, node.members, context)

    def _visit_reducer(
        self,
        reducer: _RecipeTopology,
        members: tuple[_RecipeTopology, ...],
        context: tuple[str, ...],
    ) -> None:
        member_bindings = tuple(member.binding for member in members)
        self._visit(
            reducer,
            tuple(dict.fromkeys((*context, *member_bindings))),
            member_bindings,
        )


def _topology_source(value: _RecipeTopology) -> Node:
    return src(Text(_encode_topology(value)), name=_SOURCE_NAME, weight=0.0)


def _topology_from_expression(value: Expression) -> _RecipeTopology:
    matches = [
        node for node in value.sources if isinstance(node, Source) and node.name == _SOURCE_NAME
    ]
    if not matches:
        raise ValueError("URL4 Candidate is missing required Recipe metadata")
    if len(matches) != 1 or not isinstance(matches[0].value, Text):
        raise ValueError("URL4 Candidate has invalid Recipe topology metadata")
    raw = matches[0].value.value
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("URL4 Candidate has invalid Recipe topology metadata") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "recipe"}:
        raise ValueError("URL4 Candidate has invalid Recipe topology metadata")
    if payload["schema"] != _SCHEMA:
        raise ValueError("URL4 Candidate has unsupported Recipe topology metadata")
    try:
        return _decode_node(payload["recipe"])
    except RecursionError as exc:
        raise ValueError("URL4 Candidate has invalid Recipe topology metadata") from exc


def _encode_topology(value: _RecipeTopology) -> str:
    payload = {"schema": _SCHEMA, "recipe": _encode_node(value)}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _encode_node(value: _RecipeTopology) -> dict[str, object]:
    return _ENCODERS[value.kind](value)


def _encode_model(value: _RecipeTopology) -> dict[str, object]:
    if value.kind == "model":
        assert value.role is not None
        return {
            "binding": value.binding,
            "kind": value.kind,
            "name": value.name,
            "named": value.named,
            "role": value.role,
        }
    raise AssertionError("model encoder received a non-model node")


def _encode_pipeline(value: _RecipeTopology) -> dict[str, object]:
    return {
        "binding": value.binding,
        "kind": value.kind,
        "name": value.name,
        "named": value.named,
        "stages": [_encode_node(stage) for stage in value.stages],
    }


def _encode_corrective_loop(value: _RecipeTopology) -> dict[str, object]:
    assert value.judge is not None
    return {
        "binding": value.binding,
        "check_route": value.check_route,
        "judge": _encode_node(value.judge),
        "kind": value.kind,
        "max_rounds": value.max_rounds,
        "members": [_encode_node(member) for member in value.members],
        "name": value.name,
        "protocol": value.protocol,
    }


def _encode_self_corrective(value: _RecipeTopology) -> dict[str, object]:
    return {
        "binding": value.binding,
        "check_route": value.check_route,
        "kind": value.kind,
        "max_rounds": value.max_rounds,
        "member": _encode_node(value.members[0]),
        "name": value.name,
        "protocol": value.protocol,
    }


def _encode_fusion(value: _RecipeTopology) -> dict[str, object]:
    assert value.synthesizer is not None
    policy = {}
    if value.quorum != "all" or value.optional_members:
        policy = {"quorum": value.quorum, "optional_members": value.optional_members}
    return {
        **policy,
        "binding": value.binding,
        "kind": value.kind,
        "members": [_encode_node(member) for member in value.members],
        "name": value.name,
        "synthesizer": _encode_node(value.synthesizer),
    }


_ENCODERS: dict[str, Callable[[_RecipeTopology], dict[str, object]]] = {
    "model": _encode_model,
    "pipeline": _encode_pipeline,
    "fusion": _encode_fusion,
    "corrective_loop": _encode_corrective_loop,
    "self_corrective": _encode_self_corrective,
}


def _decode_node(value: object) -> _RecipeTopology:
    if not isinstance(value, dict):
        raise ValueError("URL4 Candidate has invalid Recipe topology metadata")
    kind = value.get("kind")
    name = _text(value.get("name"))
    binding = _binding(value.get("binding"))
    decoder = {
        "model": _decode_model,
        "pipeline": _decode_pipeline,
        "fusion": _decode_fusion,
        "corrective_loop": _decode_corrective_loop,
        "self_corrective": _decode_self_corrective,
    }.get(kind if isinstance(kind, str) else "")
    if decoder is None:
        raise ValueError("URL4 Candidate has invalid Recipe topology metadata")
    return decoder(value, name, binding)


def _decode_model(
    value: dict[object, object],
    name: str,
    binding: str,
) -> _RecipeTopology:
    if set(value) != {"binding", "kind", "name", "named", "role"}:
        raise ValueError("URL4 Candidate has invalid Model topology metadata")
    named = value["named"]
    role = value["role"]
    if not isinstance(named, bool) or role not in {"model", "synthesis"}:
        raise ValueError("URL4 Candidate has invalid Model topology metadata")
    return _RecipeTopology(
        kind="model",
        name=name,
        binding=binding,
        named=named,
        role=cast(_OperationRole, role),
    )


def _decode_pipeline(
    value: dict[object, object],
    name: str,
    binding: str,
) -> _RecipeTopology:
    if set(value) != {"binding", "kind", "name", "named", "stages"}:
        raise ValueError("URL4 Candidate has invalid Pipeline topology metadata")
    named = value["named"]
    stages_value = value["stages"]
    if not isinstance(named, bool) or not isinstance(stages_value, list):
        raise ValueError("URL4 Candidate has invalid Pipeline topology metadata")
    stages = tuple(_decode_node(stage) for stage in stages_value)
    if not stages or binding != stages[-1].binding:
        raise ValueError("URL4 Candidate has invalid Pipeline topology metadata")
    return _RecipeTopology(
        kind="pipeline",
        name=name,
        binding=binding,
        named=named,
        stages=stages,
    )


def _decode_fusion(
    value: dict[object, object],
    name: str,
    binding: str,
) -> _RecipeTopology:
    expected = {"binding", "kind", "members", "name", "synthesizer"}
    if set(value) not in (expected, expected | {"quorum", "optional_members"}):
        raise ValueError("URL4 Candidate has invalid Fusion topology metadata")
    members_value = value["members"]
    if not isinstance(members_value, list):
        raise ValueError("URL4 Candidate has invalid Fusion topology metadata")
    members = tuple(_decode_node(member) for member in members_value)
    synthesizer = _decode_node(value["synthesizer"])
    if not members or binding != synthesizer.binding:
        raise ValueError("URL4 Candidate has invalid Fusion topology metadata")
    optional_members = value.get("optional_members", False)
    if not isinstance(optional_members, bool):
        raise ValueError("URL4 Candidate has invalid Fusion topology metadata")
    return _RecipeTopology(
        quorum=_quorum(value.get("quorum", "all"), len(members)),
        optional_members=optional_members,
        kind="fusion",
        name=name,
        binding=binding,
        members=members,
        synthesizer=synthesizer,
    )


def _decode_corrective_loop(
    value: dict[object, object],
    name: str,
    binding: str,
) -> _RecipeTopology:
    expected = {
        "binding",
        "check_route",
        "judge",
        "kind",
        "max_rounds",
        "members",
        "name",
        "protocol",
    }
    if set(value) != expected:
        raise ValueError("URL4 Candidate has invalid CorrectiveLoop topology metadata")
    members_value = value["members"]
    if not isinstance(members_value, list):
        raise ValueError("URL4 Candidate has invalid CorrectiveLoop topology metadata")
    members = tuple(_decode_node(member) for member in members_value)
    if len(members) < 2:
        raise ValueError("URL4 Candidate has invalid CorrectiveLoop topology metadata")
    return _RecipeTopology(
        kind="corrective_loop",
        name=name,
        binding=binding,
        members=members,
        judge=_decode_node(value["judge"]),
        max_rounds=_max_rounds(value["max_rounds"]),
        check_route=_check_route(value["check_route"]),
        protocol=_text(value["protocol"]),
    )


def _decode_self_corrective(
    value: dict[object, object],
    name: str,
    binding: str,
) -> _RecipeTopology:
    expected = {"binding", "check_route", "kind", "max_rounds", "member", "name", "protocol"}
    if set(value) != expected:
        raise ValueError("URL4 Candidate has invalid SelfCorrective topology metadata")
    return _RecipeTopology(
        kind="self_corrective",
        name=name,
        binding=binding,
        members=(_decode_node(value["member"]),),
        max_rounds=_max_rounds(value["max_rounds"]),
        check_route=_check_route(value["check_route"]),
        protocol=_text(value["protocol"]),
    )


def _max_rounds(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("URL4 Candidate has invalid corrective topology metadata")
    return value


def _check_route(value: object) -> str:
    selected = _text(value)
    if not selected.startswith("/"):
        raise ValueError("URL4 Candidate has invalid corrective topology metadata")
    return selected


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("URL4 Candidate has invalid Recipe topology metadata")
    return value


def _binding(value: object) -> str:
    selected = _text(value)
    if _BINDING.fullmatch(selected) is None:
        raise ValueError("URL4 Candidate has invalid Recipe topology metadata")
    return selected


__all__: list[str] = []
