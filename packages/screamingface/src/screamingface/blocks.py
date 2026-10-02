"""Block forms of the deterministic Fusion slot: Extract, Matches, Reduce (OME-1289 gap).

FEATURE: a researcher builds a reducer from named blocks and gets the same combine call as the
named form (block-api ans:Q1).
INVARIANT: v1 blocks use short operator names only (D-13); the catalog pins the version.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from screamingface._regex_rule import check_regex
from screamingface._signals import FIELD_PATH, Signal
from screamingface.reducer import Reducer, _ReducerPlan, _Step, _Steps

type ExtractRule = Literal[
    "boxed",
    "last_number",
    "field",
    "regex",
    "last_line",
    "whole",
    "json",
    "benchmark",
    "inspect_number",
    "inspect_aime",
]
type NormalizeRule = Literal["numeric", "text", "set", "inspect_numeric", "identity"]

# rule -> (engine op name | None for benchmark, required args, optional args)
_RULES: Mapping[str, tuple[str | None, tuple[str, ...], tuple[str, ...]]] = MappingProxyType(
    {
        "boxed": ("boxed", (), ()),
        "last_number": ("last_number", (), ()),
        "field": ("json_field", ("path",), ()),
        "regex": ("regex", ("pattern",), ("group", "occurrence", "ignore_case")),
        "last_line": ("last_line", (), ()),
        "whole": ("whole", (), ()),
        "json": ("json_object", (), ()),
        "benchmark": (None, (), ()),
        "inspect_number": ("inspect_number", (), ()),
        "inspect_aime": ("inspect_aime", (), ()),
    }
)
_NORMALIZERS = ("numeric", "text", "set", "inspect_numeric", "identity")


@dataclass(frozen=True, slots=True, init=False)
class Extract:
    """How a member's answer is read: a rule, then an optional normalizer (block form)."""

    rule: ExtractRule
    normalize: NormalizeRule | None
    args: Mapping[str, object]

    def __init__(
        self, rule: ExtractRule, normalize: NormalizeRule | None = None, **args: object
    ) -> None:
        if not isinstance(rule, str):
            raise TypeError("sf.Extract rule must be text")
        if rule not in _RULES:
            raise ValueError(f"unknown sf.Extract rule {rule!r}; the rules are {', '.join(_RULES)}")
        _check_normalizer(rule, normalize)
        _check_args(rule, args)
        # canonical: the default ignore_case=False is not stored (as sf.matches does)
        kept = {
            name: value for name, value in args.items() if (name, value) != ("ignore_case", False)
        }
        object.__setattr__(self, "rule", rule)
        object.__setattr__(self, "normalize", normalize)
        object.__setattr__(self, "args", MappingProxyType(dict(sorted(kept.items()))))

    def __hash__(self) -> int:
        return hash((self.rule, self.normalize, tuple(sorted(self.args.items()))))

    def __repr__(self) -> str:
        parts = [repr(self.rule)]
        if self.normalize is not None:
            parts.append(f"normalize={self.normalize!r}")
        parts.extend(f"{name}={value!r}" for name, value in sorted(self.args.items()))
        return f"Extract({', '.join(parts)})"

    def _python(self) -> str:
        return "sf." + repr(self)

    def _steps(self) -> tuple[_Step, _Step | None]:
        """The unpinned extract step and the optional normalize step."""

        operator = _RULES[self.rule][0]
        if operator is None:
            raise ValueError("extract='benchmark' needs a benchmark")
        normalize = None if self.normalize is None else _Step(self.normalize)
        return _Step(operator, self.args), normalize


def _check_normalizer(rule: str, normalize: object) -> None:
    if normalize is None:
        return
    if not isinstance(normalize, str) or normalize not in _NORMALIZERS:
        raise ValueError(f"sf.Extract normalize must be one of {', '.join(_NORMALIZERS)}")
    if rule == "benchmark":
        raise ValueError(
            "extract='benchmark' takes the benchmark's own normalizer; "
            "v1 does not let a recipe change it"
        )


def _check_args(rule: str, args: Mapping[str, object]) -> None:
    _, required, optional = _RULES[rule]
    for name in required:
        if name not in args:
            raise ValueError(f"sf.Extract({rule!r}) needs {name!r}")
    for name, value in args.items():
        if name not in (*required, *optional):
            raise ValueError(f"sf.Extract({rule!r}) does not take {name!r}")
        _check_scalar(rule, name, value)
    if rule == "field":
        _check_field_path(args["path"])
    if rule == "regex":
        check_regex(args, "sf.Extract('regex')")


def _check_field_path(path: object) -> None:
    if not isinstance(path, str):
        raise TypeError("sf.Extract('field') path must be text")
    if FIELD_PATH.fullmatch(path) is None:
        raise ValueError("sf.Extract('field') path must be a JSON path like 'a', 'a.b' or 'a[0].b'")


def _check_scalar(rule: str, name: str, value: object) -> None:
    is_scalar = value is None or isinstance(value, str | bool | int)
    if not is_scalar and not (isinstance(value, float) and math.isfinite(value)):
        raise TypeError(f"sf.Extract({rule!r}) {name!r} must be a JSON scalar")


@dataclass(frozen=True, slots=True)
class Matches:
    """A filter predicate: the member text matches a regex@1 pattern (RE2 on the Engine)."""

    pattern: str
    ignore_case: bool = False

    def __post_init__(self) -> None:
        check_regex(_matches_args(self), "sf.matches")

    def _python(self) -> str:
        flag = ", ignore_case=True" if self.ignore_case is True else ""
        return f"sf.matches({self.pattern!r}{flag})"


def _matches_args(value: Matches) -> Mapping[str, object]:
    """ignore_case enters the args only when set, so a default never reaches the check."""

    if value.ignore_case is False:
        return {"pattern": value.pattern}
    return {"pattern": value.pattern, "ignore_case": value.ignore_case}


def matches(pattern: str, *, ignore_case: bool = False) -> Matches:
    """A filter predicate: the member text matches the regex@1 rule (RE2 on the Engine)."""

    return Matches(pattern, ignore_case)


type ReduceMode = Literal["select", "compute"]


@dataclass(frozen=True, slots=True)
class _OpRow:
    reducer: str  # the spec reducer; Reduce.name
    modes: tuple[ReduceMode, ...]  # the default first
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    one_of: tuple[str, ...] = ()  # exactly one of these (they are also listed in optional)
    reserved: frozenset[str] = frozenset()
    named: str = ""  # the named form, for messages


# Op-table order (block-api s2.2) is the order the unknown-op message lists.
_OPS: Mapping[str, _OpRow] = MappingProxyType(
    {
        "plurality": _OpRow("vote", ("select",), ("extract",), named="sf.Vote"),
        "weighted": _OpRow(
            "vote", ("select",), ("extract", "weights"), named="sf.Vote(weights=...)"
        ),
        "argmax": _OpRow(
            "pick", ("select",), ("by_signal",), ("order",), named="sf.Pick(by_signal=...)"
        ),
        "top_k": _OpRow(
            "rank",
            ("select",),
            ("k",),
            ("by", "by_field", "by_signal", "order"),
            one_of=("by", "by_field", "by_signal"),
            reserved=frozenset({"by"}),
            named="sf.Rank",
        ),
        "filter": _OpRow("filter", ("select",), ("where",), ("extract",), named="sf.Filter"),
        "pick_field": _OpRow(
            "pick",
            ("select",),
            ("field",),
            ("normalize", "order", "equals"),
            one_of=("order", "equals"),
            named="sf.Pick(field)",
        ),
        "concat": _OpRow("concat", ("compute",), (), ("separator", "label"), named="sf.Concat"),
        "median": _OpRow("median", ("select", "compute"), ("extract",), named="sf.Median"),
        "judge": _OpRow(
            "judge",
            ("select",),
            ("judge",),
            ("rubric",),
            reserved=frozenset({"judge", "rubric"}),
            named="sf.Judge",
        ),
        "merge": _OpRow(
            "merge",
            ("compute",),
            ("fields",),
            reserved=frozenset({"fields"}),
            named="sf.Merge",
        ),
        "context": _OpRow("context", ("compute",), (), named="the Fusion recipe rewrite"),
    }
)
_MAX_WEIGHT = sys.float_info.max / 256  # D-12: keeps a weighted sum finite
_MAX_K = 256
_MAX_SEPARATOR = 1024


def _check_extract(op: str, value: object) -> Extract:
    if not isinstance(value, Extract):
        raise TypeError(f"sf.Reduce({op!r}) option 'extract' must be an sf.Extract")
    return value


def _check_weights(op: str, value: object) -> Signal | tuple[float, ...]:
    if isinstance(value, Signal):
        return value
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TypeError(f"sf.Reduce({op!r}) option 'weights' must be a sf.signal or a list")
    if not value:
        raise ValueError(f"sf.Reduce({op!r}) option 'weights' must not be empty")
    return tuple(_check_weight(op, weight) for weight in value)


def _check_weight(op: str, weight: object) -> float:
    if isinstance(weight, bool) or not isinstance(weight, int | float):
        raise TypeError(f"sf.Reduce({op!r}) weights must be numbers")
    if not 0 < weight <= _MAX_WEIGHT:
        raise ValueError(f"sf.Reduce({op!r}) weights must be above 0 and finite")
    return float(weight)


def _check_by_signal(op: str, value: object) -> Signal:
    if not isinstance(value, Signal):
        raise TypeError(f"sf.Reduce({op!r}) option 'by_signal' must be an sf.signal")
    return value


def _check_order(op: str, value: object) -> object:
    if value not in ("max", "min"):
        raise ValueError(f"sf.Reduce({op!r}) option 'order' must be 'max' or 'min'")
    return value


def _check_k(op: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"sf.Reduce({op!r}) option 'k' must be an integer")
    if not 1 <= value <= _MAX_K:
        raise ValueError(f"sf.Reduce({op!r}) option 'k' must be 1 to {_MAX_K}")
    return value


def _check_path(name: str) -> Callable[[str, object], str]:
    def check(op: str, value: object) -> str:
        if not isinstance(value, str):
            raise TypeError(f"sf.Reduce({op!r}) option {name!r} must be text")
        if FIELD_PATH.fullmatch(value) is None:
            raise ValueError(
                f"sf.Reduce({op!r}) option {name!r} must be a JSON path like 'a', 'a.b' or 'a[0].b'"
            )
        return value

    return check


def _check_where(op: str, value: object) -> Matches:
    if not isinstance(value, Matches):
        raise TypeError(f"sf.Reduce({op!r}) option 'where' must be an sf.matches predicate")
    return value


def _check_normalize(op: str, value: object) -> object:
    if value not in _NORMALIZERS:
        raise ValueError(
            f"sf.Reduce({op!r}) option 'normalize' must be one of {', '.join(_NORMALIZERS)}"
        )
    return value


def _check_equals(op: str, value: object) -> object:
    if not isinstance(value, str | bool | int | float):
        raise TypeError(f"sf.Reduce({op!r}) option 'equals' must be text, a bool or a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"sf.Reduce({op!r}) option 'equals' must be finite")
    return value


def _check_separator(op: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"sf.Reduce({op!r}) option 'separator' must be text")
    if not 1 <= len(value) <= _MAX_SEPARATOR:
        raise ValueError(
            f"sf.Reduce({op!r}) option 'separator' must be 1 to {_MAX_SEPARATOR} characters"
        )
    return value


def _check_label(op: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"sf.Reduce({op!r}) option 'label' must be a bool")
    return value


# option -> (op, value) -> canonical value
_CHECKS: Mapping[str, Callable[[str, object], object]] = MappingProxyType(
    {
        "extract": _check_extract,
        "weights": _check_weights,
        "by_signal": _check_by_signal,
        "order": _check_order,
        "k": _check_k,
        "by_field": _check_path("by_field"),
        "field": _check_path("field"),
        "where": _check_where,
        "normalize": _check_normalize,
        "equals": _check_equals,
        "separator": _check_separator,
        "label": _check_label,
    }
)


@dataclass(frozen=True, slots=True, init=False, eq=False)
class Reduce(Reducer):
    """One reduce block in the Fusion synthesizer slot; compiles to the same combine call as its
    named form (block-api ans:Q1). select returns original member text; compute builds a value."""

    name: str
    op: str
    mode: ReduceMode
    options: Mapping[str, object]

    def __init__(self, op: str, mode: ReduceMode | None = None, **options: object) -> None:
        if not isinstance(op, str):
            raise TypeError("sf.Reduce op must be text")
        row = _OPS.get(op)
        if row is None:
            raise ValueError(f"unknown sf.Reduce op {op!r}; the v1 ops are {', '.join(_OPS)}")
        selected_mode = _resolve_mode(op, row, mode)
        _check_option_names(op, row, options)
        checked = {
            name: _CHECKS[name](op, options[name])
            for name in (*row.required, *row.optional)
            if name in options
        }
        if op == "median":
            checked["extract"] = _median_extract(checked["extract"])
        object.__setattr__(self, "name", row.reducer)
        object.__setattr__(self, "op", op)
        object.__setattr__(self, "mode", selected_mode)
        object.__setattr__(self, "options", MappingProxyType(checked))

    def _key(self) -> tuple[object, ...]:
        # WHY the type is in the key: Python's True == 1 == 1.0, but a bool, an int and a float
        # compile to different JSON, so they must stay three different blocks.
        options = tuple((name, type(value), value) for name, value in sorted(self.options.items()))
        return (self.op, self.mode, options)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Reduce) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __repr__(self) -> str:
        return self._render("Reduce", repr)

    def _python(self) -> str:
        return self._render("sf.Reduce", _source)

    def _render(self, head: str, show: Callable[[object], str]) -> str:
        parts = [repr(self.op)]
        if self.mode != _OPS[self.op].modes[0]:
            parts.append(f"mode={self.mode!r}")
        parts.extend(f"{name}={show(value)}" for name, value in self.options.items())
        return f"{head}({', '.join(parts)})"

    def _plan(self) -> _ReducerPlan:
        build = _PLANS.get(self.op)
        if build is None:
            raise ValueError(
                f"sf.Reduce({self.op!r}) does not compile in this SDK version yet; "
                f"its combine operators arrive with {_OPS[self.op].named}"
            )
        return build(self)

    def _check_members(self, count: int) -> None:
        weights = self.options.get("weights")
        if isinstance(weights, tuple) and len(weights) != count:
            raise ValueError(
                f"sf.Reduce('weighted') has {len(weights)} weights for {count} members"
            )

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Reduce:
        try:
            rebuilt = _REBUILD.get(str(spec.get("reducer")))
            if rebuilt is None:
                raise ValueError("not a rebuildable reducer")
            return rebuilt(spec)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(
                f"URL4 Candidate has a {spec.get('reducer')} spec this SDK version cannot rebuild"
            ) from exc


def _resolve_mode(op: str, row: _OpRow, mode: object) -> ReduceMode:
    if mode is None:
        return row.modes[0]
    if mode not in ("select", "compute"):
        raise ValueError("sf.Reduce mode must be 'select' or 'compute'")
    if mode not in row.modes:
        raise ValueError(f"{op!r} is a {'/'.join(row.modes)} op, not {mode}")
    return mode


def _check_option_names(op: str, row: _OpRow, options: Mapping[str, object]) -> None:
    allowed = (*row.required, *row.optional)
    for name in options:
        if name not in allowed:
            takes = ", ".join(allowed) if allowed else "no options"
            raise ValueError(f"sf.Reduce({op!r}) does not take option {name!r}; it takes {takes}")
    for name in row.required:
        if name not in options:
            raise ValueError(f"sf.Reduce({op!r}) needs option {name!r}")
    if row.one_of and sum(name in options for name in row.one_of) != 1:
        raise ValueError(f"sf.Reduce({op!r}) needs exactly one of {', '.join(row.one_of)}")
    for name in options:
        if name in row.reserved:
            raise ValueError(
                f"sf.Reduce({op!r}) option {name!r} is not supported by this SDK version yet; "
                f"it arrives with {row.named}"
            )


def _median_extract(extract: object) -> Extract:
    """F19: a median reads numbers, so its normalizer is numeric (D-6) and never the benchmark's."""

    assert isinstance(extract, Extract)
    if extract.rule == "benchmark" or extract.normalize not in (None, "numeric"):
        raise ValueError("sf.Reduce('median') needs a numeric Extract that is not 'benchmark'")
    return Extract(extract.rule, normalize="numeric", **extract.args)


def _source(value: object) -> str:
    python = getattr(value, "_python", None)
    return repr(value) if python is None else python()


def _vote_plan(block: Reduce, *, reduce: str, select: str) -> _ReducerPlan:
    extract, normalize = _extract_of(block)._steps()
    weights = block.options.get("weights")
    steps = _Steps(extract=extract, normalize=normalize, reduce=_Step(reduce), select=_Step(select))
    return _ReducerPlan("vote", "answer", steps, weights if isinstance(weights, tuple) else None)


def _plurality_plan(block: Reduce) -> _ReducerPlan:
    return _vote_plan(block, reduce="mode", select="first_holder")


def _weighted_plan(block: Reduce) -> _ReducerPlan:
    if isinstance(block.options["weights"], Signal):
        raise ValueError(
            "sf.Reduce('weighted') with sf.signal weights does not compile in this SDK version "
            "yet; it arrives with sf.Vote(weights=sf.signal(...))"
        )
    return _vote_plan(block, reduce="weighted_mode", select="max_weight_holder")


def _median_plan(block: Reduce) -> _ReducerPlan:
    extract, _ = _extract_of(block)._steps()
    steps = _Steps(
        extract=extract,
        normalize=_Step("numeric"),
        reduce=_Step("median"),
        select=_Step("nearest" if block.mode == "select" else "value"),
    )
    return _ReducerPlan("median", "answer", steps)


def _extract_of(block: Reduce) -> Extract:
    extract = block.options["extract"]
    assert isinstance(extract, Extract)
    return extract


_PLANS: Mapping[str, Callable[[Reduce], _ReducerPlan]] = MappingProxyType(
    {"plurality": _plurality_plan, "weighted": _weighted_plan, "median": _median_plan}
)

# engine op name -> Extract rule (benchmark has no engine op)
_REVERSE_RULES: Mapping[str, str] = MappingProxyType(
    {engine: rule for rule, (engine, _, _) in _RULES.items() if engine is not None}
)


def _step(value: object) -> Mapping[str, object]:
    """A spec step as data from a url4 (which a person may have edited): a mapping, or refuse."""

    if not isinstance(value, Mapping):
        raise ValueError("a spec step that is not an object")
    return value


def _op_name(step: object) -> str:
    """The short name of a pinned spec step."""

    return str(_step(step)["op"]).split("@")[0]


def _no_args(step: object) -> None:
    if _step(step)["args"]:
        raise ValueError("a reduce or select step with args")


def _extract_from_spec(spec: Mapping[str, object], normalize: str | None) -> Extract:
    step = _step(spec["extract"])
    args = _step(step["args"])
    return Extract(_REVERSE_RULES[_op_name(step)], normalize, **args)  # type: ignore[arg-type]


def _normalize_from_spec(spec: Mapping[str, object]) -> str | None:
    step = spec["normalize"]
    if step is None:
        return None
    _no_args(step)
    return _op_name(step)


def _rebuild_vote(spec: Mapping[str, object]) -> Reduce:
    _no_args(spec["reduce"])
    _no_args(spec["select"])
    extract = _extract_from_spec(spec, _normalize_from_spec(spec))
    weights = spec["weights"]
    pair = (_op_name(spec["reduce"]), _op_name(spec["select"]))
    if pair == ("mode", "first_holder") and weights is None:
        return Reduce("plurality", extract=extract)
    members = spec["members"]
    if (
        pair == ("weighted_mode", "max_weight_holder")
        and isinstance(weights, Mapping)
        and isinstance(members, list)
        and set(weights) == set(members)
    ):
        # member order, not the weights' key order: canonical JSON sorts member_10 before member_2
        return Reduce("weighted", extract=extract, weights=[weights[m] for m in members])
    raise ValueError("a vote shape this SDK version cannot rebuild")


_MEDIAN_MODES: Mapping[str, ReduceMode] = MappingProxyType(
    {"nearest": "select", "value": "compute"}
)


def _rebuild_median(spec: Mapping[str, object]) -> Reduce:
    _no_args(spec["reduce"])
    _no_args(spec["select"])
    numeric = spec["weights"] is None and _normalize_from_spec(spec) == "numeric"
    if not numeric or _op_name(spec["reduce"]) != "median":
        raise ValueError("a median shape this SDK version cannot rebuild")
    extract = _extract_from_spec(spec, "numeric")
    return Reduce("median", mode=_MEDIAN_MODES[_op_name(spec["select"])], extract=extract)


_REBUILD: Mapping[str, Callable[[Mapping[str, object]], Reduce]] = MappingProxyType(
    {"vote": _rebuild_vote, "median": _rebuild_median}
)


__all__: list[str] = []
