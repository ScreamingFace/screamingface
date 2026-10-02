"""One judge reply parser in the core, and ``score:judge`` as a signal (OME-1289 E4a, unit 8E).

FEATURE: the core reads each member's ``score:judge`` from the strict judge reply, so a vote can be
weighted by a judge and a reducer can rank by it. SG#13 and SR#11 (engine part).
INVARIANT defended: the judge reply is never read loosely. A missing judge signal is a spec error,
and a malformed or oversize reply is ``judge_reply_invalid``; a message never repeats the reply.
"""

from __future__ import annotations

from typing import Any

import pytest

from screamingface_engine.combine import ports
from screamingface_engine.combine.operators import judge
from screamingface_engine.combine.ports import JudgeReplyInvalid, SpecInvalid

# --- SG#13 part 1: the parser and the cap live in ports ---------------------------------------


def test_parse_scores_and_the_reply_cap_live_in_ports() -> None:
    assert getattr(ports, "parse_scores", None) is judge.parse_scores
    assert getattr(ports, "MAX_JUDGE_REPLY_BYTES", None) == judge.MAX_JUDGE_REPLY_BYTES == 65536
    assert not hasattr(judge, "_unfenced")
    assert not hasattr(judge, "_score")


def test_judge_reply_names_the_owner_and_caps_at_64_kib() -> None:
    judge_reply: Any = getattr(ports, "judge_reply", None)
    assert callable(judge_reply)
    with pytest.raises(SpecInvalid, match="x@1 needs the judge signal"):
        judge_reply({}, "x@1")
    at_cap = "a" * 65536
    assert judge_reply({"judge": at_cap}, "x@1") == at_cap
    with pytest.raises(JudgeReplyInvalid):
        judge_reply({"judge": "a" * 65537}, "x@1")
    two_byte = "é" * 16385  # 32770 bytes: the cap counts bytes, not characters
    assert judge_reply({"judge": two_byte}, "x@1") == two_byte
