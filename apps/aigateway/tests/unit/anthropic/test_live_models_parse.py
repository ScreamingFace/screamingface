"""OME-1026 U3 (plan D5/D7): the strict, forward-compatible Anthropic page parser.

FEATURE: opt-in live Anthropic model discovery — one page of
``GET https://api.anthropic.com/v1/models`` becomes (candidate model ids, has_more, cursor).

INVARIANT (fail-closed, all-or-nothing): Anthropic's envelope carries NO ``total_count``, so
completeness cannot be reconciled by counting. Every completeness guard therefore lives in the
walk inputs, and a page whose envelope, rows, or cursor cannot be trusted fails the WHOLE
refresh rather than being salvaged — a salvaged page publishes a listing that silently omits
models, which is indistinguishable from upstream having retired them.

INVARIANT (strict, not brittle): the parser reads ONLY ``id`` (and ``type`` when present).
Every other documented or future row field is ignored, so an upstream additive change cannot
take the listing down.

INVARIANT (cursor safety, plan MAJOR-2): ``last_id`` is upstream-controlled material that this
gateway embeds in the NEXT request URL, so it must clear the same safe charset as a publishable
id BEFORE it is ever used. Building our own URL out of hostile material is not safer.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.parameter_discovery import DiscoveryError
from aigateway.plugins.anthropic_provider.live_models import parse_catalog_page


def _page(rows: list[Any], **envelope: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"data": rows, "has_more": False}
    payload.update(envelope)
    return payload


def test_a_realistic_page_parses_and_ignores_every_other_field() -> None:
    """Strict must not mean brittle: only ``id``/``type`` are read.

    Row and envelope shape per the official Models API contract (documented fields, not
    beta extras): ``id``, ``display_name``, ``type``, ``created_at``, ``max_input_tokens``,
    ``max_tokens``, plus a nested capabilities object.
    """
    payload = {
        "data": [
            {
                "id": "claude-opus-5",
                "type": "model",
                "display_name": "Claude Opus 5",
                "created_at": "2026-08-01T00:00:00Z",
                "max_input_tokens": 200_000,
                "max_tokens": 64_000,
                "capabilities": {"vision": True, "tools": {"web_search": True}},
            },
            {
                "id": "claude-opus-5-20260801",
                "type": "model",
                "display_name": "Claude Opus 5 (2026-08-01)",
                "created_at": "2026-08-01T00:00:00Z",
            },
        ],
        "has_more": False,
        "first_id": "claude-opus-5",
        "last_id": "claude-opus-5-20260801",
        "some_field_added_next_quarter": {"nested": [1, 2, 3]},
    }

    assert parse_catalog_page(payload) == (
        ("claude-opus-5", "claude-opus-5-20260801"),
        False,
        None,
    )


def test_a_paginated_page_returns_its_cursor() -> None:
    payload = _page(
        [{"id": "claude-sonnet-5", "type": "model"}],
        has_more=True,
        last_id="claude-sonnet-5",
    )

    assert parse_catalog_page(payload) == (("claude-sonnet-5",), True, "claude-sonnet-5")


def test_a_terminal_page_ignores_a_present_last_id() -> None:
    """CC-11: ``has_more=false`` WITH a ``last_id`` parses and TERMINATES.

    # WHY the cursor is dropped structurally rather than merely unused: returning it would
    # let a future walk edit continue past the documented end of the catalog. The envelope
    # populates ``last_id`` on every page including the final one, so this is the normal
    # terminal shape, not an anomaly.
    """
    payload = _page(
        [{"id": "claude-haiku-4-5"}],
        has_more=False,
        last_id="claude-haiku-4-5",
    )

    assert parse_catalog_page(payload) == (("claude-haiku-4-5",), False, None)


def test_an_empty_page_parses_rather_than_failing_here() -> None:
    # WHY: emptiness is a PUBLICATION judgement (an empty catalog must not evict a good
    # snapshot), made once over the finished walk — not a per-page parse error, because a
    # legitimately empty continuation page exists in the pagination contract.
    assert parse_catalog_page(_page([])) == ((), False, None)


def test_duplicate_ids_are_preserved_verbatim_at_parse_time() -> None:
    # INVARIANT: the parser reports the page as upstream sent it. Deduplication is a
    # publication concern (D7 first-occurrence), so parsing must not quietly reorder or
    # collapse anything a later stage is specified to handle.
    payload = _page([{"id": "claude-x-5"}, {"id": "claude-x-5"}])

    assert parse_catalog_page(payload) == (("claude-x-5", "claude-x-5"), False, None)


# --------------------------------------------------------------------------------------
# Row type policy (D7, final consistency amendment #2) — four distinct outcomes.
# --------------------------------------------------------------------------------------


def test_a_row_without_a_type_is_a_model_candidate() -> None:
    assert parse_catalog_page(_page([{"id": "claude-opus-5"}]))[0] == ("claude-opus-5",)


def test_a_row_typed_model_is_a_model_candidate() -> None:
    rows = [{"id": "claude-opus-5", "type": "model"}]
    assert parse_catalog_page(_page(rows))[0] == ("claude-opus-5",)


def test_a_row_with_an_unexpected_string_type_is_validated_then_excluded() -> None:
    """A structurally VALID non-model row is excluded by publication policy.

    # WHY excluded rather than salvaged or fatal: the row is well-formed, so the page is
    # still a trustworthy census — but this endpoint may one day list objects that are not
    # dispatchable models, and publishing them would produce ids that 404 at dispatch.
    # Exclusion is an explicit decision here, never an accident of lenient parsing.
    """
    rows = [
        {"id": "claude-opus-5", "type": "model"},
        {"id": "some-future-object", "type": "model_family"},
    ]

    assert parse_catalog_page(_page(rows))[0] == ("claude-opus-5",)


def test_a_row_with_a_non_string_type_fails_the_whole_page() -> None:
    # INVARIANT: a non-string ``type`` means the row schema is not what we believe, so no
    # row on the page can be trusted — including the ones that look fine.
    rows = [{"id": "claude-opus-5", "type": "model"}, {"id": "broken", "type": 7}]

    with pytest.raises(DiscoveryError) as exc:
        parse_catalog_page(_page(rows))

    assert exc.value.reason == "malformed_json"


def test_a_row_with_a_null_type_fails_the_whole_page() -> None:
    # ``type: null`` is PRESENT and non-string, so it is malformed — not treated as absent.
    with pytest.raises(DiscoveryError) as exc:
        parse_catalog_page(_page([{"id": "claude-opus-5", "type": None}]))

    assert exc.value.reason == "malformed_json"


# --------------------------------------------------------------------------------------
# The malformed matrix — every case fails the WHOLE page with one sanitized reason.
# --------------------------------------------------------------------------------------

_MALFORMED: list[tuple[str, Any]] = [
    ("payload_is_none", None),
    ("payload_is_a_list", [{"id": "claude-opus-5"}]),
    ("payload_is_a_string", '{"data": []}'),
    ("payload_is_an_int", 5),
    ("data_missing", {"has_more": False}),
    ("data_is_none", {"data": None, "has_more": False}),
    ("data_is_a_dict", {"data": {"id": "claude-opus-5"}, "has_more": False}),
    ("data_is_a_string", {"data": "claude-opus-5", "has_more": False}),
    ("row_is_a_string", {"data": ["claude-opus-5"], "has_more": False}),
    ("row_is_none", {"data": [None], "has_more": False}),
    ("row_is_an_int", {"data": [5], "has_more": False}),
    ("row_is_a_list", {"data": [["claude-opus-5"]], "has_more": False}),
    ("id_missing", {"data": [{"display_name": "Claude"}], "has_more": False}),
    ("id_is_none", {"data": [{"id": None}], "has_more": False}),
    ("id_is_an_int", {"data": [{"id": 5}], "has_more": False}),
    # bool is an int subclass in Python, so an id of ``true`` must not read as a value.
    ("id_is_a_bool", {"data": [{"id": True}], "has_more": False}),
    ("has_more_missing", {"data": [{"id": "claude-opus-5"}]}),
    ("has_more_is_none", {"data": [{"id": "claude-opus-5"}], "has_more": None}),
    # MINOR-2: named explicitly so no future "simplification" to truthiness can pass.
    ("has_more_is_int_one", {"data": [{"id": "claude-opus-5"}], "has_more": 1}),
    ("has_more_is_int_zero", {"data": [{"id": "claude-opus-5"}], "has_more": 0}),
    ("has_more_is_string_true", {"data": [{"id": "claude-opus-5"}], "has_more": "true"}),
    ("has_more_is_string_false", {"data": [{"id": "claude-opus-5"}], "has_more": "false"}),
    ("cursor_missing", {"data": [{"id": "claude-opus-5"}], "has_more": True}),
    ("cursor_is_none", {"data": [{"id": "x"}], "has_more": True, "last_id": None}),
    ("cursor_is_empty", {"data": [{"id": "x"}], "has_more": True, "last_id": ""}),
    ("cursor_is_an_int", {"data": [{"id": "x"}], "has_more": True, "last_id": 5}),
    # MAJOR-2 — cursor shapes that would inject or truncate the next request's query.
    (
        "cursor_injects_a_param",
        {"data": [{"id": "x"}], "has_more": True, "last_id": "x&limit=9999"},
    ),
    ("cursor_starts_a_query", {"data": [{"id": "x"}], "has_more": True, "last_id": "x?limit=1"}),
    ("cursor_has_a_fragment", {"data": [{"id": "x"}], "has_more": True, "last_id": "x#frag"}),
    ("cursor_has_a_slash", {"data": [{"id": "x"}], "has_more": True, "last_id": "a/b"}),
    ("cursor_has_a_colon", {"data": [{"id": "x"}], "has_more": True, "last_id": "a:b"}),
    ("cursor_has_a_tilde", {"data": [{"id": "x"}], "has_more": True, "last_id": "a~b"}),
    ("cursor_has_a_percent", {"data": [{"id": "x"}], "has_more": True, "last_id": "a%20b"}),
    ("cursor_has_an_equals", {"data": [{"id": "x"}], "has_more": True, "last_id": "a=b"}),
    ("cursor_has_a_plus", {"data": [{"id": "x"}], "has_more": True, "last_id": "a+b"}),
    # ``fullmatch`` semantics: ``$`` alone would accept a trailing newline.
    (
        "cursor_has_a_trailing_newline",
        {"data": [{"id": "x"}], "has_more": True, "last_id": "abc\n"},
    ),
    ("cursor_has_an_interior_space", {"data": [{"id": "x"}], "has_more": True, "last_id": "a b"}),
    ("cursor_has_a_tab", {"data": [{"id": "x"}], "has_more": True, "last_id": "a\tb"}),
    ("cursor_is_leading_dash", {"data": [{"id": "x"}], "has_more": True, "last_id": "-abc"}),
    ("cursor_is_leading_dot", {"data": [{"id": "x"}], "has_more": True, "last_id": ".abc"}),
    ("cursor_is_overlong", {"data": [{"id": "x"}], "has_more": True, "last_id": "a" * 257}),
]


@pytest.mark.parametrize("case,payload", _MALFORMED, ids=[case for case, _ in _MALFORMED])
def test_a_malformed_page_fails_the_whole_refresh(case: str, payload: Any) -> None:
    with pytest.raises(DiscoveryError) as exc:
        parse_catalog_page(payload)

    assert exc.value.reason == "malformed_json", case
    # sanitized: a fixed reason only, never the offending upstream value.
    assert exc.value.status is None, case


def test_a_maximum_length_cursor_is_accepted() -> None:
    # The bound is inclusive: exactly at the cap parses, one over fails (matrix above).
    cursor = "a" * 256
    payload = {"data": [{"id": "x"}], "has_more": True, "last_id": cursor}

    assert parse_catalog_page(payload)[2] == cursor
