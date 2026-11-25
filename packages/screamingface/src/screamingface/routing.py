"""A routed answer, as the Engine's ``/route-answer`` endpoint returns it (OME-1823).

FEATURE (BYOM routing pilot): a routing profile on the Engine binds one classifier and one chat
model per label. ``Client.route_answer`` sends it one question; the Engine classifies the
question, takes the one label with the highest score and asks that label's model once.

INVARIANT: the scores keep the classifier's order, and ``selected_label`` is the one label that
holds the highest score; the SDK refuses a result where it is not.
"""

from __future__ import annotations

from dataclasses import dataclass

from screamingface.classification import LabelScore


@dataclass(frozen=True)
class RoutedAnswer:
    """The selected model's answer to one question, with how it was selected.

    ``revision`` identifies the profile's exact classifier and branches (``sha256:<64 hex>``);
    ``classifier`` is the classifier's model ID and ``scores`` its labels and scores.
    e.g. ``RoutedAnswer(profile="expert_router_v1", ..., selected_label="code",
    selected_model="byom_<id>/code", answer="...")``.
    """

    profile: str
    revision: str
    policy: str
    contract: str
    classifier: str
    scores: tuple[LabelScore, ...]
    selected_label: str
    selected_model: str
    answer: str


__all__ = ["RoutedAnswer"]
