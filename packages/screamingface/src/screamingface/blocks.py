"""Block forms of the deterministic Fusion slot: Extract, Matches, Reduce (OME-1289 gap).

FEATURE: a researcher builds a reducer from named blocks and gets the same combine call as the
named form (block-api ans:Q1).
INVARIANT: v1 blocks use short operator names only (D-13); the catalog pins the version.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from screamingface._regex_rule import check_regex
from screamingface._signals import FIELD_PATH, JUDGE_SIGNAL, Signal
from screamingface.reducer import (
    _MAX_REDUCER_MEMBERS,
    _MEAN_SIGNAL_USE,
    _MEDIAN_JUDGE_USE,
    _NUMERIC_SELECTS,
    BENCHMARK_EXTRACT,
    Reducer,
    _check_judge_weights,
    _ModelSignal,
    _recovered_weights,
    _ReducerPlan,
    _refuse_judge_signal,
    _Statistic,
    _Step,
    _Steps,
    _vote_plan,
    _weights_option,
)

if TYPE_CHECKING:
    from screamingface.judge import JudgeNode

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
        BENCHMARK_EXTRACT: (None, (), ()),
        "inspect_number": ("inspect_number", (), ()),
        "inspect_aime": ("inspect_aime", (), ()),
    }
)
_NORMALIZERS = ("numeric", "text", "set", "inspect_numeric", "identity")
# The rules a recipe can name for itself: every rule except the benchmark's own (GP-E1 message).
NAMED_EXTRACT_RULES: tuple[str, ...] = tuple(rule for rule in _RULES if rule != BENCHMARK_EXTRACT)


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
            raise ValueError("over='benchmark' needs a benchmark")
        normalize = None if self.normalize is None else _Step(self.normalize)
        return _Step(operator, self.args), normalize


def _check_normalizer(rule: str, normalize: object) -> None:
    if normalize is None:
        return
    if not isinstance(normalize, str) or normalize not in _NORMALIZERS:
        raise ValueError(f"sf.Extract normalize must be one of {', '.join(_NORMALIZERS)}")
    if rule == "benchmark":
        raise ValueError(
            "sf.Extract('benchmark') takes the benchmark's own normalizer; "
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


# The block ops that the vote, median and mean steps lower to when they read an extractor with
# arguments (``over="field:<path>"`` or ``sf.Extract(...)``); the order is the one the unknown-op
# message lists.
_OPS: Mapping[str, _OpRow] = MappingProxyType(
    {
        "plurality": _OpRow("vote", ("select",), ("extract",)),
        "weighted": _OpRow("vote", ("select",), ("extract", "weights"), ("judge",)),
        "median": _OpRow("median", ("select", "compute"), ("extract",), ("weights",)),
        "mean": _OpRow("mean", ("compute", "select"), ("extract",), ("weights",)),
    }
)
# INVARIANT: the Engine's top_k@1 `_MAX_K` (operators/selection.py), copied; it is also the most
# members a reducer Fusion takes, so one constant serves both. sf.Rank reads it from here.
_MAX_K = _MAX_REDUCER_MEMBERS
# The step each op is the block form of: a message names the step the user wrote (O13).
_STEPS_OF_OPS: Mapping[str, str] = MappingProxyType(
    {"plurality": "sf.Vote", "weighted": "sf.Vote", "median": "sf.Median", "mean": "sf.Mean"}
)
# INVARIANT: the Engine's join@1 `_MAX_SEPARATOR_CHARS` (operators/selection.py), copied; a longer
# separator is refused before any call is made. sf.Concat reads it from here.
_MAX_SEPARATOR_CHARS = 1024


def _step_of(op: str) -> str:
    """The step a block op lowers from (``sf.Vote``, ``sf.Median``, ``sf.Mean``)."""

    return _STEPS_OF_OPS[op]


def _check_extract(op: str, value: object) -> Extract:
    if not isinstance(value, Extract):
        raise TypeError(f"{_step_of(op)} over= must be an sf.Extract")
    return value


def _check_weights(op: str, value: object) -> Signal | tuple[float, ...]:
    return _weights_option(value, f"{_step_of(op)} weights")


def _check_judge(op: str, value: object) -> object:
    # WHY lazy: judge.py imports this module to register its block form (F10)
    from screamingface.judge import JudgeNode

    if not isinstance(value, JudgeNode):
        raise TypeError(f"{_step_of(op)} judge must be an sf.Judge")
    return value


# option -> (op, value) -> canonical value
_CHECKS: Mapping[str, Callable[[str, object], object]] = MappingProxyType(
    {"extract": _check_extract, "weights": _check_weights, "judge": _check_judge}
)


@dataclass(frozen=True, slots=True, init=False, eq=False)
class ReduceNode(Reducer):
    """One reduce block in the Fusion synthesizer slot; compiles to the same combine call as its
    named form (block-api ans:Q1). select returns original member text; compute builds a value.

    A median or a mean block also takes ``select="nearest" | "value"``, the word of sf.Median and
    sf.Mean, in place of ``mode``: "nearest" is mode "select" and "value" is mode "compute". The
    block keeps only the mode, so both spellings are one block, with one repr and one url4.
    """

    _public_name: ClassVar[str] = "Vote"
    name: str
    op: str
    mode: ReduceMode
    options: Mapping[str, object]
    _carries_narrow: ClassVar[bool] = True  # the narrow carrier: see Reducer._carries_narrow
    _narrow: tuple[Reducer, ...] = field(default=(), init=False, repr=False)

    def __init__(self, op: str, mode: ReduceMode | None = None, **options: object) -> None:
        if not isinstance(op, str):
            raise TypeError("a ReduceNode op must be text")
        row = _OPS.get(op)
        if row is None:
            raise ValueError(f"unknown ReduceNode op {op!r}; the ops are {', '.join(_OPS)}")
        mode, options = _numeric_select(op, mode, options)
        selected_mode = _resolve_mode(op, row, mode)
        _check_option_names(op, row, options)
        checked = {
            name: _CHECKS[name](op, options[name])
            for name in (*row.required, *row.optional)
            if name in options
        }
        canonical = _CANONICAL.get(op)
        if canonical is not None:
            canonical(checked)
        object.__setattr__(self, "name", row.reducer)
        object.__setattr__(self, "_narrow", ())
        object.__setattr__(self, "op", op)
        object.__setattr__(self, "mode", selected_mode)
        object.__setattr__(self, "options", MappingProxyType(checked))

    def _key(self) -> tuple[object, ...]:
        # WHY the type is in the key: Python's True == 1 == 1.0, but a bool, an int and a float
        # compile to different JSON, so they must stay three different blocks.
        options = tuple((name, type(value), value) for name, value in sorted(self.options.items()))
        return (self.op, self.mode, options)

    def __eq__(self, other: object) -> bool:
        # WHY the carrier is not in ``_key``: a narrow step (Rank, Filter) has no hash. Equal
        # values still have equal hashes.
        return (
            isinstance(other, ReduceNode)
            and self._key() == other._key()
            and self._narrow == other._narrow
        )

    def __hash__(self) -> int:
        return hash(self._key())

    def __repr__(self) -> str:
        parts = [repr(self.op)]
        if self.mode != _OPS[self.op].modes[0]:
            parts.append(f"mode={self.mode!r}")
        parts.extend(f"{name}={value!r}" for name, value in self.options.items())
        return f"Reduce({', '.join(parts)})"

    def _step_name(self) -> str:
        return _step_of(self.op).removeprefix("sf.")

    def _plan(self) -> _ReducerPlan:
        return _PLANS[self.op](self)

    def _check_members(self, count: int) -> None:
        weights = self.options.get("weights")
        if isinstance(weights, tuple) and len(weights) != count:
            raise ValueError(f"{_step_of(self.op)} has {len(weights)} weights for {count} members")

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> ReduceNode:
        return _rebuilt_block(spec, lambda: _rebuild_plain(spec))

    @classmethod
    def _rebuild(cls, spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> ReduceNode:
        if not signals:
            return cls._from_spec(spec)
        return _rebuilt_block(spec, lambda: _rebuild_with_signals(spec, signals))


def _resolve_mode(op: str, row: _OpRow, mode: object) -> ReduceMode:
    if mode is None:
        return row.modes[0]
    if mode not in ("select", "compute"):
        raise ValueError("a ReduceNode mode must be 'select' or 'compute'")
    if mode not in row.modes:
        raise ValueError(f"{op!r} is a {'/'.join(row.modes)} op, not {mode}")
    return mode


def _check_option_names(op: str, row: _OpRow, options: Mapping[str, object]) -> None:
    allowed = (*row.required, *row.optional)
    for name in options:
        if name not in allowed:
            named = (*allowed, "select") if op in _SELECT_CHOICES else allowed
            takes = ", ".join(named) if named else "no options"
            raise ValueError(f"ReduceNode({op!r}) does not take option {name!r}; it takes {takes}")
    for name in row.required:
        if name not in options:
            raise ValueError(f"ReduceNode({op!r}) needs option {name!r}")


# op -> its select words as an error names them, the default first (the sf.Median / sf.Mean order)
_SELECT_CHOICES: Mapping[str, str] = MappingProxyType(
    {"median": "'nearest' or 'value'", "mean": "'value' or 'nearest'"}
)


def _numeric_select(
    op: str, mode: ReduceMode | None, options: dict[str, object]
) -> tuple[ReduceMode | None, dict[str, object]]:
    """The mode and the other options of a block that may give ``select=`` (E4b P11).

    A median or a mean block takes ``select="nearest" | "value"``, the word of sf.Median and
    sf.Mean, as a second name for ``mode``. The block keeps only the mode, so the url4, the
    evidence and the repr do not change. A short name only: blocks never pin a version (D-13).
    """

    choices = _SELECT_CHOICES.get(op)
    if choices is None or "select" not in options:
        return mode, options
    rest = dict(options)
    select = rest.pop("select")
    if mode is not None:
        raise ValueError(f"ReduceNode({op!r}) takes mode or select, not both")
    if not isinstance(select, str) or select not in _NUMERIC_MODES:
        raise ValueError(f"{_step_of(op)} select= must be {choices}, not {select!r}")
    return _NUMERIC_MODES[select], rest


def _numeric_extract(extract: object, op: str) -> Extract:
    """F19: a median or a mean reads numbers, so its normalizer is numeric (D-6) and never the
    benchmark's."""
    assert isinstance(extract, Extract)
    if extract.rule == "benchmark" or extract.normalize not in (None, "numeric"):
        raise ValueError(f"{_step_of(op)} needs a numeric sf.Extract that is not 'benchmark'")
    return Extract(extract.rule, normalize="numeric", **extract.args)


# A median and a mean block differ only in their name and in the advice text that refuses a
# score:judge weight: one code path builds and rebuilds both.


def _canonical_statistic(checked: dict[str, object], statistic: _Statistic, use: str) -> None:
    checked["extract"] = _numeric_extract(checked["extract"], statistic)
    weights = checked.get("weights")
    if isinstance(weights, Signal):
        _refuse_judge_signal(weights, _step_of(statistic), use)


def _canonical_weighted(checked: dict[str, object]) -> None:
    _check_judge_weights(checked["weights"], checked.get("judge"), "sf.Vote")


# op -> the in-place canonicalization of its checked options (BK#4: one canonical block per op)
_CANONICAL: Mapping[str, Callable[[dict[str, object]], None]] = MappingProxyType(
    {
        "median": partial(_canonical_statistic, statistic="median", use=_MEDIAN_JUDGE_USE),
        "weighted": _canonical_weighted,
        "mean": partial(_canonical_statistic, statistic="mean", use=_MEAN_SIGNAL_USE),
    }
)


def _answer_steps(extract: Extract) -> tuple[_Step | None, _Step | None, bool]:
    """The extract and normalize steps of an Extract, and whether the benchmark supplies them."""

    if extract.rule == BENCHMARK_EXTRACT:
        return None, None, True
    return (*extract._steps(), False)


def _plurality_plan(block: ReduceNode) -> _ReducerPlan:
    extract, normalize, benchmark = _answer_steps(_extract_of(block))
    return _vote_plan(extract, normalize, None, benchmark_rule=benchmark)


def _weighted_plan(block: ReduceNode) -> _ReducerPlan:
    extract, normalize, benchmark = _answer_steps(_extract_of(block))
    weights = block.options["weights"]
    assert isinstance(weights, tuple | Signal)
    judge = cast("JudgeNode | None", block.options.get("judge"))
    return _vote_plan(extract, normalize, weights, benchmark_rule=benchmark, judge=judge)


def _statistic_plan(block: ReduceNode, statistic: _Statistic) -> _ReducerPlan:
    extract, _ = _extract_of(block)._steps()
    weights = cast("tuple[float, ...] | Signal | None", block.options.get("weights"))
    steps = _Steps(
        extract=extract,
        normalize=_Step("numeric"),
        reduce=_Step(statistic if weights is None else f"weighted_{statistic}"),
        select=_Step("value" if block.mode == "compute" else "nearest"),
    )
    return _ReducerPlan(statistic, "answer", steps, weights)


def _extract_of(block: ReduceNode) -> Extract:
    extract = block.options["extract"]
    assert isinstance(extract, Extract)
    return extract


_PLANS: Mapping[str, Callable[[ReduceNode], _ReducerPlan]] = MappingProxyType(
    {
        "plurality": _plurality_plan,
        "weighted": _weighted_plan,
        "median": partial(_statistic_plan, statistic="median"),
        "mean": partial(_statistic_plan, statistic="mean"),
    }
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


def _rebuild_vote(spec: Mapping[str, object], *, judge: JudgeNode | None = None) -> ReduceNode:
    _no_args(spec["reduce"])
    _no_args(spec["select"])
    extract = _extract_from_spec(spec, _normalize_from_spec(spec))
    weights = _recovered_weights(spec)  # the one recovery rule; a refusal is a ValueError
    pair = (_op_name(spec["reduce"]), _op_name(spec["select"]))
    if pair == ("mode", "first_holder") and weights is None:
        return ReduceNode("plurality", extract=extract)
    if pair == ("weighted_mode", "max_weight_holder") and weights is not None:
        options: dict[str, Any] = {"judge": judge} if judge else {}
        return ReduceNode("weighted", extract=extract, weights=weights, **options)
    raise ValueError("a vote shape this SDK version cannot rebuild")


# The select op of a median or a mean block -> its ReduceNode mode.
_NUMERIC_MODES: Mapping[str, ReduceMode] = MappingProxyType(
    {"nearest": "select", "value": "compute"}
)
# INVARIANT: the block select words are the select words of sf.Median and sf.Mean (one vocabulary).
assert frozenset(_NUMERIC_MODES) == _NUMERIC_SELECTS


def _rebuild_statistic(spec: Mapping[str, object], statistic: _Statistic) -> ReduceNode:
    _no_args(spec["reduce"])
    _no_args(spec["select"])
    weights = _recovered_weights(spec)  # the one recovery rule; a refusal is a ValueError
    reduce = statistic if weights is None else f"weighted_{statistic}"
    if _normalize_from_spec(spec) != "numeric" or _op_name(spec["reduce"]) != reduce:
        raise ValueError(f"a {statistic} shape this SDK version cannot rebuild")
    extract = _extract_from_spec(spec, "numeric")
    options: dict[str, Any] = {} if weights is None else {"weights": weights}
    mode = _NUMERIC_MODES[_op_name(spec["select"])]
    return ReduceNode(statistic, mode=mode, extract=extract, **options)


_REBUILD: Mapping[str, Callable[[Mapping[str, object]], ReduceNode]] = MappingProxyType(
    {
        "vote": _rebuild_vote,
        "median": partial(_rebuild_statistic, statistic="median"),
        "mean": partial(_rebuild_statistic, statistic="mean"),
    }
)


def _rebuild_plain(spec: Mapping[str, object]) -> ReduceNode:
    rebuilt = _REBUILD.get(str(spec.get("reducer")))
    if rebuilt is None:
        raise ValueError("not a rebuildable reducer")
    return rebuilt(spec)


def _rebuild_with_signals(
    spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]
) -> ReduceNode:
    """Only a judge-weighted vote reads model calls (8S F6); anything else is refused."""

    if spec.get("reducer") != "vote" or spec.get("weights") != {"signal": JUDGE_SIGNAL}:
        raise ValueError("a signal shape this SDK version cannot rebuild")
    # WHY lazy: judge.py imports this module to register its block form (F10)
    from screamingface.judge import judge_from_signals

    return _rebuild_vote(spec, judge=judge_from_signals(signals, "scores"))


def _rebuilt_block(spec: Mapping[str, object], rebuild: Callable[[], ReduceNode]) -> ReduceNode:
    """Run one rebuild; every refusal is the one "cannot rebuild" error."""

    try:
        return rebuild()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(
            f"URL4 Candidate has a {spec.get('reducer')} spec this SDK version cannot rebuild"
        ) from exc


__all__: list[str] = []
