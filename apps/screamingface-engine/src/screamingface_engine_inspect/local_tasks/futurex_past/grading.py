# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages (through judge_redraw),
# absent in the default (extra-less) install the typecheck gate runs against; it is loaded only
# behind `inspect_available()`, like every other module in this package.
"""FutureX-Past's marking rules: reading the reply, levels 1-2 by rule, levels 3-4 by the judge.

FEATURE: FutureX-Past scored the way the FutureX authors score it today. Their scorer is
github.com/Futurex-ai/Futurex-Eval at 2626f7a297cd87c73a45408e23af8d838f5b60e5 (below:
"Futurex-Eval"). It publishes no licence, so nothing here is copied: the rules are re-written
from it and the judge prompts are worded by us to ask the same questions (spec
docs/spec/2026-11-16-futurex-past-local-task.md §4). Each rule's ``WHY:`` names the file and
function it follows.

Think of it as a marker with two piles. Levels 1-2 are option questions: the marker reads the
letters in the box and compares them with the key, no judge. Levels 3-4 are open questions: the
marker first asks the judge what KIND of answer the question wants (the router), then marks a
number by its distance from the truth, a name or a list by asking the judge whether they match.

Execution order for one level-3/4 reply (``grade_level_34``):

    1. read the box (``last_boxed`` → ``unwrap_text`` → ``answer_tokens``); no answer → 0, no call;
    2. route: ``legacy_type_a`` (labels), ``legacy_type_b`` (number, text, ranking) or
       ``unordered_set``; a Yes/No prompt with a non-boolean key skips the router; an
       unreadable route, or a router call that fails, falls back to ``legacy_type_b``;
    3. score by the route; every judge question goes through the injected ``Ask``, which in
       production is ``judge_until_parsed`` (redraws, then ``judge_reply_invalid``).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol


class Ask(Protocol):
    """One judge question: the prompt, the reply reader, and a purpose naming it in errors."""

    def __call__[V](
        self, prompt: str, parse: Callable[[str], V | None], purpose: str
    ) -> Awaitable[V]: ...


@dataclass(frozen=True, slots=True)
class Graded:
    """One level-3/4 Case: its score in [0, 1], the route that scored it, whether the route is
    the level default because the router was skipped, unreadable or failed, and why."""

    score: float
    route: str
    route_fallback: bool = False
    #: ``contract_conflict``, or the type name of the error the router call raised (never its
    #: message, which may hold the question); None when the router answered.
    route_fallback_why: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedNumber:
    """The judge's reading of a number out of prose; ``value`` None means "no number in it"."""

    value: float | None


# ── reading the reply (the study's futurex_parse) ───────────────────────────────────────────

# WHY one level of nesting: ``\boxed{\text{a, b}}`` is common on free-text levels; a pattern
# without it read such a reply as boxless (the study's 2026-08-08 defect).
_BOXED: Final[re.Pattern[str]] = re.compile(r"\\boxed\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
_TEXT_OPENING: Final[re.Pattern[str]] = re.compile(r"\\text\s*\{")


def last_boxed(reply: str) -> str | None:
    """The stripped content of the LAST ``\\boxed{}``, or None when the reply has none.

    WHY the last: the prompt says the reply must END with the box, and a model that reasons
    first may show a worked box earlier.
    """

    boxes: list[str] = _BOXED.findall(reply or "")
    return boxes[-1].strip() if boxes else None


def unwrap_text(box: str | None) -> str | None:
    """The box without a ``\\text{...}`` wrapper that encloses ALL of it, as Futurex-Eval's
    extractor hands its scorer the content inside the braces; any other text unchanged.

    INVARIANT (fidelity audit U7): the wrapper's own opening brace must close at the very end.
    ``\\text{A}, \\text{B}`` is two wrapped options, not one wrapper, so it stays as it is and
    ``reply_tokens`` unwraps each option instead.
    """

    opening: re.Match[str] | None = _TEXT_OPENING.match(box) if box is not None else None
    if box is None or opening is None:
        return box
    closing: int | None = _closing_brace(box, opening.end())
    return box[opening.end() : closing].strip() if closing == len(box) - 1 else box


def _closing_brace(text: str, start: int) -> int | None:
    """The index of the brace that closes the one opened just before ``start``, or None."""

    depth: int = 1
    for index in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return index
    return None


def answer_tokens(box: str | None) -> list[str]:
    """The box split on commas into stripped, non-empty tokens (the study's ``build_data``
    split; Futurex-Eval's ``extract_answers`` for a non-number)."""

    return [token.strip() for token in (box or "").split(",") if token.strip()]


def reply_tokens(box: str | None) -> list[str]:
    """The answer items of a ``futurex_past`` reply: a whole-box wrapper removed, the rest split
    on commas, and a wrapper around each single item removed (``\\text{A}, \\text{B}``)."""

    return [unwrap_text(token) or token for token in answer_tokens(unwrap_text(box))]


# ── levels 1-2: labels (Futurex-Eval eval.py, estimate_score_level_1_2) ──────────────────────

_LABEL_WRAPPER: Final[re.Pattern[str]] = re.compile(r"\\(?:boxed|text)\{(.*)\}", re.DOTALL)


def normalize_label(item: object) -> str:
    """WHY: Futurex-Eval's ``_normalize_type_a_label``: strip spaces and quotes, drop a whole
    ``\\boxed{}``/``\\text{}`` wrapper, upper-case a lone letter, spell yes/no as Yes/No."""

    text: str = str(item).strip().strip("\"'")
    wrapped: re.Match[str] | None = _LABEL_WRAPPER.fullmatch(text)
    if wrapped:
        text = wrapped.group(1).strip().strip("\"'")
    if re.fullmatch(r"[A-Za-z]", text):
        text = text.upper()
    elif re.fullmatch(r"yes|no", text, flags=re.IGNORECASE):
        text = "Yes" if text.lower() == "yes" else "No"
    return text


def label_score(gold: Sequence[object], predicted: Sequence[object]) -> float:
    """INVARIANT (Futurex-Eval ``estimate_score_level_1_2``): one key → 1.0 only when the
    normalised prediction list equals it; several keys → set F1; nothing on either side → 0."""

    truth: list[str] = [normalize_label(item) for item in gold if str(item).strip()]
    guess: list[str] = [normalize_label(item) for item in predicted if str(item).strip()]
    if len(truth) == 1:
        return 1.0 if truth == guess else 0.0
    overlap: int = len(set(truth) & set(guess))
    if overlap == 0:
        return 0.0
    precision: float = overlap / len(set(guess))
    recall: float = overlap / len(set(truth))
    return 2 * precision * recall / (precision + recall)


# ── numbers (Futurex-Eval utils.py, to_float / is_number) ───────────────────────────────────


#: A whole plain number: an optional sign and dollar, digits with optional thousands commas, an
#: optional decimal part and exponent, an optional percent sign. Nothing else may surround it.
_PLAIN_NUMBER: Final[re.Pattern[str]] = re.compile(
    r"[-+]?\$?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?%?"
)


def to_float(text: str) -> float | None:
    """The number a bare-number reply states, or None so the judge reads it.

    WHY whole-match, not upstream's ``utils.to_float`` (first numeric run): upstream reaches
    ``to_float`` only after its LLM extractor has rewritten the answer as a number. This rule
    stands in for that extractor, so it accepts only a reply that IS a plain number (``$115``,
    ``115%``, ``6,923.23``, ``1e3``); an expression such as ``1/2`` or ``10^3`` would otherwise be
    half-read as 1 or 10 with no judge call (Codex review).
    """

    stripped: str = text.strip()
    try:
        value: float | None = (
            float(re.sub(r"[$,%]", "", stripped)) if _PLAIN_NUMBER.fullmatch(stripped) else None
        )
    except ValueError:  # INVARIANT: never raise for a reply; the judge reads what this cannot
        value = None
    return value if value is not None and math.isfinite(value) else None


def normalize_gold(gold: Sequence[Any]) -> list[Any]:
    """WHY: Futurex-Eval's ``_normalize_gt``: unwrap ``\\boxed{}``/``\\text{}`` in each string
    item; a lone item that is a number (or a string holding one) becomes a float."""

    items: list[Any] = [_unwrap_gold(item) if isinstance(item, str) else item for item in gold]
    if len(items) == 1:
        items[0] = _as_number(items[0])
    return items


def _unwrap_gold(text: str) -> str:
    # WHY non-greedy and unanchored: Futurex-Eval's ``extract_boxed_for_type_b`` pattern.
    found: re.Match[str] | None = re.search(r"(?:oxed|ext)\{(.*?)\}", text, flags=re.DOTALL)
    return found.group(1).strip() if found else text


def _as_number(item: Any) -> Any:
    """A lone key as a float when it is an int or a numeric string; anything else unchanged."""

    if isinstance(item, int) and not isinstance(item, bool):
        item = str(item)
    if not isinstance(item, str):
        return item
    try:
        return float(item)
    except ValueError:
        return item


def number_score(predicted: float, gold: float) -> float:
    """INVARIANT: max(0, 1 − ((ŷ − y)/σ)²) with σ = 5% of the key, 0.01 for a zero key.

    WHY 5%: Futurex-Eval's ``estimate_score_level_3_4`` sets σ so for every number key and
    ignores the dataset's ``std`` column; the paper's "7-day std" is an upstream note (spec §4.3).
    """

    sigma: float = 0.01 if gold == 0 else 0.05 * gold
    distance: float = abs((predicted - gold) / sigma)
    # WHY the guard: a prediction one sigma away or more scores 0 anyway, and squaring an extreme
    # one (1e200) overflows; a non-finite one (inf, nan) is no prediction (Codex review).
    return 1.0 - distance**2 if math.isfinite(distance) and distance < 1.0 else 0.0


# ── the judge's questions (our wording, Futurex-Eval's decisions) ───────────────────────────

ROUTES: Final[frozenset[str]] = frozenset({"legacy_type_a", "legacy_type_b", "unordered_set"})
DEFAULT_ROUTE: Final[str] = "legacy_type_b"


def _canonical(gold: Sequence[Any]) -> str:
    return json.dumps(list(gold), ensure_ascii=False, sort_keys=True, default=str)


def router_prompt(question: str, gold: Sequence[Any]) -> str:
    """The router's question (Futurex-Eval ``metric_router._router_prompt``'s decision)."""

    return (
        "You choose how one resolved forecasting question is scored.\n\n"
        "Choose exactly one metric:\n"
        "- legacy_type_a: the answer is one or more fixed option labels.\n"
        "- legacy_type_b: the answer is a number, a text, an ordered list, or anything else.\n"
        "- unordered_set: the question asks for a collection whose order does not matter.\n\n"
        "Choose unordered_set only when the question asks for no rank, sequence, position or "
        "ordered output. Do not reinterpret the ground truth.\n\n"
        f"QUESTION:\n{question}\n\nGROUND_TRUTH:\n{_canonical(gold)}\n\n"
        f"DEFAULT_METRIC:\n{DEFAULT_ROUTE}\n\n"
        'Reply with JSON only: {"metric": "legacy_type_a|legacy_type_b|unordered_set", '
        '"reason": "<a short reason>"}'
    )


def rank_prompt(question: str, predicted: Sequence[Any], answer: Sequence[Any]) -> str:
    """Is the prediction the answer, item by item in order? (Futurex-Eval ``judge_rank``)."""

    return (
        "You judge whether a predicted list is exactly the true list.\n\n"
        f"QUESTION: {question}\n\nPREDICTION: {list(predicted)}\n\nANSWER: {list(answer)}\n\n"
        "Two items match when they name the same thing, whatever the wording, abbreviation or "
        "language. Answer \\boxed{Yes} only when both lists have the same length and the i-th "
        "item of PREDICTION matches the i-th item of ANSWER at every position; before "
        "answering \\boxed{Yes}, write the comparison for every position. The same items in "
        "another order, or a list of another length, is \\boxed{No}. Answer only \\boxed{Yes} "
        "or \\boxed{No}."
    )


def rank_overlap_prompt(question: str, predicted: Sequence[Any], answer: Sequence[Any]) -> str:
    """How many items overlap, in any order? (Futurex-Eval ``judge_rank_detail``)."""

    return (
        "You count how many items a predicted list shares with the true list.\n\n"
        f"QUESTION: {question}\n\nPREDICTION: {list(predicted)}\n\nANSWER: {list(answer)}\n\n"
        "Two items match when their content is the same; ignore differences of language. "
        "Count the shared items even when the order differs, and answer with that count as "
        "\\boxed{NUMBER}."
    )


def match_prompt(predicted: str, answer: Any) -> str:
    """Do two answers say the same thing? (Futurex-Eval ``judge_str_match``)."""

    return (
        "Decide whether the prediction matches the true answer. Compare the content only and "
        'ignore the language: "New York" and "NYC" match. Answer only \\boxed{Yes} or '
        f"\\boxed{{No}}.\n\nMODEL_PREDICTION: {predicted}\n\nREAL_ANSWER: {answer}"
    )


def number_prompt(text: str) -> str:
    """Which number does this text state? (Futurex-Eval ``extract_num_from_string``)."""

    return (
        "Extract the number from the text below and write it as \\boxed{NUMBER}. If the text "
        "holds several numbers, write their average. If it holds no number, write "
        f"\\boxed{{None}}.\n\nTEXT: {text}"
    )


def set_overlap_prompt(question: str, predicted: Sequence[str], answer: Sequence[str]) -> str:
    """How many one-to-one matches between two sets? (Futurex-Eval
    ``judge_unordered_set_overall``)."""

    return (
        "You score an answer that is an unordered set. Match entities by meaning, allowing "
        "aliases, abbreviations and other languages. Order does not matter, and each entity "
        "counts at most once. Reply with only \\boxed{N}, where N is the number of one-to-one "
        f"matches between the two sets.\n\nQUESTION:\n{question}\n\n"
        f"PREDICTED_SET:\n{list(predicted)}\n\nTRUE_SET:\n{list(answer)}"
    )


# ── reading the judge ───────────────────────────────────────────────────────────────────────


def parse_route(reply: str) -> str | None:
    """The route in the judge's JSON, or None, read as upstream's ``_parse_route`` reads it.

    WHY so strict: upstream strips a code fence only when the reply opens with one, and parses
    the WHOLE reply when it opens with ``{``, so a JSON object followed by prose is unreadable
    there and the question falls back to ``legacy_type_b`` (fidelity audit U4).
    """

    text: str = reply.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    if not text.startswith("{"):
        found: re.Match[str] | None = re.search(r"\{.*\}", text, flags=re.DOTALL)
        text = found.group(0) if found else text
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    metric: object = payload.get("metric") if isinstance(payload, dict) else None
    return metric if isinstance(metric, str) and metric in ROUTES else None


def parse_match(reply: str) -> bool:
    """WHY any "yes": Futurex-Eval reads ``'yes' in ans.lower()``, so every reply decides and a
    match is never redrawn (a blank reply is refused before this, by the provider)."""

    return "yes" in reply.lower()


def parse_count(reply: str) -> int | None:
    """The first ``\\boxed{N}`` count, as Futurex-Eval's ``re.search``; None to redraw."""

    found: re.Match[str] | None = re.search(r"\\boxed\{(\d+)\}", reply)
    return int(found.group(1)) if found else None


def parse_number(reply: str) -> ExtractedNumber | None:
    """The judge's boxed number; ``None`` in the box or a box that is not a number means "no
    number" (scores 0, as upstream); no box at all is unreadable and redrawn."""

    found: re.Match[str] | None = re.search(r"\\boxed\{([^}]+)\}", reply)
    if found is None:
        return None
    try:
        return ExtractedNumber(float(found.group(1)))
    except ValueError:
        return ExtractedNumber(None)


# ── levels 3-4 ──────────────────────────────────────────────────────────────────────────────

_CHOICE_TOKEN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z\[\\\]\^_`]{1,2}")
_BOOLEAN_DEMAND: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\\boxed\{yes\}.*?\\boxed\{no\}", re.IGNORECASE | re.DOTALL),
    re.compile(r"\byes\s*/\s*no\b", re.IGNORECASE),
)


def contract_conflict(question: str, gold: Sequence[Any]) -> bool:
    """WHY: Futurex-Eval's ``detect_contract_conflict``: a prompt that demands Yes/No with a key
    that is not Yes/No cannot be routed sensibly, so the level default scores it."""

    demands_boolean: bool = any(pattern.search(question) for pattern in _BOOLEAN_DEMAND)
    tokens: set[str] = {str(item).strip().casefold() for item in gold}
    return demands_boolean and not tokens <= {"yes", "no"}


async def grade_level_34(ask: Ask, question: str, gold: Sequence[Any], box: str | None) -> Graded:
    """Score one level-3/4 reply the Futurex-Eval way (``estimate_routed_scores``)."""

    text: str | None = unwrap_text(box)
    tokens: list[str] = reply_tokens(box)
    if not tokens or text is None:
        # WHY no call: a missing prediction scores 0 in the official roll-up.
        return Graded(score=0.0, route="no_answer")
    route, fallback_why = await _route(ask, question, gold)
    if route == "legacy_type_a":
        score: float = label_score(gold, tokens)
    elif route == "unordered_set":
        score = await _unordered(ask, question, tokens, gold)
    else:
        score = await _type_b(ask, question, normalize_gold(gold), text, tokens)
    return Graded(
        score=score,
        route=route,
        route_fallback=fallback_why is not None,
        route_fallback_why=fallback_why,
    )


async def _route(ask: Ask, question: str, gold: Sequence[Any]) -> tuple[str, str | None]:
    """The route, and why it is the fallback or None (``metric_router.route_metric``)."""

    if contract_conflict(question, gold):
        return DEFAULT_ROUTE, "contract_conflict"
    try:
        return await ask(router_prompt(question, gold), parse_route, "route"), None
    except Exception as exc:  # noqa: BLE001
        # WHY broad: Futurex-Eval's ``route_metric`` wraps the router in ``except Exception``
        # and scores the question by the level default, whether the reply stayed unreadable
        # (``JudgeReplyUnparseable`` here) or the call itself failed (a 429, a 5xx, a dropped
        # connection). Failing the Case instead would drop it from the tier-weighted headline
        # under ``coverage_declare``. The Score keeps the error's type as evidence; a judge
        # that is truly down fails the Case at the next question, which is not caught.
        return DEFAULT_ROUTE, type(exc).__name__


async def _type_b(ask: Ask, question: str, gold: list[Any], text: str, tokens: list[str]) -> float:
    """``judge_level_34_score``: a number by distance, a text by match, a list as a ranking."""

    if len(gold) != 1:
        return await _ranking(ask, question, tokens, gold)
    key: Any = gold[0]
    if isinstance(key, float):
        return await _number(ask, text, key)
    # WHY tokens[0]: upstream judges ``model_prediction[0]``, the first comma piece.
    matched: bool = await ask(match_prompt(tokens[0], key), parse_match, "match")
    return 1.0 if matched else 0.0


#: A comma that separates answer pieces: any comma EXCEPT one inside a number, between a digit
#: and exactly three more digits. WHY (first review on PR 1897): split on every comma,
#: ``12,500 points`` gave the judge ``12`` and a right answer scored 0 against the key 12500;
#: upstream's LLM extractor reads such a reply whole, as the number it is.
#: Worked example: ``12,500 points`` → one piece; ``about 249.41, or 498.82`` → ``about 249.41``;
#: ``3,000,000 units`` → one piece; ``1,2,3`` → ``1``.
_THOUSANDS_SAFE_COMMA: Final[re.Pattern[str]] = re.compile(r"(?<!\d),|,(?!\d{3}(?!\d))")


async def _number(ask: Ask, text: str, key: float) -> float:
    # WHY {,}: LaTeX's thousands separator; read raw, ``1{,}234`` would be the number 1.
    plain: str = text.replace("{,}", ",")
    predicted: float | None = to_float(plain)
    if predicted is None:
        # AIDEV-NOTE: upstream asks an LLM whether the WHOLE reply is a number; a bare number is
        # read by rule here (``to_float``) and only prose goes to the judge (spec §4.2) -- its
        # first comma piece, as upstream judges ``model_prediction[0]`` (fidelity audit U2).
        first: str = _THOUSANDS_SAFE_COMMA.split(plain)[0].strip()
        extracted: ExtractedNumber = await ask(number_prompt(first), parse_number, "number")
        predicted = extracted.value
    return 0.0 if predicted is None else number_score(predicted, key)


def _is_choice_list(items: Sequence[Any]) -> bool:
    return bool(items) and all(
        isinstance(item, str) and _CHOICE_TOKEN.fullmatch(item.strip()) for item in items
    )


async def _ranking(ask: Ask, question: str, tokens: list[str], gold: list[Any]) -> float:
    """``judge_rank_overall``: same option letters in any order → 1; the judge's position-by-
    position Yes → 1; else 0.8 × overlap / k."""

    if _is_choice_list(gold) and _is_choice_list(tokens):
        # WHY reassign: upstream sorts both letter lists and asks the rank judge about the
        # sorted ones when they differ (fidelity audit U3).
        gold = sorted(str(item).strip() for item in gold)
        tokens = sorted(item.strip() for item in tokens)
        if gold == tokens:
            return 1.0
    if await ask(rank_prompt(question, tokens, gold), parse_match, "rank"):
        return 1.0
    count: int = await ask(rank_overlap_prompt(question, tokens, gold), parse_count, "rank_overlap")
    # NAMED DEVIATION: capped at k so a Case stays in [0, 1]; upstream does not cap.
    return min(count, len(gold)) / len(gold) * 0.8


async def _unordered(ask: Ask, question: str, tokens: list[str], gold: Sequence[Any]) -> float:
    """``judge_unordered_set_overall``: the same set, case-folded → 1; else the judge counts
    one-to-one matches m, and 1 only when m = k = |prediction|, else 0.8 × m / k."""

    predicted: list[str] = list(dict.fromkeys(str(item).strip() for item in tokens))
    answer: list[str] = list(dict.fromkeys(str(item).strip() for item in gold))
    if {item.casefold() for item in predicted} == {item.casefold() for item in answer}:
        return 1.0
    count: int = await ask(
        set_overlap_prompt(question, predicted, answer), parse_count, "set_overlap"
    )
    matched: int = min(count, len(answer), len(predicted))
    full: bool = matched == len(answer) == len(predicted)
    return 1.0 if full else matched / len(answer) * 0.8
