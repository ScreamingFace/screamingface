import math
from collections.abc import Sequence
from typing import Protocol, TypedDict

MAX_TOKENS = 512


class Tokenizer(Protocol):
    def __call__(
        self, text: str, /, *, add_special_tokens: bool, truncation: bool
    ) -> Sequence[int]: ...


class Head(Protocol):
    def __call__(self, input_ids: Sequence[int], /) -> Sequence[object]: ...


class Score(TypedDict):
    label: str
    score: float


def _finite_logit(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid logit")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("invalid logit")
    return result


def classify(text: str, tokenizer: Tokenizer, head: Head) -> list[Score] | None:
    # INVARIANT: count the same unpadded encoding that reaches the head, including specials.
    tokens = tokenizer(text, add_special_tokens=True, truncation=False)
    if len(tokens) > MAX_TOKENS:
        return None
    logits = head(tokens)
    if len(logits) != 2:
        raise ValueError("expected two logits")
    a, b = map(_finite_logit, logits)
    peak = max(a, b)
    negative, positive = math.exp(a - peak), math.exp(b - peak)
    total = negative + positive
    return [
        {"label": "NEGATIVE", "score": negative / total},
        {"label": "POSITIVE", "score": positive / total},
    ]
