"""Turn one saved SDK report into a servable payload tape (OME-978).

Mental model: the bless tool's ``--report`` mode manufactures the "internet" a
keyless replay runs against — a cache table of ``(key, response)`` rows. The KEYS
can only come from the engine (it renders the request bytes; the gateway hashes
them), but every RESPONSE TEXT is already in the saved report of the paid run. This
module is the response side of that bargain: parse the report once into a tape,
then answer "which recorded text serves this captured request body?" for every
body the capture loop sees.

Stages, in execution order (the capture→splice loop in ``slice_snapshot.py`` drives
them):

1. **Parse** — ``parse_report`` reads a ``screamingface.report.v1`` document into a
   ``ReportTape``: the fusion lineup (member routes in order, the synthesizer, the
   judge), per scored Case every member answer + the synthesis + every judge
   verdict, and the status of EVERY case — failed included, because the golden pins
   those too. Anything ambiguous or unservable (two candidates, a non-fusion run,
   retried judges, duplicate identifying texts) refuses at parse time — the loop
   must never guess.
2. **Match** — ``match_body`` classifies one captured request body by its model
   route (member / synthesis / judge), pins the Case by the text the body embeds
   (question for members; member answers for the synthesis; the synthesized answer
   for judges — case FIRST, criterion second, because rubric labels repeat across
   cases), and returns the recorded text as a ``BodyMatch``. A failed case's body
   returns a ``BodySkip`` — the real run recorded nothing for it, so the replay
   must keep failing it; everything else unmatchable raises.
3. **Fabricate** — ``fabricate_payload`` wraps a recorded text in the same
   deterministic chat-completion envelope ``generate_synthetic.py`` uses, so the
   spliced row is byte-stable across re-blesses.

Worked example: the loop captures ``{"model": "openrouter/a/alpha", "messages":
[…, "How to treat a paper cut?"]}``. ``match_body`` sees a member route, finds
exactly one Case whose question is embedded, and returns that Case's recorded
alpha answer; the loop hashes the body via the gateway helper and splices
``fabricate_payload(...)`` under that key. Next round the member hits, the
synthesis body renders (embedding "alpha answer 1"), and the same walk serves it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_REPORT_SCHEMA = "screamingface.report.v1"
_INPUT_SCHEMA = "screamingface.candidate-input.v1"

#: Same fixed timestamp generate_synthetic.py stamps — fabricated payloads carry no
#: wall-clock traces, so identical content is identical bytes forever.
_PAYLOAD_CREATED = 1787184000

_GRADEABLE = "scored"


@dataclass(frozen=True, slots=True)
class Check:
    """One rubric criterion of one Case, with the judge's recorded raw reply."""

    criterion_id: str
    label: str
    raw_output: str


@dataclass(frozen=True, slots=True)
class CaseTape:
    """Everything the report recorded for one Case.

    ``question`` is the Case's identifying text (the last user turn of its input
    conversation) — the string a rendered member request must embed. A failed Case
    keeps its status but holds NO payloads: ``member_outputs`` is empty and
    ``synthesis_output`` is ``None``.
    """

    case_id: str
    status: str
    question: str
    member_outputs: Mapping[str, tuple[str, str]]  # route -> (content, finish_reason)
    synthesis_output: tuple[str, str] | None
    checks: tuple[Check, ...]


@dataclass(frozen=True, slots=True)
class ReportTape:
    """The parsed report: the fusion lineup plus every servable recorded text."""

    board: str
    revision: str
    recipe: str
    member_routes: tuple[str, ...]
    synthesizer_route: str
    judge_route: str
    rendered_url4: str
    expected_score: float | None
    expected_coverage: float
    cases: tuple[CaseTape, ...]

    @property
    def cases_by_id(self) -> dict[str, CaseTape]:
        return {case.case_id: case for case in self.cases}

    @property
    def case_statuses(self) -> dict[str, str]:
        return {case.case_id: case.status for case in self.cases}


@dataclass(frozen=True, slots=True)
class BodyMatch:
    """One captured body successfully paired with its recorded text."""

    role: str  # "member" | "synthesis" | "judge"
    case_id: str
    model: str
    content: str
    finish_reason: str


@dataclass(frozen=True, slots=True)
class BodySkip:
    """A body the tape DELIBERATELY does not serve (the real run recorded nothing).

    The loop leaves the hole in place so the replay fails the case exactly like the
    paid run did — a skip is bookkeeping, never an error.
    """

    case_id: str
    reason: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _case_question(raw_input: str) -> str:
    """The Case's identifying text: the LAST user turn of its input conversation.

    The report stores the input as a ``screamingface.candidate-input.v1`` JSON
    envelope; anything else is used verbatim — matching stays containment-based
    either way, and an unmatchable text refuses later rather than guessing here.
    """
    try:
        envelope = json.loads(raw_input)
    except (TypeError, ValueError):
        envelope = None
    if isinstance(envelope, dict) and envelope.get("schema") == _INPUT_SCHEMA:
        for message in reversed(envelope.get("messages", [])):
            if message.get("role") == "user":
                return str(message.get("content", ""))
    return raw_input


def _refuse_duplicates(texts: Sequence[str], what: str) -> None:
    seen: set[str] = set()
    for text in texts:
        if text in seen:
            raise ValueError(
                f"duplicate {what} across cases: {text[:80]!r}… — bodies could "
                f"not be told apart; refusing to build a guessing tape"
            )
        seen.add(text)


def _parse_checks(case: Mapping[str, Any], case_id: str) -> tuple[Check, ...]:
    checks: list[Check] = []
    for check in case["grade"]["checks"]:
        evidence = check.get("evidence") or []
        _require(
            len(evidence) == 1,
            f"case {case_id} check {check.get('id')!r} carries {len(evidence)} evidence "
            f"entries — the tape can only serve exactly one recorded judge reply",
        )
        _require(
            bool(evidence[0].get("valid")),
            f"case {case_id} check {check.get('id')!r} kept an invalid judge reply — "
            f"refusing to seed a reply the run itself rejected",
        )
        checks.append(
            Check(
                criterion_id=str(check["id"]),
                label=str(check["label"]),
                raw_output=str(evidence[0]["raw_output"]),
            )
        )
    return tuple(checks)


def _judge_route(cases: Sequence[Mapping[str, Any]]) -> str:
    routes = {
        str(evidence["producer"]["id"])
        for case in cases
        if case["status"] == _GRADEABLE
        for check in case["grade"]["checks"]
        for evidence in check.get("evidence") or []
    }
    _require(
        len(routes) == 1,
        f"the report's judge replies span {len(routes)} models: {sorted(routes)} — "
        f"expected exactly one judge route",
    )
    return routes.pop()


def _parse_case(
    case: Mapping[str, Any],
    op_to_route: Mapping[str, str],
    synthesis_op: str,
) -> CaseTape:
    case_id = str(case["case_id"])
    status = str(case["status"])
    question = _case_question(case["input"])
    if status != _GRADEABLE:
        # WHY empty payloads: the real report omits `operations` entirely on failed
        # cases — nothing was recorded, so the replay must keep failing them.
        return CaseTape(case_id, status, question, {}, None, ())
    invalid = case["grade"].get("metrics", {}).get("invalid_replies", 0)
    _require(
        invalid == 0,
        f"case {case_id} has invalid_replies={invalid}: the run retried its judge and "
        f"the report keeps only the final reply — a tape built from it cannot serve "
        f"the retry sequence; bless from a real dump instead",
    )
    member_outputs: dict[str, tuple[str, str]] = {}
    synthesis: tuple[str, str] | None = None
    for operation in case.get("operations") or []:
        op_id = str(operation["operation_id"])
        recorded = (str(operation["output"]), str(operation["finish_reason"]))
        if op_id == synthesis_op:
            synthesis = recorded
        else:
            member_outputs[op_to_route[op_id]] = recorded
    _require(synthesis is not None, f"scored case {case_id} has no synthesis output")
    return CaseTape(
        case_id, status, question, member_outputs, synthesis, _parse_checks(case, case_id)
    )


def parse_report(report: Mapping[str, Any]) -> ReportTape:
    """One saved report → the tape; every ambiguity refuses here, never mid-loop."""
    _require(
        report.get("schema") == _REPORT_SCHEMA,
        f"unknown report schema {report.get('schema')!r} (expected {_REPORT_SCHEMA})",
    )
    candidates = report["candidates"]
    _require(
        len(candidates) == 1,
        f"the report holds {len(candidates)} candidates — the tape needs exactly one candidate",
    )
    candidate = candidates[0]
    _require(
        candidate["kind"] == "fusion",
        f"candidate kind is {candidate['kind']!r} — only a fusion run needs a synthesized "
        f"tape (single-model boards bless from the --dump/--answers path)",
    )

    members = candidate["members"]
    op_to_route: dict[str, str] = {}
    member_routes: list[str] = []
    for member in members:
        routes = member["models"]
        _require(
            len(routes) == 1,
            f"member {member['operation_id']} spans {len(routes)} models — unsupported",
        )
        op_to_route[str(member["operation_id"])] = str(routes[0])
        member_routes.append(str(routes[0]))
    _require(
        len(set(member_routes)) == len(member_routes),
        "member routes are not distinct — a captured body could not name its member",
    )

    synthesis_ops = [op["id"] for op in candidate["operations"] if op["kind"] == "synthesis"]
    _require(
        len(synthesis_ops) == 1,
        f"expected exactly one synthesis operation, found {len(synthesis_ops)}",
    )
    leftover = [route for route in candidate["models"] if route not in member_routes]
    _require(
        len(leftover) == 1,
        f"candidate models minus members leaves {leftover!r} — expected exactly the synthesizer",
    )
    synthesizer_route = leftover[0]

    cases = tuple(_parse_case(case, op_to_route, synthesis_ops[0]) for case in candidate["cases"])
    judge_route = _judge_route(candidate["cases"])
    _require(
        judge_route not in {*member_routes, synthesizer_route},
        f"judge route {judge_route!r} collides with the candidate lineup — bodies could "
        f"not be classified by model route",
    )
    # Uniqueness guards — each one backs a containment match in match_body.
    _refuse_duplicates([case.question for case in cases], "case question")
    # WHY sets, not individual texts: member answers legitimately repeat across
    # cases (refusal strings — 9 cases shared one in the Aug-19 report). Synthesis
    # matching requires ALL of a case's member outputs to be embedded, so only two
    # cases sharing their WHOLE member-output set are indistinguishable.
    member_sets = [
        frozenset(content for content, _ in case.member_outputs.values())
        for case in cases
        if case.member_outputs
    ]
    _require(
        len(set(member_sets)) == len(member_sets),
        "two cases share their whole member-answer set — a synthesis body could not "
        "be told apart; refusing to build a guessing tape",
    )
    _refuse_duplicates(
        [case.synthesis_output[0] for case in cases if case.synthesis_output is not None],
        "synthesized answer",
    )

    return ReportTape(
        board=str(report["benchmark"]["id"]),
        revision=str(report["benchmark"]["revision"]),
        recipe=str(candidate["name"]),
        member_routes=tuple(member_routes),
        synthesizer_route=synthesizer_route,
        judge_route=judge_route,
        rendered_url4=str(candidate["url4"]),
        expected_score=candidate["score"],
        expected_coverage=float(candidate["coverage"]),
        cases=cases,
    )


def body_strings(value: Any) -> Iterator[str]:
    """Every string anywhere in a request body, unescaped — the containment haystack.

    Matching on extracted strings (not on the serialized JSON) sidesteps escaping:
    a recorded answer with newlines is found verbatim inside a message content
    string, where the same text inside ``json.dumps(body)`` would be ``\\n``-mangled.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from body_strings(item)
    elif isinstance(value, Sequence):
        for item in value:
            yield from body_strings(item)


def _contains(strings: Sequence[str], needle: str) -> bool:
    """True when a recorded text is embedded in the body — verbatim OR JSON-escaped.

    WHY the escaped forms: url4 renders a struct ``q=`` by ``json.dumps``-ing the
    whole object into ONE string (``url4.dag.nodes.StructNode``), so upstream
    answers reach downstream prompts spelled ``\\n`` / ``\\"`` / ``\\uXXXX``. Both
    ``ensure_ascii`` spellings are tried because the renderer's choice is not this
    module's to know.
    """
    spellings = [needle]
    for ensure_ascii in (True, False):
        escaped = json.dumps(needle, ensure_ascii=ensure_ascii)[1:-1]
        if escaped != needle:
            spellings.append(escaped)
    return any(spelling in text for text in strings for spelling in spellings)


def _single_case(tape: ReportTape, matched: list[CaseTape], body_head: str, how: str) -> CaseTape:
    if len(matched) == 1:
        return matched[0]
    if matched:
        raise ValueError(
            f"ambiguous case match ({len(matched)} cases by {how}) for body: {body_head}…"
        )
    raise ValueError(f"no case matches this body by {how}: {body_head}…")


def _match_member(
    tape: ReportTape, model: str, strings: list[str], head: str
) -> BodyMatch | BodySkip:
    matched = [case for case in tape.cases if case.question and _contains(strings, case.question)]
    case = _single_case(tape, matched, head, "question")
    if case.status != _GRADEABLE:
        return BodySkip(
            case_id=case.case_id,
            reason=f"case {case.case_id} is {case.status!r} (failed) in the report — "
            f"nothing was recorded; the replay must keep failing it",
        )
    recorded = case.member_outputs.get(model)
    if recorded is None:
        raise ValueError(f"case {case.case_id} has no recorded answer for member {model!r}")
    content, finish_reason = recorded
    return BodyMatch("member", case.case_id, model, content, finish_reason)


def _match_synthesis(tape: ReportTape, model: str, strings: list[str], head: str) -> BodyMatch:
    # WHY member outputs, not the question: the synthesis prompt is built FROM
    # the member answers; they are the text guaranteed to be embedded.
    matched = [
        case
        for case in tape.cases
        if case.member_outputs
        and all(_contains(strings, content) for content, _ in case.member_outputs.values())
    ]
    case = _single_case(tape, matched, head, "member outputs")
    assert case.synthesis_output is not None  # scored cases always carry one
    content, finish_reason = case.synthesis_output
    return BodyMatch("synthesis", case.case_id, model, content, finish_reason)


def _match_judge(tape: ReportTape, model: str, strings: list[str], head: str) -> BodyMatch:
    # INVARIANT: case FIRST (by the synthesized answer the judge is grading),
    # criterion second — rubric labels repeat across cases, so a label-first
    # match would attach verdicts to the wrong case.
    matched = [
        case
        for case in tape.cases
        if case.synthesis_output is not None and _contains(strings, case.synthesis_output[0])
    ]
    case = _single_case(tape, matched, head, "synthesized answer")
    hits = [check for check in case.checks if _contains(strings, check.label)]
    if len(hits) != 1:
        raise ValueError(
            f"case {case.case_id}: {len(hits)} rubric criterion labels match this "
            f"judge body (need exactly 1): {head}…"
        )
    return BodyMatch("judge", case.case_id, model, hits[0].raw_output, "stop")


def match_body(tape: ReportTape, body: Mapping[str, Any]) -> BodyMatch | BodySkip:
    """Pair one captured request body with its recorded text — or refuse loudly.

    Classification is by model route; the Case is pinned by containment of the
    report's texts inside the body's strings (see the module docstring for which
    text identifies which role). Only a failed Case's body returns a ``BodySkip``.
    """
    model = str(body.get("model"))
    strings = list(body_strings(body))
    head = json.dumps(body)[:120]

    if model in tape.member_routes:
        return _match_member(tape, model, strings, head)
    if model == tape.synthesizer_route:
        return _match_synthesis(tape, model, strings, head)
    if model == tape.judge_route:
        return _match_judge(tape, model, strings, head)
    raise ValueError(
        f"unknown model route {model!r} — not a member, the synthesizer, or the judge: {head}…"
    )


def fabricate_payload(*, model: str, content: str, finish_reason: str) -> str:
    """A recorded text → the deterministic chat-completion envelope a cache row stores.

    Same shape ``generate_synthetic.py`` fabricates (the engine reads
    ``choices[0].message.content`` + ``finish_reason``); the id is derived from the
    content so identical inputs are identical bytes across re-blesses.
    """
    digest = hashlib.sha256(f"{model}\n{finish_reason}\n{content}".encode()).hexdigest()
    return json.dumps(
        {
            "id": f"report-tape-{digest[:16]}",
            "object": "chat.completion",
            "created": _PAYLOAD_CREATED,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
        sort_keys=True,
    )


__all__ = [
    "BodyMatch",
    "BodySkip",
    "CaseTape",
    "Check",
    "ReportTape",
    "body_strings",
    "fabricate_payload",
    "match_body",
    "parse_report",
]
