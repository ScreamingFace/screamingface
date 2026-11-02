"""The shared cache's credential guard: no stored answer holds a key its own call carried.

FEATURE: hosted BYOM Unit 1 — a stored answer is replayed to and listed for every account, so an
upstream that repeats the caller's key must never get that answer stored.

INVARIANT under test: every non-empty credential sealed into the dispatch body counts, however
short, and it is matched in the answer's decoded strings and mapping keys, so the escaping of
`"` or `\\` in serialized JSON cannot hide it. A body whose credentials cannot be read fails closed.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.request_cache.credential_guard import holds_sealed_credential


def _answer(content: object) -> dict[str, Any]:
    message = {"role": "assistant", "content": content}
    return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


@pytest.mark.parametrize(
    "key", ["Zq7", 'sk-secret-"quoted"-0001', "sk-back\\slash-0001", "sk-ordinary-0001"]
)
def test_a_sealed_key_anywhere_in_an_answer_is_found(key: str) -> None:
    body = {"api_key": key}

    assert holds_sealed_credential(_answer(f"you sent Bearer {key}"), body)
    assert holds_sealed_credential({**_answer("ok"), key: "a key used as a field name"}, body)
    assert holds_sealed_credential({"data": [({"deep": ["x", f"..{key}.."]},)]}, body)
    assert not holds_sealed_credential(_answer("nothing to see"), body)


# WHY: the wire text of the JSON number 12345678 repeats the key "12345678" verbatim.
@pytest.mark.parametrize("echo", [12345678, 12345678.0, 9123456780, {12345678: "x"}])
def test_a_key_of_digits_repeated_as_a_number_is_found(echo: object) -> None:
    body = {"api_key": "12345678"}

    assert holds_sealed_credential({**_answer("ok"), "credential_echo": echo}, body)


def test_numbers_booleans_and_null_without_the_key_are_storable() -> None:
    answer = {**_answer("ok"), "seed": 1234567, "ratio": 0.5, "cached": True, "note": None}

    assert not holds_sealed_credential(answer, {"api_key": "12345678"})


def test_a_padded_key_is_found_without_its_padding() -> None:
    assert holds_sealed_credential(_answer("sk-padded-0001"), {"api_key": " sk-padded-0001 "})


def test_a_credential_header_and_its_bearer_token_count_and_other_headers_do_not() -> None:
    headers = {"Authorization": "Bearer tok-1", "x-api-key": "k2", "X-Title": "My App"}
    body = {"extra_headers": headers}

    assert holds_sealed_credential(_answer("the token tok-1"), body)
    assert holds_sealed_credential(_answer("the key k2"), body)
    # WHY: a title or a referer is not a credential; an answer may well mention it.
    assert not holds_sealed_credential(_answer("built by My App"), body)


@pytest.mark.parametrize("body", [{}, {"api_key": ""}, {"api_key": "   "}, {"api_key": None}])
def test_an_answer_is_storable_when_the_call_sealed_no_credential(body: dict[str, Any]) -> None:
    assert not holds_sealed_credential(_answer("Bearer anything"), body)


def test_an_unreadable_body_fails_closed() -> None:
    class _Unreadable(dict[str, Any]):
        def get(self, *_args: Any) -> Any:
            raise RuntimeError("unreadable")

    assert holds_sealed_credential(_answer("nothing to see"), _Unreadable())
