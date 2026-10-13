"""The judge operators read a judge reply strictly and copy the chosen member (OME-1289 E4a, U8).

FEATURE: a judge model picks a member; the Fusion's answer is that member's own text.
STORY: as a researcher, I never get the judge's prose as an answer -- a reply that is not exactly
one member id (or one finite score per member) fails the case with ``judge_reply_invalid``.
INVARIANT defended: no fallback branch. A parse failure always raises, and no message repeats
what the judge wrote.
"""

from __future__ import annotations

import logging
import string
from typing import Any

import pytest
from combine_flow_support import judge_spec
from combine_support import context_text, request, spec_text

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.operators.judge import parse_label, parse_scores
from screamingface_engine.combine.ports import JudgeReplyInvalid
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.world.combine import CombineRoute
from url4.core.errors import ResolutionError

_MEMBERS = ("member_1", "member_2", "member_3")
_LOGGER = "screamingface_engine.combine.endpoint"


# --- JG-1 -------------------------------------------------------------------------------------


def test_label_parser_accepts_exact_member_id_only() -> None:
    assert parse_label("member_2", _MEMBERS) == "member_2"
    assert parse_label(" \n member_3\t\n", _MEMBERS) == "member_3"
    assert parse_label("\u00a0member_1\u00a0", _MEMBERS) == "member_1"
    broken = [
        '"member_2"',
        "member_2.",
        "```member_2```",
        "member_7",
        "I think member 2 is best.",
        "",
        "   ",
        "MEMBER_2",
        "member_02",
        "member-2",
        "member_2 member_3",
        "member_2\nmember_3",
        "member_\uff12",
        "\u200bmember_2",
        "'member_2'",
        "member_2,",
        "<member_2>",
        "**member_2**",
    ]
    for reply in broken:
        with pytest.raises(JudgeReplyInvalid):
            parse_label(reply, _MEMBERS)


def test_label_parser_rejects_one_extra_character_unless_it_is_whitespace() -> None:
    for char in string.printable:
        for reply in (char + "member_2", "member_2" + char):
            if char.isspace():
                assert parse_label(reply, _MEMBERS) == "member_2", repr(reply)
            else:
                with pytest.raises(JudgeReplyInvalid):
                    parse_label(reply, _MEMBERS)


# --- JG-2 -------------------------------------------------------------------------------------

_BODY = '{"member_1": 1, "member_2": 2, "member_3": 3}'

_INVALID_SCORES = {
    "extra-key": '{"member_1": 1, "member_2": 2, "member_3": 3, "member_4": 4}',
    "string-value": '{"member_1": "0.5", "member_2": 2, "member_3": 3}',
    "infinity": '{"member_1": Infinity, "member_2": 2, "member_3": 3}',
    "minus-infinity": '{"member_1": -Infinity, "member_2": 2, "member_3": 3}',
    "huge-int": '{"member_1": 1' + "0" * 400 + ', "member_2": 2, "member_3": 3}',
    "null": '{"member_1": null, "member_2": 2, "member_3": 3}',
    "list-value": '{"member_1": [1], "member_2": 2, "member_3": 3}',
    "prose-before": f"Scores:\n{_BODY}",
    "prose-after": f"{_BODY}\nThat is all.",
    "fence-after-prose-same-line": f"Here: ```json\n{_BODY}\n```",
    "no-newline": f"```json {_BODY}```",
    "other-tag": f"```python\n{_BODY}\n```",
    "empty-fence": "``````",
    "trailing-comma": '{"member_1": 1, "member_2": 2, "member_3": 3,}',
    "single-quotes": "{'member_1': 1, 'member_2': 2, 'member_3': 3}",
    "empty": "",
}


@pytest.mark.parametrize("reply", list(_INVALID_SCORES.values()), ids=list(_INVALID_SCORES))
def test_scores_parser_requires_one_finite_number_per_member(reply: str) -> None:
    with pytest.raises(JudgeReplyInvalid):
        parse_scores(reply, _MEMBERS)


# --- JG-3 -------------------------------------------------------------------------------------


def _route(returns: Any, reply: str) -> tuple[str | ResolutionError, list[OperationCall]]:
    """Call the combine route in this test's own capture scope (a nested scope would hide calls)."""
    intent = spec_text(judge_spec(3, returns))
    context = context_text(["A", "B", "C"], {"judge": reply})
    route = CombineRoute(BUILTIN_OPERATORS)
    with capture_operation_calls() as calls:
        try:
            result: str | ResolutionError = route(request(intent, context))
        except ResolutionError as error:
            result = error
    return result, list(calls)


def _last_log_line(caplog: pytest.LogCaptureFixture) -> str:
    lines = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
    assert lines
    return lines[-1]


@pytest.mark.parametrize(
    ("returns", "reply", "echoed"),
    [
        ("label", "I think member 2 is best.", "member 2 is best"),
        ("scores", '{"member_1": 1}', "member_1"),
    ],
    ids=["label", "scores"],
)
def test_parse_failure_raises_judge_reply_invalid_never_uses_prose(
    returns: str, reply: str, echoed: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        result, calls = _route(returns, reply)
    assert isinstance(result, ResolutionError)
    assert result.code == "judge_reply_invalid"
    assert result.permanent is True
    assert echoed not in str(result)
    assert _last_log_line(caplog).endswith("outcome=judge_reply_invalid")
    assert calls == []


def test_a_successful_judge_step_records_exactly_one_call() -> None:
    """The positive control of the no-call checks above: the same scope does see a record."""
    result, calls = _route("label", "member_2")
    assert result == "B"
    assert len(calls) == 1
    assert calls[0].output == "B"
