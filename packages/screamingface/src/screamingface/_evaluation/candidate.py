"""Compile benchmark-agnostic Recipe values into Candidate URL4."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from url4 import Node, RelExpr, RenderError, Text, expr, render, src, struct

from screamingface._evaluation.combine_spec import COMBINE_ROUTE, combine_spec_text
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
    _RecipeTopology,
    _topology_source,
)
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.errors import PlanningError
from screamingface.fusion import Fusion
from screamingface.model import Model
from screamingface.operation import OperationInfo
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe
from screamingface.reducer import Reducer

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


def compile_candidate(
    recipe: Recipe,
    *,
    check_surface: _CheckSurface | None = None,
    operators: _OperatorCatalog | None = None,
    benchmark_rule: _BenchmarkAnswerRule | None = None,
) -> _CompiledCandidate:
    """Compile one complete, benchmark-independent Recipe into Candidate URL4.

    ``check_surface`` is the ONE benchmark-supplied compilation input: a
    corrective loop renders the manifest's advertised check route into its
    check steps (never a hardcoded path). Non-loop Recipes ignore it.

    ``operators`` is the Engine's combine-operator catalog (OME-1289): a reducer
    pins its operator names against it, and a Recipe without a reducer ignores it.

    ``benchmark_rule`` is the benchmark's answer rule, read only by ``extract='benchmark'``.
    """

    try:
        return _CandidateCompiler(
            check_surface=check_surface, operators=operators, benchmark_rule=benchmark_rule
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
        needed = True
    else:
        needed = any(_needs_operators(child) for child in _children(value))
    return needed


def _children(value: Recipe) -> tuple[Recipe | Reducer, ...]:
    if isinstance(value, Fusion):
        children: tuple[Recipe | Reducer, ...] = (*value.members, value.synthesizer)
    elif isinstance(value, Pipeline):
        children = value.stages
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
    ) -> None:
        self._sources: list[Node] = []
        self._operations: list[OperationInfo] = []
        self._parameter_assignments: list[_ModelParameterAssignment] = []
        self._active: set[int] = set()
        self._model_count = 0
        self._synthesis_count = 0
        self._panel_count = 0
        self._check_surface = check_surface
        self._operators = operators
        self._benchmark_rule = benchmark_rule

    def compile(self, recipe: Recipe) -> _CompiledCandidate:
        if getattr(recipe, "optional", False):
            raise ValueError("optional=True is only supported on Fusion members")
        # Corrective loops are ROOT-ONLY by construction (member/judge positions
        # reject them), so this dispatch is the single loop entry point.
        if isinstance(recipe, CorrectiveLoop | SelfCorrective):
            from screamingface._evaluation.corrective import _compile_corrective

            root = _compile_corrective(self, recipe, self._check_surface)
        else:
            root = self._recipe(recipe)
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
            if isinstance(recipe, Fusion | CorrectiveLoop)
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
    ) -> tuple[_ResolvedRecipe, tuple[Node, ...]]:
        """Compile a nested Recipe and detach its sources for isolated placement."""

        start = len(self._sources)
        resolved = self._recipe(
            recipe,
            input_context=input_context,
            input_dependencies=input_dependencies,
            synthesis=synthesis,
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
                )
            if isinstance(recipe, Fusion):
                return self._compile_fusion(recipe, input_context, input_dependencies)
            if isinstance(recipe, Pipeline):
                return self._pipeline(
                    recipe,
                    input_context=input_context,
                    input_dependencies=input_dependencies,
                    synthesis=synthesis,
                )
            raise TypeError("candidate must be an sf.Model, sf.Fusion, or sf.Pipeline")
        finally:
            self._active.remove(identity)

    def _compile_fusion(
        self, fusion: Fusion, input_context: str, input_dependencies: tuple[str, ...]
    ) -> _ResolvedRecipe:
        if fusion.quorum == "all" and not any(member.optional for member in fusion.members):
            members = tuple(
                self._recipe(
                    member, input_context=input_context, input_dependencies=input_dependencies
                )
                for member in fusion.members
            )
            return self._fusion(fusion, members, input_context=input_context)
        captured = tuple(
            self._capture_recipe(
                member,
                input_context=input_context,
                input_dependencies=input_dependencies,
                synthesis=False,
            )
            for member in fusion.members
        )
        members = tuple(member for member, _ in captured)
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
            return self._fusion(fusion, members, input_context=input_context, panel=f"${panel}")
        context = render(struct({"input": input_context, "outputs": f"${panel}"}))
        return self._fusion(fusion, members, input_context=input_context, context=context)

    def _model(
        self,
        model: Model,
        *,
        input_context: str,
        input_dependencies: tuple[str, ...],
        synthesis: bool,
    ) -> _ResolvedRecipe:
        default_prompt = DEFAULT_SYNTHESIS_PROMPT if synthesis else DEFAULT_ANSWER_PROMPT
        prompt = model.prompt or default_prompt
        params = resolved_params(model.params)
        route = _canonical_model(model.model)
        self._model_count += 1
        binding = f"model_{self._model_count}"
        operation_id = f"op_{binding}"
        self._sources.append(
            src(
                RelExpr(
                    path=_model_route(route),
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
        self._record_parameter_assignment(operation_id, route, model.params)
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
        )

    def _fusion(
        self,
        fusion: Fusion,
        members: tuple[_ResolvedRecipe, ...],
        *,
        input_context: str,
        context: str | None = None,
        panel: str | None = None,
    ) -> _ResolvedRecipe:
        self._synthesis_count += 1
        binding = f"synthesis_{self._synthesis_count}"
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
        fusion: Fusion,
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
        self._sources.append(
            src(
                RelExpr(
                    path=_model_route(synthesizer),
                    context=context,
                    intent=Text(_url4_text(prompt)),
                    params=resolved_params(model.params),
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
        )

    def _recipe_synthesizer(
        self,
        fusion: Fusion,
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
        )

    def _reducer_synthesizer(
        self,
        fusion: Fusion,
        reducer: Reducer,
        members: tuple[_ResolvedRecipe, ...],
        *,
        binding: str,
        operation_id: str,
        input_context: str,
        dependencies: tuple[str, ...],
        panel: str | None = None,
    ) -> _ResolvedRecipe:
        """Compile a reducer to ONE combine call whose intent is the canonical spec.

        WHY the ``binding`` param: the Engine attributes an operation's output by the
        call's ``(path, params)`` fingerprint, and every combine call shares one path,
        so the binding name is what keeps two reducers' evidence apart. ``panel`` is the
        reference of a quorum Fusion's broadcast panel; the combine call and its signal calls
        then read it in place of every member's output.
        """

        if self._operators is None:
            raise ValueError(
                "a reducer needs the SF Engine operator catalog to compile; "
                "evaluate it through an sf.Client"
            )
        spec = combine_spec_text(
            reducer,
            member_count=len(members),
            operators=self._operators,
            benchmark_rule=self._benchmark_rule,
        )
        # The combine call reads the same question-and-panel value a Model synthesizer does;
        # building it here keeps a later extra input (signals) a local change.
        context = _fusion_context(input_context, members, panel=panel)
        self._sources.append(
            src(
                RelExpr(
                    path=COMBINE_ROUTE,
                    context=context,
                    intent=Text(spec),
                    params=(("binding", binding),),
                ),
                name=binding,
                weight=0.0,
            )
        )
        self._operations.append(
            _compiled_operation(
                id=operation_id,
                kind="combine",
                label=f"{fusion.name} combine",
                depends_on=dependencies,
            )
        )
        return _ResolvedRecipe(
            reference=f"${binding}",
            operation_id=operation_id,
            name=fusion.name,
            kind="fusion",
            models=_ordered_unique(_member_models(members)),
            topology=_RecipeTopology(
                kind="fusion",
                quorum=fusion.quorum,
                optional=fusion.optional,
                name=fusion.name,
                binding=binding,
                members=tuple(_required_topology(member) for member in members),
                synthesizer=_RecipeTopology(kind="reducer", name=reducer.name, binding=binding),
            ),
            members=members,
        )

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
        resolved: _ResolvedRecipe | None = None
        stage_topologies: list[_RecipeTopology] = []
        for index, stage in enumerate(pipeline.stages):
            resolved = self._recipe(
                stage,
                input_context=context,
                input_dependencies=dependencies,
                synthesis=synthesis and index == 0,
            )
            context = resolved.reference
            dependencies = (resolved.operation_id,)
            models = _ordered_unique((*models, *resolved.models))
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
        )

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
    input_context: str, members: tuple[_ResolvedRecipe, ...], *, panel: str | None = None
) -> str:
    """Build canonical JSON at runtime so arbitrary answers remain safely escaped.

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
    return render(struct(value))


def _member_models(members: tuple[_ResolvedRecipe, ...]) -> tuple[str, ...]:
    return tuple(route for member in members for route in member.models)


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
