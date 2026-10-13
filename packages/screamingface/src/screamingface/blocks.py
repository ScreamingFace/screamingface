"""Block forms of the deterministic Fusion slot: Extract, Matches, Reduce (OME-1289 gap).

FEATURE: a researcher builds a reducer from named blocks and gets the same combine call as the
named form (block-api ans:Q1).
INVARIANT: v1 blocks use short operator names only (D-13); the catalog pins the version.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from screamingface import _candidate_policy
from screamingface._regex_rule import check_regex
from screamingface._signals import FIELD_PATH, JUDGE_SIGNAL, Signal, _Comparison
from screamingface.reducer import (
    _MAX_REDUCER_MEMBERS,
    _MEAN_SIGNAL_USE,
    BENCHMARK_EXTRACT,
    Reducer,
    _check_judge_weights,
    _field_path,
    _ModelSignal,
    _recovered_weights,
    _ReducerPlan,
    _refuse_judge_signal,
    _Step,
    _Steps,
    _vote_plan,
    _weights_option,
)

if TYPE_CHECKING:
    from screamingface.judge import Judge

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
class _BlockForm:
    """How a named reducer registers as the block form of one op (F10): the named modules fill
    ``_BLOCK_FORMS``, so this module imports none of them at module level. A check that needs a
    named module's type (``Judge``, ``fields._FieldRules``) imports it lazily, in the function."""

    build: Callable[[Mapping[str, object]], Reducer]  # checked options -> the named reducer
    options: Callable[[Reducer], Mapping[str, object]]  # named reducer -> canonical options


_BLOCK_FORMS: dict[str, _BlockForm] = {}


@dataclass(frozen=True, slots=True)
class _OpRow:
    reducer: str  # the spec reducer; Reduce.name
    modes: tuple[ReduceMode, ...]  # the default first
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    one_of: tuple[str, ...] = ()  # exactly one of these (they are also listed in optional)
    named: str = ""  # the named form, for messages


# Op-table order (block-api s2.2) is the order the unknown-op message lists.
_OPS: Mapping[str, _OpRow] = MappingProxyType(
    {
        "plurality": _OpRow("vote", ("select",), ("extract",), named="sf.Vote"),
        "weighted": _OpRow(
            "vote",
            ("select",),
            ("extract", "weights"),
            ("judge",),
            named="sf.Vote(weights=...)",
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
        "mean": _OpRow("mean", ("compute", "select"), ("extract",), ("weights",), named="sf.Mean"),
        "judge": _OpRow("judge", ("select",), ("judge",), ("rubric",), named="sf.Judge"),
        "merge": _OpRow("merge", ("compute",), ("fields",), named="sf.Merge"),
        "context": _OpRow("context", ("compute",), (), named="the Fusion recipe rewrite"),
    }
)
# INVARIANT: the Engine's top_k@1 `_MAX_K` (operators/selection.py), copied; it is also the most
# members a reducer Fusion takes, so one constant serves both. sf.Rank reads it from here.
_MAX_K = _MAX_REDUCER_MEMBERS
# INVARIANT: the Engine's join@1 `_MAX_SEPARATOR_CHARS` (operators/selection.py), copied; a longer
# separator is refused before any call is made. sf.Concat reads it from here.
_MAX_SEPARATOR_CHARS = 1024
CONTEXT_MISUSE = (
    "sf.Reduce('context') is the first half of the Fusion recipe: put the synthesizer right after "
    "it, as sf.Pipeline([sf.Fusion(members, synthesizer=sf.Reduce('context')), synthesizer, ...])"
)


def _check_extract(op: str, value: object) -> Extract:
    if not isinstance(value, Extract):
        raise TypeError(f"sf.Reduce({op!r}) option 'extract' must be an sf.Extract")
    return value


def _check_weights(op: str, value: object) -> Signal | tuple[float, ...]:
    return _weights_option(value, f"sf.Reduce({op!r}) weights")


def _check_by_signal(op: str, value: object) -> Signal:
    if not isinstance(value, Signal):
        raise TypeError(f"sf.Reduce({op!r}) option 'by_signal' must be an sf.signal")
    return value


def _check_fields(op: str, value: object) -> object:
    # WHY lazy: fields.py imports this module to register its block forms (F10)
    from screamingface.fields import _FieldRules

    if not isinstance(value, Mapping | _FieldRules):
        raise TypeError(
            f"sf.Reduce({op!r}) option 'fields' must be a mapping of field name to sf.FieldRule"
        )
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
        return _field_path(value, f"sf.Reduce({op!r}) option {name!r}")

    return check


def _check_judge(op: str, value: object) -> object:
    # WHY lazy: judge.py imports this module to register its block form (F10)
    from screamingface.judge import Judge

    if not isinstance(value, Judge):
        raise TypeError(f"sf.Reduce({op!r}) option 'judge' must be an sf.Judge")
    return value


def _check_by(op: str, value: object) -> object:
    # WHY lazy: judge.py imports this module to register its block form (F10)
    from screamingface.judge import Judge

    if not isinstance(value, Judge):
        raise TypeError(f"sf.Reduce({op!r}) option 'by' must be an sf.Judge")
    return value


def _check_rubric(op: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"sf.Reduce({op!r}) option 'rubric' must be text")
    selected = _candidate_policy.prompt(value, f"sf.Reduce({op!r}) rubric")
    assert selected is not None  # a str never comes back as None
    return selected


def _check_where(op: str, value: object) -> Matches | _Comparison:
    if not isinstance(value, Matches | _Comparison):
        raise TypeError(
            f"sf.Reduce({op!r}) option 'where' must be an sf.matches predicate or a signal "
            "comparison like sf.signal(key) >= 0.6"
        )
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
    if not 1 <= len(value) <= _MAX_SEPARATOR_CHARS:
        raise ValueError(
            f"sf.Reduce({op!r}) option 'separator' must be 1 to {_MAX_SEPARATOR_CHARS} characters"
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
        "fields": _check_fields,
        "order": _check_order,
        "k": _check_k,
        "by_field": _check_path("by_field"),
        "field": _check_path("field"),
        "where": _check_where,
        "normalize": _check_normalize,
        "equals": _check_equals,
        "separator": _check_separator,
        "label": _check_label,
        "by": _check_by,
        "judge": _check_judge,
        "rubric": _check_rubric,
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
        canonical = _CANONICAL.get(op)
        if canonical is not None:
            canonical(checked)
        checked = _block_form_options(op, checked)
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

    def _compiles_to_combine(self) -> bool:
        # WHY: 'context' is the first half of the Fusion recipe; the recipe rewrite removes it
        # before compile, so it never makes a combine call (no operators, no member cap).
        return self.op != "context"

    def _plan(self) -> _ReducerPlan:
        if self.op == "context":
            raise ValueError(CONTEXT_MISUSE)
        build = _PLANS.get(self.op)
        if build is not None:
            return build(self)
        form = _BLOCK_FORMS.get(self.op)
        if form is None:
            raise ValueError(
                f"sf.Reduce({self.op!r}) does not compile in this SDK version yet; "
                f"its combine operators arrive with {_OPS[self.op].named}"
            )
        return form.build(self.options)._plan()

    def _check_members(self, count: int) -> None:
        form = _BLOCK_FORMS.get(self.op)
        if form is not None:
            form.build(self.options)._check_members(count)
            return
        weights = self.options.get("weights")
        if isinstance(weights, tuple) and len(weights) != count:
            raise ValueError(
                f"sf.Reduce({self.op!r}) has {len(weights)} weights for {count} members"
            )

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Reduce:
        return _rebuilt_block(spec, lambda: _rebuild_plain(spec))

    @classmethod
    def _rebuild(cls, spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> Reduce:
        if not signals:
            return cls._from_spec(spec)
        return _rebuilt_block(spec, lambda: _rebuild_with_signals(spec, signals))


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


def _numeric_extract(extract: object, op: str) -> Extract:
    """F19: a median or a mean reads numbers, so its normalizer is numeric (D-6) and never the
    benchmark's."""
    assert isinstance(extract, Extract)
    if extract.rule == "benchmark" or extract.normalize not in (None, "numeric"):
        raise ValueError(f"sf.Reduce({op!r}) needs a numeric Extract that is not 'benchmark'")
    return Extract(extract.rule, normalize="numeric", **extract.args)


def _median_extract(extract: object) -> Extract:
    return _numeric_extract(extract, "median")


def _canonical_median(checked: dict[str, object]) -> None:
    checked["extract"] = _median_extract(checked["extract"])


def _canonical_mean(checked: dict[str, object]) -> None:
    checked["extract"] = _numeric_extract(checked["extract"], "mean")
    weights = checked.get("weights")
    if isinstance(weights, Signal):
        _refuse_judge_signal(weights, "sf.Reduce('mean')", _MEAN_SIGNAL_USE)


def _canonical_weighted(checked: dict[str, object]) -> None:
    _check_judge_weights(checked["weights"], checked.get("judge"), "sf.Reduce('weighted')")


# op -> the in-place canonicalization of its checked options (BK#4: one canonical block per op)
_CANONICAL: Mapping[str, Callable[[dict[str, object]], None]] = MappingProxyType(
    {"median": _canonical_median, "weighted": _canonical_weighted, "mean": _canonical_mean}
)


def _block_form_options(op: str, checked: dict[str, object]) -> dict[str, object]:
    """The options of the named reducer a registered op builds, in row order (BK-1).

    The wrapper below is for the block forms 9S and 10S register (Pick, Merge, Rank, Concat,
    Filter): their named constructors raise their own messages, and the block names the op.
    """

    form = _BLOCK_FORMS.get(op)
    if form is None:
        return checked
    try:
        return dict(form.options(form.build(checked)))
    except (TypeError, ValueError) as exc:
        raise type(exc)(f"sf.Reduce({op!r}): {exc}") from None


def _source(value: object) -> str:
    python = getattr(value, "_python", None)
    return repr(value) if python is None else python()


def _answer_steps(extract: Extract) -> tuple[_Step | None, _Step | None, bool]:
    """The extract and normalize steps of an Extract, and whether the benchmark supplies them."""

    if extract.rule == BENCHMARK_EXTRACT:
        return None, None, True
    return (*extract._steps(), False)


def _plurality_plan(block: Reduce) -> _ReducerPlan:
    extract, normalize, benchmark = _answer_steps(_extract_of(block))
    return _vote_plan(extract, normalize, None, benchmark_rule=benchmark)


def _weighted_plan(block: Reduce) -> _ReducerPlan:
    extract, normalize, benchmark = _answer_steps(_extract_of(block))
    weights = block.options["weights"]
    assert isinstance(weights, tuple | Signal)
    judge = cast("Judge | None", block.options.get("judge"))
    return _vote_plan(extract, normalize, weights, benchmark_rule=benchmark, judge=judge)


def _median_plan(block: Reduce) -> _ReducerPlan:
    extract, _ = _extract_of(block)._steps()
    steps = _Steps(
        extract=extract,
        normalize=_Step("numeric"),
        reduce=_Step("median"),
        select=_Step("nearest" if block.mode == "select" else "value"),
    )
    return _ReducerPlan("median", "answer", steps)


def _mean_plan(block: Reduce) -> _ReducerPlan:
    extract, _ = _extract_of(block)._steps()
    weights = cast("tuple[float, ...] | Signal | None", block.options.get("weights"))
    steps = _Steps(
        extract=extract,
        normalize=_Step("numeric"),
        reduce=_Step("mean" if weights is None else "weighted_mean"),
        select=_Step("value" if block.mode == "compute" else "nearest"),
    )
    return _ReducerPlan("mean", "answer", steps, weights)


def _extract_of(block: Reduce) -> Extract:
    extract = block.options["extract"]
    assert isinstance(extract, Extract)
    return extract


_PLANS: Mapping[str, Callable[[Reduce], _ReducerPlan]] = MappingProxyType(
    {
        "plurality": _plurality_plan,
        "weighted": _weighted_plan,
        "median": _median_plan,
        "mean": _mean_plan,
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


def _rebuild_vote(spec: Mapping[str, object], *, judge: Judge | None = None) -> Reduce:
    _no_args(spec["reduce"])
    _no_args(spec["select"])
    extract = _extract_from_spec(spec, _normalize_from_spec(spec))
    weights = _recovered_weights(spec)  # the one recovery rule; a refusal is a ValueError
    pair = (_op_name(spec["reduce"]), _op_name(spec["select"]))
    if pair == ("mode", "first_holder") and weights is None:
        return Reduce("plurality", extract=extract)
    if pair == ("weighted_mode", "max_weight_holder") and weights is not None:
        options: dict[str, Any] = {"judge": judge} if judge else {}
        return Reduce("weighted", extract=extract, weights=weights, **options)
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


_MEAN_MODES: Mapping[str, ReduceMode] = MappingProxyType({"value": "compute", "nearest": "select"})


def _rebuild_mean(spec: Mapping[str, object]) -> Reduce:
    _no_args(spec["reduce"])
    _no_args(spec["select"])
    weights = _recovered_weights(spec)  # the one recovery rule; a refusal is a ValueError
    reduce = "mean" if weights is None else "weighted_mean"
    if _normalize_from_spec(spec) != "numeric" or _op_name(spec["reduce"]) != reduce:
        raise ValueError("a mean shape this SDK version cannot rebuild")
    extract = _extract_from_spec(spec, "numeric")
    options: dict[str, Any] = {} if weights is None else {"weights": weights}
    return Reduce("mean", mode=_MEAN_MODES[_op_name(spec["select"])], extract=extract, **options)


_REBUILD: Mapping[str, Callable[[Mapping[str, object]], Reduce]] = MappingProxyType(
    {"vote": _rebuild_vote, "median": _rebuild_median, "mean": _rebuild_mean}
)


def _rebuild_plain(spec: Mapping[str, object]) -> Reduce:
    rebuilt = _REBUILD.get(str(spec.get("reducer")))
    if rebuilt is None:
        raise ValueError("not a rebuildable reducer")
    return rebuilt(spec)


def _rebuild_with_signals(spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> Reduce:
    """Only a judge-weighted vote reads model calls (8S F6); anything else is refused."""

    if spec.get("reducer") != "vote" or spec.get("weights") != {"signal": JUDGE_SIGNAL}:
        raise ValueError("a signal shape this SDK version cannot rebuild")
    # WHY lazy: judge.py imports this module to register its block form (F10)
    from screamingface.judge import judge_from_signals

    return _rebuild_vote(spec, judge=judge_from_signals(signals, "scores"))


def _rebuilt_block(spec: Mapping[str, object], rebuild: Callable[[], Reduce]) -> Reduce:
    """Run one rebuild; every refusal is the one "cannot rebuild" error."""

    try:
        return rebuild()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(
            f"URL4 Candidate has a {spec.get('reducer')} spec this SDK version cannot rebuild"
        ) from exc


__all__: list[str] = []
