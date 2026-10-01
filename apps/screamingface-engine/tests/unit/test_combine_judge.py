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
from combine_support import context_text, request, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.operators.judge import parse_label, parse_scores
from screamingface_engine.combine.ports import CombineError, JudgeReplyInvalid
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
_EXPECTED = {"member_1": 1.0, "member_2": 2.0, "member_3": 3.0}


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"member_1": 0.2, "member_2": 0.9, "member_3": 0.5}', (0.2, 0.9, 0.5)),
        ('{"member_3": 0.5, "member_1": 0.2, "member_2": 0.9}', (0.2, 0.9, 0.5)),
        (_BODY, (1.0, 2.0, 3.0)),
        (f"```json\n{_BODY}\n```", (1.0, 2.0, 3.0)),
        (f"```\n{_BODY}\n```", (1.0, 2.0, 3.0)),
        (f"  \n```json\n{_BODY}\n```\n ", (1.0, 2.0, 3.0)),
        ('{"member_1": -1, "member_2": -2.5, "member_3": 0}', (-1.0, -2.5, 0.0)),
        ('{"member_1": 1e-7, "member_2": 0, "member_3": 0}', (1e-07, 0.0, 0.0)),
    ],
    ids=[
        "plain",
        "reply-order-differs",
        "ints",
        "json-fence",
        "untagged-fence",
        "fence-with-whitespace",
        "negative",
        "exponent",
    ],
)
def test_scores_parser_accepts_one_finite_number_per_member(
    reply: str, expected: tuple[float, ...]
) -> None:
    parsed = parse_scores(reply, _MEMBERS)
    assert list(parsed) == list(_MEMBERS)
    assert tuple(parsed.values()) == expected


_INVALID_SCORES = {
    "missing-member": '{"member_1": 1, "member_2": 2}',
    "extra-key": '{"member_1": 1, "member_2": 2, "member_3": 3, "member_4": 4}',
    "string-value": '{"member_1": "0.5", "member_2": 2, "member_3": 3}',
    "nan": '{"member_1": NaN, "member_2": 2, "member_3": 3}',
    "infinity": '{"member_1": Infinity, "member_2": 2, "member_3": 3}',
    "minus-infinity": '{"member_1": -Infinity, "member_2": 2, "member_3": 3}',
    "overflow": '{"member_1": 1e400, "member_2": 2, "member_3": 3}',
    "huge-int": '{"member_1": 1' + "0" * 400 + ', "member_2": 2, "member_3": 3}',
    "true": '{"member_1": true, "member_2": 2, "member_3": 3}',
    "null": '{"member_1": null, "member_2": 2, "member_3": 3}',
    "list-value": '{"member_1": [1], "member_2": 2, "member_3": 3}',
    "duplicate-key": '{"member_1": 1, "member_1": 1, "member_2": 2, "member_3": 3}',
    "top-level-array": "[0.1, 0.2, 0.3]",
    "prose-before": f"Scores:\n{_BODY}",
    "prose-after": f"{_BODY}\nThat is all.",
    "fence-after-prose": f"Scores:\n```json\n{_BODY}\n```",
    "fence-after-prose-same-line": f"Here: ```json\n{_BODY}\n```",
    "uppercase-tag": f"```JSON\n{_BODY}\n```",
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


def _failure(returns: Any, reply: str) -> ResolutionError:
    result, _ = _route(returns, reply)
    assert isinstance(result, ResolutionError)
    return result


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


def test_a_judge_reply_over_64_kib_is_judge_reply_invalid() -> None:
    error = _failure("label", "member_1" + " " * (64 * 1024))
    assert error.code == "judge_reply_invalid"


# --- JG-4 -------------------------------------------------------------------------------------


def test_by_label_copies_member_text_byte_for_byte() -> None:
    outputs = [" A\r\n", "B text \u00e9 ", "C"]
    outcome = run(
        spec_text(judge_spec(3, "label")),
        context_text(outputs, {"judge": "member_2"}),
        registry=BUILTIN_OPERATORS,
    )
    assert outcome.output == "B text \u00e9 "


def test_label_accepts_a_member_marked_too_large() -> None:
    big = "x" * (1024 * 1024 + 1)
    outcome = run(
        spec_text(judge_spec(2, "label")),
        context_text(["small", big], {"judge": "member_2"}),
        registry=BUILTIN_OPERATORS,
    )
    assert outcome.output == big
    assert [m.status for m in outcome.evidence.members] == ["voted", "too_large"]


# --- JG-5 -------------------------------------------------------------------------------------


def test_max_score_tie_goes_to_author_order() -> None:
    outcome = run(
        spec_text(judge_spec(3, "scores")),
        context_text(["A", "B", "C"], {"judge": '{"member_1":0.9,"member_2":0.5,"member_3":0.9}'}),
        registry=BUILTIN_OPERATORS,
    )
    assert outcome.output == "A"
    assert outcome.evidence.tie is True
    assert outcome.evidence.chosen == ["member_1"]


# --- scores from numeric values (rank by field) ----------------------------------------------


def test_scores_from_numeric_values_for_rank_by_field() -> None:
    spec = vote_spec(
        3,
        reducer="rank",
        extract={"op": "json_field@1", "args": {"path": "score"}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "scores@1", "args": {"source": "values"}},
        select={"op": "max_score@1", "args": {}},
    )
    outcome = run(
        spec_text(spec),
        context_text(['{"score": 5}', '{"score": 9}', '{"score": "x"}']),
        registry=BUILTIN_OPERATORS,
    )
    assert outcome.output == '{"score": 9}'
    assert [m.score for m in outcome.evidence.members] == [5.0, 9.0, None]
    assert outcome.evidence.members[2].status == "not_numeric"


# --- missing signal and bad args --------------------------------------------------------------


def test_scores_reject_a_missing_signal_and_bad_args() -> None:
    plain = context_text(["A", "B", "C"])
    with pytest.raises(CombineError) as missing:
        run(spec_text(judge_spec(3, "scores")), plain, registry=BUILTIN_OPERATORS)
    assert missing.value.code == "combine_spec_invalid"
    assert "judge signal" in str(missing.value)

    for args in ({}, {"source": "x"}, {"source": "judge", "x": 1}):
        spec = judge_spec(3, "scores")
        spec["reduce"] = {"op": "scores@1", "args": args}
        with pytest.raises(CombineError) as bad:
            run(spec_text(spec), "not json at all", registry=BUILTIN_OPERATORS)
        assert bad.value.code == "combine_spec_invalid"
        assert "scores@1 args are invalid" in str(bad.value)


def test_label_rejects_a_missing_signal() -> None:
    with pytest.raises(CombineError) as missing:
        run(
            spec_text(judge_spec(3, "label")),
            context_text(["A", "B", "C"]),
            registry=BUILTIN_OPERATORS,
        )
    assert missing.value.code == "combine_spec_invalid"


# --- JG-8 -------------------------------------------------------------------------------------


def _members(scores: tuple[float | None, ...]) -> list[dict[str, Any]]:
    return [
        {
            "member": f"member_{i}",
            "raw": None,
            "value": None,
            "status": "voted",
            "weight": None,
            "score": scores[i - 1],
        }
        for i in range(1, 4)
    ]


def test_evidence_has_raw_parsed_and_presentation_order() -> None:
    """CHAR once wired: the wire shape of both judge returns, pinned in full."""
    label = run(
        spec_text(judge_spec(3, "label")),
        context_text(["A", "B", "C"], {"judge": "member_2"}),
        registry=BUILTIN_OPERATORS,
    )
    assert label.evidence.model_dump(by_alias=True) == {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "judge",
        "operators": ["label@1", "by_label@1"],
        "members": _members((None, None, None)),
        "tally": None,
        "judge": {"raw": "member_2", "returns": "label", "parsed": "member_2"},
        "fields": None,
        "chosen": ["member_2"],
        "built": False,
        "agreement": None,
        "tie": False,
        "median": None,
        "presentation_order": "author",
        "separator_collision": None,
        "finish_reason": "stop",
    }

    reply = '{"member_1":0.2,"member_2":0.9,"member_3":0.5}'
    scored = run(
        spec_text(judge_spec(3, "scores")),
        context_text(["A", "B", "C"], {"judge": reply}),
        registry=BUILTIN_OPERATORS,
    )
    assert scored.evidence.model_dump(by_alias=True) == {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "judge",
        "operators": ["scores@1", "max_score@1"],
        "members": _members((0.2, 0.9, 0.5)),
        "tally": None,
        "judge": {
            "raw": reply,
            "returns": "scores",
            "parsed": {"member_1": 0.2, "member_2": 0.9, "member_3": 0.5},
        },
        "fields": None,
        "chosen": ["member_2"],
        "built": False,
        "agreement": None,
        "tie": False,
        "median": None,
        "presentation_order": "author",
        "separator_collision": None,
        "finish_reason": "stop",
    }
