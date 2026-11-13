"""A chat request carrying url4's largest legal attachment passes the gateway's real body cap.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1545``; PR #1588 review blocker 2,
owner decision 2026-11-13). url4 admits at most ``MAX_ATTACHMENT_BYTES`` decoded attachment bytes
per run and the Engine sends them base64-encoded in every model call. INVARIANT: such a call, with
the Engine's 256 KiB envelope reserve, is not refused ``request_too_large`` by the real app at its
default cap; a picture past the old 8,000,000-byte url4 cap (the reviewer's 6,500,000-byte case
is already over) still is.

url4's cap is read from its source with ``ast``, never imported: url4 is not installed in this
project. The Engine suite holds the twin
(``apps/screamingface-engine/tests/unit/test_url4_attachment_cap_fits_the_gateway.py``), which
pins the arithmetic for 20 entries and drives the Engine's own request construction.
"""

from __future__ import annotations

import ast
import base64
import json
import math
from pathlib import Path

import pytest

from aigateway.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[4]
_URL4_CAPS = _REPO_ROOT / "packages/url4/src/url4/dag/_caps.py"
_ENVELOPE_RESERVE = 256 * 1024  # the Engine twin's reserve: prompt, params, JSON around messages


def _url4_attachment_cap() -> int:
    for node in ast.walk(ast.parse(_URL4_CAPS.read_text())):
        if (
            isinstance(node, ast.Assign)
            and [getattr(t, "id", None) for t in node.targets] == ["MAX_ATTACHMENT_BYTES"]
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            return node.value.value
    raise AssertionError(f"MAX_ATTACHMENT_BYTES = <int> not found in {_URL4_CAPS}")


def _picture_request(decoded: int) -> bytes:
    payload = b"A" * (4 * math.ceil(decoded / 3))
    prompt = b"p" * (_ENVELOPE_RESERVE - 4096)
    return (
        b'{"model":"anthropic/claude-haiku-4-5","messages":[{"role":"user","content":['
        b'{"type":"image_url","image_url":{"url":"data:image/png;base64,'
        + payload
        + b'"}},{"type":"text","text":"'
        + prompt
        + b'"}]}]}'
    )


@pytest.fixture
def default_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIGW_MAX_REQUEST_BYTES", raising=False)


def test_url4s_largest_legal_picture_is_not_refused_by_the_body_cap(
    default_cap, authenticated_client
) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        content=_picture_request(_url4_attachment_cap()),
        headers={"content-type": "application/json"},
    )

    assert resp.status_code != 413, resp.text
    assert "request_too_large" not in resp.text


def test_a_picture_past_the_aligned_cap_is_refused_by_the_body_cap(
    default_cap, authenticated_client
) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        content=_picture_request(6_500_000),
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 413, resp.text
    assert resp.json()["detail"]["code"] == "request_too_large"


# --- The shared recipe: the Gateway half of the byte-level boundary test (PR #1588 round 6) ---
#
# INVARIANT: the SAME ``tests/fixtures/url4_attachment_cap_request/recipe.json`` the Engine half
# (``apps/screamingface-engine/tests/unit/test_url4_attachment_cap_fits_the_gateway.py``) proves
# is byte-identical to what the Engine really sends for url4's largest legal picture, expanded
# here into the real app at its default cap: exactly the cap passes the body cap, one byte more
# is ``413 request_too_large``. Data is shared, never code: apps do not import each other.

_RECIPE = Path(__file__).resolve().parents[1] / "fixtures/url4_attachment_cap_request/recipe.json"


def _recipe() -> dict:
    return json.loads(_RECIPE.read_text(encoding="utf-8"))


def _expanded(recipe: dict, total: int) -> bytes:
    """The recipe as one request body of exactly ``total`` bytes (the Engine half's twin)."""
    decoded = recipe["picture"]["decoded_bytes"]
    picture = base64.b64encode((bytes(range(256)) * (decoded // 256 + 1))[:decoded])
    slots = recipe["slots"]
    head, rest = recipe["envelope"].encode().split(slots["picture"].encode())
    middle, tail = rest.split(slots["prompt"].encode())
    room = total - len(head) - len(picture) - len(middle) - len(tail)
    body = head + picture + middle + recipe["prompt_fill"].encode() * room + tail
    assert len(body) == total
    return body


def test_the_shared_recipe_is_cut_for_this_gateways_default_cap() -> None:
    recipe = _recipe()
    cap = Settings.model_fields["max_request_bytes"].default

    assert recipe["gateway_cap_bytes"] == cap
    assert recipe["boundary_bytes"] == {"passes": cap, "refused": cap + 1}
    assert recipe["picture"]["decoded_bytes"] == _url4_attachment_cap()


def test_the_engines_request_at_exactly_the_cap_passes_the_body_cap(
    default_cap, authenticated_client
) -> None:
    recipe = _recipe()

    resp = authenticated_client.post(
        "/v1/chat/completions",
        content=_expanded(recipe, recipe["boundary_bytes"]["passes"]),
        headers={"content-type": "application/json"},
    )

    assert resp.status_code != 413, resp.text
    assert "request_too_large" not in resp.text
    # WHY: the next refusal after the body cap — this test provisions no provider profile —
    # proves the whole 8,388,608-byte body was read, parsed as JSON and routed by its model.
    assert resp.json()["detail"] == {
        "code": "profile_not_found",
        "provider": "anthropic",
        "name": "default",
    }


def test_the_engines_request_one_byte_over_the_cap_is_request_too_large(
    default_cap, authenticated_client
) -> None:
    recipe = _recipe()

    resp = authenticated_client.post(
        "/v1/chat/completions",
        content=_expanded(recipe, recipe["boundary_bytes"]["refused"]),
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 413, resp.text
    assert resp.json()["detail"]["code"] == "request_too_large"
