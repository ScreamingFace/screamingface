"""``sf.Fusion``: a shortcut that builds the ``sf.Fanout(...) >> <step>`` chain (E4b surface §3b).

FEATURE (owner decision 2026-10-20, revises A4): ``sf.Fusion(members, synthesizer=S, ...)`` stays
public as a function. It returns the ordinary chain, so ``==``, ``repr``, the cards and
``Url4.to_python()`` show the canonical ``sf.Fanout(...) >> ...`` form.
INVARIANT: no second compile path: the result is the chain that ``sf.Fanout(members, ...) >> S``
builds, so it compiles to the same bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from screamingface._surface.chain import Pipeline, Step
from screamingface._surface.fanout import Fanout
from screamingface._surface.synthesize import Synthesize
from screamingface.recipe import Recipe
from screamingface.signal_sources import SignalSource

_JUDGE_ONLY_SCORES = (
    "sf.Fusion synthesizer= takes a reducer, a writer or a narrow step; sf.Judge only scores: "
    "use sf.Fanout(...) >> sf.Judge(...) >> <reader>"
)


def Fusion(  # noqa: N802 - the public name of the shortcut is the name of the old class
    members: Sequence[str | Recipe],
    *,
    synthesizer: str | Recipe | Step,
    signals: Mapping[str, SignalSource] | None = None,
    quorum: int | Literal["all"] = "all",
    name: str | None = None,
    prompt: str | None = None,
    optional: bool = False,
) -> Pipeline:
    """Fan the input out to ``members``, then close the block with ``synthesizer``.

    A shortcut for ``sf.Fanout(members, signals=, quorum=, name=, prompt=) >> S``. ``S`` is the
    ``synthesizer`` as it is when it is a reduce step (``sf.Vote``, ``sf.Median``, ``sf.Mean``,
    ``sf.ArgMax``, ``sf.ArgMin``, ``sf.First``, ``sf.Merge``, ``sf.JudgePick``, ``sf.Gate``), an
    ``sf.Synthesize(...)`` or a narrow step (``sf.Rank``, ``sf.Filter``, ``sf.Concat``: the chain
    stays open, so add ``>> sf.Synthesize(...)``). A route string, an ``sf.Model`` or a recipe
    becomes ``sf.Synthesize(synthesizer)``. ``sf.Judge`` only scores, so it is refused.
    ``optional=True`` gives ``sf.Pipeline([chain], optional=True)``, a block that is an optional
    member of an outer ``sf.Fanout``.

    The result is the ordinary chain: its ``repr`` and ``Url4.to_python()`` show the
    ``sf.Fanout(...) >> ...`` form. ``sf.Fusion`` is a function, so ``isinstance(x, sf.Fusion)``
    is not supported.
    """

    fanout = Fanout(members, signals=signals, quorum=quorum, name=name, prompt=prompt)
    chain = fanout >> _closing(synthesizer)
    return Pipeline([chain], optional=True) if optional else chain


def _closing(synthesizer: str | Recipe | Step) -> Step:
    """The step after the Fanout: a step as it is, anything else as the writer of the block."""

    if isinstance(synthesizer, Step):
        if synthesizer._category == "score":
            raise ValueError(_JUDGE_ONLY_SCORES)
        return synthesizer
    return Synthesize(synthesizer)


__all__ = ["Fusion"]
