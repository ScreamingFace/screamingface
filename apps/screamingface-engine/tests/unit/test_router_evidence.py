"""Reading a Router classifier's output into C6 evidence (contracts C4/C5, Unit 5.2).

FEATURE: Router Recipe extension. The llm reply parser keeps E4c's tokenization, trimming,
case-insensitive match, single-token read and reply bound, but keeps recognized labels in reply
order and every distinct unknown token; KEYWORDS output and url4 `collect` error rows are read
strictly.

INVARIANT: a model reply is untrusted text: it selects declared labels only and never raises.
"""

from __future__ import annotations

import json

import pytest

from screamingface_engine.combine.ports import MAX_JUDGE_REPLY_BYTES, parse_selector_reply
from screamingface_engine.world.router_evidence import (
    RowFailure,
    read_error_row,
    read_keywords,
    read_llm_reply,
)
from screamingface_engine.world.routing_policy import SelectorEvidence
from url4.core.errors import ResolutionError

_LABELS = ("math", "code", "general")


def _llm(reply: str, *, multi: bool = True, labels: tuple[str, ...] = _LABELS) -> SelectorEvidence:
    return read_llm_reply(reply, labels, multi=multi)


# --- the llm reply parser -------------------------------------------------------------------------


def test_recognized_labels_keep_reply_order_each_once() -> None:
    evidence = _llm("general, math; GENERAL code math")

    assert evidence == SelectorEvidence("llm", ("general", "math", "code"), (), "ok")


def test_e4c_gate_parsing_is_unchanged() -> None:
    # WHY beside the Router parser: E4c keeps declared order and only the first unknown token.
    assert parse_selector_reply("general, math x y", _LABELS, multi=True) == (
        ["math", "general"],
        "unrecognized",
        "x",
    )


@pytest.mark.parametrize("reply", ["**Code**.", '"code"', "(code)!", "  code  ", "CoDe"])
def test_wrapping_punctuation_and_case_are_ignored(reply: str) -> None:
    assert _llm(reply).labels == ("code",)


def test_a_declared_label_with_capitals_matches_any_case() -> None:
    assert _llm("code", labels=("Code", "Math")).labels == ("Code",)


def test_unknown_tokens_keep_reply_order_each_once() -> None:
    evidence = _llm("zeta math alpha zeta")

    assert evidence == SelectorEvidence("llm", ("math",), ("zeta", "alpha"), "unrecognized")


def test_an_unknown_token_is_cut_at_64_characters_then_kept_once() -> None:
    long = "x" * 64
    evidence = _llm(f"{long}a {long}b")

    assert evidence.unknown == (long,)
    assert evidence.parse == "unrecognized"


def test_32_distinct_unknown_tokens_are_kept() -> None:
    tokens = [f"t{index}" for index in range(32)]
    evidence = _llm(" ".join(["code", *tokens]))

    assert evidence.unknown == tuple(tokens)
    assert evidence.labels == ("code",)


def test_33_distinct_unknown_tokens_are_unparsed() -> None:
    reply = " ".join(["code", *(f"t{index}" for index in range(33))])

    assert _llm(reply) == SelectorEvidence("llm", (), (), "unparsed")


def test_33_tokens_with_one_repeat_are_32_distinct() -> None:
    reply = " ".join(["t0", *(f"t{index}" for index in range(32))])

    assert _llm(reply).parse == "unrecognized"


@pytest.mark.parametrize("reply", ["", "   ", "...", ", ; ,", "**"])
def test_a_reply_with_no_token_is_unparsed(reply: str) -> None:
    assert _llm(reply) == SelectorEvidence("llm", (), (), "unparsed")


def test_a_reply_over_the_bound_is_unparsed() -> None:
    reply = "code " + "x" * MAX_JUDGE_REPLY_BYTES

    assert _llm(reply) == SelectorEvidence("llm", (), (), "unparsed")


def test_a_single_selector_reads_the_first_token_only() -> None:
    assert _llm("zeta code", multi=False) == SelectorEvidence("llm", (), ("zeta",), "unrecognized")
    assert _llm("code zeta math", multi=False) == SelectorEvidence("llm", ("code",), (), "ok")


# --- KEYWORDS output (regex) ----------------------------------------------------------------------


def _keywords(result: object, **extra: object) -> str:
    return json.dumps({"summary": {"chars": 3, "sha256": "0" * 16}, "router_1": result, **extra})


def test_keywords_labels_are_read_in_keywords_order() -> None:
    text = _keywords({"labels": ["code", "math"], "matched": ["code", "math"]})

    assert read_keywords(text, _LABELS, multi=True) == SelectorEvidence(
        "regex", ("code", "math"), (), "ok"
    )


def test_no_matching_rule_is_no_match() -> None:
    text = _keywords({"labels": [], "matched": []})

    assert read_keywords(text, _LABELS, multi=False) == SelectorEvidence(
        "regex", (), (), "no_match"
    )


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("not json", id="not-json"),
        pytest.param(json.dumps(["x"]), id="not-an-object"),
        pytest.param(json.dumps({"summary": {}}), id="no-selector"),
        pytest.param(
            _keywords({"labels": []}, router_2={"labels": [], "matched": []}), id="two-selectors"
        ),
        pytest.param(_keywords({"labels": ["other"], "matched": []}), id="undeclared-label"),
        pytest.param(_keywords({"labels": ["code", "code"], "matched": []}), id="repeated-label"),
        pytest.param(_keywords({"labels": "code", "matched": []}), id="labels-not-a-list"),
        pytest.param(_keywords(["code"]), id="result-not-an-object"),
    ],
)
def test_malformed_keywords_output_is_a_contract_error(text: str) -> None:
    with pytest.raises(ResolutionError) as caught:
        read_keywords(text, _LABELS, multi=True)

    assert caught.value.code == "benchmark_contract_error"
    assert caught.value.permanent is True


def test_a_single_keywords_selector_with_two_labels_is_a_contract_error() -> None:
    text = _keywords({"labels": ["code", "math"], "matched": ["code", "math"]})

    with pytest.raises(ResolutionError):
        read_keywords(text, _LABELS, multi=False)


# --- url4 collect error rows ----------------------------------------------------------------------


def _row(exc: BaseException) -> str:
    """A url4 ``collect`` error row, as url4 spec 5.3.6 writes it.

    WHY a mirror, not url4's private writer: the private-import ratchet
    (`test_url4_private_import_ratchet`) forbids it; `test_router_runtime` reads real rows.
    """
    error: dict[str, object] = {"kind": type(exc).__name__, "message": str(exc) or repr(exc)}
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        error["code"] = code
    permanent = getattr(exc, "permanent", None)
    if isinstance(permanent, bool):
        error["retryable"] = not permanent
    return json.dumps({"error": error})


@pytest.mark.parametrize(
    ("exc", "failure"),
    [
        pytest.param(
            ResolutionError("busy", code="aigateway_http_503", permanent=False),
            RowFailure("aigateway_http_503", permanent=False),
            id="transient",
        ),
        pytest.param(
            ResolutionError("gone", code="model_not_found", permanent=True),
            RowFailure("model_not_found", permanent=True),
            id="permanent",
        ),
        pytest.param(RuntimeError("boom"), RowFailure("upstream_error", permanent=True), id="bare"),
        pytest.param(
            ResolutionError("x", code="router_definition_invalid", permanent=False),
            RowFailure("upstream_error", permanent=False),
            id="router-code-is-reserved",
        ),
        pytest.param(
            ResolutionError("x", code="Not A Code", permanent=True),
            RowFailure("upstream_error", permanent=True),
            id="outside-the-grammar",
        ),
    ],
)
def test_an_error_row_reads_its_bounded_code_and_permanence(
    exc: BaseException, failure: RowFailure
) -> None:
    assert read_error_row(_row(exc)) == failure


@pytest.mark.parametrize(
    "row",
    [
        "the answer is 4",
        "",
        json.dumps({"answer": 4}),
        json.dumps({"error": "busy"}),
        json.dumps({"error": {"kind": "X"}}),
        json.dumps({"error": {"kind": "X", "message": "m", "extra": 1}}),
        json.dumps({"error": {"kind": "X", "message": "m"}, "case_id": "c"}),
        json.dumps({"error": {"kind": "X", "message": "m", "code": 7}}),
        json.dumps({"error": {"kind": "X", "message": "m", "retryable": "no"}}),
        '{"error": {"kind": "X", "message": "m"}, "error": {"kind": "X", "message": "m"}}',
    ],
)
def test_text_that_is_not_exactly_an_error_row_is_text(row: str) -> None:
    assert read_error_row(row) is None
