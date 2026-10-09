"""The RDS input document codec and its ``?q=`` target (contracts C1, C2; rows 6-codec, 8).

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, a group's sources reach a code pointer as one JSON
# document, so the pointer receives each input exactly as its source resolved.
#
# INVARIANT: a target built by `encode_rds_target` decodes back to the same
# document under both wire conventions (the raw one url4 writes and the
# fully-encoded one a standard HTTP client sends).
"""

from __future__ import annotations

import random
from urllib.parse import quote

import pytest

from url4.wire.rds import (
    RdsValue,
    decode_q_payload,
    decode_rds_document,
    encode_rds_document,
    encode_rds_target,
)

_TEXT_ALPHABET = ("\n", "'", '"', "%", "&", "(", ")", "#", "+", " ", "\\", "é", "日", "😀")


def _q_value(target: str) -> str:
    # The test targets carry no `q=` inside their path or query tail, so the
    # first `q=` is the last parameter's name.
    return target.partition("?")[2].partition("q=")[2]


def _random_text(rng: random.Random) -> str:
    return "".join(rng.choice(_TEXT_ALPHABET) for _ in range(rng.randrange(8)))


def _random_value(rng: random.Random) -> RdsValue:
    # The candidates are all built, so the draw consumes the same numbers every run.
    candidates: list[RdsValue] = [
        "",
        _random_text(rng),
        [_random_text(rng), {"k": _random_text(rng), "n": rng.randrange(10)}],
        {"a": _random_text(rng), "b": [_random_text(rng), ""]},
    ]
    return rng.choice(candidates)


def _corpus() -> list[dict[str, RdsValue]]:
    rng = random.Random(20261009)
    return [{f"in{n}": _random_value(rng) for n in range(rng.randrange(1, 5))} for _ in range(200)]


# --- row 6: the document codec ------------------------------------------------------


def test_document_keeps_key_order():
    document = encode_rds_document({"member_2": "b", "member_1": "a"})

    assert document == '{"v":1,"inputs":{"member_2":"b","member_1":"a"}}'


def test_document_keeps_non_ascii_raw():
    document = encode_rds_document({"a": "é日"})

    assert document == '{"v":1,"inputs":{"a":"é日"}}'


def test_document_has_no_whitespace_separators():
    document = encode_rds_document({"a": "x y", "b": ["p", {"k": 1}]})

    assert document == '{"v":1,"inputs":{"a":"x y","b":["p",{"k":1}]}}'


def test_document_of_no_inputs_is_an_empty_object():
    assert encode_rds_document({}) == '{"v":1,"inputs":{}}'


# --- contract C2: the target string -------------------------------------------------


def test_target_puts_q_last_after_the_query_tail():
    target = encode_rds_target(
        "/ensemble/combine/v1",
        "reducer=vote&extract=last_number@1",
        '{"v":1,"inputs":{"member_1":"A says 4"}}',
    )

    assert target == (
        "/ensemble/combine/v1?reducer=vote&extract=last_number@1"
        "&q=(%7B%22v%22:1,%22inputs%22:%7B%22member_1%22:%22A%20says%204%22%7D%7D)"
    )


def test_target_without_query_tail_has_no_separator():
    target = encode_rds_target("/p", "", '{"v":1,"inputs":{}}')

    assert target == "/p?q=(%7B%22v%22:1,%22inputs%22:%7B%7D%7D)"


def test_target_keeps_path_and_query_bytes_as_written():
    target = encode_rds_target("/a b/c", "x=%20y", "{}")

    assert target == "/a b/c?x=%20y&q=(%7B%7D)"


def test_target_escapes_plus_so_a_full_decode_keeps_it():
    target = encode_rds_target("/p", "", '{"a":"1+1"}')

    assert "+" not in target
    assert "%2B" in target


# --- contract C1: decoding the document ---------------------------------------------


def test_decode_document_returns_inputs_of_a_valid_v1_document():
    assert decode_rds_document('{"v":1,"inputs":{"a":"x"}}') == {"a": "x"}


@pytest.mark.parametrize(
    "text",
    [
        '{"v":2,"inputs":{}}',
        '{"v":true,"inputs":{}}',
        '{"v":"1","inputs":{}}',
        '{"inputs":{}}',
        "[1]",
        '{"v":1,"inputs":[]}',
        '{"v":1,"inputs":"x"}',
        '{"v":1',
        "",
    ],
)
def test_decode_document_returns_none_for_an_invalid_document(text: str):
    assert decode_rds_document(text) is None


def test_decode_document_returns_none_for_nesting_too_deep_to_parse():
    # WHY: json.loads raises RecursionError on this input, not JSONDecodeError. The
    # payload is attacker-controlled over HTTP, so the decoder must return None.
    assert decode_rds_document("[" * 100000 + "]" * 100000) is None


# --- contract C2 step 2: the q payload -----------------------------------------------


def test_decode_q_payload_unescapes_the_raw_body():
    assert decode_q_payload("(%7B%7D)") == "{}"


def test_decode_q_payload_unescapes_a_fully_encoded_payload():
    assert decode_q_payload("%28a%2Bb%20c%29") == "a+b c"


def test_decode_q_payload_returns_none_for_a_raw_llm_call():
    assert decode_q_payload("(ctx)!intent") is None


def test_decode_q_payload_returns_none_without_parens_or_escapes():
    assert decode_q_payload("x") is None


def test_decode_q_payload_returns_none_for_a_fully_encoded_llm_call():
    assert decode_q_payload("%28ctx%29%21go") is None


def test_decode_q_payload_returns_none_for_a_raw_body_with_a_nested_paren():
    assert decode_q_payload("(a(b))") is None


# --- row 8: the seeded corpus round-trip --------------------------------------------


def test_seeded_corpus_round_trips_the_raw_convention():
    for inputs in _corpus():
        document = encode_rds_document(inputs)
        raw_q = _q_value(encode_rds_target("/p", "", document))

        assert decode_rds_document(decode_q_payload(raw_q) or "") == inputs


def test_seeded_corpus_round_trips_the_fully_encoded_convention():
    for inputs in _corpus():
        document = encode_rds_document(inputs)
        full_q = quote("(" + document + ")", safe="")

        assert decode_rds_document(decode_q_payload(full_q) or "") == inputs


# --- contract C2: the worked example ------------------------------------------------


def test_one_input_target_has_the_exact_literal():
    target = encode_rds_target(
        "/ensemble/combine/v1",
        "reducer=vote&extract=last_number@1",
        encode_rds_document({"member_1": "A says 4"}),
    )

    assert target == (
        "/ensemble/combine/v1?reducer=vote&extract=last_number@1"
        "&q=(%7B%22v%22:1,%22inputs%22:%7B%22member_1%22:%22A%20says%204%22%7D%7D)"
    )


def test_c2_worked_example_target_matches_the_contract():
    document = encode_rds_document(
        {
            "member_1": "A says 4",
            "member_2": "B: 5 (final)\nok",
            "extract_pattern": "ANSWER: \\d+",
        }
    )
    target = encode_rds_target(
        "/ensemble/combine/v1", "reducer=vote&extract=last_number@1", document
    )

    assert target == (
        "/ensemble/combine/v1?reducer=vote&extract=last_number@1"
        "&q=(%7B%22v%22:1,%22inputs%22:%7B%22member_1%22:%22A%20says%204%22,"
        "%22member_2%22:%22B:%205%20%28final%29%5Cnok%22,"
        "%22extract_pattern%22:%22ANSWER:%20%5C%5Cd%2B%22%7D%7D)"
    )


def test_c2_worked_example_decodes_to_the_three_named_inputs():
    target = encode_rds_target(
        "/ensemble/combine/v1",
        "reducer=vote&extract=last_number@1",
        encode_rds_document(
            {
                "member_1": "A says 4",
                "member_2": "B: 5 (final)\nok",
                "extract_pattern": "ANSWER: \\d+",
            }
        ),
    )

    decoded = decode_rds_document(decode_q_payload(_q_value(target)) or "")

    assert decoded == {
        "member_1": "A says 4",
        "member_2": "B: 5 (final)\nok",
        "extract_pattern": "ANSWER: \\d+",
    }
