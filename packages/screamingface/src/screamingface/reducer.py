"""Deterministic Fusion synthesizers: pure rules compiled to one combine call (OME-1289)."""

from __future__ import annotations

import copy
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast, get_args

from screamingface._candidate_policy import GenerationParams
from screamingface._evaluation.operators import STAGES
from screamingface._immutable_json import freeze_mapping, thaw_mapping
from screamingface._signals import FIELD_PATH, JUDGE_SIGNAL, Signal

if TYPE_CHECKING:
    # Gate, Judge: the public names in the sf.Vote signature until the swap (unit 7e)
    from screamingface.gate import Gate, GateNode
    from screamingface.judge import Judge, JudgeNode
    from screamingface.model import Model

type _ReducerKind = Literal["answer", "selection", "projection"]
type _ReducerName = Literal[
    "vote", "median", "judge", "pick", "merge", "project", "rank", "concat", "filter", "mean"
]
# One source for each vocabulary: the Literal above is the list, the sets are derived from it.
REDUCER_NAMES: frozenset[str] = frozenset(get_args(_ReducerName.__value__))
REDUCER_KINDS: frozenset[str] = frozenset(get_args(_ReducerKind.__value__))
# The two statistic reducers: sf.Median, sf.Mean and their sf.Reduce blocks share one code path.
type _Statistic = Literal["median", "mean"]


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

    key: str  # "judge", "writer_<field>", "fallback_judge" or "fallback_writer"
    model: str  # the route as sf.Model stores it
    prompt: str  # the full system text in Python form ("\n" newlines)
    params: GenerationParams
    # The field a writer call writes. It marks a call fed by a projection of that field's values
    # (not by the Fusion context), so the compiler adds the projection combine call before it.
    field: str | None = None


# The reducer signal keys of a gate fallback call (E4b part 5, P5). The topology maps them to the
# judge and writer roles (_signal_role); the Engine `_SIGNAL` pattern accepts both (C6).
_FALLBACK_JUDGE_KEY = "fallback_judge"
_FALLBACK_WRITER_KEY = "fallback_writer"
# The gate ``otherwise`` word -> the key of its fallback call ("abstain" has no call).
_FALLBACK_KEYS: Mapping[Literal["judge", "writer"], str] = MappingProxyType(
    {"judge": _FALLBACK_JUDGE_KEY, "writer": _FALLBACK_WRITER_KEY}
)
# The key of E4a's judge call: the one call that every step reading score:judge reads.
_JUDGE_KEY = "judge"
# The keys of the model calls that judge the members: E4a's "judge" and a vote gate's fallback
# label judge (E4b part 5).
_JUDGE_CALL_KEYS: frozenset[str] = frozenset({_JUDGE_KEY, _FALLBACK_JUDGE_KEY})
# NR-S1 (narrow PRD, O10): the most narrow steps before one main step; the Engine ports the same
# bound, and the SDK evidence decoder reads it.
MAX_NARROW_STEPS = 4
# The ONE table of the narrow steps (narrow PRD §2, NARROW_RULES): select op name -> the reducer
# of that narrow step. The url4 rebuild reads a narrow item through it.
_NARROW_SELECTS: Mapping[str, str] = MappingProxyType({"kept": "filter", "top_k": "rank"})
_NARROW_REDUCERS: frozenset[str] = frozenset(_NARROW_SELECTS.values())


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
    # E4b part 5 (P1): the vote's gate; combine_spec_text writes its _spec() as "gate".
    gate: GateNode | None = None
    # E4b narrow (narrow.md §6): the plans of the narrow steps that run before this step in the
    # same combine call, in chain order; combine_spec_text writes them as the spec "narrow" list.
    # Only ``Reducer._combine_plan`` fills it, so a step's own ``_plan()`` leaves it empty.
    narrow: tuple[_ReducerPlan, ...] = ()


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


def _step_plans(plan: _ReducerPlan) -> tuple[_ReducerPlan, ...]:
    """The plan of each step of one combine call: the narrow steps in order, then the main step.

    WHY per step: each step reads at most one signal (NR-S3), so a check that reads a plan's
    signal or weights runs on each of these (narrow.md §5).
    """

    return (*plan.narrow, plan)


def _with_narrow(plan: _ReducerPlan, narrow: tuple[Reducer, ...]) -> _ReducerPlan:
    """``plan`` with the plans of its narrow steps, and the model calls of every step once.

    INVARIANT (narrow.md §6): a judge that more than one step reads is ONE call, so the combine
    call reads each signal key once. Two calls under one key that differ (a different prompt or
    params) cannot be one call, so they are refused.
    """

    if not narrow:
        return plan
    plans = tuple(step._plan() for step in narrow)
    calls: dict[str, _ModelSignal] = {}
    for call in (*(call for step in plans for call in step.signal_calls), *plan.signal_calls):
        known = calls.setdefault(call.key, call)
        if known != call:
            raise ValueError(
                f"two steps of one combine call read the {call.key!r} call with a different "
                "prompt or params, so it cannot be one call"
            )
    return replace(plan, narrow=plans, signal_calls=tuple(calls.values()))


def _narrow_steps(reducer: Reducer) -> tuple[Reducer, ...]:
    """The narrow steps a reducer carries (lowering §2.2, "the narrow carrier")."""

    return reducer._narrow if reducer._carries_narrow else ()


def _narrowed[R: Reducer](reducer: R, narrow: tuple[Reducer, ...]) -> R:
    """A copy of ``reducer`` that runs ``narrow`` first, in the same combine call; ``reducer``
    itself when ``narrow`` is empty.

    INVARIANT: the ONE gate of the carrier. The lowering (``S/_surface/lowering.py``) and the url4
    rebuild (``S/url4.py``) are its only callers, so a hand-edited url4 meets the same rules as a
    chain: NR-S1 (at most ``MAX_NARROW_STEPS``), NR-C1 (no main step that makes its own call over
    every member), only Rank and Filter as narrow steps, and one judge call.
    WHY a copy: a lowered step can be a value that other steps share (the block's judge node is
    the synthesizer of ``ArgMax("score:judge")``), so the carrier is never set on it in place.
    """

    if not narrow:
        return reducer
    if not reducer._carries_narrow:
        raise ValueError(f"sf.{reducer._public_name} cannot follow a narrow step")
    if len(narrow) > MAX_NARROW_STEPS:
        raise ValueError(f"a combine call takes 1 to {MAX_NARROW_STEPS} narrow steps")
    whole = reducer._whole_context_call()
    if whole is not None:  # NR-C1 (O11): it would see the members the narrow steps left out
        raise ValueError(
            f"{whole} makes its own call over every member, so it cannot follow a narrow step"
        )
    for step in narrow:
        if step._plan().reducer not in _NARROW_REDUCERS or _narrow_steps(step):
            raise ValueError(f"sf.{step._public_name} is not a narrow step")
    _with_narrow(reducer._plan(), narrow)
    copied = copy.copy(reducer)
    object.__setattr__(copied, "_narrow", narrow)
    return copied


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
    # The narrow carrier (lowering §2.2): the narrow steps that run before this step in its combine
    # call. A class that a narrow step can come before sets ``_carries_narrow`` and declares the
    # private dataclass field ``_narrow`` (``init=False``, default ``()``, out of the repr), set
    # in its ``__init__`` to ``()``. Only ``_narrowed`` gives it steps; it is not a parameter, so
    # no public signature or field moves. Equality reads it: equal values compile to equal bytes.
    _carries_narrow: ClassVar[bool] = False
    _narrow: tuple[Reducer, ...]
    # The class name a message shows as ``sf.<name>``: a node class keeps its public name of today
    # until the swap rewords those messages (unit 7g); any other reducer shows its class name.
    _public_name: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "_public_name" not in vars(cls):
            cls._public_name = cls.__name__

    @abstractmethod
    def _plan(self) -> _ReducerPlan:
        """The reducer name, kind (answer | selection | projection), unpinned operator steps and
        weights; the compiler pins the steps against the Engine catalog."""

    def _whole_context_call(self) -> str | None:
        """What makes its own model call over the whole Fusion context, so it cannot follow a
        narrow step (NR-C1, O11), in the user's words; None for a step with no such call."""

        return None

    def _combine_plan(self) -> _ReducerPlan:
        """The plan of the whole combine call: ``_plan()`` with the narrow steps this reducer
        carries (narrow.md §6). Every compile place reads this one, never ``_plan()`` alone."""

        return _with_narrow(self._plan(), _narrow_steps(self))

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


# The select ops of sf.Median and sf.Mean: the nearest member's text, or the number itself.
_NUMERIC_SELECTS: frozenset[str] = frozenset({"nearest", "value"})

# What sf.Mean tells an author who passed sf.signal("score:judge") (MN-E4).
_MEAN_SIGNAL_USE = "a JSON field signal such as sf.signal('field:confidence')"


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


def _check_weight_count(name: str, weights: tuple[float, ...] | Signal | None, count: int) -> None:
    """Raise ValueError when authored weights (one per member) do not match ``count`` members."""
    if isinstance(weights, tuple) and len(weights) != count:
        raise ValueError(f"{name} has {len(weights)} weights for {count} members")


def _reads_judge(weights: object) -> bool:
    return isinstance(weights, Signal) and weights.key == JUDGE_SIGNAL


def _refuse_min_order_judge(judge: JudgeNode, label: str) -> None:
    """JO-D1 (P6): a judge with order='min' is only a Fusion synthesizer.

    Rank, Vote and Filter (unit 6) read the judge's scores with their own rule (Rank has its own
    order=), so a second order would conflict. The message never echoes the rubric.
    """

    if judge.order == "min":
        raise ValueError(
            f"{label} cannot use sf.Judge(..., order='min'): a judge with order='min' works only "
            "as the Fusion synthesizer; give this judge the default order='max'"
        )


def _check_judge_pair(
    judge: object, reads_judge: bool, label: str, *, reader: str, read_by: str, unpaired: str
) -> None:
    """The one pairing rule (8S F5): a score:judge read and a scores judge go together.

    The Engine reads score:judge strictly, so a lone half would fail after the member calls are
    paid. ``reader`` names what reads the scores ("vote", "filter"). ``read_by`` names the
    argument that reads the judge. ``unpaired`` starts the error for a read with no judge. The
    messages never echo the rubric.
    """

    if judge is None:
        if reads_judge:
            raise ValueError(
                f"{unpaired} needs a judge on the same reducer: "
                "add judge=sf.Judge(..., returns='scores')"
            )
        return
    # WHY lazy: judge.py imports this module (cycle)
    from screamingface.judge import JudgeNode

    if not isinstance(judge, JudgeNode):
        raise TypeError(f"{label} judge must be an sf.Judge")
    if judge.returns != "scores":
        raise ValueError(
            f"{label} judge needs sf.Judge(..., returns='scores'): "
            f"the {reader} reads one score per member"
        )
    _refuse_min_order_judge(judge, label)  # P6 / JO-D1: refuses order="min"
    if not reads_judge:
        raise ValueError(f"{label} judge is read only by {read_by}")


def _check_judge_weights(weights: object, judge: object, label: str) -> None:
    """The pairing rule of a vote: weights=sf.signal('score:judge') and a scores judge."""

    signal = "weights=sf.signal('score:judge')"
    _check_judge_pair(
        judge, _reads_judge(weights), label, reader="vote", read_by=signal, unpaired=signal
    )


def _vote_gate(gate: object) -> GateNode | None:
    """``gate`` when it is None or an sf.Gate, else TypeError (GA-E3)."""

    if gate is None:
        return None
    # WHY lazy: gate.py imports judge.py, which imports this module (cycle)
    from screamingface.gate import GateNode

    if not isinstance(gate, GateNode):
        raise TypeError("Vote gate must be an sf.Gate")
    return gate


def _check_verify(verify: object) -> None:
    """The reserved verifier slot (ans:Q4, P15): only None now; a later part adds the check."""

    if verify is not None:
        raise ValueError("sf.Vote verify= is reserved for a later part; pass None or leave it out")


def _vote_plan(
    extract: _Step | None,
    normalize: _Step | None,
    weights: tuple[float, ...] | Signal | None,
    *,
    benchmark_rule: bool,
    judge: JudgeNode | None = None,
    gate: GateNode | None = None,
) -> _ReducerPlan:
    """The one plan behind sf.Vote and sf.Reduce('plurality'|'weighted') (BK-1, BK#4)."""

    weighted = weights is not None
    steps = _Steps(
        reduce=_Step("weighted_mode" if weighted else "mode"),
        select=_Step("max_weight_holder" if weighted else "first_holder"),
        extract=extract,
        normalize=normalize,
    )
    calls = () if judge is None else (judge._signal_call(),)
    fallback = None if gate is None else gate._signal_call()
    return _ReducerPlan(
        "vote",
        "answer",
        steps,
        weights,
        benchmark_rule=benchmark_rule,
        signal_calls=calls if fallback is None else (*calls, fallback),
        gate=gate,
    )


def _recovered_weights(spec: Mapping[str, object]) -> tuple[float, ...] | Signal | None:
    """The weights of a decoded vote, median or mean spec, else ValueError.

    The error names the vote: a bad shape is the vote's "cannot rebuild" error, and an unknown
    signal key is the Signal's own error. sf.Median and sf.Mean (``_numeric_from_spec``) and the
    block rebuilds (``_rebuilt_block`` in blocks.py) replace it with their own error.
    """

    weights = spec["weights"]
    if weights is None:
        return None
    if isinstance(weights, Mapping) and set(weights) == {"signal"}:
        return _recovered_signal(weights["signal"])
    return _recovered_member_weights(weights, spec["members"])


def _recovered_signal(key: object) -> Signal:
    """A decoded signal key as a Signal; the error names the vote (see ``_recovered_weights``)."""
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


# The part 5 keys of a spec gate; E4b part 6 adds the optional "abstain_band" (C6).
_GATE_SPEC_KEYS: frozenset[str] = frozenset({"cmp", "observe", "otherwise", "threshold"})
_BAND_KEY = "abstain_band"


def _rebuilt_fallback(fallback: _ModelSignal) -> JudgeNode | Model:
    """The sf.Judge or sf.Model of a gate fallback call read back from url4 (C7)."""

    if fallback.key == _FALLBACK_JUDGE_KEY:
        # WHY lazy: judge.py imports this module (cycle)
        from screamingface.judge import judge_from_signals

        # judge_from_signals reads only the key "judge" (S/judge.py), so the key is renamed first;
        # its signature does not change (C7).
        return _decoded("vote", judge_from_signals, (replace(fallback, key="judge"),), "label")
    # WHY lazy: the model module imports the recipe tree, which imports this module
    from screamingface._evaluation.policy import DEFAULT_SYNTHESIS_PROMPT
    from screamingface.model import Model

    # The url4.py rule of a model synthesizer: the default prompt rebuilds as no prompt (GA-D3).
    prompt = None if fallback.prompt == DEFAULT_SYNTHESIS_PROMPT else fallback.prompt
    return _decoded(
        "vote", Model, fallback.model, prompt=prompt, params=dict(fallback.params) or None
    )


def _rebuilt_band(raw: Mapping[str, object]) -> tuple[object, ...] | None:
    """The spec gate band as the tuple sf.Gate checks; None when the key is absent.

    WHY a present non-list (null included) is the vote's "cannot rebuild" here and never reaches
    sf.Gate: the constructor takes abstain_band=None as "no band", so a hand-edited null would
    rebuild as a gate with no band, which compiles to different bytes (BA-E2, BD-I2).
    """

    if _BAND_KEY not in raw:
        return None
    band = raw[_BAND_KEY]
    if not isinstance(band, list):
        raise _cannot_rebuild("vote")
    return tuple(band)


def _rebuilt_gate(spec: Mapping[str, object], fallback: _ModelSignal | None) -> GateNode | None:
    """The gate of a decoded vote spec and its fallback call, else the vote's "cannot rebuild".

    INVARIANT (C7): the spec ``otherwise`` and the fallback call agree: "abstain" has no call,
    "judge" has the ``fallback_judge`` call, "writer" has the ``fallback_writer`` call. Any other
    pair is a hand-edited url4 (GA-E4). The gate holds the four part 5 keys, or those four and
    "abstain_band" (C6).
    """

    raw = spec.get("gate")
    if raw is None:
        if fallback is not None:
            raise _cannot_rebuild("vote")  # a fallback call with no gate
        return None
    if not isinstance(raw, Mapping) or set(raw) - {_BAND_KEY} != _GATE_SPEC_KEYS:
        raise _cannot_rebuild("vote")
    expected: dict[str, str | None] = {"abstain": None, **_FALLBACK_KEYS}
    wire = raw["otherwise"]
    found = None if fallback is None else fallback.key
    if not isinstance(wire, str) or wire not in expected or expected[wire] != found:
        raise _cannot_rebuild("vote")
    band = _rebuilt_band(raw)
    # WHY lazy: gate.py imports this module (cycle)
    from screamingface.gate import GateNode

    otherwise: object = "abstain" if fallback is None else _rebuilt_fallback(fallback)
    return _decoded(
        "vote",
        GateNode,
        raw["observe"],
        raw["cmp"],
        raw["threshold"],
        otherwise=otherwise,
        abstain_band=band,
    )


@dataclass(frozen=True, slots=True, init=False)
class VoteNode(Reducer):
    """Plurality vote: the first member (author order) holding the most common answer, verbatim.

    ``extract='benchmark'`` reads answers with the benchmark's own grading rule (resolved before any
    spend); for rules with arguments use
    ``sf.Reduce('plurality', extract=sf.Extract('regex', pattern=...))``.

    ``judge=sf.Judge(..., returns='scores')`` goes with ``weights=sf.signal('score:judge')`` and
    never alone: the judge scores each member in one call, and each answer weighs the scores of its
    holders. A half pair raises ``ValueError`` when the vote is built.

    ``gate=sf.Gate(...)`` keeps the majority only when one recorded number passes a threshold;
    else the gate's fallback answers (see ``sf.Gate``). ``verify=`` is reserved for a later
    verifier check and takes only None.
    """

    _public_name: ClassVar[str] = "Vote"
    name: str
    extract: str
    normalize: str | None
    weights: tuple[float, ...] | Signal | None
    judge: JudgeNode | None
    gate: GateNode | None
    verify: None
    _carries_narrow: ClassVar[bool] = True  # the narrow carrier: see Reducer._carries_narrow
    _narrow: tuple[Reducer, ...] = field(default=(), init=False, repr=False)

    def __init__(
        self,
        *,
        extract: str = "last_line",
        normalize: str | None = _DEFAULT_NORMALIZE,
        weights: Sequence[float] | Signal | None = None,
        judge: Judge | None = None,
        gate: Gate | None = None,
        verify: None = None,
    ) -> None:
        _Step(extract)  # TypeError for a non-str or blank name
        object.__setattr__(self, "name", "vote")
        object.__setattr__(self, "_narrow", ())
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "normalize", _vote_normalize(extract, normalize))
        object.__setattr__(
            self, "weights", None if weights is None else _weights_option(weights, "Vote weights")
        )
        _check_judge_weights(self.weights, judge, "Vote")
        object.__setattr__(self, "judge", judge)
        object.__setattr__(self, "gate", _vote_gate(gate))
        _check_verify(verify)
        object.__setattr__(self, "verify", None)

    @property
    def _is_benchmark(self) -> bool:
        return self.extract == BENCHMARK_EXTRACT

    def _whole_context_call(self) -> str | None:
        if self.gate is not None and self.gate.otherwise != "abstain":
            return "a gate with a model fallback"
        return None

    def _plan(self) -> _ReducerPlan:
        benchmark = self._is_benchmark
        return _vote_plan(
            None if benchmark else _Step(self.extract),
            None if self.normalize is None else _Step(self.normalize),
            self.weights,
            benchmark_rule=benchmark,
            judge=self.judge,
            gate=self.gate,
        )

    def _check_members(self, count: int) -> None:
        _check_weight_count(self.name, self.weights, count)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> VoteNode:
        return cls._from_spec_parts(spec, None)

    @classmethod
    def _rebuild(cls, spec: Mapping[str, object], signals: tuple[_ModelSignal, ...]) -> VoteNode:
        fallback_keys = frozenset(_FALLBACK_KEYS.values())
        fallbacks = tuple(signal for signal in signals if signal.key in fallback_keys)
        others = tuple(signal for signal in signals if signal.key not in fallback_keys)
        if len(fallbacks) > 1:
            raise _cannot_rebuild("vote")  # FC-I1: at most one fallback call
        fallback = fallbacks[0] if fallbacks else None
        if not others:
            return cls._from_spec_parts(spec, None, fallback)
        # WHY lazy: judge.py imports this module (cycle)
        from screamingface.judge import judge_from_signals

        judge = judge_from_signals(others, "scores")
        if spec["weights"] != {"signal": JUDGE_SIGNAL}:
            raise _cannot_rebuild("vote")
        return cls._from_spec_parts(spec, judge, fallback)

    @classmethod
    def _from_spec_parts(
        cls,
        spec: Mapping[str, object],
        judge: JudgeNode | None,
        fallback: _ModelSignal | None = None,
    ) -> VoteNode:
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
            "vote",
            cls,
            extract=extract,
            normalize=ops["normalize"],
            weights=weights,
            judge=judge,
            gate=_rebuilt_gate(spec, fallback),
        )

    def __repr__(self) -> str:
        return self._render("Vote", repr)

    def _python(self) -> str:
        return self._render("sf.Vote", _as_python)

    def _render(self, head: str, show: Callable[[object], str]) -> str:
        weights = "" if self.weights is None else f", weights={show(self.weights)}"
        judge = "" if self.judge is None else f", judge={show(self.judge)}"
        gate = "" if self.gate is None else f", gate={show(self.gate)}"
        if self._is_benchmark:
            return f"{head}(extract={self.extract!r}{weights}{judge}{gate})"
        return (
            f"{head}(extract={self.extract!r}, normalize={self.normalize!r}{weights}{judge}{gate})"
        )

    __hash__: ClassVar[Any] = None


_MEDIAN_JUDGE_USE = "authored weights or another signal, such as sf.signal('field:confidence')"

# sf.Median and sf.Mean share these helpers: the same options, plan, url4 rebuild and repr. Only
# the name, the default select, the select-choices text and the score:judge advice are different.


def _numeric_weights(
    label: Literal["Median", "Mean"],
    extract: str,
    select: str,
    weights: Sequence[float] | Signal | None,
    *,
    selects: str,
    judge_use: str,
) -> tuple[float, ...] | Signal | None:
    """Check the options of sf.Median or sf.Mean (``label``) and return the checked weights.

    ``selects`` is the select choices as the error names them. ``judge_use`` is what to use in
    place of a score:judge weight: a Median or a Mean has no judge.
    """

    _Step(extract)
    _Step(select)
    if _op_name(extract) == BENCHMARK_EXTRACT:
        raise ValueError(
            f"sf.{label} needs the numeric normalizer, so it cannot read extract='benchmark' "
            "(the benchmark brings its own normalizer)"
        )
    if _op_name(select) not in _NUMERIC_SELECTS:
        raise ValueError(f"{label} select must be {selects}, not {select!r}")
    checked = None if weights is None else _weights_option(weights, f"{label} weights")
    if isinstance(checked, Signal):
        _refuse_judge_signal(checked, label, judge_use)
    return checked


def _numeric_plan(
    name: _Statistic,
    extract: str,
    select: str,
    weights: tuple[float, ...] | Signal | None,
) -> _ReducerPlan:
    """The plan of sf.Median or sf.Mean: ``weighted_<name>`` when there are weights."""

    steps = _Steps(
        reduce=_Step(name if weights is None else f"weighted_{name}"),
        select=_Step(select),
        extract=_Step(extract),
        normalize=_Step("numeric"),
    )
    return _ReducerPlan(name, "answer", steps, weights)


def _numeric_from_spec[R: Reducer](cls: type[R], spec: Mapping[str, object], name: _Statistic) -> R:
    """Rebuild sf.Median or sf.Mean (``name``) from a decoded spec, else "cannot rebuild"."""

    ops = _spec_ops(spec, name)
    extract, select = ops["extract"], ops["select"]
    try:
        weights = _recovered_weights(spec)
    except ValueError as exc:
        raise _cannot_rebuild(name) from exc
    reduce = name if weights is None else f"weighted_{name}"
    if (
        extract is None
        or select is None
        or _op_name(ops["normalize"]) != "numeric"
        or _op_name(ops["reduce"]) != reduce
        or _op_name(select) not in _NUMERIC_SELECTS
    ):
        raise _cannot_rebuild(name)
    return _decoded(name, cls, extract=extract, select=select, weights=weights)


def _numeric_render(
    reducer: MedianNode | MeanNode, head: str, show: Callable[[object], str]
) -> str:
    weights = "" if reducer.weights is None else f", weights={show(reducer.weights)}"
    return f"{head}(extract={reducer.extract!r}, select={reducer.select!r}{weights})"


@dataclass(frozen=True, slots=True, init=False)
class MedianNode(Reducer):
    """Median of the members' numeric answers: the nearest member's text, or the number itself.

    ``weights`` (one positive number per member, or ``sf.signal(key)``) makes it a weighted median:
    a member with a missing or non-positive weight is dropped and is never the nearest pick. For a
    JSON field answer, use ``sf.Reduce("median", extract=sf.Extract("field", path=...),
    select=...)``.
    """

    _public_name: ClassVar[str] = "Median"
    name: str
    extract: str
    select: str
    weights: tuple[float, ...] | Signal | None
    _carries_narrow: ClassVar[bool] = True  # the narrow carrier: see Reducer._carries_narrow
    _narrow: tuple[Reducer, ...] = field(default=(), init=False, repr=False)

    def __init__(
        self,
        *,
        extract: str = "last_number",
        select: str = "nearest",
        weights: Sequence[float] | Signal | None = None,
    ) -> None:
        checked = _numeric_weights(
            "Median",
            extract,
            select,
            weights,
            selects="'nearest' or 'value'",
            judge_use=_MEDIAN_JUDGE_USE,
        )
        object.__setattr__(self, "name", "median")
        object.__setattr__(self, "_narrow", ())
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "select", select)
        object.__setattr__(self, "weights", checked)

    def _plan(self) -> _ReducerPlan:
        return _numeric_plan("median", self.extract, self.select, self.weights)

    def _check_members(self, count: int) -> None:
        _check_weight_count(self.name, self.weights, count)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> MedianNode:
        return _numeric_from_spec(cls, spec, "median")

    def __repr__(self) -> str:
        return _numeric_render(self, "Median", repr)

    def _python(self) -> str:
        return _numeric_render(self, "sf.Median", _as_python)

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False)
class MeanNode(Reducer):
    """Mean of the members' numeric answers: the number itself, or the nearest member's text.

    ``weights`` is one positive number per member (author order) or ``sf.signal(key)``. A member
    with no usable weight is dropped: it is not in the mean and never the nearest member. For a
    JSON field answer, use ``sf.Reduce("mean", extract=sf.Extract("field", path=...))``.
    """

    _public_name: ClassVar[str] = "Mean"
    name: str
    extract: str
    select: str
    weights: tuple[float, ...] | Signal | None
    _carries_narrow: ClassVar[bool] = True  # the narrow carrier: see Reducer._carries_narrow
    _narrow: tuple[Reducer, ...] = field(default=(), init=False, repr=False)

    def __init__(
        self,
        *,
        extract: str = "last_number",
        select: str = "value",
        weights: Sequence[float] | Signal | None = None,
    ) -> None:
        checked = _numeric_weights(
            "Mean",
            extract,
            select,
            weights,
            selects="'value' or 'nearest'",
            judge_use=_MEAN_SIGNAL_USE,
        )
        object.__setattr__(self, "name", "mean")
        object.__setattr__(self, "_narrow", ())
        object.__setattr__(self, "extract", extract)
        object.__setattr__(self, "select", select)
        object.__setattr__(self, "weights", checked)

    def _plan(self) -> _ReducerPlan:
        return _numeric_plan("mean", self.extract, self.select, self.weights)

    def _check_members(self, count: int) -> None:
        _check_weight_count(self.name, self.weights, count)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> MeanNode:
        return _numeric_from_spec(cls, spec, "mean")

    def __repr__(self) -> str:
        return _numeric_render(self, "Mean", repr)

    def _python(self) -> str:
        return _numeric_render(self, "sf.Mean", _as_python)

    __hash__: ClassVar[Any] = None


_REDUCER_CLASSES.update(vote=VoteNode, median=MedianNode, mean=MeanNode)

__all__ = ["Mean", "Median", "Reducer", "Vote"]


# The public names until the swap (unit 7e) exports the new surface.
Vote = VoteNode
Median = MedianNode
Mean = MeanNode
