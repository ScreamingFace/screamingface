"""`rubric_check` — one check-surface adapter every rubric benchmark configures.

FEATURE: benchmark-independent corrective loop (OME-830, the template stage).
STORY: as the next rubric benchmark (GDPval-rubric, FSResearch), I get a mid-run
check surface by declaring a `RubricCheck` — no adapter code of my own.

Mental model: a marker who is handed a rubric, a marking policy, and a phone
number for a judge. The marking WORK is identical everywhere; only the paperwork
differs. So the work lives here once, and each benchmark supplies paperwork:

- `RubricShape` — where the criteria sit in that benchmark's rubric file, and
  which fields carry the id, the requirement text, the weight, and (if it has
  one) the area a criterion belongs to.
- `RubricCheck` — the marking policy: which judge, the pass criterion's NAME and
  threshold, how a question is rendered for the judge, and which sanitized
  feedback vocabulary the benchmark may safely speak.

Per check, in execution order:

1. **Resolve the case** by exact input text — a black-box `$candidate` only ever
   sees `$input`, so the check is input-addressed, never case-id addressed.
2. **Read every criterion** through the shape so satisfaction and canonical
   rubric coverage cannot silently diverge.
3. **One judge pass**, weight-blind. The answer is part of the exact request, so
   one draft's cached verdict cannot serve another; an unusable reply retries
   with a bounded marker in the prompt, then fails the check.
4. **Score**: `clamp(sum of met weights / sum of positive weights)`. Penalties
   (negative weights) only subtract — they are not points a draft can win.
5. **Sanitize** the shortfall to the benchmark's declared vocabulary. Requirement
   text is the answer key and must never cross back toward the Candidate.

Worked example (weights +3, +1, +1, -2; positives sum to 5): a draft meeting the
first two scores 4/5 = 0.8 — passing at a 0.7 threshold. The same draft that also
trips the -2 penalty scores (4-2)/5 = 0.4 and fails, and its feedback names only
the areas that fell short.

INVARIANT: this module is shared machinery and imports NO benchmark package. The
scoring formula lives here rather than borrowing a benchmark's grader, because
check semantics are pinned by the pass criterion's own name (`<benchmark>-pass.vN`)
— a canonical-grading change must never silently move a check threshold.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.ensemble.policy import CHECK_SURFACE_SCHEMA
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.evaluation import candidate_answer, compact_json, json_object
from screamingface_engine.benchmarks.spine.verdict import recovered_array
from url4 import RelExpr, Text, expr, render, src
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

# One judge call plus two retries. A retry exists for unusable REPLIES, never to
# shop for a better verdict — only a bounded retry marker changes.
CHECK_ATTEMPTS = 3
CHECK_INTENT = "check"
FEEDBACK_INTENT = "feedback"

# INVARIANT: this ships as a rendered URL4 intent — a single quote would corrupt the
# expression's re-parse, and a newline would need escaping. Quote- and newline-free,
# pinned by every adapter's tests.
CHECK_INSTRUCTIONS = (
    "You are grading one response against a numbered list of rubric requirements. "
    "For each requirement decide MET when the response satisfies it and UNMET when it "
    "does not. A requirement marked negative describes something the response must "
    "avoid: mark it MET only when the response actually does the thing it should avoid. "
    "Judge only what the response says. Return raw JSON only, starting with [ and "
    "containing one object per requirement in order, each with the fields id and "
    "status, where status is MET or UNMET. Do not add commentary."
)

type FeedbackVocabulary = Literal["areas", "severity"]
type QuestionStyle = Literal["text", "chat_envelope"]


@dataclass(frozen=True, slots=True)
class RubricShape:
    """Where one benchmark's rubric file keeps its criteria, and under which names.

    ``layout="sections"`` walks ``<items>[].<nested>[]`` (DRACO's axis sections);
    ``layout="flat"`` walks ``<items>[]`` (HealthBench's rubric items). Field names
    are arguments so a new benchmark spells its own JSON without new Python.
    """

    layout: Literal["sections", "flat"]
    items: str
    id_field: str
    text_field: str
    weight_field: str
    nested: str | None = None
    # Tried in order; the first non-empty value names the criterion's area. Empty
    # means the benchmark has no area vocabulary (so it cannot speak "areas").
    area_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RubricCheck:
    """One benchmark's complete check-surface declaration — arguments, not code."""

    label: str
    criterion: str
    threshold: float
    shape: RubricShape
    judge_model: str
    judge_params: tuple[tuple[str, str], ...] = ()
    feedback: FeedbackVocabulary = "areas"
    question: QuestionStyle = "text"

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"{self.label} check threshold must sit in [0, 1]")
        if self.feedback == "areas" and not self.shape.area_fields:
            raise ValueError(
                f"{self.label} cannot speak area-level feedback: its rubric shape "
                "declares no area fields"
            )

    def route(self, prefix: str) -> str:
        """The check route for one protocol prefix.

        The pass criterion rides in the path: a different criterion is a different
        route, so it reaches the manifest, every compiled Candidate url4, and the
        recipe topology of every run record.
        """

        return f"{prefix}/check-surface/{self.criterion}"


def check_surface(node: Url4Node, root: Path, config: RubricCheck):
    """Build one benchmark's check endpoint from its declaration.

    Closes over ``node`` so the judge route resolves at REQUEST time: benchmark
    installation must keep working in worlds that hold no model routes at all.
    """

    async def check(request: Request) -> str:
        if request.intent == FEEDBACK_INTENT:
            return _surface_feedback(config, request.context)
        if request.intent != CHECK_INTENT:
            raise _unsupported(f"{config.label} check surface", request.intent)
        question, invocation, answer = _payload(config, request.context)
        case_id = _case_by_input(config, root, question)
        criteria = _criteria(config, root, case_id)
        verdicts = await _judged(
            node, config, question=_asked(config, question), answer=answer, criteria=criteria
        )
        satisfaction = _score(criteria, verdicts)
        if satisfaction is None:
            raise _unavailable(
                f"{config.label} case {case_id} has no positively weighted criterion to "
                "check against"
            )
        return compact_json(
            {
                "schema": CHECK_SURFACE_SCHEMA,
                "passed": satisfaction >= config.threshold,
                "satisfaction": satisfaction,
                "feedback": _feedback(config, criteria, verdicts),
                "answer": answer,
                "invocation": invocation,
            }
        )

    return check


# --- inputs -----------------------------------------------------------------------


def _payload(config: RubricCheck, value: object) -> tuple[str, str, str]:
    payload = json_object(value, f"{config.label} check surface")
    if set(payload) != {"input", "invocation"}:
        raise _unavailable(
            f"{config.label} check surface context must carry exactly input and invocation"
        )
    question = payload["input"]
    invocation = payload["invocation"]
    if not isinstance(question, str) or not isinstance(invocation, str):
        raise _unavailable(f"{config.label} check surface input and invocation must be text")
    try:
        answer = candidate_answer(invocation).text
    except (TypeError, ValueError) as exc:
        raise _unavailable(
            f"{config.label} check surface Candidate Invocation is invalid: {exc}"
        ) from exc
    return question, invocation, answer


def _case_by_input(config: RubricCheck, root: Path, question: str) -> int:
    """Resolve the case whose pinned input is exactly ``question``.

    Ambiguity is a bounded failure, never a guess: a silently mismatched case
    would grade a draft against another case's rubric.
    """

    cases = json.loads(_read(root / "cases.json", f"{config.label} cases"))
    if not isinstance(cases, list):
        raise _unavailable(f"{config.label} cases must be a JSON array")
    matches = [
        case.get("id") for case in cases if isinstance(case, dict) and case.get("input") == question
    ]
    if not matches:
        raise _unavailable(f"no {config.label} case matches the check surface input")
    if len(matches) > 1:
        raise _unavailable(f"the check surface input matches more than one {config.label} case")
    case_id = matches[0]
    if isinstance(case_id, bool) or not isinstance(case_id, int):
        raise _unavailable(f"{config.label} case id must be an integer")
    return case_id


def _asked(config: RubricCheck, question: str) -> str:
    """Render the case input the way this benchmark's judge expects to read it."""

    if config.question == "text":
        return question
    envelope = json.loads(question) if question.strip().startswith("{") else None
    if not isinstance(envelope, Mapping) or envelope.get("schema") != CANDIDATE_INPUT_SCHEMA:
        raise _unavailable(f"{config.label} check surface input is not a chat envelope")
    messages = envelope.get("messages")
    decoded = json.loads(messages) if isinstance(messages, str) else messages
    if not isinstance(decoded, list) or not decoded:
        raise _unavailable(f"{config.label} check surface input carries no messages")
    return "\n\n".join(
        f"{turn.get('role')}: {turn.get('content')}"
        for turn in decoded
        if isinstance(turn, Mapping)
    )


# --- rubric reading ---------------------------------------------------------------


def _criteria(config: RubricCheck, root: Path, case_id: int) -> list[dict[str, Any]]:
    rubric = json.loads(
        _read(root / "rubrics" / f"{case_id}.json", f"{config.label} rubric {case_id}")
    )
    if not isinstance(rubric, Mapping):
        raise _unavailable(f"{config.label} rubric {case_id} must be a JSON object")
    criteria = list(_read_criteria(config.shape, rubric))
    if not criteria:
        raise _unavailable(f"{config.label} rubric {case_id} carries no criteria")
    return criteria


def _read_criteria(shape: RubricShape, rubric: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    for group, rows in _groups(shape, rubric):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            yield {
                "id": str(row.get(shape.id_field)),
                "text": str(row.get(shape.text_field, "")),
                "weight": _weight(row.get(shape.weight_field)),
                "area": group,
            }


def _groups(
    shape: RubricShape,
    rubric: Mapping[str, Any],
) -> Iterator[tuple[str, Sequence[Any]]]:
    container = rubric.get(shape.items)
    if not isinstance(container, list):
        return
    if shape.layout == "flat":
        yield "", container
        return
    for section in container:
        if not isinstance(section, Mapping):
            continue
        rows = section.get(shape.nested or "")
        if isinstance(rows, list):
            yield _area(shape, section), rows


def _area(shape: RubricShape, section: Mapping[str, Any]) -> str:
    for name in shape.area_fields:
        value = section.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return "unknown"


def _weight(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


# --- judging ----------------------------------------------------------------------


async def _judged(
    node: Url4Node,
    config: RubricCheck,
    *,
    question: str,
    answer: str,
    criteria: Sequence[Mapping[str, Any]],
) -> dict[str, bool]:
    prompt = build_check_prompt(question, answer, criteria)
    last_reply = ""
    for attempt in range(1, CHECK_ATTEMPTS + 1):
        try:
            reply = await node.evaluate(
                _judge_expression(config), env={"prompt": _attempt_prompt(prompt, attempt)}
            )
        except ResolutionError as exc:
            if getattr(exc, "code", None) != "model_token_cap":
                raise
            # Re-attribute the runner's token-cap failure to the CHECK JUDGE: without the
            # role, the report reads as the candidate running dry. Same budget, same
            # truncation — retrying pays to fail identically, so fail on first strike.
            raise _unavailable(
                f"the {config.label} check judge ran out of tokens "
                f"(judge {_judge_budget(config)}, set in the benchmark's check_policy): {exc}"
            ) from exc
        verdicts = _verdicts(reply.text, criteria)
        if verdicts is not None:
            return verdicts
        last_reply = reply.text or ""
    # Url4Result carries no finish_reason, so the reply's shape is the only signal a
    # reader gets: a long reply whose tail is mid-JSON means truncation (raise the
    # judge's token budget); a short prose tail means the judge ignored the format.
    raise _unavailable(
        f"the {config.label} check judge returned no usable verdict in {CHECK_ATTEMPTS} attempts"
        f" (judge {_judge_budget(config)}, set in the benchmark's check_policy; "
        f"last reply: {len(last_reply)} chars, tail: {last_reply[-160:]!r})"
    )


def _judge_budget(config: RubricCheck) -> str:
    """The judge's token budget as message text — the knob a failure must name."""
    cap = dict(config.judge_params).get("max_tokens")
    return f"max_tokens={cap}" if cap is not None else "max_tokens unset (provider default)"


def build_check_prompt(
    question: str,
    answer: str,
    criteria: Sequence[Mapping[str, Any]],
) -> str:
    """Frame one whole-rubric check pass: the ask, the draft, the numbered rules.

    Weights never appear — the judge reports satisfaction and scoring applies the
    weights afterwards, so a judge cannot optimize for score. Only the SIGN is
    disclosed, as the requirement's type, exactly as canonical grading does.
    """

    lines = [
        "<query>",
        question,
        "</query>",
        "<response>",
        answer,
        "</response>",
        "<requirements>",
    ]
    for ordinal, criterion in enumerate(criteria, start=1):
        kind = "negative" if float(criterion.get("weight", 0)) < 0 else "positive"
        lines.append(f"[{ordinal}] ({kind}) {criterion['text']}")
    lines.append("</requirements>")
    return "\n".join(lines)


def _attempt_prompt(prompt: str, attempt: int) -> str:
    """Vary only retry requests without inventing provider model parameters."""

    if attempt == 1:
        return prompt
    return f"{prompt}\n<retry_attempt>{attempt}</retry_attempt>"


def _judge_expression(config: RubricCheck) -> str:
    # WHY the prompt is an env binding, not inlined: it carries the Candidate's own
    # answer, and a quote or comma in that text would corrupt the rendered expression.
    # Retry identity belongs in that bound prompt, not in fake model parameters that
    # the gateway would correctly reject before provider dispatch.
    return render(
        expr(
            src(
                RelExpr(
                    path="/" + config.judge_model.removeprefix("/"),
                    context="$prompt",
                    intent=Text(CHECK_INSTRUCTIONS),
                    params=config.judge_params,
                ),
                name="verdict",
                weight=0.0,
            ),
            intent=Text("$verdict"),
        )
    )


def _verdicts(
    reply: str,
    criteria: Sequence[Mapping[str, Any]],
) -> dict[str, bool] | None:
    """Map an ordinal-keyed judge reply onto criterion ids, or None if unusable.

    Every selected requirement must carry exactly one MET/UNMET verdict: a partial
    reply would silently score unjudged criteria as failed. A repeated ordinal
    collapses in the mapping and so fails the same completeness check.
    """

    decoded = _decoded_array(reply)
    if decoded is None or len(decoded) != len(criteria):
        return None
    verdicts: dict[str, bool] = {}
    for row in decoded:
        judged = _verdict_row(row, len(criteria))
        if judged is None:
            break
        ordinal, met = judged
        verdicts[str(criteria[ordinal - 1]["id"])] = met
    return verdicts if len(verdicts) == len(criteria) else None


def _verdict_row(row: object, count: int) -> tuple[int, bool] | None:
    if not isinstance(row, dict):
        return None
    ordinal = row.get("id")
    status = row.get("status")
    # Judges routinely quote the ordinal ('"id": "51"'); a digit string is the same
    # verdict, so it decodes rather than voiding an otherwise-complete reply.
    if isinstance(ordinal, str) and ordinal.strip().isdigit():
        ordinal = int(ordinal.strip())
    numbered = not isinstance(ordinal, bool) and isinstance(ordinal, int) and 1 <= ordinal <= count
    decided = isinstance(status, str) and status.strip().upper() in {"MET", "UNMET"}
    if not (numbered and decided):
        return None
    assert isinstance(ordinal, int) and isinstance(status, str)
    return ordinal, status.strip().upper() == "MET"


def _decoded_array(reply: str) -> list[object] | None:
    # The shared JSON-recovery primitive (spine.verdict, OME-1099) — same fence
    # stripping and first-value scan as the per-item verdict parsers.
    return recovered_array(reply or "")


# --- scoring + sanitization -------------------------------------------------------


def _score(
    criteria: Sequence[Mapping[str, Any]],
    verdicts: Mapping[str, bool],
) -> float | None:
    """`clamp(earned / best possible)` over the judged criteria; None if unscorable.

    Penalties are not points a draft can win, so only positive weights enter the
    denominator; meeting a negative criterion subtracts from what was earned. With
    nothing positive to win, "we could not score this" is not the same fact as
    "this scored zero" — hence None rather than 0.0.
    """

    best = sum(float(row["weight"]) for row in criteria if float(row["weight"]) > 0)
    if best <= 0:
        return None
    earned = sum(float(row["weight"]) for row in criteria if verdicts.get(str(row["id"]), False))
    return max(0.0, min(1.0, earned / best))


def _feedback(
    config: RubricCheck,
    criteria: Sequence[Mapping[str, Any]],
    verdicts: Mapping[str, bool],
) -> str:
    """Say what fell short in the benchmark's safe vocabulary — never a requirement.

    INVARIANT (sealed envelope): this text is the only thing a check sends back
    toward the Candidate, and requirement text IS the answer key. `areas` names
    rubric sections (categories a panel could infer from the question anyway);
    `severity` is for benchmarks with no area vocabulary at all, and says only
    whether the shortfall was a missing requirement or a violated prohibition.
    """

    missed = [row for row in criteria if _shortfall(row, verdicts)]
    if not missed:
        return ""
    if config.feedback == "areas":
        areas: list[str] = []
        for row in missed:
            area = str(row["area"])
            if area not in areas:
                areas.append(area)
        return "The answer did not satisfy these rubric areas: " + " | ".join(areas)
    violated = any(float(row["weight"]) < 0 for row in missed)
    omitted = any(float(row["weight"]) >= 0 for row in missed)
    parts = []
    if omitted:
        parts.append("it left required elements out")
    if violated:
        parts.append("it did something the rubric prohibits")
    return "The answer fell short: " + " and ".join(parts) + "."


def _shortfall(row: Mapping[str, Any], verdicts: Mapping[str, bool]) -> bool:
    weight = float(row["weight"])
    met = bool(verdicts.get(str(row["id"]), False))
    return (weight >= 0 and not met) or (weight < 0 and met)


def _surface_feedback(config: RubricCheck, value: object) -> str:
    record = json_object(value, f"{config.label} check-surface feedback")
    if record.get("schema") != CHECK_SURFACE_SCHEMA:
        raise _unavailable(f"feedback input must be a {CHECK_SURFACE_SCHEMA} check-surface record")
    feedback = record.get("feedback")
    if not isinstance(feedback, str):
        raise _unavailable("check-surface record feedback must be text")
    return feedback


def _unsupported(label: str, intent: str) -> ResolutionError:
    return ResolutionError(
        f"unsupported {label} operation {intent!r}",
        code="benchmark_operation_unsupported",
        permanent=True,
    )


def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _unavailable(f"could not read {label} at {str(path)!r}: {exc}") from exc


__all__ = [
    "CHECK_ATTEMPTS",
    "CHECK_INSTRUCTIONS",
    "RubricCheck",
    "RubricShape",
    "build_check_prompt",
    "check_surface",
]
