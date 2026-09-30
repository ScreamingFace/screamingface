"""The replay pin forms: the two id forms in front of the registry's name forms.

FEATURE: OME-1307 (E14) replay grants (RP-8).
INVARIANT: standard library and `scoreboard.core.registry` only.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from scoreboard.core.registry import DatePin, InvalidPin, NamePin, RevisionPin, parse_pin


@dataclass(frozen=True, slots=True)
class ResultPin:
    result_id: UUID


@dataclass(frozen=True, slots=True)
class ScorePin:
    score_id: UUID


ReplayPin = ResultPin | ScorePin | NamePin | RevisionPin | DatePin


_RESULT_PREFIX = "result:"
_SCORE_PREFIX = "score:"


def parse_replay_pin(raw: str) -> ReplayPin:
    """`result:<uuid>` and `score:<uuid>` are tried first (SB-registry `parse_pin` does not parse
    them); anything else is a system pin for the merged parser.

    AIDEV-NOTE: no strip here. A pin with a trailing space is the parser's concern (SR-20).
    """
    if raw.startswith(_RESULT_PREFIX):
        return ResultPin(_uuid(raw, raw.removeprefix(_RESULT_PREFIX)))
    if raw.startswith(_SCORE_PREFIX):
        return ScorePin(_uuid(raw, raw.removeprefix(_SCORE_PREFIX)))
    return parse_pin(raw)


def _uuid(raw: str, text: str) -> UUID:
    try:
        return UUID(text)
    except ValueError:
        raise InvalidPin(raw, "not a result or score id") from None
