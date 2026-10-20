"""``Judge`` (a score step) and ``JudgePick`` (a reducer) (E4b surface, surface §4 and §6).

FEATURE: ``Judge(model, *, rubric, params=None)`` scores every member of its block in one call and
puts ``score:judge`` on each member; it does not pick. ``JudgePick(model, *, rubric, params=None)``
asks a judge model to name one member, and copies that member's text.
INVARIANT: both hold today's ``sf.Judge`` as their compile node, built when the step is built, so
today's rules raise here and equality uses today's typed key (a bool param is not a number).
AIDEV-NOTE: before the swap the scores judge keeps today's ``@1`` template; unit 7 brings the
neutral ``@2`` template (D2) and the ``JudgeNode`` name (O7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from screamingface._candidate_policy import GenerationParams
from screamingface._surface.chain import Step, _Category
from screamingface.judge import Judge as JudgeNode


@dataclass(frozen=True, slots=True, init=False)
class _JudgeStep(Step):
    """A judge model call over every member: ``Judge`` scores them, ``JudgePick`` picks one."""

    _returns: ClassVar[Literal["scores", "label"]]
    _writes_judge_signal: ClassVar[bool] = True
    model: str = field(compare=False)
    rubric: str = field(compare=False)
    params: GenerationParams = field(compare=False)
    _node: JudgeNode = field(repr=False)

    def __init__(
        self,
        model: str,
        *,
        rubric: str,
        params: Mapping[str, str | int | float | bool] | None = None,
    ) -> None:
        node = JudgeNode(model, returns=self._returns, rubric=rubric, params=params)
        object.__setattr__(self, "model", node.model)
        object.__setattr__(self, "rubric", node.rubric)
        object.__setattr__(self, "params", node.params)
        object.__setattr__(self, "_node", node)

    def __repr__(self) -> str:
        params = f", params={dict(self.params)!r}" if self.params else ""
        return f"{type(self).__name__}({self.model!r}, rubric={self.rubric!r}{params})"

    __hash__: ClassVar[Any] = None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Judge(_JudgeStep):
    """Score every member of the block with one judge call: the score step after ``sf.Fanout``.

    ``rubric`` says what a high number means. The steps after it read the scores as
    ``score:judge``: ``sf.ArgMax``/``sf.ArgMin("score:judge")``, ``sf.Rank(by="score:judge")``,
    ``sf.Filter(where=sf.signal("score:judge") >= x)`` and ``sf.Vote(weights="score:judge")``. A
    judge that no step reads is refused, because a judge call costs money.
    """

    _category: ClassVar[_Category] = "score"
    _returns: ClassVar[Literal["scores", "label"]] = "scores"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class JudgePick(_JudgeStep):
    """A judge model names one member; the answer is that member's text, unchanged.

    The members are shown to the judge in the order they were written, so a judge may favor a
    position. It makes its own call over every member, so it cannot follow a narrow step, and a
    block takes one judge: a ``sf.Judge`` step and a ``JudgePick`` do not go together.
    """

    _category: ClassVar[_Category] = "reduce"
    _returns: ClassVar[Literal["scores", "label"]] = "label"
    _sees_every_member: ClassVar[bool] = True


__all__ = ["Judge", "JudgePick"]
