"""A first-class, string-compatible ScreamingFace URL4 value."""

from __future__ import annotations

import contextlib
import math
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from url4 import (
    Binding,
    Expression,
    Iteration,
    Node,
    RelExpr,
    RelUrl,
    Source,
    Text,
    Url4Error,
    build,
    render,
    walk,
)
from url4.core.nodes import children

from screamingface import _candidate_policy
from screamingface import reducer as reducer_module
from screamingface._benchmark_identity import benchmark_id as _flat_benchmark_id
from screamingface._evaluation.combine_spec import (
    COMBINE_MODEL,
    decode_combine_spec,
    spec_operator_pairs,
)
from screamingface._evaluation.operators import Stage, _OperatorCatalog
from screamingface._evaluation.policy import DEFAULT_ANSWER_PROMPT, DEFAULT_SYNTHESIS_PROMPT
from screamingface._evaluation.reducer_signals import _ProjectionReducer
from screamingface._evaluation.topology import (
    _SIGNAL_ROLES,
    _RecipeTopology,
    _SignalTopology,
    _topology_bindings,
    _topology_from_expression,
    _writer_key,
)
from screamingface._operation_bindings import (
    OPERATION_BINDING,
    OPERATION_BINDING_PARAM,
)
from screamingface._signals import JUDGE_SIGNAL
from screamingface.blocks import ReduceNode
from screamingface.reducer import (
    _JUDGE_CALL_KEYS,
    _JUDGE_KEY,
    _NARROW_SELECTS,
    Reducer,
    _ModelSignal,
    _narrow_steps,
    _narrowed,
    _op_name,
)
from screamingface.signal_sources import (
    SignalSource,
    declared_from_spec,
    injected_member_params,
    python_signals,
)
from screamingface.warnings import DuplicateMembersWarning, JudgeWriterWarning

if TYPE_CHECKING:
    from screamingface._evaluation.benchmark import _CheckSurface
    from screamingface.recipe import Recipe

_BINDING = OPERATION_BINDING
# A quorum panel (OME-1557) gathers member results; it is a reference, never an operation.
_REFERENCE = re.compile(rf"\$({OPERATION_BINDING.pattern.strip('^$')}|panel_\d+)")
_BENCHMARK_ROUTE = re.compile(
    r"/benchmarks/([A-Za-z0-9._~/-]+?)/"
    r"(?:cases|tasks|aggregate|criterion-verdict|criterion-evaluation|case-evaluation)\b"
)
_INTEGER = re.compile(r"-?(?:0|[1-9]\d*)")
_FLOAT = re.compile(r"-?(?:(?:0|[1-9]\d*)\.\d+|(?:0|[1-9]\d*)[eE][+-]?\d+)")
_NESTED_RECIPE_ROUTES = frozenset(
    {
        "/ensemble/corrective/v1/member",
        "/ensemble/corrective/v1/role",
    }
)
_DEFAULT_CORRECTIVE_ROUNDS = 3
_MODEL_CALLS = "URL4 Candidate Recipe topology does not match its model calls"
# The optional spec keys whose url4 must recompile byte for byte (see ``_validate_topology``).
_PROVED_SPEC_KEYS = frozenset({"signals", "narrow"})
# AIDEV-NOTE: the editable Python of a narrow block is the new surface's chain (rebuild-display
# §1, unit 6); today's classes have no spelling for it, so to_python refuses it until then.
_NARROW_PYTHON = (
    "URL4 Candidate has narrow steps before its reducer; their editable Python comes with the "
    "map, select, reduce surface"
)
# WHY the optional sources tail: the combine context is {input, outputs or panel, samples,
# signals, sources} (E4b part 7 writes `samples` before `signals`), and `signals` holds only
# '$judge_N'/'$writer_N' values (no braces), so the first `}` ends it.
_CONTEXT_SIGNALS = re.compile(r"signals: \{([^{}]*)\}(?:, sources: \{.*\})?\}\Z", re.DOTALL)
_SIGNAL_KEY = re.compile(r"([A-Za-z0-9_]+): '")
# A call that reads a quorum Fusion's broadcast panel (OME-1289 unit 13).
_PANEL_CONTEXT = re.compile(r"\bpanel: '\$panel_\d+'")


class Url4(str):
    """An immutable URL4 expression that can produce an editable Python fork."""

    def __new__(cls, value: str) -> Url4:
        if not isinstance(value, str):
            raise TypeError("URL4 must be a string")
        if not value.strip():
            raise ValueError("URL4 must be a non-empty string")
        return super().__new__(cls, value)

    def to_python(self) -> str:
        """Return editable ScreamingFace Python for a compiled Candidate or Evaluation."""

        return _to_python(self)


@dataclass(frozen=True, slots=True)
class _Call:
    binding: str
    model: str
    dependencies: tuple[str, ...]
    context: str
    prompt: str
    params: tuple[tuple[str, str], ...]
    raw_intent: str


@dataclass(frozen=True, slots=True)
class _DecodedCandidate:
    """A checked url4: its root, its Candidate expression, its calls and its Recipe topology."""

    root: Node
    candidate: Expression
    linked: bool
    calls: dict[str, _Call]
    topology: _RecipeTopology


def _decode_candidate(value: str) -> _DecodedCandidate:
    """Decode and check a url4: the ONE decode path of ``to_python`` and the new-surface rebuild
    (``S/_surface/rebuild.py``)."""

    try:
        root = build(value)
    except Url4Error as exc:
        raise ValueError(f"URL4 must be valid URL4: {exc}") from exc
    candidate, linked = _candidate_expression(root)
    calls = _calls(candidate)
    topology = _topology_from_expression(candidate)
    final = _final_binding(candidate, calls, topology)
    _validate_topology(candidate, topology, calls, final)
    return _DecodedCandidate(root, candidate, linked, calls, topology)


def _to_python(value: str) -> str:
    decoded = _decode_candidate(value)
    root, calls, topology = decoded.root, decoded.calls, decoded.topology
    lines = _render_topology(topology, calls, indent=0)
    lines[0] = f"candidate = {lines[0]}"
    source = ["import screamingface as sf", "", *lines]
    if decoded.linked:
        benchmark = _benchmark_id(root)
        if benchmark is not None:
            source.extend(["", *_evaluation_call(benchmark, _limit(root))])
    return "\n".join(source)


def _candidate_expression(root: Node) -> tuple[Expression, bool]:
    if not isinstance(root, Expression):
        raise ValueError("URL4 must contain a compiled ScreamingFace Candidate")
    for node in root.sources:
        if isinstance(node, Source) and node.name == "candidate" and isinstance(node.value, Text):
            try:
                candidate = build(node.value.value)
            except Url4Error as exc:
                raise ValueError("URL4 contains an invalid embedded Candidate") from exc
            if not isinstance(candidate, Expression):
                raise ValueError("URL4 contains an invalid embedded Candidate")
            return candidate, True
    return root, False


def _calls(candidate: Expression) -> dict[str, _Call]:
    calls: dict[str, _Call] = {}
    panels = _panel_dependencies(candidate)
    for node in _executable_nodes(candidate):
        if (
            not isinstance(node, Source)
            or node.name is None
            or _BINDING.fullmatch(node.name) is None
            or not isinstance(node.value, RelExpr)
            or not isinstance(node.value.intent, Text)
        ):
            continue
        context = node.value.context or ""
        dependencies = tuple(
            dict.fromkeys(
                dependency
                for reference in _REFERENCE.findall(context)
                for dependency in panels.get(reference, (reference,))
            )
        )
        calls[node.name] = _Call(
            binding=node.name,
            model=node.value.path.removeprefix("/"),
            dependencies=dependencies,
            context=context,
            prompt=_python_text(node.value.intent.value),
            params=_params(node.value.params),
            raw_intent=node.value.intent.value,
        )
    if not calls:
        raise ValueError("URL4 contains no compiled ScreamingFace model calls")
    return calls


def _panel_dependencies(candidate: Expression) -> dict[str, tuple[str, ...]]:
    panels: dict[str, tuple[str, ...]] = {}
    for node in _executable_nodes(candidate):
        if (
            not isinstance(node, Source)
            or node.name is None
            or re.fullmatch(r"panel_\d+", node.name) is None
            or not isinstance(node.value, Expression)
        ):
            continue
        references = []
        for slot in node.value.sources:
            if isinstance(slot, Source | Binding) and isinstance(slot.value, Expression):
                if isinstance(slot.value.intent, Text):
                    references.extend(_REFERENCE.findall(slot.value.intent.value))
        panels[node.name] = tuple(references)
    return panels


def _combine_operator_pairs(calls: Mapping[str, _Call]) -> tuple[tuple[Stage, str], ...]:
    """The distinct (stage, operator) pairs the combine calls' specs use, in call and step order."""

    return tuple(
        dict.fromkeys(
            pair
            for call in calls.values()
            if call.model == COMBINE_MODEL
            for pair in spec_operator_pairs(decode_combine_spec(call.raw_intent))
        )
    )


def _executable_nodes(value: Node):
    """Walk static nodes plus URL4 bodies carried as executable loop data."""

    yield value
    for child in children(value):
        yield from _executable_nodes(child)
    if isinstance(value, Iteration):
        try:
            if value.intent is None:
                raise ValueError("URL4 Candidate iteration body has no result intent")
            body = build(f"({value.body})!{value.intent}")
        except Url4Error as exc:
            raise ValueError("URL4 Candidate contains an invalid iteration body") from exc
        yield from _executable_nodes(body)
    if (
        isinstance(value, RelExpr)
        and value.path in _NESTED_RECIPE_ROUTES
        and isinstance(value.intent, Text)
    ):
        try:
            nested = build(value.intent.value)
        except Url4Error as exc:
            raise ValueError("URL4 Candidate contains an invalid nested Recipe") from exc
        yield from _executable_nodes(nested)


def _final_binding(
    candidate: Expression,
    calls: dict[str, _Call],
    topology: _RecipeTopology,
) -> str:
    if not isinstance(candidate.intent, Text):
        raise ValueError("URL4 Candidate has an unsupported result binding")
    match = re.fullmatch(r"\$(model_\d+|synthesis_\d+|loop_candidate)", candidate.intent.value)
    if match is None:
        raise ValueError("URL4 Candidate has an unsupported result binding")
    selected = match.group(1)
    if topology.kind in {"corrective_loop", "self_corrective"}:
        if selected != topology.binding or not _has_binding(candidate, selected):
            raise ValueError("URL4 Candidate has an unsupported result binding")
    elif selected not in calls:
        raise ValueError("URL4 Candidate has an unsupported result binding")
    return selected


def _has_binding(value: Expression, name: str) -> bool:
    return any(isinstance(node, Source) and node.name == name for node in value.sources)


def _render_model(
    call: _Call,
    *,
    role: str,
    explicit_name: str | None,
    indent: int,
    force_name: bool = False,
    drop_params: frozenset[str] = frozenset(),
) -> list[str]:
    prefix = " " * indent
    lines = [f"{prefix}sf.Model(", f"{prefix}    {call.model!r},"]
    inferred_name = call.model.rsplit("/", 1)[-1]
    if explicit_name is not None and (force_name or explicit_name != inferred_name):
        lines.append(f"{prefix}    name={explicit_name!r},")
    if call.prompt != _role_default_prompt(role):
        lines.append(f"{prefix}    prompt={call.prompt!r},")
    params = _editable_params(call, drop_params)
    if params:
        lines.append(f"{prefix}    params={params!r},")
    lines.append(f"{prefix})")
    return lines


def _role_default_prompt(role: str | None) -> str:
    """The prompt the compiler gives a model call of this topology role when it has none."""

    return DEFAULT_SYNTHESIS_PROMPT if role == "synthesis" else DEFAULT_ANSWER_PROMPT


def _render_topology(
    value: _RecipeTopology,
    calls: dict[str, _Call],
    *,
    indent: int,
    drop_params: frozenset[str] = frozenset(),
) -> list[str]:
    if value.kind == "model":
        assert value.role is not None
        lines = _render_model(
            calls[value.binding],
            role=value.role,
            explicit_name=value.name,
            indent=indent,
            force_name=value.named,
            drop_params=drop_params,
        )
    elif value.kind == "pipeline":
        lines = _render_pipeline_topology(value, calls, indent=indent)
    elif value.kind in {"corrective_loop", "self_corrective"}:
        lines = _render_corrective_topology(value, calls, indent=indent)
    elif value.kind == "reducer":
        reducer = _reducer_from_topology(value, calls)
        if _narrow_steps(reducer):
            raise ValueError(_NARROW_PYTHON)
        lines = [f"{' ' * indent}{reducer._python()}"]
    else:
        lines = _render_fusion_topology(value, calls, indent=indent)
    if value.optional:
        lines.insert(-1, f"{' ' * indent}    optional=True,")
    return lines


def _render_corrective_topology(
    value: _RecipeTopology,
    calls: dict[str, _Call],
    *,
    indent: int,
) -> list[str]:
    prefix = " " * indent
    if value.kind == "self_corrective":
        member = value.members[0]
        lines = [f"{prefix}sf.SelfCorrective("]
        rendered = _render_topology(member, calls, indent=indent + 4)
        rendered[-1] += ","
        lines.extend(rendered)
        if value.name != member.name:
            lines.append(f"{prefix}    name={value.name!r},")
    else:
        assert value.judge is not None
        lines = [f"{prefix}sf.CorrectiveLoop(", f"{prefix}    ["]
        for member in value.members:
            rendered = _render_topology(member, calls, indent=indent + 8)
            rendered[-1] += ","
            lines.extend(rendered)
        lines.append(f"{prefix}    ],")
        inferred_name = "+".join(member.name for member in value.members)
        if value.name != inferred_name:
            lines.append(f"{prefix}    name={value.name!r},")
        judge = _render_topology(value.judge, calls, indent=indent + 4)
        judge[0] = f"{prefix}    judge={judge[0].lstrip()}"
        judge[-1] += ","
        lines.extend(judge)
    if value.max_rounds != _DEFAULT_CORRECTIVE_ROUNDS:
        lines.append(f"{prefix}    max_rounds={value.max_rounds!r},")
    lines.append(f"{prefix})")
    return lines


def _render_pipeline_topology(
    value: _RecipeTopology,
    calls: dict[str, _Call],
    *,
    indent: int,
) -> list[str]:
    prefix = " " * indent
    lines = [f"{prefix}sf.Pipeline(", f"{prefix}    ["]
    for stage in value.stages:
        rendered = _render_topology(stage, calls, indent=indent + 8)
        rendered[-1] += ","
        lines.extend(rendered)
    lines.append(f"{prefix}    ],")
    inferred_name = "->".join(stage.name for stage in value.stages)
    if value.named or value.name != inferred_name:
        lines.append(f"{prefix}    name={value.name!r},")
    lines.append(f"{prefix})")
    return lines


def _render_fusion_topology(
    value: _RecipeTopology,
    calls: dict[str, _Call],
    *,
    indent: int,
) -> list[str]:
    assert value.synthesizer is not None
    prefix = " " * indent
    declared = _fusion_signals(value, calls)
    drop = _injected_names(declared)
    lines = [f"{prefix}sf.Fusion(", f"{prefix}    ["]
    for member in value.members:
        rendered = _render_topology(member, calls, indent=indent + 8, drop_params=drop)
        rendered[-1] += ","
        lines.extend(rendered)
    lines.append(f"{prefix}    ],")
    inferred_name = "+".join(member.name for member in value.members)
    if value.name != inferred_name:
        lines.append(f"{prefix}    name={value.name!r},")
    if declared is not None:
        lines.append(f"{prefix}    signals={python_signals(declared)},")
    synthesizer = _render_topology(value.synthesizer, calls, indent=indent + 4)
    synthesizer[0] = f"{prefix}    synthesizer={synthesizer[0].lstrip()}"
    synthesizer[-1] += ","
    lines.extend(synthesizer)
    if value.quorum != "all":
        lines.append(f"{prefix}    quorum={value.quorum!r},")
    lines.append(f"{prefix})")
    return lines


def _validate_topology(
    candidate: Expression,
    value: _RecipeTopology,
    calls: dict[str, _Call],
    final: str,
) -> None:
    if value.binding != final:
        raise ValueError("URL4 Candidate Recipe topology does not match its result binding")
    if value.kind in {"corrective_loop", "self_corrective"}:
        _validate_compiled_corrective(candidate, value, calls)
        return
    bindings = _topology_bindings(value)
    if set(bindings) != set(calls):
        raise ValueError("URL4 Candidate Recipe topology does not match its model calls")
    for name, binding in bindings.items():
        if calls[name].dependencies != binding.context_dependencies:
            raise ValueError("URL4 Candidate Recipe topology does not match its model calls")
        _require_call_kind(binding.node, calls[name])
    # INVARIANT: default-valued metadata cannot conceal executable policy.
    # WHY the signals clause (E4b part 7 unit 5): a declared source adds calls, so it must prove
    # its bytes. Hand edit: add a consistency entry to the spec of a plain Median url4; without
    # this clause it rebuilds as an sf.Consistency recipe and replays with no sample calls.
    # WHY not every combine call (review P7 #5): a replay with an unpinned or wrong-stage operator
    # must fail with its operator error, which the recompile would hide behind a metadata error.
    # WHY the narrow clause (E4b narrow): a narrow item changes which members the reduce reads, so
    # a spec with ``narrow`` proves its bytes too. The cost: an unpinned or wrong-stage operator
    # in a narrow spec shows as this recompile's metadata error, not as its operator error.
    if (
        _has_fusion_policy(value)
        or _has_executable_fusion_policy(candidate)
        or any(
            not _PROVED_SPEC_KEYS.isdisjoint(decode_combine_spec(call.raw_intent))
            for call in calls.values()
            if call.model == COMBINE_MODEL
        )
    ):
        # WHY the pinned catalog (OME-1289 unit 13): a quorum Fusion may end in a reducer.
        _require_recompiles(candidate, _recipe_from_topology(value, calls), calls)


def _require_recompiles(
    candidate: Expression,
    recipe: Recipe,
    calls: Mapping[str, _Call],
    *,
    check_surface: _CheckSurface | None = None,
) -> None:
    """Refuse a url4 unless the Recipe it describes recompiles to it byte for byte.

    The compiler is the protocol's one authoritative implementation. The operators come from the
    ids the url4 itself pins, so the check needs no I/O. WHY the warnings are silenced: this
    recompile only proves the url4 is canonical; the researcher already heard about a duplicate
    member or a writer that uses the judge's model when they compiled the Candidate, and recovery
    runs far from their code.
    """

    if not _recompiles(candidate, recipe, calls, check_surface=check_surface):
        raise ValueError("URL4 Candidate does not match its Recipe metadata")


def _recompiles(
    candidate: Expression,
    recipe: Recipe,
    calls: Mapping[str, _Call],
    *,
    check_surface: _CheckSurface | None = None,
) -> bool:
    """Whether ``recipe`` compiles to ``candidate`` byte for byte (see ``_require_recompiles``).

    A compile error is not a mismatch: it raises, so a programming error never reads as one.
    """

    from screamingface._evaluation.candidate import compile_candidate

    operators = _OperatorCatalog.from_pinned(_combine_operator_pairs(calls))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DuplicateMembersWarning)
        warnings.simplefilter("ignore", JudgeWriterWarning)
        expected = compile_candidate(recipe, check_surface=check_surface, operators=operators).url4
    return render(candidate) == expected


def _has_executable_fusion_policy(candidate: Expression) -> bool:
    return any(
        (isinstance(node, Expression) and any(key == "quorum" for key, _ in node.params))
        or (
            isinstance(node, Source)
            and any(key in {"optional", "required"} for key, _ in node.annotations)
        )
        for node in _executable_nodes(candidate)
    )


def _has_fusion_policy(value: _RecipeTopology) -> bool:
    # WHY samples (E4b part 7): a sample slot is optional and a panel quorum is policy, so a node
    # with samples is policy even when its markers are hand-removed (the recompile must run).
    # The signals clause of _validate_topology does not cover it: a hand edit can drop the spec's
    # signals and the markers but keep the samples rider (review P7 #5).
    if value.quorum != "all" or value.optional or value.samples:
        return True
    children = (*value.members, *value.stages)
    if value.synthesizer is not None:
        children += (value.synthesizer,)
    return any(_has_fusion_policy(child) for child in children)


def _binding_first(call: _Call) -> bool:
    return call.params[:1] == ((OPERATION_BINDING_PARAM, call.binding),)


def _require_call_kind(node: _RecipeTopology, call: _Call) -> None:
    """A reducer node is exactly a combine call (and its intent a valid spec), and only that."""

    if (node.kind == "reducer") != (call.model == COMBINE_MODEL):
        raise ValueError(_MODEL_CALLS)
    if node.kind == "reducer":
        _require_reducer_call(node, call)
    elif node.role in _SIGNAL_ROLES or node.role == "sample":
        # INVARIANT: the binding param also keeps a signal or a sample call apart from a
        # same-route member (a sample repeats its member's route and prompt; E4b part 7 SC-I1).
        if not _binding_first(call):
            raise ValueError(_MODEL_CALLS)
    elif any(name == OPERATION_BINDING_PARAM for name, _ in call.params):
        # A member or synthesis call never carries it (a user param cannot name it either).
        raise ValueError(_MODEL_CALLS)


def _require_reducer_call(node: _RecipeTopology, call: _Call) -> None:
    spec = decode_combine_spec(call.raw_intent)
    # INVARIANT: the binding param is what keeps two reducers' evidence apart, the node's name is
    # the spec's reducer, and the context's signal keys are the node's: any of them drifting means
    # the url4 was edited by hand.
    if (
        call.params != ((OPERATION_BINDING_PARAM, call.binding),)
        or node.name != spec["reducer"]
        or _context_signal_keys(call.context) != tuple(signal.key for signal in node.signals)
    ):
        raise ValueError(_MODEL_CALLS)


def _context_signal_keys(context: str) -> tuple[str, ...]:
    """The keys of the ``signals`` struct of a combine call's context (none if absent)."""

    match = _CONTEXT_SIGNALS.search(context)
    return () if match is None else tuple(_SIGNAL_KEY.findall(match.group(1)))


def _reducer_from_call(call: _Call) -> Reducer:
    """The reducer a combine call holds when it reads no signal call (a pure rule)."""

    return _rebuilt_reducer(decode_combine_spec(call.raw_intent), ())


def _reducer_from_topology(node: _RecipeTopology, calls: dict[str, _Call]) -> Reducer:
    """Rebuild the reducer a node names from its combine call and the signal calls it reads."""

    call = calls.get(node.binding)
    if call is None:
        raise ValueError(_MODEL_CALLS)
    spec = decode_combine_spec(call.raw_intent)
    return _rebuilt_reducer(spec, tuple(_model_signal(signal, calls) for signal in node.signals))


def _rebuilt_reducer(  # noqa: PLR0911
    spec: dict[str, object], signals: tuple[_ModelSignal, ...]
) -> Reducer:
    """The named reducer when its own _rebuild accepts the spec exactly (BK-D2), else sf.Reduce.

    WHY suppress: a named class refusing a spec (step args, weights it cannot hold) means only
    "not this named form"; sf.Reduce then rebuilds it. When both refuse, the named class's error
    is the one raised, because it says what the spec was meant to be.

    A spec with ``gate`` rebuilds only through sf.Vote (P17): sf.Reduce has no gate and would drop
    it, so there is no sf.Reduce fallback, and a gate on another reducer is that reducer's
    "cannot rebuild" error.
    """

    if "narrow" in spec:
        return _rebuilt_narrowed(spec, signals)
    # WHY through the module: the registry may be replaced as a whole (tests do).
    named = reducer_module._REDUCER_CLASSES.get(str(spec["reducer"]))
    if "gate" in spec:
        if named is None or spec["reducer"] != "vote":
            raise reducer_module._cannot_rebuild(str(spec["reducer"]))
        return named._rebuild(spec, signals)
    if named is None:
        return ReduceNode._rebuild(spec, signals)
    try:
        return named._rebuild(spec, signals)
    except (TypeError, ValueError):
        with contextlib.suppress(TypeError, ValueError):
            return ReduceNode._rebuild(spec, signals)
        raise


def _rebuilt_narrowed(spec: dict[str, object], signals: tuple[_ModelSignal, ...]) -> Reducer:
    """The main reducer of a spec with ``narrow``, carrying its narrow steps (narrow.md §2).

    Each narrow item rebuilds as the sf.Filter or sf.Rank spec it is, and the main step as the spec
    with no ``narrow`` key. The judge call goes to each step that reads ``score:judge``; every other
    call (a gate fallback) is the main step's. The url4 recompile then proves the bytes.
    """

    judge = tuple(signal for signal in signals if signal.key == _JUDGE_KEY)
    others = tuple(signal for signal in signals if signal.key != _JUDGE_KEY)
    main = {key: value for key, value in spec.items() if key != "narrow"}
    steps = tuple(
        _rebuilt_narrow_step(cast("dict[str, object]", item), main, judge)
        for item in cast("list[object]", spec["narrow"])
    )
    reducer = _rebuilt_reducer(main, (*(judge if _reads_judge(main) else ()), *others))
    try:
        return _narrowed(reducer, steps)
    except ValueError as exc:
        raise reducer_module._cannot_rebuild(str(spec["reducer"])) from exc


def _rebuilt_narrow_step(
    item: dict[str, object], main: dict[str, object], judge: tuple[_ModelSignal, ...]
) -> Reducer:
    """One narrow item as the spec of its own reducer: the main spec's schema and members, the
    item's four stages, and no weights."""

    select = cast("dict[str, object]", item["select"])
    name = _NARROW_SELECTS.get(str(_op_name(str(select["op"]))))
    if name is None:
        raise reducer_module._cannot_rebuild(str(main["reducer"]))
    step = {
        "schema": main["schema"],
        "reducer": name,
        "members": main["members"],
        **item,
        "weights": None,
    }
    named = reducer_module._REDUCER_CLASSES[name]
    return named._rebuild(step, judge if _reads_judge(step) else ())


def _reads_judge(spec: Mapping[str, object]) -> bool:
    """Whether a decoded step reads the judge reply: a judge pick, a judge score, a
    ``score:judge`` filter, or ``score:judge`` weights."""

    reduce = cast("Mapping[str, object]", spec["reduce"])
    args = cast("Mapping[str, object]", reduce["args"])
    return (
        spec["reducer"] == "judge"
        or (_op_name(str(reduce["op"])) == "scores" and args.get("source") == "judge")
        or args.get("key") == JUDGE_SIGNAL
        or spec["weights"] == {"signal": JUDGE_SIGNAL}
    )


def _model_signal(signal: _SignalTopology, calls: dict[str, _Call]) -> _ModelSignal:
    call = calls.get(signal.source.binding)
    if call is None or not _binding_first(call):
        raise ValueError(_MODEL_CALLS)
    params = _candidate_policy.params(
        {name: _scalar(value) for name, value in call.params[1:]},
        f"{signal.source.role} params",
    )
    field = _projected_field(signal, calls, call)
    prompt = call.prompt
    if signal.key in _JUDGE_CALL_KEYS:
        # Lazy: screamingface.judge imports the reducer registry that this module also feeds.
        from screamingface.judge import outputs_form_prompt

        prompt = outputs_form_prompt(
            prompt, reads_panel=_PANEL_CONTEXT.search(call.context) is not None
        )
    return _ModelSignal(signal.key, call.model, prompt, params, field)


def _projected_field(signal: _SignalTopology, calls: dict[str, _Call], writer: _Call) -> str | None:
    """The field a writer writes: the one its projection call projects, else None (a judge)."""

    if signal.projection is None:
        return None
    projection = calls.get(signal.projection.binding)
    if projection is None or writer.context != f"${signal.projection.binding}":
        raise ValueError(_MODEL_CALLS)
    # The whole spec must be what a projection writes (refuses a stray extract, arg or step).
    field = _ProjectionReducer._from_spec(decode_combine_spec(projection.raw_intent)).field
    # INVARIANT: the signal key names the field the projection projects; any drift is a hand edit.
    if signal.key != _writer_key(field):
        raise ValueError(_MODEL_CALLS)
    return field


def _validate_compiled_corrective(
    candidate: Expression,
    topology: _RecipeTopology,
    calls: dict[str, _Call],
) -> None:
    """Fail closed unless the executable loop exactly recompiles from its rider.

    Corrective Recipes statically unroll repeated member and judge calls. Their
    public topology intentionally describes each reusable Recipe once, so a
    subset check cannot prove that later rounds execute the same Recipes. The
    compiler is the protocol's one authoritative implementation: reconstruct
    the public Recipe from the rider and its declared calls, recompile it, and
    require byte-identical canonical URL4 before showing editable Python.
    """

    recipe = _recipe_from_topology(topology, calls)
    check_surface = _replay_check_surface(topology)
    assert check_surface is not None
    _require_recompiles(candidate, recipe, calls, check_surface=check_surface)


def _replay_check_surface(topology: _RecipeTopology) -> _CheckSurface | None:
    """The check surface a corrective Candidate recompiles with; None for any other Candidate."""

    from screamingface._evaluation.benchmark import _CheckSurface

    if topology.check_route is None:
        return None
    return _CheckSurface(
        check_route=topology.check_route,
        feedback_intent="replay-validation",
        expected_check_cost="free",
    )


def _recipe_from_topology(
    value: _RecipeTopology,
    calls: dict[str, _Call],
    *,
    drop_params: frozenset[str] = frozenset(),
    editable: bool = False,
) -> Recipe:
    """Reconstruct one inert public Recipe without evaluating generated Python.

    ``drop_params`` names the member params that the parent Fusion's declaration injected (P16).
    ``editable=True`` (the new-surface rebuild, ``S/_surface/rebuild.py``) gives a model call whose
    prompt is the default of its topology role no prompt, as ``to_python`` writes it; the url4
    recompile check reads the default form (False), which compiles to the same bytes.
    """

    from screamingface.corrective import CorrectiveLoop, SelfCorrective
    from screamingface.model import Model
    from screamingface.pipeline import Pipeline

    if value.kind == "model":
        call = calls.get(value.binding)
        if call is None:
            raise ValueError("URL4 Candidate Recipe topology does not match its model calls")
        default = editable and call.prompt == _role_default_prompt(value.role)
        selected = Model(
            call.model,
            name=value.name if value.named else None,
            prompt=None if default else call.prompt,
            params=_editable_params(call, drop_params),
            optional=value.optional,
        )
    elif value.kind == "pipeline":
        selected = Pipeline(
            [_recipe_from_topology(stage, calls, editable=editable) for stage in value.stages],
            name=value.name if value.named else None,
            optional=value.optional,
        )
    elif value.kind == "fusion":
        selected = _fusion_from_topology(value, calls, editable=editable)
    elif value.kind == "self_corrective":
        assert value.max_rounds is not None
        member = _recipe_from_topology(value.members[0], calls, editable=editable)
        selected = SelfCorrective(
            member,
            name=value.name if value.name != member.name else None,
            max_rounds=value.max_rounds,
        )
    else:
        assert value.max_rounds is not None
        assert value.judge is not None
        inferred_name = "+".join(member.name for member in value.members)
        selected = CorrectiveLoop(
            [_recipe_from_topology(member, calls, editable=editable) for member in value.members],
            name=value.name if value.name != inferred_name else None,
            judge=_recipe_from_topology(value.judge, calls, editable=editable),
            max_rounds=value.max_rounds,
        )
    return selected


def _fusion_from_topology(
    value: _RecipeTopology, calls: dict[str, _Call], *, editable: bool = False
) -> Recipe:
    """One Fusion; its members show only the params the author wrote (P16, DS-D10)."""

    from screamingface.fusion import FusionNode

    assert value.synthesizer is not None
    inferred_name = "+".join(member.name for member in value.members)
    declared = _fusion_signals(value, calls)
    drop = _injected_names(declared)
    return FusionNode(
        [
            _recipe_from_topology(member, calls, drop_params=drop, editable=editable)
            for member in value.members
        ],
        name=value.name if value.name != inferred_name else None,
        signals=declared,
        synthesizer=_synthesizer_from_topology(value.synthesizer, calls, editable=editable),
        quorum=value.quorum,
        optional=value.optional,
    )


def _fusion_signals(
    value: _RecipeTopology, calls: dict[str, _Call]
) -> dict[str, SignalSource] | None:
    """The declaration in a reducer Fusion's combine spec (E4b part 3), or None."""
    synthesizer = value.synthesizer
    if synthesizer is None or synthesizer.kind != "reducer":
        return None
    call = calls.get(synthesizer.binding)
    if call is None:
        raise ValueError(_MODEL_CALLS)
    return declared_from_spec(decode_combine_spec(call.raw_intent).get("signals"))


def _injected_names(declared: Mapping[str, SignalSource] | None) -> frozenset[str]:
    """The member params a declaration injects at compile time; the rebuild drops them (P16)."""
    return frozenset(injected_member_params(declared))


def _synthesizer_from_topology(
    value: _RecipeTopology, calls: dict[str, _Call], *, editable: bool = False
) -> Recipe | Reducer:
    if value.kind != "reducer":
        return _recipe_from_topology(value, calls, editable=editable)
    return _reducer_from_topology(value, calls)


def _editable_params(
    call: _Call, drop: frozenset[str] = frozenset()
) -> dict[str, str | int | float | bool]:
    selected: dict[str, str | int | float | bool] = {}
    for name, value in call.params:
        if name not in drop:
            selected[name] = _scalar(value)
    return selected


def _params(values: tuple[tuple[str, str | None], ...]) -> tuple[tuple[str, str], ...]:
    if any(value is None for _, value in values):
        raise ValueError("URL4 Candidate model parameters must have scalar values")
    return tuple((name, value) for name, value in values if value is not None)


def _scalar(value: str) -> str | int | float | bool:
    selected: str | int | float | bool = value
    if value == "true":
        selected = True
    elif value == "false":
        selected = False
    elif _INTEGER.fullmatch(value):
        selected = int(value)
    elif _FLOAT.fullmatch(value):
        number = float(value)
        if math.isfinite(number):
            selected = number
    return selected


def _python_text(value: str) -> str:
    return value.replace("\u2028", "\n").replace("$$", "$")


def _benchmark_id(root: Node) -> str | None:
    for node in walk(root):
        path = (
            node.path
            if isinstance(node, RelExpr)
            else node.value
            if isinstance(node, RelUrl)
            else None
        )
        if path is None or (match := _BENCHMARK_ROUTE.fullmatch(path)) is None:
            continue
        components = match.group(1).split("/")
        if len(components) >= 2:
            return _flat_benchmark_id("/".join(components[:-1]))
    return None


def _limit(root: Node) -> int | None:
    for node in walk(root):
        if isinstance(node, Iteration) and node.directives.slice is not None:
            start, stop = node.directives.slice
            if start == 0:
                return stop
    return None


def _evaluation_call(benchmark: str, limit: int | None) -> list[str]:
    lines = ["report = sf.evaluate(", "    candidate,", f"    benchmark={benchmark!r},"]
    if limit is not None:
        lines.append(f"    limit={limit},")
    lines.append(")")
    return lines


__all__ = ["Url4"]
