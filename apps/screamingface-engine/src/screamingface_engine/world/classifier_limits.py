"""The strict reader of a classifier row's C7 `input_contracts` and `limits` (Unit 5.2).

FEATURE: Router Recipe extension (contracts C7, C17). The Gateway's `/v1/classifiers` and
`/v1/classifiers/details` rows say which inputs a classifier takes and the bounds it enforces.
The dynamic named-profile preflight and the Engine classifier catalog read them here, once.

INVARIANT: strict and pure. A row that breaks any C7 rule is unusable (`None`): no value is
coerced, repaired, defaulted or inferred from a model ID, and an unknown `limits.contract` is
unusable rather than read as a known one. No HTTP, url4, configuration or recorder import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeGuard

from screamingface_engine.combine.ports import utf8_exceeds

LIMITS_CONTRACT = "classifier-limits-v1"
CHOICE_INPUT_CONTRACT = "classification-choice-input-v1"
MAX_LIMIT = 2147483647

_TEXT_MAXIMA = {"max_labels": MAX_LIMIT, "max_label_bytes": MAX_LIMIT, "max_text_chars": MAX_LIMIT}
# WHY these maxima: the C7 choice ranges are the C16 bounds a Router can send (candidates,
# labels, descriptions, instructions), and the Gateway refuses a choice target outside them.
_CHOICE_MAXIMA = {
    "max_labels": 32,
    "max_label_bytes": 64,
    "max_text_chars": MAX_LIMIT,
    "max_options": 32,
    "max_description_chars": 1024,
    "max_instructions_chars": 4096,
}
_CONTRACT_SETS = (("text",), ("choice",), ("text", "choice"))


@dataclass(frozen=True, slots=True)
class ClassifierCapability:
    """A valid C7 row: its input contracts and its limits, as the Gateway published them."""

    input_contracts: tuple[str, ...]
    limits: dict[str, int | str] | None

    def projection(self) -> dict[str, object]:
        """The row's two C7 fields, as C17 republishes them."""
        return {
            "input_contracts": list(self.input_contracts),
            "limits": None if self.limits is None else dict(self.limits),
        }


@dataclass(frozen=True, slots=True)
class ChoiceRequest:
    """The counts and lengths of one C7 choice input, in option order."""

    labels: tuple[str, ...]
    descriptions: tuple[str, ...]
    instructions: str
    text: str


@dataclass(frozen=True, slots=True)
class TextRequest:
    """A fixed-label classifier's scalar input: its text and the labels it must return."""

    labels: tuple[str, ...]
    text: str


def read_capability(input_contracts: object, limits: object) -> ClassifierCapability | None:
    """The row's capability, or ``None`` when ``input_contracts`` and ``limits`` break C7.

    WHY ``ChoiceLimits`` iff ``choice``: a choice input has three more bounds, and a row that
    omitted them would let an input through that the Gateway itself would refuse.
    """
    contracts = tuple(input_contracts) if isinstance(input_contracts, list) else ()
    if contracts not in _CONTRACT_SETS:
        return None
    if limits is None:
        return ClassifierCapability(contracts, None) if contracts == ("text",) else None
    maxima = _CHOICE_MAXIMA if "choice" in contracts else _TEXT_MAXIMA
    return ClassifierCapability(contracts, dict(limits)) if _valid_limits(limits, maxima) else None


def choice_fits(capability: ClassifierCapability, request: ChoiceRequest) -> bool:
    """Whether the classifier takes ``request`` within every one of its published limits."""
    limits = capability.limits
    if "choice" not in capability.input_contracts or limits is None:
        return False
    count = len(request.labels)
    return (
        count <= _bound(limits, "max_options")
        and count <= _bound(limits, "max_labels")
        and not any(
            utf8_exceeds(label, _bound(limits, "max_label_bytes")) for label in request.labels
        )
        and all(
            len(text) <= _bound(limits, "max_description_chars") for text in request.descriptions
        )
        and len(request.instructions) <= _bound(limits, "max_instructions_chars")
        and len(request.text) <= _bound(limits, "max_text_chars")
    )


def text_fits(capability: ClassifierCapability, request: TextRequest) -> bool:
    """Whether the classifier takes the scalar ``request`` within its published text limits.

    WHY the label bounds too: a fixed-label classifier returns at most ``max_labels`` labels of at
    most ``max_label_bytes`` each, so a label set it cannot return would spend the classification
    and then fail coverage (C6).
    INVARIANT (C7, C17): ``limits: null`` is a valid row for direct scalar classification only;
    a Router that needs the classifier refuses it, since nothing bounds what it may be sent.
    """
    limits = capability.limits
    if "text" not in capability.input_contracts or limits is None:
        return False
    return (
        len(request.labels) <= _bound(limits, "max_labels")
        and not any(
            utf8_exceeds(label, _bound(limits, "max_label_bytes")) for label in request.labels
        )
        and len(request.text) <= _bound(limits, "max_text_chars")
    )


def choice_input(request: ChoiceRequest) -> dict[str, object]:
    """The C7 structured-choice input the classification port sends, options in request order.

    INVARIANT (C2): option order is candidate order, the order the revision hashed.
    """
    return {
        "contract": CHOICE_INPUT_CONTRACT,
        "text": request.text,
        "instructions": request.instructions,
        "options": [
            {"label": label, "description": description}
            for label, description in zip(request.labels, request.descriptions, strict=True)
        ],
    }


def _valid_limits(limits: object, maxima: dict[str, int]) -> TypeGuard[dict[str, int | str]]:
    if not isinstance(limits, dict) or set(limits) != {"contract", *maxima}:
        return False
    if limits["contract"] != LIMITS_CONTRACT or not all(
        _limit(limits[key], most) for key, most in maxima.items()
    ):
        return False
    # INVARIANT (C7): a choice answer may return every option it was offered.
    return "max_options" not in maxima or limits["max_options"] <= limits["max_labels"]


def _limit(value: object, most: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= most


def _bound(limits: dict[str, int | str], key: str) -> int:
    value = limits[key]
    # INVARIANT: `read_capability` admitted only integers under these keys.
    return value if isinstance(value, int) else 0


__all__ = [
    "CHOICE_INPUT_CONTRACT",
    "LIMITS_CONTRACT",
    "MAX_LIMIT",
    "ChoiceRequest",
    "ClassifierCapability",
    "TextRequest",
    "choice_fits",
    "choice_input",
    "read_capability",
    "text_fits",
]
