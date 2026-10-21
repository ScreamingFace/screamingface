"""Compile benchmark-agnostic Recipe values into Candidate URL4."""

from __future__ import annotations

import itertools
import re
import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from url4 import Node, RelExpr, RenderError, Text, expr, render, src, struct

from screamingface._environment import SDK_PACKAGE_ROOT
from screamingface._evaluation.combine_sources import CallFingerprint, _SourceCall, member_sources
from screamingface._evaluation.combine_spec import (
    COMBINE_ROUTE,
    accounting_signal,
    combine_spec_text,
)
from screamingface._evaluation.model import (
    _compiled_operation,
    _member_projection,
    _MemberProjection,
    _model_parameter_assignment,
    _ModelParameterAssignment,
)
from screamingface._evaluation.policy import (
    DEFAULT_ANSWER_PROMPT,
    DEFAULT_SYNTHESIS_PROMPT,
    resolved_params,
)
from screamingface._evaluation.topology import (
    _operation_shape,
    _RecipeTopology,
    _SampleTopology,
    _topology_source,
)
from screamingface._operation_bindings import OPERATION_BINDING_PARAM
from screamingface._surface.lowering import lower
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.errors import PlanningError
from screamingface.fusion import FusionNode, _consistency_member
from screamingface.model import Model
from screamingface.operation import OperationInfo
from screamingface.pipeline import Pipeline
from screamingface.recipe import OPTIONAL_MEMBERS_ONLY, Recipe
from screamingface.reducer import _JUDGE_CALL_KEYS, Reducer
from screamingface.signal_sources import (
    Consistency,
    consistency_seed,
    consistency_source,
    injected_member_params,
)
from screamingface.warnings import DuplicateMembersWarning, JudgeWriterWarning

if TYPE_CHECKING:
    from screamingface._evaluation.answer_rule import _BenchmarkAnswerRule
    from screamingface._evaluation.benchmark import _CheckSurface
    from screamingface._evaluation.operators import _OperatorCatalog

type _CandidateKind = Literal["model", "fusion", "pipeline", "corrective_loop", "self_corrective"]


@dataclass(frozen=True, slots=True)
class _CompiledCandidate:
    kind: _CandidateKind
    url4: str
    models: tuple[str, ...]
    operations: tuple[OperationInfo, ...]
    members: tuple[_MemberProjection, ...]
    parameter_assignments: tuple[_ModelParameterAssignment, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedRecipe:
    reference: str
    operation_id: str
    name: str
    kind: _CandidateKind
    models: tuple[str, ...]
    topology: _RecipeTopology
    members: tuple[_ResolvedRecipe, ...] = ()
    calls: tuple[_SourceCall, ...] = ()
    # The reducer's label ("Rank", "Concat", "Reduce('top_k')") when this Recipe's output is a
    # selection for the next Pipeline stage, else None; also the flag the compile checks read.
    selection: str | None = None


# The member params that a consistency sample call sets itself (ans:Q3): it keeps every other
# author param of the member, in author order.
_SAMPLE_PARAMS: frozenset[str] = frozenset({"seed", "temperature"})


@dataclass(frozen=True, slots=True)
class _CompiledSamples:
    """The consistency sample calls of one Fusion (E4b part 7); empty when it declares none."""

    references: Mapping[str, str]  # member_k -> "$panel_M", in member order
    operation_ids: tuple[str, ...]  # op_model_N of every sample call, in compile order
    topology: tuple[_SampleTopology, ...]


_NO_SAMPLES = _CompiledSamples(MappingProxyType({}), (), ())


def entry_recipe(recipe: Recipe, *, warn_judge_writers: bool = True) -> Recipe:
    """The compile entry of a Recipe: lower it, and warn about a judge writer.

    WHY the warning reads the user's own value (review P2 #3, E4b surface lowering §2.4): the
    lowering changes the stages, so only the user's value carries the stage numbers the user
    wrote. WHY lower first: it refuses an open chain (CH-8) before the warning reads the stages.
    ``lower()`` is idempotent, so a lowered value passes through unchanged; the warning runs once,
    at the first entry (``warn_judge_writers=False`` at every later one).
    """

    lowered = lower(recipe)
    if warn_judge_writers:
        _warn_judge_writers(recipe)
    return lowered


def compile_candidate(
    recipe: Recipe,
    *,
    check_surface: _CheckSurface | None = None,
    operators: _OperatorCatalog | None = None,
    benchmark_rule: _BenchmarkAnswerRule | None = None,
    warn_judge_writers: bool = True,
) -> _CompiledCandidate:
    """Compile one complete, benchmark-independent Recipe into Candidate URL4.

    ``check_surface`` is the ONE benchmark-supplied compilation input: a
    corrective loop renders the manifest's advertised check route into its
    check steps (never a hardcoded path). Non-loop Recipes ignore it.

    ``operators`` is the Engine's combine-operator catalog (OME-1289): a reducer
    pins its operator names against it, and a Recipe without a reducer ignores it.

    ``benchmark_rule`` is the benchmark's answer rule, read only by ``extract='benchmark'``.

    ``warn_judge_writers=False`` says an earlier entry already warned on the user's own Recipe
    (the Evaluation entry does); the compile always lowers (LO-3).
    """

    recipe = entry_recipe(recipe, warn_judge_writers=warn_judge_writers)
    try:
        first = _CandidateCompiler(
            check_surface=check_surface, operators=operators, benchmark_rule=benchmark_rule
        )
        compiled = first.compile(recipe)
        if not first.reads_accounting:
            return compiled
        # WHY a second pass: I-C2 counts claimants over the whole expression, which is known only
        # after a full compile (a later stage or a sibling Fusion may reuse a member's call). The
        # compile is deterministic, so both passes see the same calls.
        return _CandidateCompiler(
            check_surface=check_surface,
            operators=operators,
            benchmark_rule=benchmark_rule,
            claims=first.claims,
            warned_fusions=first.warned_fusions,
        ).compile(recipe)
    except RenderError as exc:
        raise PlanningError(
            "The SDK could not encode Candidate generation parameters for the SF Engine",
            code="invalid_candidate_parameter",
            permanent=True,
            details={"reason": str(exc)},
        ) from exc


def recipes_need_operators(recipes: Sequence[Recipe]) -> bool:
    """Whether any Recipe holds a reducer, i.e. compiling needs the Engine's operator catalog."""

    return any(_needs_operators(recipe) for recipe in recipes)


def _needs_operators(value: Recipe | Reducer) -> bool:
    if isinstance(value, Reducer):
        return True
    return any(_needs_operators(child) for child in _children(value))


def _children(value: Recipe) -> tuple[Recipe | Reducer, ...]:
    if isinstance(value, FusionNode):
        children: tuple[Recipe | Reducer, ...] = (*value.members, value.synthesizer)
    elif isinstance(value, Pipeline):
        children = value._stage_values()
    elif isinstance(value, CorrectiveLoop):
        children = (*value.members, value.judge)
    elif isinstance(value, SelfCorrective):
        children = (value.member,)
    else:
        children = ()
    return children


class _CandidateCompiler:
    """Compile one immutable Recipe while preserving every declared invocation position."""

    def __init__(
        self,
        *,
        check_surface: _CheckSurface | None = None,
        operators: _OperatorCatalog | None = None,
        benchmark_rule: _BenchmarkAnswerRule | None = None,
        claims: Mapping[CallFingerprint, int] | None = None,
        warned_fusions: set[int] | None = None,
    ) -> None:
        self._sources: list[Node] = []
        self._operations: list[OperationInfo] = []
        self._parameter_assignments: list[_ModelParameterAssignment] = []
        self._active: set[int] = set()
        self._warned_fusions: set[int] = set() if warned_fusions is None else warned_fusions
        self._model_count = 0
        self._synthesis_count = 0
        self._panel_count = 0
        self._judge_count = 0
        self._writer_count = 0
        self._check_surface = check_surface
        self._operators = operators
        self._benchmark_rule = benchmark_rule
        self._claims = claims
        self._fingerprints: Counter[CallFingerprint] = Counter()
        self._reads_accounting = False

    @property
    def claims(self) -> Mapping[CallFingerprint, int]:
        """How many model calls of this compile send each (path, params) fingerprint."""

        return MappingProxyType(self._fingerprints)

    @property
    def reads_accounting(self) -> bool:
        """Whether a reducer of this compile read an accounting signal (it needs `sources`)."""

        return self._reads_accounting

    @property
    def warned_fusions(self) -> set[int]:
        """The Fusions that already warned about duplicate members (pass 2 must not warn again)."""

        return self._warned_fusions

    def compile(self, recipe: Recipe) -> _CompiledCandidate:
        if getattr(recipe, "optional", False):
            raise ValueError(OPTIONAL_MEMBERS_ONLY)
        # Corrective loops are ROOT-ONLY by construction (member/judge positions
        # reject them), so this dispatch is the single loop entry point.
        if isinstance(recipe, CorrectiveLoop | SelfCorrective):
            # WHY lazy: corrective imports _children from this module at load, so a top-level
            # import here would be a cycle.
            from screamingface._evaluation.corrective import _compile_corrective

            root = _compile_corrective(self, recipe, self._check_surface)
        else:
            root = self._recipe(recipe)
            if root.selection is not None:
                raise ValueError(
                    f"a sf.{root.selection} must be followed by sf.Synthesize: {recipe.name!r} "
                    "ends the candidate with a selection"
                )
        members = (
            tuple(
                _member_projection(
                    operation_id=resolved.operation_id,
                    name=member.name,
                    kind=resolved.kind,
                    models=resolved.models,
                )
                for member, resolved in zip(recipe.members, root.members, strict=True)
            )
            if isinstance(recipe, FusionNode | CorrectiveLoop)
            else ()
        )
        sources = [*self._sources, _topology_source(root.topology)]
        return _CompiledCandidate(
            kind=root.kind,
            url4=render(expr(*sources, intent=Text(root.reference))),
            models=root.models,
            operations=tuple(self._operations),
            members=members,
            parameter_assignments=tuple(self._parameter_assignments),
        )

    def _append_source(self, value: Node) -> None:
        """Attach one source owned by a composite compiler extension."""

        self._sources.append(value)

    def _capture_recipe(
        self,
        recipe: Recipe,
        *,
        input_context: str,
        input_dependencies: tuple[str, ...] = (),
        synthesis: bool,
        member_params: Mapping[str, bool | int] | None = None,
    ) -> tuple[_ResolvedRecipe, tuple[Node, ...]]:
        """Compile a nested Recipe and detach its sources for isolated placement."""

        start = len(self._sources)
        resolved = self._recipe(
            recipe,
            input_context=input_context,
            input_dependencies=input_dependencies,
            synthesis=synthesis,
            member_params=member_params,
        )
        if resolved.selection is not None:
            raise ValueError(
                f"a sf.{resolved.selection} block cannot feed a corrective loop: its selection "
                "goes only to the sf.Synthesize that closes the block"
            )
        captured = tuple(self._sources[start:])
        del self._sources[start:]
        return resolved, captured

    def _recipe(
        self,
        recipe: Recipe,
        *,
        input_context: str = "$input",
        input_dependencies: tuple[str, ...] = (),
        synthesis: bool = False,
        member_params: Mapping[str, bool | int] | None = None,
    ) -> _ResolvedRecipe:
        identity = id(recipe)
        if identity in self._active:
            raise ValueError(f"Candidate graph contains a cycle at {recipe.name!r}")
        self._active.add(identity)
        try:
            if isinstance(recipe, Model):
                return self._model(
                    recipe,
                    input_context=input_context,
                    input_dependencies=input_dependencies,
                    synthesis=synthesis,
                    member_params=member_params,
                )
            if isinstance(recipe, FusionNode):
                return self._compile_fusion(recipe, input_context, input_dependencies)
            if isinstance(recipe, Pipeline):
                return self._pipeline(
                    recipe,
                    input_context=input_context,
                    input_dependencies=input_dependencies,
                    synthesis=synthesis,
                )
            raise TypeError("candidate must be an sf.Model or an sf.Pipeline")
        finally:
            self._active.remove(identity)

    def _compile_fusion(
        self, fusion: FusionNode, input_context: str, input_dependencies: tuple[str, ...]
    ) -> _ResolvedRecipe:
        member_params = injected_member_params(fusion.signals)
        if fusion.quorum == "all" and not any(member.optional for member in fusion.members):
            members = tuple(
                self._recipe(
                    member,
                    input_context=input_context,
                    input_dependencies=input_dependencies,
                    member_params=member_params,
                )
                for member in fusion.members
            )
            _reject_selection_members(members)
            return self._fusion(
                fusion,
                members,
                input_context=input_context,
                input_dependencies=input_dependencies,
            )
        captured = tuple(
            self._capture_recipe(
                member,
                input_context=input_context,
                input_dependencies=input_dependencies,
                synthesis=False,
                member_params=member_params,
            )
            for member in fusion.members
        )
        members = tuple(member for member, _ in captured)
        _reject_selection_members(members)
        self._panel_count += 1
        panel = f"panel_{self._panel_count}"
        slots = tuple(
            src(
                expr(*sources, intent=Text(member.reference)),
                name=f"member_{index}",
                weight=1.0,
                required=not fusion.members[index - 1].optional,
            )
            for index, (member, sources) in enumerate(captured, 1)
        )
        # Only complete member results contribute. Metadata, intermediate stages,
        # the upstream input, and synthesis must never count toward this floor.
        quorum = len(members) if fusion.quorum == "all" else fusion.quorum
        # WHY broadcast for a reducer (OME-1289 unit 13): the text panel joins `member_i: answer`
        # lines that a combine call cannot split safely; the broadcast panel gives one JSON row
        # per member that answered, named and exact. A model reads the text panel, as before.
        reads_rows = isinstance(fusion.synthesizer, Reducer)
        self._sources.append(
            src(
                expr(*slots, intent=Text(""), broadcast=reads_rows, params={"quorum": quorum}),
                name=panel,
                weight=0.0,
            )
        )
        if reads_rows:
            return self._fusion(
                fusion,
                members,
                input_context=input_context,
                input_dependencies=input_dependencies,
                panel=f"${panel}",
            )
        context = render(struct({"input": input_context, "outputs": f"${panel}"}))
        return self._fusion(
            fusion,
            members,
            input_context=input_context,
            input_dependencies=input_dependencies,
            context=context,
        )

    def _model(
        self,
        model: Model,
        *,
        input_context: str,
        input_dependencies: tuple[str, ...],
        synthesis: bool,
        member_params: Mapping[str, bool | int] | None = None,
    ) -> _ResolvedRecipe:
        default_prompt = DEFAULT_SYNTHESIS_PROMPT if synthesis else DEFAULT_ANSWER_PROMPT
        prompt = model.prompt or default_prompt
        # WHY after the author params (U4-D5, P12): a Fusion that declares sf.Logprob or
        # sf.Entropy adds `logprobs` (and `top_logprobs`) to each member call, and the preflight
        # reads them from the parameter assignment like any author param.
        selected: Mapping[str, str | int | float | bool] = (
            {**model.params, **member_params} if member_params else model.params
        )
        params = resolved_params(selected)
        route = _canonical_model(model.model)
        self._model_count += 1
        binding = f"model_{self._model_count}"
        operation_id = f"op_{binding}"
        call = self._count_call(binding, _model_route(route), params)
        self._sources.append(
            src(
                RelExpr(
                    path=call.path,
                    context=input_context,
                    intent=Text(_url4_text(prompt)),
                    params=params,
                ),
                name=binding,
                weight=0.0,
            )
        )
        self._operations.append(
            _compiled_operation(
                id=operation_id,
                kind="synthesis" if synthesis else "model",
                label=f"{model.name} {'synthesis' if synthesis else 'answer'}",
                depends_on=input_dependencies,
            )
        )
        self._record_parameter_assignment(operation_id, route, selected)
        return _ResolvedRecipe(
            reference=f"${binding}",
            operation_id=operation_id,
            name=model.name,
            kind="model",
            models=(route,),
            topology=_RecipeTopology(
                kind="model",
                optional=model.optional,
                name=model.name,
                binding=binding,
                named=model._sample_id is not None,
                role="synthesis" if synthesis else "model",
            ),
            calls=(call,),
        )

    def _count_call(
        self, binding: str, path: str, params: tuple[tuple[str, str], ...]
    ) -> _SourceCall:
        """Record one model call of the expression (combine calls are never counted)."""

        call = _SourceCall(binding, path, params)
        self._fingerprints[call.fingerprint] += 1
        return call

    def _fusion(
        self,
        fusion: FusionNode,
        members: tuple[_ResolvedRecipe, ...],
        *,
        input_context: str,
        input_dependencies: tuple[str, ...],
        context: str | None = None,
        panel: str | None = None,
    ) -> _ResolvedRecipe:
        binding = self._next_binding("synthesis")
        operation_id = f"op_{binding}"
        dependencies = tuple(member.operation_id for member in members)
        synthesizer = fusion.synthesizer
        if isinstance(synthesizer, Reducer):
            return self._reducer_synthesizer(
                fusion,
                synthesizer,
                members,
                binding=binding,
                operation_id=operation_id,
                input_context=input_context,
                input_dependencies=input_dependencies,
                dependencies=dependencies,
                panel=panel,
            )
        context = context if context is not None else _fusion_context(input_context, members)
        if isinstance(synthesizer, Model):
            return self._model_synthesizer(
                fusion,
                synthesizer,
                members,
                binding=binding,
                operation_id=operation_id,
                context=context,
                dependencies=dependencies,
            )
        return self._recipe_synthesizer(
            fusion, synthesizer, members, context=context, dependencies=dependencies
        )

    def _model_synthesizer(
        self,
        fusion: FusionNode,
        model: Model,
        members: tuple[_ResolvedRecipe, ...],
        *,
        binding: str,
        operation_id: str,
        context: str,
        dependencies: tuple[str, ...],
    ) -> _ResolvedRecipe:
        synthesizer = _canonical_model(model.model)
        prompt = model.prompt or DEFAULT_SYNTHESIS_PROMPT
        call = self._count_call(binding, _model_route(synthesizer), resolved_params(model.params))
        self._sources.append(
            src(
                RelExpr(
                    path=call.path,
                    context=context,
                    intent=Text(_url4_text(prompt)),
                    params=call.params,
                ),
                name=binding,
                weight=0.0,
            )
        )
        self._operations.append(
            _compiled_operation(
                id=operation_id,
                kind="synthesis",
                label=f"{fusion.name} synthesis",
                depends_on=dependencies,
            )
        )
        self._record_parameter_assignment(operation_id, synthesizer, model.params)
        return _ResolvedRecipe(
            reference=f"${binding}",
            operation_id=operation_id,
            name=fusion.name,
            kind="fusion",
            models=_ordered_unique((*_member_models(members), synthesizer)),
            topology=_RecipeTopology(
                kind="fusion",
                quorum=fusion.quorum,
                optional=fusion.optional,
                name=fusion.name,
                binding=binding,
                members=tuple(_required_topology(member) for member in members),
                synthesizer=_RecipeTopology(
                    kind="model",
                    name=model.name,
                    binding=binding,
                    named=model._sample_id is not None,
                    role="synthesis",
                ),
            ),
            members=members,
            calls=(*_member_calls(members), call),
        )

    def _recipe_synthesizer(
        self,
        fusion: FusionNode,
        synthesizer: Recipe,
        members: tuple[_ResolvedRecipe, ...],
        *,
        context: str,
        dependencies: tuple[str, ...],
    ) -> _ResolvedRecipe:
        # WHY: a complete Recipe used as the synthesizer receives the same explicit
        # question-and-panel value as a direct Model synthesizer. Its internal serial or
        # parallel topology remains ordinary Recipe compilation rather than a special path.
        resolved_synthesizer = self._recipe(
            synthesizer,
            input_context=context,
            input_dependencies=dependencies,
            synthesis=True,
        )
        return _ResolvedRecipe(
            reference=resolved_synthesizer.reference,
            operation_id=resolved_synthesizer.operation_id,
            name=fusion.name,
            kind="fusion",
            models=_ordered_unique((*_member_models(members), *resolved_synthesizer.models)),
            topology=_RecipeTopology(
                kind="fusion",
                quorum=fusion.quorum,
                optional=fusion.optional,
                name=fusion.name,
                binding=resolved_synthesizer.reference.removeprefix("$"),
                members=tuple(_required_topology(member) for member in members),
                synthesizer=_required_topology(resolved_synthesizer),
            ),
            members=members,
            calls=(*_member_calls(members), *resolved_synthesizer.calls),
            selection=resolved_synthesizer.selection,
        )

    def _reducer_synthesizer(
        self,
        fusion: FusionNode,
        reducer: Reducer,
        members: tuple[_ResolvedRecipe, ...],
        *,
        binding: str,
        operation_id: str,
        input_context: str,
        input_dependencies: tuple[str, ...],
        dependencies: tuple[str, ...],
        panel: str | None = None,
    ) -> _ResolvedRecipe:
        """Compile a reducer to ONE combine call whose intent is the canonical spec.

        WHY the ``binding`` param: the Engine attributes an operation's output by the
        call's ``(path, params)`` fingerprint, and every combine call shares one path,
        so the binding name is what keeps two reducers' evidence apart. ``panel`` is the
        reference of a quorum Fusion's broadcast panel; the combine call and its signal calls
        then read it in place of every member's output. A Fusion that declares ``sf.Consistency``
        also gets one sample panel per member (``_sample_panels``); the combine call reads them
        from the context key ``samples``.
        """

        if self._operators is None:
            raise ValueError(
                "a reducer needs the SF Engine operator catalog to compile; "
                "evaluate it through an sf.Client"
            )
        # WHY once per Fusion object: a corrective loop recompiles its member Fusion every round.
        if id(fusion) not in self._warned_fusions:
            self._warned_fusions.add(id(fusion))
            _warn_duplicate_members(fusion)
        spec = combine_spec_text(
            reducer,
            member_count=len(members),
            operators=self._operators,
            benchmark_rule=self._benchmark_rule,
            signals=fusion.signals,
        )
        sources = self._claim_accounting_sources(fusion, reducer, members)
        # E4b part 7: the sample calls come after the members and before the signal calls, so the
        # operation order is members, samples, signals, combine.
        samples = self._sample_panels(fusion, input_context, input_dependencies)
        # Lazy: reducer_signals imports this module's helpers at module top.
        from screamingface._evaluation.reducer_signals import _compile_signals

        plan = reducer._combine_plan()
        signals = _compile_signals(
            self,
            fusion,
            plan,
            members,
            input_context=input_context,
            dependencies=dependencies,
            panel=panel,
        )
        # The combine call reads the same question-and-panel value a Model synthesizer does,
        # plus the references of the model calls it reads (the signals).
        self._append_combine(
            binding=binding,
            operation_id=operation_id,
            context=_fusion_context(
                input_context,
                members,
                signals.references,
                sources=sources,
                panel=panel,
                samples=samples.references,
            ),
            spec_text=spec,
            label=f"{fusion.name} combine",
            # WHY the samples last (P7): S/_case_views.py takes depends_on[:len(members)] as the
            # member producers, so the members stay first and the signal calls keep their place.
            depends_on=(*dependencies, *signals.operation_ids, *samples.operation_ids),
        )
        return _ResolvedRecipe(
            reference=f"${binding}",
            operation_id=operation_id,
            name=fusion.name,
            kind="fusion",
            models=_ordered_unique((*_member_models(members), *signals.models)),
            topology=_RecipeTopology(
                kind="fusion",
                quorum=fusion.quorum,
                optional=fusion.optional,
                name=fusion.name,
                binding=binding,
                members=tuple(_required_topology(member) for member in members),
                synthesizer=_RecipeTopology(
                    kind="reducer",
                    name=reducer.name,
                    binding=binding,
                    signals=signals.topology,
                    samples=samples.topology,
                ),
            ),
            members=members,
            # AIDEV-NOTE: the combine call itself is never a claimant; judge and writer calls
            # stay out too, because their `binding` param already makes their fingerprint unique;
            # so do the consistency sample calls (E4b part 7).
            calls=_member_calls(members),
            selection=reducer._step_name() if plan.kind == "selection" else None,
        )

    def _claim_accounting_sources(
        self, fusion: FusionNode, reducer: Reducer, members: tuple[_ResolvedRecipe, ...]
    ) -> dict[str, dict[str, dict[str, str]]] | None:
        """The context `sources`: only when the reducer reads an accounting signal (SG#5, SG#6),
        or when the Fusion declares sf.Logprob or sf.Entropy (erd §4: the Engine finds each
        member's reply logprobs by the same call fingerprints)."""

        if accounting_signal(reducer) is None and not injected_member_params(fusion.signals):
            return None
        self._reads_accounting = True
        return member_sources([member.calls for member in members], self._claims or {})

    def _sample_panels(
        self, fusion: FusionNode, input_context: str, input_dependencies: tuple[str, ...]
    ) -> _CompiledSamples:
        """The consistency sample calls of each member, one broadcast panel per member (E4b part
        7, erd §2–§3).

        WHY ``quorum=0`` and optional slots: a failed sample drops its slot and never fails the
        Case (ans:Q4). The panel number is the next one after any member panel.
        """

        source = consistency_source(fusion.signals)
        if source is None:
            return _NO_SAMPLES
        references: dict[str, str] = {}
        topology: list[_SampleTopology] = []
        for position, value in enumerate(fusion.members, 1):
            # INVARIANT (CN-I2): a Fusion that declares sf.Consistency has only sf.Model members.
            member = _consistency_member(position, value)
            calls = [
                self._sample_call(
                    member,
                    position,
                    index,
                    source,
                    input_context=input_context,
                    input_dependencies=input_dependencies,
                )
                for index in range(1, source.n + 1)
            ]
            self._panel_count += 1
            panel = f"panel_{self._panel_count}"
            self._sources.append(
                src(
                    expr(
                        *(slot for slot, _ in calls),
                        intent=Text(""),
                        broadcast=True,
                        params={"quorum": 0},
                    ),
                    name=panel,
                    weight=0.0,
                )
            )
            references[f"member_{position}"] = f"${panel}"
            topology.append(_SampleTopology(f"member_{position}", tuple(node for _, node in calls)))
        return _CompiledSamples(
            references=MappingProxyType(references),
            operation_ids=tuple(
                f"op_{node.binding}" for entry in topology for node in entry.sources
            ),
            topology=tuple(topology),
        )

    def _sample_call(
        self,
        member: Model,
        position: int,
        index: int,
        source: Consistency,
        *,
        input_context: str,
        input_dependencies: tuple[str, ...],
    ) -> tuple[Node, _RecipeTopology]:
        """Sample ``index`` of member ``position``: its optional slot, its operation and its
        parameter assignment.

        WHY the binding param first: it keeps the sample's fingerprint apart from every member
        call (SC-I1). The call is never a claimant (I-C2), so it does not go to ``_count_call``.
        """

        route = _canonical_model(member.model)
        self._model_count += 1
        binding = f"model_{self._model_count}"
        selected: dict[str, str | int | float | bool] = {
            **{name: value for name, value in member.params.items() if name not in _SAMPLE_PARAMS},
            "temperature": source.temperature,
            "seed": consistency_seed(position, index),
        }
        call = src(
            RelExpr(
                path=_model_route(route),
                context=input_context,
                intent=Text(_url4_text(member.prompt or DEFAULT_ANSWER_PROMPT)),
                params=((OPERATION_BINDING_PARAM, binding), *resolved_params(selected)),
            ),
            name=binding,
            weight=0.0,
        )
        node = _RecipeTopology(kind="model", name=member.name, binding=binding, role="sample")
        kind, suffix = _operation_shape(node)
        self._operations.append(
            _compiled_operation(
                id=f"op_{binding}",
                kind=kind,
                label=f"{member.name} {suffix}",
                depends_on=input_dependencies,
            )
        )
        self._record_parameter_assignment(f"op_{binding}", route, selected)
        slot = src(
            expr(call, intent=Text(f"${binding}")),
            name=f"sample_{index}",
            weight=1.0,
            required=False,
        )
        return slot, node

    def _pipeline(
        self,
        pipeline: Pipeline,
        *,
        input_context: str,
        input_dependencies: tuple[str, ...],
        synthesis: bool,
    ) -> _ResolvedRecipe:
        context = input_context
        dependencies = input_dependencies
        models: tuple[str, ...] = ()
        calls: tuple[_SourceCall, ...] = ()
        resolved: _ResolvedRecipe | None = None
        stage_topologies: list[_RecipeTopology] = []
        for index, stage in enumerate(pipeline._stage_values()):
            resolved = self._recipe(
                stage,
                input_context=context,
                input_dependencies=dependencies,
                synthesis=synthesis and index == 0,
            )
            context = resolved.reference
            dependencies = (resolved.operation_id,)
            models = _ordered_unique((*models, *resolved.models))
            calls = (*calls, *resolved.calls)
            stage_topologies.append(_required_topology(resolved))
        assert resolved is not None
        return _ResolvedRecipe(
            reference=resolved.reference,
            operation_id=resolved.operation_id,
            name=pipeline.name,
            kind="pipeline",
            models=models,
            topology=_RecipeTopology(
                kind="pipeline",
                optional=pipeline.optional,
                name=pipeline.name,
                binding=resolved.reference.removeprefix("$"),
                named=pipeline._is_named,
                stages=tuple(stage_topologies),
            ),
            calls=calls,
            selection=resolved.selection,
        )

    def _append_combine(
        self,
        *,
        binding: str,
        operation_id: str,
        context: str,
        spec_text: str,
        label: str,
        depends_on: tuple[str, ...],
    ) -> None:
        """Attach one ``/ensemble/combine/v1`` source and its ``combine`` operation."""

        self._sources.append(
            src(
                RelExpr(
                    path=COMBINE_ROUTE,
                    context=context,
                    intent=Text(spec_text),
                    params=((OPERATION_BINDING_PARAM, binding),),
                ),
                name=binding,
                weight=0.0,
            )
        )
        self._operations.append(
            _compiled_operation(id=operation_id, kind="combine", label=label, depends_on=depends_on)
        )

    def _next_binding(self, prefix: Literal["synthesis", "judge", "writer"]) -> str:
        """The next ``<prefix>_N`` binding; each prefix counts on its own."""

        if prefix == "synthesis":
            self._synthesis_count += 1
            number = self._synthesis_count
        elif prefix == "judge":
            self._judge_count += 1
            number = self._judge_count
        else:
            self._writer_count += 1
            number = self._writer_count
        return f"{prefix}_{number}"

    def _append_operation(self, operation: OperationInfo) -> None:
        """Attach one operation owned by a composite compiler extension."""

        self._operations.append(operation)

    def _record_parameter_assignment(
        self,
        operation_id: str,
        model: str,
        params: Mapping[str, str | int | float | bool],
    ) -> None:
        if not params:
            return
        self._parameter_assignments.append(
            _model_parameter_assignment(
                operation_id=operation_id,
                model=model,
                params=params,
            )
        )


def _fusion_context(
    input_context: str,
    members: tuple[_ResolvedRecipe, ...],
    signals: Mapping[str, str] | None = None,
    *,
    sources: Mapping[str, object] | None = None,
    panel: str | None = None,
    samples: Mapping[str, str] | None = None,
) -> str:
    """Build canonical JSON at runtime so arbitrary answers remain safely escaped.

    Key order is input, outputs (or panel), samples, signals, sources. ``samples`` (the panel
    reference of each member's consistency samples, E4b part 7) and ``signals`` (the references of
    the model calls a reducer reads) are written only when not empty, and ``sources`` only when
    given, so a Fusion without them keeps its exact bytes (SG#6). WHY ``samples`` before
    ``signals``: the replay rule ``_CONTEXT_SIGNALS`` (S/url4.py) finds ``signals`` at the end.
    ``panel`` replaces ``outputs`` for a quorum Fusion: it lists only the members that answered
    (OME-1557).
    """

    value: dict[str, object] = {"input": input_context}
    if panel is None:
        value["outputs"] = {
            f"member_{index}": member.reference for index, member in enumerate(members, 1)
        }
    else:
        value["panel"] = panel
    if samples:
        value["samples"] = dict(samples)
    if signals:
        value["signals"] = dict(signals)
    if sources is not None:
        value["sources"] = sources
    return render(struct(value))


def _warn_duplicate_members(fusion: FusionNode) -> None:
    """Warn for each group of direct Model members that send one identical request.

    Any reducer synthesizer triggers it, a named reducer or an sf.Reduce block alike (BK-D7): the
    check runs in _reducer_synthesizer, which every Reducer reaches.

    WHY: the gateway keys its response cache on the request, so equal members may be served
    by one cached answer and a vote would count it N times. The key is what the compiler
    actually sends (canonical route, effective prompt, encoded params), so names never count
    and a spelling that renders the same request is the same member. Recipe members are
    skipped: their inner requests are compiled elsewhere.
    """

    groups: dict[tuple[str, str, tuple[tuple[str, str], ...]], list[int]] = {}
    for position, member in enumerate(fusion.members, start=1):
        if isinstance(member, Model):
            key = (
                _canonical_model(member.model),
                member.prompt or DEFAULT_ANSWER_PROMPT,
                tuple(sorted(resolved_params(member.params))),
            )
            groups.setdefault(key, []).append(position)
    for (route, _prompt, _params), positions in groups.items():
        if len(positions) >= 2:
            warnings.warn(
                f"sf.Fanout {fusion.name!r}: members {_positions(positions)} send the same request "
                f"to {route!r}; identical requests may be served by one cached answer. "
                "Use sf.samples() for independent samples.",
                DuplicateMembersWarning,
                skip_file_prefixes=(SDK_PACKAGE_ROOT,),
            )


def _positions(positions: list[int]) -> str:
    head = ", ".join(str(position) for position in positions[:-1])
    return f"{head} and {positions[-1]}"


def _warn_judge_writers(recipe: Recipe) -> None:
    """Run the judge-writer check (JW-1) once on each Pipeline of the user's own Recipe.

    WHY once per Pipeline object, walked before the compile: a corrective loop compiles its member
    every round, the accounting pass compiles the whole Recipe a second time (JW-D2), and one
    Pipeline object may sit in two places. The seen set also stops a cyclic value, which only the
    compiler names.
    """

    seen: set[int] = set()
    pending: list[Recipe | Reducer] = [recipe]
    while pending:
        value = pending.pop()
        if isinstance(value, Reducer) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, Pipeline):
            # WJ-1: the chain before the lowering: a closed block is one stage.
            _warn_judge_writer(value.name, value._stage_values())
            # E6: a block that lowers to Pipeline([FusionNode, writer]) holds a judge and a writer.
            for inner in value._block_pipelines():
                _warn_judge_writer(inner.name, inner._stage_values())
            pending.extend(reversed(value._held_recipes()))
        else:
            pending.extend(reversed(_children(value)))


def _warn_judge_writer(name: str, stages: tuple[Recipe, ...]) -> None:
    """Warn when a stage writes with the model that judged the stage just before it (JW-1).

    WHY a warning and not an error (ans:Q1): one strong model in two roles is a legal recipe,
    but the epic rule is "the writer is not the scorer", so the researcher must hear it before
    the run is paid. Only adjacent stages count, and only a direct Model writer (P10). Both
    sides go through _canonical_model, so "/a/b" and "a/b" are one model (review M2). The
    message names the Pipeline, the two stage positions and the route, never a prompt, a
    rubric or a member.
    """

    for position, (stage, following) in enumerate(itertools.pairwise(stages), start=1):
        if not isinstance(following, Model):
            continue
        route = _canonical_model(following.model)
        if route not in _judge_routes(stage):
            continue
        warnings.warn(
            f"Pipeline {name!r}: stages {position} and {position + 1} use the same "
            f"model {route!r}: stage {position} scores the members as the judge, and stage "
            f"{position + 1} writes the answer, so the writer is also the scorer. Give one of "
            "the two stages another model, or keep both and ignore this warning.",
            JudgeWriterWarning,
            skip_file_prefixes=(SDK_PACKAGE_ROOT,),
        )


def _judge_routes(stage: Recipe) -> frozenset[str]:
    """The canonical routes of the judges that a reducer Fusion stage reads, else empty (P9).

    WHY a set: a gated vote may read two judges (a scores judge and the gate's fallback label
    judge), and a writer on either model is also a scorer (review P5 #2). "judge" is E4a's key,
    paired with exactly the three ways the Engine reads a judge (the judge reducer, scores@1 by
    judge, score:judge).
    """

    reducer = stage.synthesizer if isinstance(stage, FusionNode) else None
    if not isinstance(reducer, Reducer):
        return frozenset()
    return frozenset(
        _canonical_model(call.model)
        for call in reducer._combine_plan().signal_calls
        if call.key in _JUDGE_CALL_KEYS
    )


def _member_calls(members: tuple[_ResolvedRecipe, ...]) -> tuple[_SourceCall, ...]:
    return tuple(call for member in members for call in member.calls)


def _member_models(members: tuple[_ResolvedRecipe, ...]) -> tuple[str, ...]:
    return tuple(route for member in members for route in member.models)


def _reject_selection_members(members: tuple[_ResolvedRecipe, ...]) -> None:
    """A selection goes only to the stage that closes its block, so it is never a member."""

    for member in members:
        if member.selection is not None:
            raise ValueError(
                f"a sf.{member.selection} block cannot be a sf.Fanout member: its selection "
                "goes only to the sf.Synthesize that closes the block"
            )


def _required_topology(value: _ResolvedRecipe) -> _RecipeTopology:
    return value.topology


def _canonical_model(model: str) -> str:
    return model.removeprefix("/")


def _model_route(model: str) -> str:
    if _MODEL_ROUTE_RE.fullmatch(model) is None:
        raise PlanningError(
            f"Model {model!r} cannot be addressed by this Engine because its id is not a "
            "valid URL4 expression path. Choose a model returned by `sf.models.list()`.",
            code="invalid_model_route",
            permanent=True,
            details={"model": model},
        )
    return "/" + model


_MODEL_ROUTE_RE = re.compile(r"[A-Za-z0-9\-_.~]+(?:/[A-Za-z0-9\-_.~]+)*", re.ASCII)


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _url4_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\n", "\u2028").replace("\t", " ")
    unsupported = next(
        (character for character in normalized if character < " " or character == "\x7f"),
        None,
    )
    if unsupported is not None:
        raise ValueError(
            f"Candidate prompt contains unsupported control character U+{ord(unsupported):04X}"
        )
    return normalized.replace("$", "$$")


__all__: list[str] = []
