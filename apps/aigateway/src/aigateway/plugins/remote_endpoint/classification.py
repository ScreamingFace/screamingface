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

from typing import Any

from aigateway.core.plugin_base import CLASSIFICATION_RESULT_CONTRACT

from .completion import strict_json


def classification_request(text: str) -> dict[str, Any]:
    return {"inputs": text}


def classification_result(model: str, scores: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "object": "classification",
        "model": model,
        "contract": CLASSIFICATION_RESULT_CONTRACT,
        "scores": scores,
    }


def decode_scores(
    content_type: str | None, body: bytes, *, envelope: str
) -> list[dict[str, Any]] | None:
    """The `{label, score}` list of a 200 response, or None when it breaks the contract."""
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
    if len(labels) != len(value):
        return None
    # WHY only these two fields: they are the whole result contract; other upstream fields stay.
    return [{"label": item["label"], "score": item["score"]} for item in value]


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
