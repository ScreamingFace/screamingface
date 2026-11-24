"""MedXpertQA's commit turn: the chat it continues, and who answers it (OME-1980).

FEATURE: MedXpertQA two-turn protocol. Turn 1 asks the Candidate to reason; turn 2, the
**commit**, asks it to finish "Therefore, among A through J, the answer is". The official
harness sends turn 2 as the next message of the SAME chat, so the model completes its own
sentence and the letter comes first, which is what its first-letter answer reader needs.

Two pieces, in the order a Case uses them:

1. ``commit_chat`` — the chat turn 2 sends: the turn-1 prompt as the user, the Candidate's own
   turn-1 answer as the assistant, then the trigger as the user. It is written as the Engine's
   candidate-input envelope, which the model connector already expands into real messages.
2. ``commit_recipe`` — who answers it. When ONE model call wrote the turn-1 answer, only that
   model commits; anything else runs whole, as on turn 1.

Worked example, a Fusion of members X, Y, Z and synthesizer S on a Case whose key is D:

    turn 1:  X, Y, Z reason; S combines their answers into "...the fracture is in the humerus, D"
    chat:    user "Q: ...\\nA: Let's think step by step." · assistant "...humerus, D"
             · user "Therefore, among A through J, the answer is"
    recipe:  S alone, on that chat, without its synthesis prompt
    turn 2:  S replies "D." — 5 calls for the Case instead of 8

References:
    - Official harness, the four-message commit: https://github.com/TsinghuaC3I/MedXpertQA/blob/5f1db162d0d2b03d62da2d4fe086076a36105e18/eval/main.py#L92-L107
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import replace

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.invocation import BUDGET_SOURCE
from screamingface_engine.benchmarks.operation_outputs import final_reference
from url4 import render
from url4.core.errors import ParseError
from url4.core.nodes import Expression, RelExpr, Source, Text
from url4.core.parser import build

#: The binding a compiled Candidate feeds its Case input through (``$input``).
INPUT_REF = "$input"
# INVARIANT: only these step names can be ONE model call. A compiled reducer (Vote, Rank,
# Filter) is also a ``synthesis_N`` source, so the name alone is not enough: the step must also
# be a direct call to a model route (see ``commit_recipe``).
_MODEL_STEP = re.compile(r"^(?:model|synthesis)_\d+$")


def commit_chat(prompt: str, answer: str, trigger: str) -> str:
    """The chat turn 2 sends, as a candidate-input envelope.

    Messages, in the official harness's order: the turn-1 prompt (user), the Candidate's own
    turn-1 answer (assistant), the trigger (user). An empty answer (a refusal, an empty reply,
    or an abstain) leaves the assistant message out, because some providers refuse an empty
    one; the model then gets one cold chance to commit (owner's call on OME-1980).

    INVARIANT: the bytes depend only on the three texts, so a rerun sends the same turn 2 and
    the AI Gateway's request cache serves it (OME-1786).
    """

    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    if answer:
        messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": trigger})
    return json.dumps(
        {"schema": CANDIDATE_INPUT_SCHEMA, "messages": messages},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def commit_recipe(candidate: str, is_model_route: Callable[[str], bool]) -> str:
    """The recipe turn 2 runs: the one model that wrote the turn-1 answer, else the whole Candidate.

    Stage 1 — find the step the Candidate's result comes from (its root intent is exactly
        ``$name``, a Gate followed to its JOIN), with the same reader the Engine's per-step
        records use.
    Stage 2 — is that step ONE model call? Its name is ``model_N`` or ``synthesis_N`` AND its
        value is a direct call to one of the world's model routes. A Vote's ``synthesis_1`` is
        a call to the Engine's combine route, so it fails here.
    Stage 3 — build the shortcut: that step alone, reading ``$input`` (the commit chat), plus
        the Candidate's budget source so its caps still bind. A synthesizer drops its synthesis
        prompt (there is no panel to synthesize on turn 2); a plain model keeps its own
        instruction, the one it answered turn 1 under.

    Anything that fails a stage, or text that does not parse, returns ``candidate`` unchanged:
    the whole recipe runs on the chat, as every model ran on turn 1.

    ``is_model_route`` says whether a path is one of the world's model routes (the routes the
    model connector serves). Every other path (combine, corrective loop, Benchmark routes) is
    the Engine's own step, never one model call.
    """

    # Stages 1 and 2 — which step wrote the answer, and is it one model call?
    found: tuple[Expression, Source, RelExpr] | None = _one_model_step(candidate, is_model_route)
    if found is None:
        return candidate
    root, step, model_call = found

    # Stage 3 — that model alone, on the chat, under the Candidate's budget.
    # WHY an empty instruction, not none: url4 requires every call to carry one, and the model
    # connector sends no system message for an empty instruction.
    synthesizer: bool = (step.name or "").startswith("synthesis_")
    intent: Text = Text("") if synthesizer else _text_intent(model_call)
    call: RelExpr = replace(model_call, context=INPUT_REF, intent=intent)
    budget: list[Source] = [
        source
        for source in root.sources
        if isinstance(source, Source) and source.name == BUDGET_SOURCE
    ]
    return render(
        Expression(
            sources=(*budget, replace(step, value=call)),
            intent=Text(f"${step.name}"),
        )
    )


def _one_model_step(
    candidate: str, is_model_route: Callable[[str], bool]
) -> tuple[Expression, Source, RelExpr] | None:
    """The root, the step its result comes from, and that step's call, when it is ONE model call."""

    name: str | None = final_reference(candidate)
    root: Expression | None = (
        _parsed(candidate) if name is not None and _MODEL_STEP.fullmatch(name) else None
    )
    step: Source | None = None if root is None or name is None else _source(root, name)
    call: object = None if step is None else step.value
    if (
        root is None
        or step is None
        or not isinstance(call, RelExpr)
        or not is_model_route(call.path)
    ):
        return None
    return root, step, call


def _parsed(candidate: str) -> Expression | None:
    """The recipe text as its root expression; None when it does not parse as one."""

    try:
        root: object = build(candidate)
    except ParseError:
        return None
    return root if isinstance(root, Expression) else None


def _source(root: Expression, name: str) -> Source | None:
    """The root source called ``name``; a step nested deeper is not one the shortcut can lift."""

    matches: list[Source] = [
        source for source in root.sources if isinstance(source, Source) and source.name == name
    ]
    return matches[0] if len(matches) == 1 else None


def _text_intent(call: RelExpr) -> Text:
    """The call's own instruction when it is plain text, else an empty one."""

    return call.intent if isinstance(call.intent, Text) else Text("")


__all__ = ["INPUT_REF", "commit_chat", "commit_recipe"]
