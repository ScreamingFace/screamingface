"""sf.Gate: keep a vote's majority only when one recorded number passes a threshold (E4b part 5).

The gate is data, never Python code: one named number (``observe``), one comparison (``cmp``) and
one threshold, written into the combine spec as ``gate``. When ``observed cmp threshold`` holds,
the vote's majority is the answer. Otherwise the fallback (``otherwise``) gives the answer: an
abstain with the reason ``gate_not_met``, a label judge that names a member, or a model that
writes. In this version the fallback call runs on every Case; the gate chooses and records
(ans:Q1). E4c (OME-1291) removes the unused call with no wire change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from screamingface.judge import Judge
from screamingface.model import Model

type GateCmp = Literal[">=", ">", "<=", "<"]


@dataclass(frozen=True, slots=True, init=False)
class Gate:
    """Keep the majority when ``observe cmp threshold`` holds; else run ``otherwise``.

    ``observe``: "agreement", "chosen:<name>" or "mean:<name>" (a name the Fusion declares).
    ``otherwise``: "abstain" (the Case abstains with gate_not_met), an sf.Judge(returns="label")
    that names a member whose text is the answer, or an sf.Model that writes the answer.
    In this version the fallback call runs on every Case; the gate chooses and records.
    """

    observe: str
    cmp: GateCmp
    threshold: float
    otherwise: Literal["abstain"] | Judge | Model

    def __init__(
        self,
        observe: str,
        cmp: GateCmp,
        threshold: float,
        *,
        otherwise: Literal["abstain"] | Judge | Model = "abstain",
    ) -> None:
        raise NotImplementedError("sf.Gate is built in E4b part 5 unit 3 commit B")

    # WHY unhashable (as sf.Vote): a gate may hold an sf.Model, which is unhashable.
    __hash__: ClassVar[Any] = None


__all__ = ["Gate"]
