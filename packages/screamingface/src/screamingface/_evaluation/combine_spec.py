"""The combine call's spec: canonical bytes out of a Reducer, and back out of url4 (OME-1289)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from url4 import Text

from screamingface._evaluation.operators import STAGES, Stage, _OperatorCatalog
from screamingface._immutable_json import thaw_mapping
from screamingface.reducer import REDUCER_NAMES, Reducer, _Step

COMBINE_ROUTE = "/ensemble/combine/v1"
COMBINE_MODEL = COMBINE_ROUTE.removeprefix("/")  # how url4._calls sees the route
COMBINE_SPEC_SCHEMA = "screamingface.combine-spec.v1"
_MAX_SPEC_BYTES = 64 * 1024
_SPEC_KEYS = frozenset(
    {"schema", "reducer", "members", "extract", "normalize", "reduce", "select", "weights"}
)
_INVALID_SPEC = "URL4 Candidate has an invalid combine spec"


def canonical_json(value: object) -> str:
    """Sorted-key compact JSON that url4 can carry as text without rewriting it.

    WHY ``$`` is escaped (D-1): url4 rewrites ``$name`` and ``$N`` inside an intent, and a
    doubled ``$$`` is not a safe escape there, so the spec text never holds a raw ``$``.
    WHY the DEL escape: ``json.dumps`` never escapes U+007F, and url4 rejects a raw DEL in
    quoted text.
    """

    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        .replace("$", "\\u0024")
        .replace("\x7f", "\\u007f")
    )


def combine_spec_text(reducer: Reducer, *, member_count: int, operators: _OperatorCatalog) -> str:
    """Build the canonical combine spec for ``reducer`` with every operator pinned."""

    if reducer._reducer not in REDUCER_NAMES:
        raise ValueError(f"{reducer._reducer!r} is not a known reducer")
    steps = reducer._steps()
    weights = reducer._weights()
    if weights is not None and len(weights) != member_count:
        raise ValueError(f"{reducer.name} has {len(weights)} weights for {member_count} members")
    members = [f"member_{index}" for index in range(1, member_count + 1)]
    spec = {
        "schema": COMBINE_SPEC_SCHEMA,
        "reducer": reducer._reducer,
        "members": members,
        "extract": _pinned_step("extract", steps.extract, operators),
        "normalize": _pinned_step("normalize", steps.normalize, operators),
        "reduce": _pinned_step("reduce", steps.reduce, operators),
        "select": _pinned_step("select", steps.select, operators),
        "weights": None if weights is None else {m: float(w) for m, w in zip(members, weights)},
    }
    text = canonical_json(spec)
    size = len(text.encode("utf-8"))
    if size > _MAX_SPEC_BYTES:
        raise ValueError(f"combine spec is {size} bytes; the limit is {_MAX_SPEC_BYTES}")
    return text


def _pinned_step(
    stage: Stage, step: _Step | None, operators: _OperatorCatalog
) -> dict[str, object] | None:
    if step is None:
        return None
    return {"op": operators.pin(stage, step.op), "args": thaw_mapping(step.args)}


def combine_spec_intent(spec_text: str) -> Text:
    return Text(spec_text)


def decode_combine_spec(raw_intent: str) -> dict[str, object]:
    """Recover the spec from the RAW intent text of a combine call.

    The raw text, never ``_python_text`` output: that turns U+2028 into a newline, which
    would corrupt the JSON.
    """

    try:
        spec = json.loads(raw_intent)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(_INVALID_SPEC) from exc
    if not _is_spec(spec):
        raise ValueError(_INVALID_SPEC)
    return cast(dict[str, object], spec)


def _is_spec(spec: object) -> bool:
    if not isinstance(spec, dict) or set(spec) != _SPEC_KEYS:
        return False
    members = spec["members"]
    return (
        spec["schema"] == COMBINE_SPEC_SCHEMA
        and isinstance(spec["reducer"], str)
        and isinstance(members, list)
        and bool(members)
        and members == [f"member_{index}" for index in range(1, len(members) + 1)]
        and all(_is_step(spec[stage]) for stage in STAGES)
        and spec["reduce"] is not None
        and spec["select"] is not None
        and (spec["weights"] is None or isinstance(spec["weights"], dict))
    )


def _is_step(step: object) -> bool:
    return step is None or (
        isinstance(step, dict)
        and set(step) == {"op", "args"}
        and isinstance(step["op"], str)
        and isinstance(step["args"], dict)
    )


def spec_operator_pairs(spec: Mapping[str, object]) -> tuple[tuple[Stage, str], ...]:
    """The (stage, pinned id) pairs a decoded spec uses, in step order."""

    pairs: list[tuple[Stage, str]] = []
    for stage in STAGES:
        step = spec[stage]
        if step is not None:
            pairs.append((stage, str(cast(Mapping[str, object], step)["op"])))
    return tuple(pairs)


__all__: list[str] = []
