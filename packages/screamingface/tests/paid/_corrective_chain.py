"""Did the Corrective Loop entry's retry chain actually run? Read from its kept Report.

Mental model: the referee (`_report_problems`) only asks "did the pipe break?". A
Corrective Loop can come back green with every Case passing in round 1, and then the
chain this entry exists for never ran: the checker's words about failed requirements
(the Draft Feedback), the judge turning them into coaching, and the retry prompt that
carries the coaching and the previous answer. This module reads each Case's
`rounds_executed` from the kept Report and says whether any Case got past round 1.

WHY rounds and not the coaching text: the Report keeps no check record and no coaching
reply. A loop only reaches round 2 through the coaching call (it sits inside the gate a
no-pass round opens, and a failing coaching call fails the Case), so a Case with 2+
rounds is the Report's proof that the chain ran end to end.

Worked example: Cases [1: 1 round, passed; 6: 3 rounds, never passed] print

    case 1 · 1 round · check passed · scored
    case 6 · 3 rounds · check never passed · scored

and count as exercised. If every Case reads 1 round, the entry stays green but the
overview carries the "chain not exercised" warning (owner decision: a lucky press is a
warning, not a red press; infrastructure failures stay red through the referee).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_INDENT: Final = "    "
#: The first round that only a coaching call can reach.
_RETRY_ROUND: Final = 2

CHAIN_NOT_EXERCISED: Final = (
    "chain not exercised: no Case got past round 1, so no Draft Feedback reached a "
    "retry this press (a warning, not a failure; press again to re-roll)"
)


@dataclass(frozen=True, slots=True)
class CaseRounds:
    """One Case of the loop: how many rounds ran and how it stopped."""

    case_id: str
    #: None when the Case failed before the loop reported (e.g. a member's token cap).
    rounds: int | None
    #: "passed" (a draft passed the check) or "max_rounds" (none did); None as above.
    stop_reason: str | None
    status: str


@dataclass(frozen=True, slots=True)
class ChainEvidence:
    """Every Case's rounds, in Report order."""

    cases: tuple[CaseRounds, ...]

    @property
    def exercised(self) -> bool:
        """True when at least one Case ran a retry round, i.e. the chain ran."""
        return any((case.rounds or 0) >= _RETRY_ROUND for case in self.cases)


def read_chain_evidence(report_path: Path) -> ChainEvidence | None:
    """Read each Case's rounds from the entry's kept Report export.

    Returns:
        The evidence, or None when no Report was kept (evaluate raised): that entry is
        already red through the referee, so there is nothing to warn about.
    """
    try:
        exported: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
        cases: list[dict[str, Any]] = exported["candidates"][0].get("cases") or []
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None
    return ChainEvidence(tuple(_case_rounds(case) for case in cases))


def chain_lines(evidence: ChainEvidence | None) -> list[str]:
    """The per-Case lines printed under the entry's stats line."""
    if evidence is None:
        return []
    return [_INDENT + _case_line(case) for case in evidence.cases]


def chain_warning(evidence: ChainEvidence | None) -> str | None:
    """The overview warning when the press proved nothing about the chain, else None."""
    if evidence is None or evidence.exercised:
        return None
    return CHAIN_NOT_EXERCISED


def _case_rounds(case: dict[str, Any]) -> CaseRounds:
    """Project one exported Case onto the fields the chain check reads."""
    rounds: Any = case.get("rounds_executed")
    stop_reason: Any = case.get("stop_reason")
    return CaseRounds(
        case_id=str(case.get("case_id")),
        rounds=rounds if isinstance(rounds, int) and not isinstance(rounds, bool) else None,
        stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        status=str(case.get("status")),
    )


def _case_line(case: CaseRounds) -> str:
    """One Case as ``case 6 · 3 rounds · check never passed · scored``."""
    if case.rounds is None:
        return f"case {case.case_id} · no loop outcome · {case.status}"
    noun: str = "round" if case.rounds == 1 else "rounds"
    check: str = "check passed" if case.stop_reason == "passed" else "check never passed"
    return f"case {case.case_id} · {case.rounds} {noun} · {check} · {case.status}"
