"""Client-side corrective-loop compilation — the whole loop in one `$candidate`.

FEATURE: benchmark-independent corrective loop (OME-796 / OME-828).
STORY: as a user, `sf.CorrectiveLoop([a, b], judge=c)` runs on ANY benchmark
advertising a check surface — the loop is a way of BEING a worker, so it lives
inside the candidate plug, never in a benchmark's template.

Mental model: statically unrolled retakes behind gates. The compiler emits, per
round k (1..max_rounds), in execution order:

1. (k > 1) one coach call — the judge (panel) or the member itself (solo)
   authors retry hints from the previous round; reached ONLY inside the gated
   continuation, so coaching is bought exclusively by a no-pass round.
2. Every member drafts (ordinary compiled Recipe calls; round 1 sees the bare
   `$input`, later rounds see input + own previous answer + the coaching).
3. Every draft is checked mid-run via the manifest's `check_route` (never a
   hardcoded path) — the check-surface record carries passed/satisfaction/
   feedback, sanitized behind the benchmark's adapter.
4. The round object (member label -> record) feeds the generic engine gates:
   `tie:k:R` (0-or-1 judge tie-break), the verbatim SELECT, and `continue:k:R`
   whose 0-or-1 payload gates the next round's entire subtree — an empty gate
   means the deeper rounds NEVER execute, which is what makes `max_rounds` a
   cost cap.
5. (k < R) the ANSWER route collapses {selected, next} bottom-up so the deepest
   executed round's selection is the candidate's single verbatim output.

Worked example (2 members, max_rounds=3, round 1 has a passer): 2 member calls
+ 2 checks + gate/select data calls; the continuation iterate sees [] and the
other 4 member calls + 3 judge calls never run.

The routes and schemas under `# Transport contract` mirror the Engine's
ensemble policy. Loop prose is Client-owned because the Client renders it into
the executable expression; the protocol revision below identifies both the
Engine route version and that Client-authored behavior.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from url4 import Expression, Node, RelExpr, Text, iterate, ref, render, src, struct

from screamingface._evaluation.topology import _RecipeTopology
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.errors import PlanningError

if TYPE_CHECKING:
    from screamingface._evaluation.benchmark import _CheckSurface
    from screamingface._evaluation.candidate import _CandidateCompiler, _ResolvedRecipe
    from screamingface.recipe import Recipe

# --- Transport contract (mirrors screamingface_engine.benchmarks.ensemble.policy) -----------

CORRECTIVE_API_VERSION = "v1"
_CORRECTIVE_PREFIX = f"/ensemble/corrective/{CORRECTIVE_API_VERSION}"
GATE_ROUTE = f"{_CORRECTIVE_PREFIX}/gate"
SELECT_ROUTE = f"{_CORRECTIVE_PREFIX}/select"
ANSWER_ROUTE = f"{_CORRECTIVE_PREFIX}/answer"
MEMBER_ROUTE = f"{_CORRECTIVE_PREFIX}/member"
ROLE_ROUTE = f"{_CORRECTIVE_PREFIX}/role"
RESULT_ROUTE = f"{_CORRECTIVE_PREFIX}/result"
CHECK_SURFACE_SCHEMA = "screamingface.check-surface.v1"
CHECK_INTENT = "check"
_MIN_MEMBERS = 2
MEMBER_LABEL_SCHEME = "lowercase-base26"
_NESTED_INPUT_REF = "$_sf_recipe_input"

RETRY_INSTRUCTION = (
    "Write a new answer to the original request. Correct every requirement named in the "
    "feedback and return only the new answer."
)
SELF_FEEDBACK_INSTRUCTION = (
    "Write short concrete feedback telling yourself how to fix every failed requirement "
    "named in the verification feedback. Do not write a new answer."
)
JUDGE_FEEDBACK_INSTRUCTION = (
    "You are the judge for a team of answer writers. Their answers failed the listed "
    "requirements. Write short concrete corrective feedback that tells the writers how "
    "to satisfy every failed requirement. Do not write an answer yourself."
)
TIE_BREAK_INSTRUCTION = (
    "Every candidate answer already satisfies the requirements. Pick the best-written "
    "one. Reply with exactly one candidate label and nothing else."
)
# INVARIANT (OME-1168): the coach's per-member verdict projection carries ONLY
# these check-surface fields — never the record's Candidate Invocation envelope.
COACH_VERDICT_FIELDS = ("answer", "feedback")

CORRECTIVE_FLOW = (
    "at most max_rounds attempts; every member answers each executed attempt; an "
    "attempt with >=1 passing check STOPS the case; the judge tie-breaks only among "
    "passers of the stopping attempt; judge feedback is authored only for a no-pass "
    "attempt; a case that never passes selects the answer with maximal check "
    "satisfaction, judge label tie-break on exact ties; the selected Candidate Invocation "
    "is always one member outcome verbatim, including provider refusal identity"
)

# Run records carry this Client-owned protocol revision (via the Recipe
# topology) alongside the benchmark revision embedded in the check route, so a
# loop result self-identifies both its composition and checking semantics.
CORRECTIVE_PROTOCOL_REVISION = hashlib.sha256(
    "\n".join(
        (
            CORRECTIVE_API_VERSION,
            CORRECTIVE_FLOW,
            CHECK_SURFACE_SCHEMA,
            str(_MIN_MEMBERS),
            MEMBER_LABEL_SCHEME,
            # WHY hashed: the coach prompt's verdict shape is Client-rendered
            # behavior — reshaping it (OME-1168) must move the revision.
            ",".join(COACH_VERDICT_FIELDS),
            RETRY_INSTRUCTION,
            SELF_FEEDBACK_INSTRUCTION,
            JUDGE_FEEDBACK_INSTRUCTION,
            TIE_BREAK_INSTRUCTION,
        )
    ).encode()
).hexdigest()[:16]

# --- compilation ------------------------------------------------------------------


def _compile_corrective(
    compiler: _CandidateCompiler,
    recipe: CorrectiveLoop | SelfCorrective,
    check_surface: _CheckSurface | None,
) -> _ResolvedRecipe:
    """Render one corrective loop as sources on the compiler, root-position only."""

    if check_surface is None:
        # WHY fail here too: the runner preflights this with the benchmark's name
        # before compiling, but compile_candidate is also a public seam — a loop
        # without a check surface must never render a spendable expression.
        raise PlanningError(
            "The selected benchmark does not support mid-run checking, so a "
            "corrective loop cannot run on it",
            code="check_surface_missing",
            permanent=True,
        )
    return _LoopRenderer(compiler, recipe, check_surface).render()


class _LoopRenderer:
    """Build the gated round chain bottom-up onto one `_CandidateCompiler`."""

    def __init__(
        self,
        compiler: _CandidateCompiler,
        recipe: CorrectiveLoop | SelfCorrective,
        check_surface: _CheckSurface,
    ) -> None:
        self._compiler = compiler
        self._recipe = recipe
        self._surface = check_surface
        self._solo = isinstance(recipe, SelfCorrective)
        self._members = (recipe.member,) if isinstance(recipe, SelfCorrective) else recipe.members
        self._judge = recipe.member if isinstance(recipe, SelfCorrective) else recipe.judge
        self._max_rounds = recipe.max_rounds
        self._labels = _member_labels(len(self._members))
        self._round_one_members: tuple[_ResolvedRecipe, ...] = ()
        self._judge_models: tuple[str, ...] = ()
        self._judge_topology: _RecipeTopology | None = None

    def render(self) -> _ResolvedRecipe:
        from screamingface._evaluation.candidate import _ordered_unique, _ResolvedRecipe

        sources, reference = self._round(1, coach_reference=None)
        sources.append(
            src(
                RelExpr(path=RESULT_ROUTE, context=reference, intent=Text("result")),
                name="loop_result",
                weight=0.0,
            )
        )
        # WHY one nested group: the top-level envelope's reduce-over-iteration
        # decode is greedy, so gated iterations may not sit bare in the outer
        # intent-bearing group. Nesting the whole loop as ONE named inner
        # expression keeps every iteration in grammar-parsed (safe) position and
        # gives the candidate a single result binding.
        inner = Expression(sources=tuple(sources), intent=Text("$loop_result"))
        self._compiler._append_source(src(inner, name="loop_candidate", weight=0.0))
        reference = "$loop_candidate"
        members = self._round_one_members
        models = _ordered_unique(
            (
                *(model for member in members for model in member.models),
                *self._judge_models,
            )
        )
        binding = reference.removeprefix("$")
        topology = self._topology(binding, members)
        return _ResolvedRecipe(
            reference=reference,
            operation_id=members[0].operation_id,
            name=self._recipe.name,
            kind="self_corrective" if self._solo else "corrective_loop",
            models=models,
            topology=topology,
            members=() if self._solo else members,
        )

    def _round(
        self,
        attempt: int,
        *,
        coach_reference: str | None,
    ) -> tuple[list[Node], str]:
        """Sources for round `attempt` and the reference to its collapsed answer."""

        sources: list[Node] = []
        # Stage 2 — every member drafts.
        resolved_members: list[_ResolvedRecipe] = []
        for index, member in enumerate(self._members):
            label = self._labels[index]
            context = self._member_context(attempt, label, coach_reference)
            resolved, captured = self._captured(
                member,
                input_context=_NESTED_INPUT_REF,
                synthesis=False,
            )
            invocation = f"loop_member_{attempt}_{label}"
            sources.extend(
                self._invocation_sources(
                    resolved,
                    captured,
                    route=MEMBER_ROUTE,
                    input_context=context,
                    name=invocation,
                )
            )
            resolved_members.append(resolved)
            # Stage 3 — the benchmark's advertised check surface marks the draft.
            sources.append(
                src(
                    RelExpr(
                        path=self._surface.check_route,
                        context=render(struct({"input": "$input", "invocation": f"${invocation}"})),
                        intent=Text(CHECK_INTENT),
                    ),
                    name=f"loop_check_{attempt}_{label}",
                    weight=0.0,
                )
            )
        if attempt == 1:
            self._round_one_members = tuple(resolved_members)
        member_dependencies = tuple(member.operation_id for member in resolved_members)
        # Stage 4 — the round object the generic gates and select consume.
        sources.append(
            src(
                struct({label: f"$loop_check_{attempt}_{label}" for label in self._labels}),
                name=f"loop_round_{attempt}",
                weight=0.0,
            )
        )
        tie_reference = self._tie_break(attempt, sources, member_dependencies)
        # Verbatim selection of the round's representative answer.
        sources.append(
            src(
                RelExpr(
                    path=SELECT_ROUTE,
                    context=render(
                        struct({"round": f"$loop_round_{attempt}", "tie": tie_reference})
                    ),
                    intent=Text(str(attempt)),
                ),
                name=f"loop_selection_{attempt}",
                weight=0.0,
            )
        )
        selection = f"$loop_selection_{attempt}"
        if attempt == self._max_rounds:
            return sources, selection
        # Stage 5 — the continue gate and the gated deeper subtree.
        gate_name = f"loop_continue_gate_{attempt}"
        sources.append(
            src(
                RelExpr(
                    path=GATE_ROUTE,
                    context=f"$loop_round_{attempt}",
                    intent=Text(f"continue:{attempt}:{self._max_rounds}"),
                ),
                name=gate_name,
                weight=0.0,
            )
        )
        body: list[Node] = []
        coach = self._coach(attempt, body, member_dependencies)
        deeper, deeper_reference = self._round(attempt + 1, coach_reference=coach)
        body.extend(deeper)
        sources.append(
            self._gated_source(
                iterate(
                    ref(gate_name),
                    body=tuple(body),
                    intent=Text(deeper_reference),
                    on_error="fail",
                ),
                name=f"loop_next_{attempt}",
            )
        )
        sources.append(
            src(
                RelExpr(
                    path=ANSWER_ROUTE,
                    context=render(
                        struct(
                            {
                                "selected": selection,
                                "next": f"$loop_next_{attempt}",
                            }
                        )
                    ),
                    intent=Text(str(attempt)),
                ),
                name=f"loop_answer_{attempt}",
                weight=0.0,
            )
        )
        return sources, f"$loop_answer_{attempt}"

    def _member_context(
        self,
        attempt: int,
        label: str,
        coach_reference: str | None,
    ) -> str:
        if attempt == 1:
            return "$input"
        assert coach_reference is not None
        previous_answer = f"$loop_check_{attempt - 1}_{label}.answer"
        if self._solo:
            return (
                "$input"
                f" | Previous answer: {previous_answer}"
                f" | Feedback: {coach_reference}"
                f" | {RETRY_INSTRUCTION}"
            )
        return (
            "$input"
            f" | Your previous answer: {previous_answer}"
            f" | Judge feedback: {coach_reference}"
            f" | {RETRY_INSTRUCTION}"
        )

    def _tie_break(
        self,
        attempt: int,
        sources: list[Node],
        member_dependencies: tuple[str, ...],
    ) -> str:
        """Append the 0-or-1 judge tie-break; solo rounds never tie."""

        if self._solo:
            # A one-member round has no tie to break; the select endpoint treats
            # empty tie text as "no judge label" and its deterministic rules apply.
            return ""
        gate_name = f"loop_tie_gate_{attempt}"
        sources.append(
            src(
                RelExpr(
                    path=GATE_ROUTE,
                    context=f"$loop_round_{attempt}",
                    intent=Text(f"tie:{attempt}:{self._max_rounds}"),
                ),
                name=gate_name,
                weight=0.0,
            )
        )
        # WHY the judge model runs inside the gated iterate: a lone passer (the
        # commonest outcome) must cost ZERO judge calls.
        resolved, captured = self._captured(
            self._judge,
            input_context=_NESTED_INPUT_REF,
            synthesis=True,
            input_dependencies=member_dependencies,
        )
        role_name = f"loop_tie_role_{attempt}"
        role_sources = self._invocation_sources(
            resolved,
            captured,
            route=ROLE_ROUTE,
            input_context=_structured_context(
                {
                    "request": "$input",
                    "task": TIE_BREAK_INSTRUCTION,
                    "candidates": "$item.candidates",
                }
            ),
            name=role_name,
        )
        if self._judge_topology is None:
            # The judge compiles once per gated position; every compile resolves
            # the same recipe, so the round-1 tie-break compilation stands for
            # the role in the topology rider and the models list.
            self._judge_models = resolved.models
            self._judge_topology = resolved.topology
        sources.append(
            self._gated_source(
                iterate(
                    ref(gate_name),
                    body=tuple(role_sources),
                    intent=Text(f"${role_name}"),
                    on_error="fail",
                ),
                name=f"loop_tie_pick_{attempt}",
            )
        )
        return f"$loop_tie_pick_{attempt}"

    def _coach(
        self,
        attempt: int,
        body: list[Node],
        member_dependencies: tuple[str, ...],
    ) -> str:
        """Append the coaching call to the gated body; return its reference.

        INVARIANT: coaching lives ONLY inside the continue-gated subtree —
        feedback is authored solely for a no-pass round, so a passing round
        never buys a coaching call (exact-round coaching is anti-LANL spend).
        """

        if self._solo:
            label = self._labels[0]
            context = (
                "$input"
                f" | Your answer: $loop_check_{attempt}_{label}.answer"
                f" | Verification feedback: $loop_check_{attempt}_{label}.feedback"
                f" | {SELF_FEEDBACK_INSTRUCTION}"
            )
        else:
            # WHY a projection, not the round object (OME-1168): the round's
            # records carry each member's full Candidate Invocation envelope
            # (accounting/usage token counts, provider/model identity) for the
            # SELECT endpoint's verbatim-selection invariant. Pasting that into
            # the coach prompt makes a recorded run unreplayable (live token
            # counts vs replay's cache-hit zeros re-key the request) and leaks
            # member identity the judge's role design withholds. The coach
            # consumes exactly answer + check feedback per member.
            context = _structured_context(
                {
                    "request": "$input",
                    "task": JUDGE_FEEDBACK_INSTRUCTION,
                    "verdicts": {
                        label: {
                            "answer": f"$loop_check_{attempt}_{label}.answer",
                            "feedback": f"$loop_check_{attempt}_{label}.feedback",
                        }
                        for label in self._labels
                    },
                }
            )
        resolved, captured = self._captured(
            self._judge,
            input_context=_NESTED_INPUT_REF,
            synthesis=True,
            input_dependencies=member_dependencies,
        )
        role_name = f"loop_coach_{attempt}"
        body.extend(
            self._invocation_sources(
                resolved,
                captured,
                route=ROLE_ROUTE,
                input_context=context,
                name=role_name,
            )
        )
        return f"${role_name}"

    def _gated_source(self, iteration: Node, *, name: str) -> Node:
        """Bind one gated iteration under `name` (always in nested position)."""

        return src(iteration, name=name, weight=0.0)

    def _captured(
        self,
        recipe: Recipe,
        *,
        input_context: str,
        synthesis: bool,
        input_dependencies: tuple[str, ...] = (),
    ) -> tuple[_ResolvedRecipe, tuple[Node, ...]]:
        """Compile one Recipe and detach its sources for nested placement."""

        return self._compiler._capture_recipe(
            recipe,
            input_context=input_context,
            input_dependencies=input_dependencies,
            synthesis=synthesis,
        )

    def _invocation_sources(
        self,
        resolved: _ResolvedRecipe,
        captured: tuple[Node, ...],
        *,
        route: str,
        input_context: str,
        name: str,
    ) -> list[Node]:
        """Invoke one nested Recipe behind an isolated outcome boundary."""

        expression = Expression(sources=tuple(captured), intent=Text(resolved.reference))
        return [
            src(
                RelExpr(
                    path=route,
                    context=input_context,
                    # The nested Recipe uses a reserved input name that no
                    # enclosing candidate scope owns. The Engine endpoint binds
                    # it to this invocation's current-round context.
                    intent=Text(render(expression)),
                ),
                name=name,
                weight=0.0,
            )
        ]

    def _topology(
        self,
        binding: str,
        members: tuple[_ResolvedRecipe, ...],
    ) -> _RecipeTopology:
        if self._solo:
            return _RecipeTopology(
                kind="self_corrective",
                name=self._recipe.name,
                binding=binding,
                members=(members[0].topology,),
                max_rounds=self._max_rounds,
                check_route=self._surface.check_route,
                protocol=CORRECTIVE_PROTOCOL_REVISION,
            )
        # The topology's judge entry is descriptive identity, not an executable
        # binding: the round-1 tie-break compilation stands for the role.
        assert self._judge_topology is not None
        return _RecipeTopology(
            kind="corrective_loop",
            name=self._recipe.name,
            binding=binding,
            members=tuple(member.topology for member in members),
            judge=self._judge_topology,
            max_rounds=self._max_rounds,
            check_route=self._surface.check_route,
            protocol=CORRECTIVE_PROTOCOL_REVISION,
        )


def _structured_context(value: dict[str, object]) -> str:
    return render(src(struct(value), name="payload"))


def _member_labels(count: int) -> tuple[str, ...]:
    """Return stable lowercase labels: a..z, aa..az, ba..."""

    return tuple(_member_label(index) for index in range(count))


def _member_label(index: int) -> str:
    value = index + 1
    selected = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        selected = chr(ord("a") + remainder) + selected
    return selected


__all__ = [
    "ANSWER_ROUTE",
    "CHECK_INTENT",
    "CHECK_SURFACE_SCHEMA",
    "CORRECTIVE_FLOW",
    "CORRECTIVE_PROTOCOL_REVISION",
    "GATE_ROUTE",
    "JUDGE_FEEDBACK_INSTRUCTION",
    "MEMBER_ROUTE",
    "MEMBER_LABEL_SCHEME",
    "RETRY_INSTRUCTION",
    "RESULT_ROUTE",
    "ROLE_ROUTE",
    "SELECT_ROUTE",
    "SELF_FEEDBACK_INSTRUCTION",
    "TIE_BREAK_INSTRUCTION",
    "_compile_corrective",
]
