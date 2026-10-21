"""sf.Gate: keep a vote's majority only when one recorded number passes a threshold (E4b part 5).

The gate is data, never Python code: one named number (``observe``), one comparison (``cmp``) and
one threshold, written into the combine spec as ``gate``. When ``observed cmp threshold`` holds,
the vote's majority is the answer. Otherwise the fallback (``otherwise``) gives the answer: an
abstain with the reason ``gate_not_met``, a label judge that names a member, or a model that
writes. In this version the fallback call runs on every Case; the gate chooses and records
(ans:Q1). E4c (OME-1291) removes the unused call with no wire change.
``abstain_band=(lo, hi)`` (E4b part 6, ans:Q2): when the number is inside the closed band, the
Case abstains with the reason ``in_band``; the Engine checks the band before the comparison.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Literal, cast

from screamingface._evaluation.policy import DEFAULT_SYNTHESIS_PROMPT
from screamingface._signals import _finite_number, is_signal_key
from screamingface.combine_evidence import _GATE_CMPS, _GATE_SOURCES, GateCmp, _is_gate_observe
from screamingface.judge import JudgeNode
from screamingface.model import Model
from screamingface.reducer import _FALLBACK_JUDGE_KEY, _FALLBACK_WRITER_KEY, _ModelSignal

_KEEP_HIGH: tuple[str, ...] = (">=", ">")
_AGREEMENT = "agreement"
_ABSTAIN: Literal["abstain"] = "abstain"
_OBSERVE_RULE = (
    "Gate observe must be 'agreement', 'chosen:<name>' or 'mean:<name>', where <name> is a "
    "declared signal name"
)
_E4A_HINT = "; an E4a key such as cost_usd is not a gate input"
_OTHERWISE_RULE = "Gate otherwise must be 'abstain', an sf.Judge or an sf.Model"
_BAND_PAIR = "Gate abstain_band must be a pair (lo, hi) of numbers"
_BAND_FINITE = "Gate abstain_band must be finite"


@dataclass(frozen=True, slots=True, init=False)
class GateNode:
    """Keep the majority when ``observe cmp threshold`` holds; else run ``otherwise``.

    ``observe``: "agreement", "chosen:<name>" or "mean:<name>" (a name the Fusion declares).
    ``otherwise``: "abstain" (the Case abstains with gate_not_met), an sf.Judge(returns="label")
    that names a member whose text is the answer, or an sf.Model that writes the answer.
    ``abstain_band``: None, or (lo, hi) with lo <= hi: when the observed number is inside the
    closed band [lo, hi], the Case abstains with in_band for every ``otherwise``; outside it the
    gate compares as above. A missing number skips the band.
    In this version the fallback call runs on every Case; the gate chooses and records.
    """

    observe: str
    cmp: GateCmp
    threshold: float
    otherwise: Literal["abstain"] | JudgeNode | Model
    abstain_band: tuple[float, float] | None

    def __init__(
        self,
        observe: str,
        cmp: GateCmp,
        threshold: float,
        *,
        otherwise: Literal["abstain"] | JudgeNode | Model = "abstain",
        abstain_band: tuple[float, float] | None = None,
    ) -> None:
        checked_observe = _observe(observe)
        checked_cmp = _cmp(cmp)
        number = _threshold(threshold)
        _check_agreement(checked_observe, checked_cmp, number)
        band = _band(abstain_band, checked_observe)
        object.__setattr__(self, "observe", checked_observe)
        object.__setattr__(self, "cmp", checked_cmp)
        object.__setattr__(self, "threshold", number)
        object.__setattr__(self, "otherwise", _otherwise(otherwise))
        object.__setattr__(self, "abstain_band", band)

    def _spec(self) -> dict[str, object]:
        """{"cmp", "observe", "otherwise": "abstain" | "judge" | "writer", "threshold": float}, plus
        "abstain_band": [lo, hi] only when set, so a gate without a band keeps its part 5 bytes
        (BD-I1)."""
        spec: dict[str, object] = {
            "cmp": self.cmp,
            "observe": self.observe,
            "otherwise": _otherwise_word(self.otherwise),
            "threshold": self.threshold,
        }
        if self.abstain_band is not None:
            spec["abstain_band"] = list(self.abstain_band)
        return spec

    def _signal_call(self) -> _ModelSignal | None:
        """None for abstain; else the one model call whose reply the vote reads (P5, C2)."""

        otherwise = self.otherwise
        if isinstance(otherwise, JudgeNode):
            # WHY replace: Judge._signal_call builds the label template and the rubric; this
            # never builds the judge prompt a second time (C7).
            return replace(otherwise._signal_call(), key=_FALLBACK_JUDGE_KEY)
        if isinstance(otherwise, Model):
            # The model synthesizer's default prompt (S/_evaluation/candidate.py).
            return _ModelSignal(
                _FALLBACK_WRITER_KEY,
                otherwise.model,
                otherwise.prompt or DEFAULT_SYNTHESIS_PROMPT,
                otherwise.params,
            )
        return None

    def _declared_name(self) -> str | None:
        """<name> of chosen:<name> / mean:<name>; None for agreement."""
        if self.observe == _AGREEMENT:
            return None
        return self.observe.split(":", 1)[1]

    def __repr__(self) -> str:
        return self._render("Gate", repr)

    def _python(self) -> str:
        return self._render("sf.Gate", _python_form)

    def _render(self, head: str, show: Callable[[JudgeNode | Model], str]) -> str:
        # WHY no otherwise for abstain: the default keeps the repr short (GA-D8).
        otherwise = "" if isinstance(self.otherwise, str) else f", otherwise={show(self.otherwise)}"
        # WHY no band when None: a gate without a band keeps its part 5 repr (BA-D1).
        band = "" if self.abstain_band is None else f", abstain_band={self.abstain_band!r}"
        return f"{head}({self.observe!r}, {self.cmp!r}, {self.threshold!r}{otherwise}{band})"

    # WHY unhashable (as sf.Vote): a gate may hold an sf.Model, which is unhashable.
    __hash__: ClassVar[Any] = None


def _observe(value: object) -> str:
    """``value`` when it is agreement, chosen:<name> or mean:<name> with a declared name."""
    if not isinstance(value, str):
        raise TypeError("Gate observe must be text")
    if _is_gate_observe(value):
        return value
    form, colon, name = value.partition(":")
    named = bool(colon) and form in _GATE_SOURCES
    # WHY the hint: chosen:cost_usd looks right but reads an E4a key, not a declared signal.
    hint = _E4A_HINT if named and is_signal_key(name) else ""
    raise ValueError(_OBSERVE_RULE + hint)


def _cmp(value: object) -> GateCmp:
    if value not in _GATE_CMPS:
        raise ValueError("Gate cmp must be '>=', '>', '<=' or '<'")
    return cast("GateCmp", value)


def _threshold(value: object) -> float:
    """A finite float; an int is stored as a float, a bool is refused."""
    return _finite_number(value, "Gate threshold must be a number", "Gate threshold must be finite")


def _check_agreement(observe: str, cmp: GateCmp, threshold: float) -> None:
    """P4: an agreement gate keeps a high agreement, and an agreement is a share in [0, 1]."""
    if observe != _AGREEMENT:
        return
    if cmp not in _KEEP_HIGH:
        raise ValueError(
            "an agreement gate keeps the majority when the agreement is high; use '>=' or '>'"
        )
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("an agreement gate threshold must be between 0 and 1")


def _band(value: object, observe: str) -> tuple[float, float] | None:
    """P7: None (no band), or a closed band (lo, hi) of finite floats with lo <= hi; an agreement
    band is a share in [0, 1]. Checked after _check_agreement (band-api §2.1)."""
    if value is None:
        return None
    lo, hi = _band_pair(value)
    if lo > hi:
        raise ValueError("Gate abstain_band needs lo <= hi")
    if observe == _AGREEMENT and not 0.0 <= lo <= hi <= 1.0:
        raise ValueError("an agreement gate abstain_band must be between 0 and 1")
    return (lo, hi)


def _band_pair(value: object) -> tuple[float, float]:
    """Two finite floats out of a tuple or list of exactly two numbers; an int becomes a float,
    a bool is refused (the _threshold rule)."""
    if not isinstance(value, tuple | list) or len(value) != 2:
        raise TypeError(_BAND_PAIR)
    # WHY both types first: a pair such as (inf, True) is a TypeError, not a ValueError.
    if any(isinstance(item, bool) or not isinstance(item, int | float) for item in value):
        raise TypeError(_BAND_PAIR)
    lo = _finite_number(value[0], _BAND_PAIR, _BAND_FINITE)
    hi = _finite_number(value[1], _BAND_PAIR, _BAND_FINITE)
    return (lo, hi)


def _otherwise(value: object) -> Literal["abstain"] | JudgeNode | Model:
    """The checked fallback. The messages never echo a rubric or a prompt."""
    if isinstance(value, str):
        if value != _ABSTAIN:
            raise ValueError(_OTHERWISE_RULE)
        return _ABSTAIN
    if isinstance(value, JudgeNode):
        if value.returns != "label":
            raise ValueError(
                "a gate fallback judge needs sf.Judge(..., returns='label'): it names one member"
            )
        return value
    if isinstance(value, Model):
        # WHY _sample_id: it holds an explicit name= (Model.__repr__ reads it the same way).
        if value._sample_id is not None or value.optional:
            raise ValueError("a gate fallback sf.Model takes no name= and is never optional")
        return value
    raise TypeError(_OTHERWISE_RULE)


def _otherwise_word(value: Literal["abstain"] | JudgeNode | Model) -> str:
    """The spec word (erd §1). The model, prompt and params live in the url4 fallback call."""
    if isinstance(value, JudgeNode):
        return "judge"
    if isinstance(value, Model):
        return "writer"
    return "abstain"


def _python_form(value: JudgeNode | Model) -> str:
    """``sf.Judge(...)`` or ``sf.Model(...)``: the text ``Url4.to_python`` writes."""
    return f"sf.{value!r}"


__all__ = ["GateNode"]
