"""A text classifier's answer, as the Engine's ``/classify`` endpoint returns it (OME-1796).

FEATURE (OME-1796, hosted BYOM Unit 3): a configured endpoint can host a text classifier, for
example a Hugging Face text-classification deployment. ``sf.classify`` sends it one text
through the Engine and returns its labels and scores as these types.

INVARIANT: the scores come back in the order the classifier sent them, ties included. Nothing
is sorted, dropped or picked, so the top label is the caller's choice, not this package's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelScore:
    """One label and the score the classifier gave it.

    e.g. ``LabelScore(label="POSITIVE", score=0.98)``.
    """

    label: str
    score: float


@dataclass(frozen=True)
class Classification:
    """The labels and scores one classifier gave one text, in the classifier's order.

    ``contract`` names the result shape, ``classification-scores-v1`` today.
    e.g. ``Classification(model="byom_<id>/classifier_v1", contract="classification-scores-v1",
    scores=(LabelScore("POSITIVE", 0.98), LabelScore("NEGATIVE", 0.02)))``.
    """

    model: str
    contract: str
    scores: tuple[LabelScore, ...]


__all__ = ["Classification", "LabelScore"]
