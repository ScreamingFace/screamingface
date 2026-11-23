"""The `systemone-choice-v1` request a choice classifier receives, and its one answer decoder.

# FEATURE: Router Recipe extension Unit 5.1 (contract C7) — a Router's structured choice goes
# upstream as ONE native SystemOne `choice` question, the common subset Laya and Jev both accept;
# its label probabilities come back as `classification-scores-v1` without recalculation.
# INVARIANT: the criteria follow `options` order and the scores follow the answer's key order.
# Nothing is sorted: `json.dumps` without `sort_keys` keeps insertion order on the wire.
# INVARIANT: the upstream model comes from the target, never from the request; nothing else is
# sent (no Laya runtime control, no Jev assets, no extra header).
# INVARIANT: readiness and dispatch both read the answer with `decode_choice`, so a key is
# published only after the endpoint answered what a later classification is held to.
# INVARIANT: an answer that also reports an error, as a non-null `error` on the envelope or on the
# choice answer, is not an answer, as for a chat completion (`completion.py`): a Router reading its
# probabilities would select, and pay for, a branch on a classifier that said it failed.
# WHY the sum is not checked: Laya rounds each probability to four decimals without renormalizing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aigateway.core.classification_input import CHOICE_INPUT_CONTRACT, is_label

from .completion import strict_json
from .definitions import ChoiceTarget
from .limits import ClassifierLimits

QUESTION = "choice"
_PING = "ping"


def choice_request(target: ChoiceTarget, choice: Mapping[str, Any]) -> dict[str, Any]:
    """The native body of one choice; ``choice`` has passed the input contract's checks."""
    request: dict[str, Any] = {}
    if target.upstream_model is not None:
        request["model"] = target.upstream_model
    request["state"] = {"body": choice["text"]}
    criteria = {option["label"]: option["description"] for option in choice["options"]}
    request["questions"] = {
        QUESTION: {"type": "choice", "instructions": choice["instructions"], "criteria": criteria}
    }
    return request


def probe_choice(limits: ClassifierLimits) -> dict[str, Any]:
    """A fixed synthetic choice within ``limits``, so a readiness probe carries no caller data."""

    def clip(key: str) -> str:
        return _PING[: getattr(limits, key)]

    return {
        "contract": CHOICE_INPUT_CONTRACT,
        "text": clip("max_text_chars"),
        "instructions": clip("max_instructions_chars"),
        "options": [
            {"label": clip("max_label_bytes"), "description": clip("max_description_chars")}
        ],
    }


def decode_choice(
    content_type: str | None, body: bytes, *, limits: ClassifierLimits
) -> list[dict[str, Any]] | None:
    """The `{label, score}` list of a 200 answer, or None when it breaks the contract."""
    try:
        value = strict_json(content_type, body, unique_keys=True)
    except (ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or value.get("error") is not None:
        return None
    if not _usage_kept_the_input(value):
        return None
    answers = value.get("answers")
    if not isinstance(answers, dict) or list(answers) != [QUESTION]:
        return None
    answer = answers[QUESTION]
    if (
        not isinstance(answer, dict)
        or answer.get("type") != "choice"
        or answer.get("error") is not None
    ):
        return None
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or not 1 <= len(probabilities) <= limits.max_labels:
        return None
    if not all(
        is_label(label, max_bytes=limits.max_label_bytes) and _is_probability(score)
        for label, score in probabilities.items()
    ):
        return None
    # WHY a label outside the options passes: coverage and unknown labels are Engine policy.
    return [{"label": label, "score": score} for label, score in probabilities.items()]


def _usage_kept_the_input(value: dict[str, Any]) -> bool:
    """False when `usage` is malformed or reports input the classifier did not read.

    # WHY: a truncated state, a dropped question or colliding option spans (Laya's `options`
    # report) mean the probabilities answer another question than the one asked.
    """
    if "usage" not in value:
        return True
    usage = value["usage"]
    if not isinstance(usage, dict) or "options" in usage:
        return False
    if "truncated" in usage and usage["truncated"] is not False:
        return False
    dropped = usage.get("state_tokens_dropped", 0)
    if type(dropped) is not int or dropped != 0:
        return False
    return usage.get("truncated_questions", []) == []


def _is_probability(value: Any) -> bool:
    # WHY the bool test: a JSON `true` decodes to a bool, which isinstance counts as an int.
    # `strict_json` has already refused every non-finite number.
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 1
