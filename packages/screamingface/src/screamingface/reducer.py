"""Deterministic Fusion synthesizers: pure rules compiled to one combine call (OME-1289)."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast, get_args

from screamingface._candidate_policy import GenerationParams
from screamingface._evaluation.operators import STAGES
from screamingface._immutable_json import freeze_mapping, thaw_mapping
from screamingface._signals import FIELD_PATH, JUDGE_SIGNAL, Signal

if TYPE_CHECKING:
    from screamingface.judge import Judge

type _ReducerKind = Literal["answer", "selection", "projection"]
type _ReducerName = Literal["vote", "median", "judge", "pick", "merge", "project", "rank", "concat"]
# One source for each vocabulary: the Literal above is the list, the sets are derived from it.
REDUCER_NAMES: frozenset[str] = frozenset(get_args(_ReducerName.__value__))
REDUCER_KINDS: frozenset[str] = frozenset(get_args(_ReducerKind.__value__))


@dataclass(frozen=True, slots=True, init=False)
class _Step:
    """One operator use: a short name ('last_number') or a pinned id ('last_number@1')."""

    op: str
    args: Mapping[str, object]

    def __init__(self, op: str, args: Mapping[str, object] | None = None) -> None:
        if not isinstance(op, str) or not op.strip():
            raise TypeError("a reducer operator must be a non-empty string")
        object.__setattr__(self, "op", op)
        object.__setattr__(
            self, "args", freeze_mapping({} if args is None else args, f"operator {op!r} args")
        )


@dataclass(frozen=True, slots=True)
class _Steps:
    reduce: _Step
    select: _Step
    extract: _Step | None = None
    normalize: _Step | None = None


@dataclass(frozen=True, slots=True)
class _ModelSignal:
    """One model call whose reply the combine call reads as ``context.signals[key]``."""

    key: str  # "judge" or "writer_<field>"
    model: str  # the route as sf.Model stores it
    prompt: str  # the full system text in Python form ("\n" newlines)
    params: GenerationParams
    # The field a writer call writes. It marks a call fed by a projection of that field's values
    # (not by the Fusion context), so the compiler adds the projection combine call before it.
    field: str | None = None


@dataclass(frozen=True, slots=True)
class _ReducerPlan:
    """What a reducer compiles to: the combine spec minus its member list, with unpinned ops.

    SEAM (OME-1289 gap, block-api delta 1): sf.Reduce builds one now; the named reducers (unit 5+)
    build one too, so a block and its named form compile to the same bytes.
    """

    reducer: _ReducerName
    kind: _ReducerKind
    steps: _Steps
    weights: tuple[float, ...] | Signal | None = None
    # FEATURE (GP-1): extract and normalize come from the selected benchmark's answer rule; the
    # builder leaves both steps None and compile (resolve_benchmark_rule) fills them before pinning.
    benchmark_rule: bool = False
    # AIDEV-NOTE: the model calls the combine call reads besides its members. 9S adds writer calls
    # and 10S Rank-by-judge calls here, so a block and its named form keep sharing one plan.
    signal_calls: tuple[_ModelSignal, ...] = ()
    # The signal a by_signal reduce step reads (Pick by signal; 10S adds Rank and Filter). A
    # weighted vote reads its signal through ``weights`` instead; see ``_read_signal``.
    reads: Signal | None = None


_MAX_PATH_CHARS = 256


def _field_path(value: object, label: str) -> str:
    """``value`` if it is a JSON field path of at most 256 characters, else TypeError/ValueError."""

    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if len(value) > _MAX_PATH_CHARS or FIELD_PATH.fullmatch(value) is None:
        raise ValueError(
            f"{label} {value!r} must be a JSON path like 'score', 'a.b' or 'a[0].b' "
            f"(at most {_MAX_PATH_CHARS} characters)"
        )
    return value


def _read_signal(plan: _ReducerPlan) -> Signal | None:
    """The one signal a plan reads, through its weights or its ``reads`` (GE5: at most one)."""

    # INVARIANT (GE5): a spec reads at most one signal, so weights and reads never both hold one.
    assert not (isinstance(plan.weights, Signal) and plan.reads is not None)
    return plan.weights if isinstance(plan.weights, Signal) else plan.reads


def _refuse_judge_signal(signal: Signal, label: str, use: str) -> None:
    """Refuse ``score:judge`` on a reducer that has no judge: the Engine reads it strictly (GE15),
    so the case would fail after the member calls are paid. ``use`` names what to do instead."""

    if signal.key == JUDGE_SIGNAL:
        raise ValueError(
            f"{label} cannot read sf.signal({JUDGE_SIGNAL!r}): it has no judge; use {use}"
        )


BENCHMARK_EXTRACT = "benchmark"  # the rule name sf.Vote, sf.Median and sf.Extract share


class Reducer(ABC):
    """Non-constructible umbrella type for deterministic Fusion synthesizers.

    A reducer is not a Recipe: it is valid only as ``sf.Fusion(..., synthesizer=<reducer>)``.
    """

    name: str

    @abstractmethod
    def _plan(self) -> _ReducerPlan:
        """The reducer name, kind (answer | selection | projection), unpinned operator steps and
        weights; the compiler pins the steps against the Engine catalog."""

    @classmethod
    @abstractmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Reducer:
        """Rebuild an equal reducer from a decoded combine spec.

        An operator the reducer names without a version (for example ``last_line``) is written as a
        short name, so the editable Python of ``Url4.to_python`` pins it again to the newest version
        of the catalog it is compiled against.
        """

    @classmethod
    def _rebuild(cls, spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> Reducer:
        """Rebuild from a decoded spec plus the model calls it reads (url4). A pure rule refuses
        signals."""
        if signals:
            raise ValueError("URL4 Candidate has invalid Reducer topology metadata")
        return cls._from_spec(spec)

    def _python(self) -> str:
        """The ``sf.`` source that rebuilds this reducer (read by ``Url4.to_python``)."""
        return f"sf.{self!r}"

    def _check_members(self, count: int) -> None:
        """Raise ValueError when this reducer cannot serve ``count`` members (Fusion build time)."""
        return None

    def _compiles_to_combine(self) -> bool:
        """Whether this reducer compiles to a combine call. sf.Reduce('context') does not: the
        Fusion recipe rewrite removes it, so it needs no operators and has no member cap."""
        return True


# Concrete reducers register here (later units add more names beside vote and median).
_REDUCER_CLASSES: dict[str, type[Reducer]] = {}


_MEDIAN_SELECTS: frozenset[str] = frozenset({"nearest", "value"})


def _op_name(op: str | None) -> str | None:
    return None if op is None else op.split("@", 1)[0]


def _cannot_rebuild(name: str) -> ValueError:
    return ValueError(f"URL4 Candidate has a {name} spec this SDK version cannot rebuild")


def _decoded[T](name: str, build: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a public constructor on url4 data (a person may have edited it).

    A refusal means the spec is not one this SDK writes, so it is the one "cannot rebuild" error
    and never the constructor's own text (for example a score:judge spec with no judge call).
    """

    try:
        return build(*args, **kwargs)
    except (TypeError, ValueError) as exc:
        raise _cannot_rebuild(name) from exc


def _spec_steps(spec: Mapping[str, object]) -> dict[str, tuple[str, Mapping[str, object]] | None]:
    """stage -> (pinned op id, args), None for an absent step: what a decoded spec holds."""

    steps: dict[str, tuple[str, Mapping[str, object]] | None] = {}
    for stage in STAGES:
        step = spec[stage]
        if step is None:
            steps[stage] = None
            continue
        assert isinstance(step, Mapping)
        steps[stage] = (str(step["op"]), cast("Mapping[str, object]", step["args"]))
    return steps


def _step_matches(
    observed: tuple[str, Mapping[str, object]] | None, expected: _Step | None
) -> bool:
    """Does a decoded spec step equal the step a reducer writes?

    The op NAME must be equal. When the expected op is pinned (``name@v``) the id must be equal
    too. The args must be equal.
    """

    if observed is None or expected is None:
        return observed is None and expected is None
    op_id, args = observed
    same_op = op_id == expected.op if "@" in expected.op else _op_name(op_id) == expected.op
    return same_op and dict(args) == thaw_mapping(expected.args)


def _steps_match(spec: Mapping[str, object], steps: _Steps) -> bool:
    """Do all four stages of a decoded spec equal ``steps``, and the spec has no weights?"""

    observed = _spec_steps(spec)
    return spec["weights"] is None and all(
        _step_matches(observed[stage], getattr(steps, stage)) for stage in STAGES
    )


def _require_steps(spec: Mapping[str, object], steps: _Steps, name: str) -> None:
    """Refuse (a hand-edited url4) unless the spec is exactly what ``steps`` would write."""

    if not _steps_match(spec, steps):
        raise _cannot_rebuild(name)


def _spec_ops(spec: Mapping[str, object], name: str) -> dict[str, str | None]:
    """stage -> pinned op id (None for an absent step). Refuses step args: v1 takes none."""

    ops: dict[str, str | None] = {}
    for stage, step in _spec_steps(spec).items():
        if step is not None and step[1]:
            raise _cannot_rebuild(name)
        ops[stage] = None if step is None else step[0]
    return ops


class _DefaultNormalize(str):
    """sf.Vote's default normalizer, told apart from an explicit normalize='text' (GP-E2).

    WHY a str subclass: the public signature (and its snapshot) still renders ``= 'text'``.
    """

    __slots__ = ()


_DEFAULT_NORMALIZE: str = _DefaultNormalize("text")


def _vote_normalize(extract: str, normalize: str | None) -> str | None:
    """The normalizer a Vote stores; extract='benchmark' takes the benchmark's own (GP-E2)."""

    if _op_name(extract) != BENCHMARK_EXTRACT:
        if normalize is not None:
            _Step(normalize)  # TypeError for a non-str or blank name
        return None if normalize is None else str(normalize)
    if extract != BENCHMARK_EXTRACT:
        raise ValueError(
            "extract='benchmark' names the benchmark's answer rule and takes no version"
        )
    if normalize is not _DEFAULT_NORMALIZE:
        raise ValueError(
            "sf.Vote(extract='benchmark') takes the benchmark's own normalizer; "
            "v1 does not let a recipe change it"
        )
    return None


# WHY the cap: the Engine sums weights, and a sum over every member must stay a finite float
# (D-7/D-12). It is the Engine's own cap, sys.float_info.max / the member limit.
_MAX_REDUCER_MEMBERS = 256
_MAX_WEIGHT = sys.float_info.max / _MAX_REDUCER_MEMBERS


def _weights_option(value: object, label: str) -> tuple[float, ...] | Signal:
    """A Signal as given, or one positive finite float per member (the one weights rule)."""

    if isinstance(value, Signal):
        return value
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise _weights_type_error(label)
    if not value:
        raise ValueError(f"{label} must not be empty")
    return tuple(_weight(item, label) for item in value)


def _weight(item: object, label: str) -> float:
    if isinstance(item, bool) or not isinstance(item, int | float):
        raise _weights_type_error(label)
    if not 0 < item <= _MAX_WEIGHT:  # NaN fails the comparison; an int compares exactly
        raise ValueError(
            f"{label} must be finite and greater than zero, and at most {_MAX_WEIGHT!r}, "
            f"not {item!r}"
        )
    return float(item)


def _weights_type_error(label: str) -> TypeError:
    return TypeError(f"{label} must be a sequence of numbers, one per member, or an sf.signal")


def _reads_judge(weights: object) -> bool:
    return isinstance(weights, Signal) and weights.key == JUDGE_SIGNAL


def _check_judge_weights(weights: object, judge: object, label: str) -> None:
    """The one pairing rule (8S F5): weights=sf.signal('score:judge') and a scores judge go
    together. The Engine reads score:judge strictly, so a lone half would fail after the member
    calls are paid. The messages never echo the rubric.
    """

    if judge is not None:
        # WHY lazy: judge.py imports this module (cycle)
        from screamingface.judge import Judge

        if not isinstance(judge, Judge):
            raise TypeError(f"{label} judge must be an sf.Judge")
        if judge.returns != "scores":
            raise ValueError(
                f"{label} judge needs sf.Judge(..., returns='scores'): "
                "the vote reads one score per member"
            )
        if not _reads_judge(weights):
            raise ValueError(f"{label} judge is read only by weights=sf.signal('score:judge')")
    elif _reads_judge(weights):
        raise ValueError(
            "weights=sf.signal('score:judge') needs a judge on the same reducer: "
            "add judge=sf.Judge(..., returns='scores')"
        )


def _vote_plan(
    extract: _Step | None,
    normalize: _Step | None,
    weights: tuple[float, ...] | Signal | None,
    *,
    benchmark_rule: bool,
    judge: Judge | None = None,
) -> _ReducerPlan:
    """The one plan behind sf.Vote and sf.Reduce('plurality'|'weighted') (BK-1, BK#4)."""

    weighted = weights is not None
    steps = _Steps(
        reduce=_Step("weighted_mode" if weighted else "mode"),
        select=_Step("max_weight_holder" if weighted else "first_holder"),
        extract=extract,
        normalize=normalize,
    )
    return _ReducerPlan(
        "vote",
        "answer",
        steps,
        weights,
        benchmark_rule=benchmark_rule,
        signal_calls=() if judge is None else (judge._signal_call(),),
    )


def _recovered_weights(spec: Mapping[str, object]) -> tuple[float, ...] | Signal | None:
    """The weights of a decoded vote spec, or ValueError when they are not a Vote's."""

    weights = spec["weights"]
    if weights is None:
        return None
    if isinstance(weights, Mapping) and set(weights) == {"signal"}:
        return _recovered_signal(weights["signal"])
    return _recovered_member_weights(weights, spec["members"])


def _recovered_signal(key: object) -> Signal:
    if not isinstance(key, str):
        raise _cannot_rebuild("vote")
    return Signal(key)


def _recovered_member_weights(weights: object, members: object) -> tuple[float, ...]:
    if (
        not isinstance(weights, Mapping)
        or not isinstance(members, list)
        or set(weights) != set(members)
    ):
        raise _cannot_rebuild("vote")
    # member order, not the weights' key order: canonical JSON sorts member_10 before member_2
    values = [weights[member] for member in members]
    if any(isinstance(v, bool) or not isinstance(v, int | float) for v in values):
        raise _cannot_rebuild("vote")
    return tuple(values)


def _as_python(value: object) -> str:
    python = getattr(value, "_python", None)
    return repr(value) if python is None else python()


@dataclass(frozen=True, slots=True, init=False)
class Vote(Reducer):
    """Plurality vote: the first member (author order) holding the most common answer, verbatim.

    ``extract='benchmark'`` reads answers with the benchmark's own grading rule (resolved before any
    spend); for rules with arguments use
    ``sf.Reduce('plurality', extract=sf.Extract('regex', pattern=...))``.

    ``judge=sf.Judge(..., returns='scores')`` goes with ``weights=sf.signal('score:judge')`` and
    never alone: the judge scores each member in one call, and each answer weighs the scores of its
    holders. A half pair raises ``ValueError`` when the vote is built.
    """

    name: str
    extract: str
    normalize: str | None
    weights: tuple[float, ...] | Signal | None
    judge: Judge | None

    def __init__(
        self,
        *,
        extract: str = "last_line",
        normalize: str | None = _DEFAULT_NORMALIZE,
        weights: Sequence[float] | Signal | None = None,
        judge: Judge | None = None,
    ) -> None:
        _Step(extract)  # TypeError for a non-str or blank name
        object.__setattr__(self, "name", "vote")
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "normalize", _vote_normalize(extract, normalize))
        object.__setattr__(
            self, "weights", None if weights is None else _weights_option(weights, "Vote weights")
        )
        _check_judge_weights(self.weights, judge, "Vote")
        object.__setattr__(self, "judge", judge)

    @property
    def _is_benchmark(self) -> bool:
        return self.extract == BENCHMARK_EXTRACT

    def _plan(self) -> _ReducerPlan:
        benchmark = self._is_benchmark
        return _vote_plan(
            None if benchmark else _Step(self.extract),
            None if self.normalize is None else _Step(self.normalize),
            self.weights,
            benchmark_rule=benchmark,
            judge=self.judge,
        )

    def _check_members(self, count: int) -> None:
        if isinstance(self.weights, tuple) and len(self.weights) != count:
            raise ValueError(f"{self.name} has {len(self.weights)} weights for {count} members")

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Vote:
        return cls._from_spec_parts(spec, None)

    @classmethod
    def _rebuild(cls, spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> Vote:
        if not signals:
            return cls._from_spec(spec)
        # WHY lazy: judge.py imports this module (cycle)
        from screamingface.judge import judge_from_signals

        judge = judge_from_signals(signals, "scores")
        if spec["weights"] != {"signal": JUDGE_SIGNAL}:
            raise _cannot_rebuild("vote")
        return cls._from_spec_parts(spec, judge)

    @classmethod
    def _from_spec_parts(cls, spec: Mapping[str, object], judge: Judge | None) -> Vote:
        ops = _spec_ops(spec, "vote")
        extract = ops["extract"]
        weights = _recovered_weights(spec)
        pair = (_op_name(ops["reduce"]), _op_name(ops["select"]))
        # the operator pair must agree with the weights, or the spec is not a Vote this SDK writes
        expected = (
            ("mode", "first_holder") if weights is None else ("weighted_mode", "max_weight_holder")
        )
        if extract is None or pair != expected:
            raise _cannot_rebuild("vote")
        return _decoded(
            "vote", cls, extract=extract, normalize=ops["normalize"], weights=weights, judge=judge
        )

    def __repr__(self) -> str:
        return self._render("Vote", repr)

    def _python(self) -> str:
        return self._render("sf.Vote", _as_python)

    def _render(self, head: str, show: Callable[[object], str]) -> str:
        weights = "" if self.weights is None else f", weights={show(self.weights)}"
        judge = "" if self.judge is None else f", judge={show(self.judge)}"
        if self._is_benchmark:
            return f"{head}(extract={self.extract!r}{weights}{judge})"
        return f"{head}(extract={self.extract!r}, normalize={self.normalize!r}{weights}{judge})"

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False)
class Median(Reducer):
    """Median of the members' numeric answers: the nearest member's text, or the number itself."""

    name: str
    extract: str
    select: str

    def __init__(
        self, *, extract: str = "last_number", select: str = "nearest", weights: None = None
    ) -> None:
        if weights is not None:
            raise TypeError("weights apply to Vote only")
        _Step(extract)
        _Step(select)
        if _op_name(extract) == BENCHMARK_EXTRACT:
            raise ValueError(
                "sf.Median needs the numeric normalizer, so it cannot read extract='benchmark' "
                "(the benchmark brings its own normalizer)"
            )
        if _op_name(select) not in _MEDIAN_SELECTS:
            raise ValueError(f"Median select must be 'nearest' or 'value', not {select!r}")
        object.__setattr__(self, "name", "median")
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "select", select)

    def _plan(self) -> _ReducerPlan:
        steps = _Steps(
            reduce=_Step("median"),
            select=_Step(self.select),
            extract=_Step(self.extract),
            normalize=_Step("numeric"),
        )
        return _ReducerPlan("median", "answer", steps)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> Median:
        ops = _spec_ops(spec, "median")
        extract = ops["extract"]
        select = ops["select"]
        if (
            extract is None
            or select is None
            or _op_name(ops["normalize"]) != "numeric"
            or _op_name(ops["reduce"]) != "median"
            or _op_name(select) not in _MEDIAN_SELECTS
            or spec["weights"] is not None
        ):
            raise _cannot_rebuild("median")
        return cls(extract=extract, select=select)

    def __repr__(self) -> str:
        return f"Median(extract={self.extract!r}, select={self.select!r})"

    __hash__: ClassVar[Any] = None


_REDUCER_CLASSES.update(vote=Vote, median=Median)

__all__ = ["Median", "Reducer", "Vote"]
