"""The token log-probability numbers of one chat-completions reply (E4b part 3, logprob-capture).

FEATURE: a member call that asks for `logprobs` (and maybe `top_logprobs`) carries, on its terminal
reply, the numbers a combine step reads: the token count, the exact sum of the token
log-probabilities, and the mean token entropy.
STORY: as a researcher, I weight or pick members by how sure each model was of its own answer.
INVARIANT: no token string and no `bytes` array leaves this module; only four numbers do (LC-D1,
OME-990). Nothing here logs.
INVARIANT: pure, and never raises on any decoded JSON value: the reply is untrusted gateway input
(C3). A bad shape gives None for the numbers it touches.
INVARIANT: the token values and the top lists are checked apart (LC-D2): a bad or positive token
value makes `logprob_sum` None; a bad top entry makes only `entropy_mean` None.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from screamingface_engine.operation_accounting import ReplyLogprobs


def reply_logprobs(data: Mapping[str, Any], top_k: int | None) -> ReplyLogprobs | None:
    """The numbers of ``choices[0].logprobs.content`` (RED stub, E4b part 3 unit 3)."""
    raise NotImplementedError


__all__ = ["reply_logprobs"]
