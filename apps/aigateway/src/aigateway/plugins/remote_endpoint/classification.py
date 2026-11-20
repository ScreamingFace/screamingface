"""The `hf-text-classification-v1` request a classifier receives, and the one decoder of its answer.

# FEATURE: hosted BYOM Unit 3 — the caller's text goes upstream as `{"inputs": <input>}` with no
# template and no truncation; the labels and scores come back unchanged.
# INVARIANT: readiness and dispatch both build the request with `classification_request` and read
# the answer with `decode_scores`, so a key is published only after the endpoint answered exactly
# what a later classification will be held to.
# INVARIANT: `flat` is a list of `{label, score}`; `single-batch` is a list holding exactly one such
# list. Nothing else is flattened, picked, sorted or dropped, so upstream order and ties are kept.
# WHY the sum is not checked: a multi-label classifier scores each label on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from aigateway.core.plugin_base import CLASSIFICATION_RESULT_CONTRACT

from .completion import strict_json
from .definitions import ChoiceTarget, ClassifierTarget
from .limits import ClassifierLimits
from .systemone import choice_request, decode_choice

type ScoresDecoder = Callable[[str | None, bytes], list[dict[str, Any]] | None]


def classification_request(text: str) -> dict[str, Any]:
    return {"inputs": text}


def classifier_exchange(
    target: ClassifierTarget, value: Any
) -> tuple[dict[str, Any], ScoresDecoder]:
    """The upstream body of ``value`` and the decoder of its answer, by the target's contract.

    # INVARIANT: dispatch and readiness both call this, so a probe is held to the same codec a
    # classification is. ``value`` already passed the route's contract check for this target.
    """
    if isinstance(target, ChoiceTarget):
        return choice_request(target, value), partial(decode_choice, limits=target.limits)
    decode = partial(decode_scores, envelope=target.response_envelope, limits=target.limits)
    return classification_request(value), decode


def classification_result(model: str, scores: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "object": "classification",
        "model": model,
        "contract": CLASSIFICATION_RESULT_CONTRACT,
        "scores": scores,
    }


def decode_scores(
    content_type: str | None,
    body: bytes,
    *,
    envelope: str,
    limits: ClassifierLimits | None = None,
) -> list[dict[str, Any]] | None:
    """The `{label, score}` list of a 200 response, or None when it breaks the contract.

    # INVARIANT (C7): with declared ``limits``, an answer over `max_labels` labels or with a label
    # over `max_label_bytes` UTF-8 bytes breaks the contract; without them nothing new is checked.
    """
    try:
        value = strict_json(content_type, body)
    except (ValueError, RecursionError):
        return None
    if envelope == "single-batch":
        if not isinstance(value, list) or len(value) != 1:
            return None
        value = value[0]
    if not isinstance(value, list) or not value or not all(map(_is_label_score, value)):
        return None
    labels = {item["label"] for item in value}
    if len(labels) != len(value) or not _within(value, limits):
        return None
    # WHY only these two fields: they are the whole result contract; other upstream fields stay.
    return [{"label": item["label"], "score": item["score"]} for item in value]


def _within(items: list[dict[str, Any]], limits: ClassifierLimits | None) -> bool:
    if limits is None:
        return True
    return len(items) <= limits.max_labels and all(
        len(item["label"].encode("utf-8")) <= limits.max_label_bytes for item in items
    )


def _is_label_score(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    label, score = item.get("label"), item.get("score")
    # WHY the bool test: a JSON `true` decodes to a bool, which isinstance counts as an int.
    # `strict_json` has already refused every non-finite number.
    return (
        isinstance(label, str)
        and bool(label)
        and isinstance(score, int | float)
        and not isinstance(score, bool)
        and 0 <= score <= 1
    )
