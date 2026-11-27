import asyncio
import json

import pytest

from bert_reference.server import create_application

JSON = [(b"content-type", b"application/json")]


def exchange(headers=JSON, chunks=(b'{"inputs":"ping"}',), tokens=512, logits=(0.0, 0.0)):
    events, reads, calls = [], [], []
    ids = (101,) + (7,) * (tokens - 2) + (102,)

    def tokenize(text, *, add_special_tokens, truncation):
        assert add_special_tokens and not truncation
        calls.append(("tokenizer", text))
        return ids

    def head(encoding):
        assert encoding is ids
        calls.append(("head", len(encoding)))
        if isinstance(logits, Exception):
            raise logits
        return logits

    async def receive():
        number = len(reads)
        reads.append(number)
        return {
            "type": "http.request",
            "body": chunks[number],
            "more_body": number + 1 < len(chunks),
        }

    async def send(event):
        events.append(event)

    scope = {"type": "http", "method": "POST", "path": "/classify", "headers": headers}
    asyncio.run(create_application(tokenize, head)(scope, receive, send))
    assert events[0]["headers"] == [(b"content-type", b"application/json")]
    return events[0]["status"], json.loads(events[1]["body"]), reads, calls


@pytest.mark.parametrize(
    "headers",
    [
        JSON,
        JSON + [(b"content-encoding", b"identity")],
        [
            (b"Content-Type", b'\tApplication/JSON ; CHARSET="UTF-8" '),
            (b"Content-Encoding", b"\tIdentity "),
        ],
        [(b"content-type", b"application/json;charset=utf-8")],
    ],
)
@pytest.mark.parametrize("count", [511, 512])
def test_exact_text_encoding_and_tied_scores(headers, count):
    text = "  MiXeD café\n🦊 "
    status, response, _, calls = exchange(headers, (json.dumps({"inputs": text}).encode(),), count)
    assert (status, response) == (
        200,
        [{"label": "NEGATIVE", "score": 0.5}, {"label": "POSITIVE", "score": 0.5}],
    )
    assert calls == [("tokenizer", text), ("head", count)]


@pytest.mark.parametrize(
    "headers",
    [
        [],
        JSON * 2,
        *[
            [(b"content-type", value)]
            for value in (
                b"application/problem+json",
                b"application/json, application/json",
                b"application/json; charset=latin1",
                b"application/json; charset =utf-8",
                b"application/json; other=foo",
                b"application/json; charset=utf-8; charset=utf-8",
            )
        ],
        *[
            JSON + [(b"content-encoding", value)]
            for value in (
                b"",
                b"identity, identity",
                b"gzip",
            )
        ],
        JSON + [(b"Content-Encoding", b"identity")] * 2,
    ],
)
def test_bad_headers_win_without_reading_invalid_oversize_body(headers):
    assert exchange(headers, (b"a" * 65_537,)) == (
        415,
        {"error": {"code": "unsupported_media_type"}},
        [],
        [],
    )


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b"{}",
        b"null",
        b"[]",
        b'{"inputs":["x"]}',
        b'{"inputs":null}',
        b'{"inputs":1}',
        b'{"inputs":"\xff"}',
        rb'{"inputs":"\ud800"}',
        b'{"inputs":"x","inputs":"x"}',
        b'{"inputs":"x","extra":0}',
    ],
)
def test_bad_shape_precedes_token_limit(body):
    assert exchange(chunks=(body,), tokens=513) == (
        400,
        {"error": {"code": "invalid_request"}},
        [0],
        [],
    )


def test_fragmented_body_crossing_wins_over_json_and_stops_reading():
    assert exchange(chunks=(b"x" * 65_536, b"x", b"unread")) == (
        413,
        {"error": {"code": "request_too_large"}},
        [0, 1],
        [],
    )
    assert exchange(chunks=(b'{"inputs":""}', b" " * (65_536 - 13)))[0] == 200


def test_special_tokens_cross_limit_before_head():
    failure = RuntimeError("sensitive-local-detail")
    assert exchange(tokens=513, logits=failure) == (
        422,
        {"error": {"code": "input_token_limit_exceeded"}},
        [0],
        [("tokenizer", "ping")],
    )
    assert exchange(tokens=512, logits=failure)[:2] == (
        500,
        {"error": {"code": "classifier_failed"}},
    )


@pytest.mark.parametrize(
    "logits", [(float("nan"), 0), (float("inf"), 0), (0, True), (0,), (0, 0, 0)]
)
def test_invalid_logits_do_not_escape(logits):
    assert exchange(logits=logits)[:2] == (500, {"error": {"code": "classifier_failed"}})


def test_stable_softmax_uses_both_logits_in_original_order():
    status, result, _, _ = exchange(logits=(1000, 1001))
    assert status == 200
    assert [row["label"] for row in result] == ["NEGATIVE", "POSITIVE"]
    assert [row["score"] for row in result] == pytest.approx([0.268941421, 0.731058579])


@pytest.mark.parametrize(
    "logit", ["0.5", None, float("-inf")], ids=["numeric-string", "none", "-inf"]
)
def test_refuses_coercible_or_negative_infinite_logits(logit: object):
    assert exchange(logits=(logit, 0))[:2] == (500, {"error": {"code": "classifier_failed"}})
