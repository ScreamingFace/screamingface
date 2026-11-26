"""A request that carries a Case file by reference keys exactly like today's inline request.

FEATURE: Case files sent by blob reference (OME-1970, PR 3 of 9). A **blob reference** is the
text ``blob:sha256/<64 hex>``, the SHA-256 of a file's bytes, sent where the file's base64 used
to be after the Engine has uploaded the file to the gateway once. In key material it is a
``BlobReference`` standing exactly where the file's ``data:`` URI string stood.

INVARIANT under test (owner decision 2, 26 Nov): both stores key a reference request with the
SAME digest today's inline request gets — the response cache (``build_reference_cache_key``,
beside today's ``build_global_cache_key``) and the pinned cache a published run is replayed
from (``request_digest``). So no cached answer and no pinned copy is lost, and
``KEY_REVISION`` does not move.

WHY the inline request comes from a recorded fixture, not a hand-written dict: the claim is
"byte for byte what the Engine sends today", so the inline side is the gateway suite's existing
recording of an Engine picture call (``tests/fixtures/url4_attachment_cap_request/recipe.json``).
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import inspect
import json
import random
import threading
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.store import FrozenCopyStore, request_digest
from aigateway.core.plugin_base import ProviderPluginBase
from aigateway.core.request_cache.canonical import CanonicalizationError, canonical_digest
from aigateway.core.request_cache.global_controls import GlobalCacheControls
from aigateway.core.request_cache.global_keys import (
    CacheBypass,
    GlobalCacheKeyResult,
    build_attempt_cache_key,
    build_global_cache_key,
    build_reference_cache_key,
)
from aigateway.core.request_cache.global_plan import build_reference_cache_plan
from aigateway.core.request_cache.reference_digest import (
    BlobReference,
    ReferencedFile,
    UnknownBlobReference,
    canonical_digest_with_references,
)
from aigateway.routes.chat_cache_stage import look_up_global_cache
from tests.unit.test_frozen_copy_support import chat_response, run_async

_RECIPE = Path(__file__).resolve().parents[1] / "fixtures/url4_attachment_cap_request/recipe.json"
_PROVIDER = "fake"
_AUTH_MODES = ("api_key",)
# Room for the recorded 10.7 MB inline request; the default test store caps entries at 2 MB.
_ROOMY_ENTRY_BYTES = 50_000_000

type Lookup = Callable[[str], ReferencedFile | None]


# --- the recorded inline request and its reference twin -------------------------------------


def _recipe() -> dict[str, Any]:
    """The fixture's own description of one Engine picture call."""
    return json.loads(_RECIPE.read_text())


def _picture_bytes(decoded: int) -> bytes:
    """The fixture's picture: bytes 0..255 repeated, cut to ``decoded`` (its documented rule)."""
    return (bytes(range(256)) * (decoded // 256 + 1))[:decoded]


def _inline_request(picture: bytes) -> dict[str, Any]:
    """Today's request, exactly as the fixture records it: the picture's base64 inside JSON."""
    recipe = _recipe()
    envelope: str = recipe["envelope"]
    text: str = envelope.replace("@PICTURE@", base64.b64encode(picture).decode("ascii")).replace(
        "@PROMPT@", recipe["prompt_fill"]
    )
    return json.loads(text)


def _sha256(data: bytes) -> str:
    """The hex SHA-256 a blob reference names a file by."""
    return hashlib.sha256(data).hexdigest()


def _with_reference(value: Any, data_uri: str, reference: BlobReference) -> Any:
    """``value`` with every string equal to ``data_uri`` replaced by ``reference``."""
    if value == data_uri:
        return reference
    if isinstance(value, dict):
        return {k: _with_reference(v, data_uri, reference) for k, v in value.items()}
    if isinstance(value, list):
        return [_with_reference(v, data_uri, reference) for v in value]
    return value


def _reference_request(picture: bytes) -> tuple[dict[str, Any], dict[str, ReferencedFile]]:
    """The same call with the picture sent by reference, plus the gateway's file lookup table."""
    inline: dict[str, Any] = _inline_request(picture)
    b64: str = base64.b64encode(picture).decode("ascii")
    media_type: str = _recipe()["picture"]["media_type"]
    reference = BlobReference(_sha256(picture))
    by_reference: dict[str, Any] = _with_reference(
        inline, f"data:{media_type};base64,{b64}", reference
    )
    assert by_reference != inline, "the fixture's data URI was not found to replace"
    return by_reference, {reference.sha256: ReferencedFile(media_type, b64)}


def _projection(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
    """A pure stand-in provider projection; the file travels in ``messages``, not here."""
    return {
        "resolved_model": str(body["model"]).split("/", 1)[1],
        "provider_adapter_revision": "pa-1",
        "prepared": {"api_base": "https://example.invalid"},
    }


def _response_key(body: dict[str, Any], files: Lookup | None = None) -> str:
    """The response cache's key: today's builder inline, the reference builder with files."""
    built = (
        build_global_cache_key(
            provider=_PROVIDER,
            body=body,
            rules=(),
            projection=_projection,
            provider_auth_modes=_AUTH_MODES,
        )
        if files is None
        else build_reference_cache_key(
            provider=_PROVIDER,
            body=body,
            rules=(),
            projection=_projection,
            provider_auth_modes=_AUTH_MODES,
            files=files,
        )
    )
    assert isinstance(built, GlobalCacheKeyResult), built
    return built.key_hash


def _attempt_key(body: dict[str, Any], files: Lookup | None = None) -> str:
    """The response cache's key for Attempt 2 of ``body`` (OME-1458), either way."""
    built = (
        build_attempt_cache_key(
            attempt=2,
            provider=_PROVIDER,
            body=body,
            rules=(),
            projection=_projection,
            provider_auth_modes=_AUTH_MODES,
        )
        if files is None
        else build_reference_cache_key(
            provider=_PROVIDER,
            body=body,
            rules=(),
            projection=_projection,
            provider_auth_modes=_AUTH_MODES,
            files=files,
            attempt=2,
        )
    )
    assert isinstance(built, GlobalCacheKeyResult), built
    return built.key_hash


@pytest.fixture(scope="module")
def picture() -> bytes:
    """The recorded call's 8,000,000-byte picture (10,666,668 bytes as base64)."""
    return _picture_bytes(_recipe()["picture"]["decoded_bytes"])


# --- decision 2: the key stays today's, in both stores ---------------------------------------


def test_a_reference_request_keys_like_todays_inline_request_in_both_stores(
    picture: bytes,
) -> None:
    """The one test that carries decision 2: same file, same key, whichever way it travels."""
    inline: dict[str, Any] = _inline_request(picture)
    by_reference, files = _reference_request(picture)

    # The response cache, ordinary and Attempt 2.
    assert _response_key(by_reference, files.get) == _response_key(inline)
    assert _attempt_key(by_reference, files.get) == _attempt_key(inline)
    # The pinned cache, ordinary and Attempt 2.
    assert request_digest("chat", by_reference, files=files.get) == request_digest("chat", inline)
    assert request_digest("chat", by_reference, 2, files=files.get) == request_digest(
        "chat", inline, 2
    )


def test_one_changed_byte_of_the_file_changes_both_keys(picture: bytes) -> None:
    """A different file is a different request: the reference key follows the bytes."""
    inline: dict[str, Any] = _inline_request(picture)
    changed: bytes = picture[:-1] + bytes([picture[-1] ^ 1])
    by_reference, files = _reference_request(changed)

    assert _response_key(by_reference, files.get) != _response_key(inline)
    assert request_digest("chat", by_reference, files=files.get) != request_digest("chat", inline)
    # ...and it is exactly the key the changed file gets inline.
    assert _response_key(by_reference, files.get) == _response_key(_inline_request(changed))


def test_a_reference_the_lookup_does_not_hold_is_refused_by_name_in_both_stores(
    picture: bytes,
) -> None:
    """No file, no key: the caller must hear "unknown file", never a silent bypass or miss.

    WHY not a ``CacheBypass``: a request whose file the gateway no longer holds cannot be
    dispatched either, so a bypass would only defer the same failure to the upstream slot.
    """
    by_reference, _ = _reference_request(picture)
    nothing: dict[str, ReferencedFile] = {}

    with pytest.raises(UnknownBlobReference) as raised:
        _response_key(by_reference, nothing.get)
    assert raised.value.sha256 == _sha256(picture)
    with pytest.raises(UnknownBlobReference):
        request_digest("chat", by_reference, files=nothing.get)


def test_without_a_lookup_a_reference_is_never_keyed(picture: bytes) -> None:
    """The plain path refuses a reference, so it can never key one as something else."""
    by_reference, _ = _reference_request(picture)

    with pytest.raises(CanonicalizationError):
        canonical_digest({"request": by_reference})
    built = build_global_cache_key(
        provider=_PROVIDER,
        body=by_reference,
        rules=(),
        projection=_projection,
        provider_auth_modes=_AUTH_MODES,
    )
    assert built == CacheBypass("canonicalization_failure")


def test_the_reference_entry_points_accept_no_identity_profile_or_credential_input() -> None:
    """Plan §10, proven structurally, for the two new reference entry points.

    ``files`` is the one new parameter. It is a lookup of stored files, not identity: two
    callers sending the same file reach the same hash (the test above proves it is today's
    inline hash). A later parameter named ``account_id`` fails here even if no test passes one.
    """
    assert set(inspect.signature(build_reference_cache_key).parameters) == {
        "provider",
        "body",
        "rules",
        "projection",
        "provider_auth_modes",
        "files",
        "attempt",
    }
    assert set(inspect.signature(build_reference_cache_plan).parameters) == {
        "body",
        "plugin",
        "controls",
        "cache_enabled",
        "files",
    }
    assert not inspect.iscoroutinefunction(build_reference_cache_plan)


def test_a_reference_names_a_sha256_and_nothing_else() -> None:
    """A malformed digest is refused at construction, before it can reach a key."""
    for bad in ("", "abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65):
        with pytest.raises(ValueError):
            BlobReference(bad)


# --- both stores, end to end, off the event loop ---------------------------------------------


def test_a_pinned_copy_captured_inline_is_found_by_reference_and_back(
    picture: bytes, authenticated_client: TestClient
) -> None:
    """A published run captured inline replays by reference, and the reverse, off the loop."""
    client = authenticated_client
    owner = UUID(client.get("/v1/auth/me").json()["id"])
    inline: dict[str, Any] = _inline_request(picture)
    by_reference, files = _reference_request(picture)
    hashing_threads: set[int] = set()

    def lookup(sha256: str) -> ReferencedFile | None:
        hashing_threads.add(threading.get_ident())
        return files.get(sha256)

    async def _round_trip() -> tuple[int, Any, Any, Any]:
        frozen = FrozenCopyStore(max_entry_bytes=_ROOMY_ENTRY_BYTES)
        inline_copy = await frozen.open(owner)
        await frozen.capture(
            inline_copy, "chat", inline, chat_response("x"), 200, case_key="", occurrence=0
        )
        found_by_reference = await frozen.find(
            inline_copy, "chat", by_reference, None, "", 0, files=lookup
        )
        reference_copy = await frozen.open(owner)
        await frozen.capture(
            reference_copy,
            "chat",
            by_reference,
            chat_response("y"),
            200,
            case_key="",
            occurrence=0,
            files=lookup,
        )
        found_inline = await frozen.find(reference_copy, "chat", inline, None, "", 0)
        return threading.get_ident(), found_by_reference, found_inline, reference_copy

    loop_thread, found_by_reference, found_inline, _ = run_async(client, _round_trip)

    assert found_by_reference is not None and found_by_reference.response_json["id"] == "x"
    assert found_inline is not None and found_inline.response_json["id"] == "y"
    # The stored row holds the reference text, not the file: the row stays a few KB.
    stored: str = json.dumps(found_inline.request_json)
    assert f"blob:sha256/{_sha256(picture)}" in stored
    assert len(stored) < 1_000
    # WHY: hashing an 18 MB file takes tens of milliseconds; on the loop it stalls every call.
    assert hashing_threads and loop_thread not in hashing_threads


def test_the_response_cache_lookup_hashes_a_reference_request_off_the_event_loop(
    picture: bytes,
) -> None:
    """The route's cache stage keys a reference request like inline, on a worker thread."""
    inline: dict[str, Any] = _inline_request(picture)
    by_reference, files = _reference_request(picture)
    hashing_threads: set[int] = set()
    looked_up: list[str] = []

    def lookup(sha256: str) -> ReferencedFile | None:
        hashing_threads.add(threading.get_ident())
        return files.get(sha256)

    class _Store:
        """A response cache that holds nothing and records the key it was asked for."""

        def cache_available(self) -> bool:
            return True

        async def get(self, key_hash: str) -> None:
            looked_up.append(key_hash)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                request_cache_store=_Store(),
                settings=SimpleNamespace(request_cache_enabled=True),
            )
        )
    )
    plugin = SimpleNamespace(
        custom_llm_provider=_PROVIDER,
        participates_in_global_cache=lambda model=None: True,
        chat_parameter_rules=lambda model, auth_type: (),
        available_auth_modes=lambda: _AUTH_MODES,
        global_cache_projection=_projection,
    )

    async def _look_up() -> tuple[int, Any]:
        outcome = await look_up_global_cache(
            cast(Request, request),
            body=by_reference,
            plugin=cast(ProviderPluginBase, plugin),
            controls=GlobalCacheControls(participate=True),
            files=lookup,
        )
        return threading.get_ident(), outcome

    loop_thread, outcome = asyncio.run(_look_up())

    assert outcome.status == "miss"
    assert looked_up == [_response_key(inline)]
    assert hashing_threads and loop_thread not in hashing_threads


# --- the twin reproduces the canonical form byte for byte ------------------------------------

_PNG = ReferencedFile("image/png", base64.b64encode(bytes(range(256)) * 9).decode("ascii"))
_PDF = ReferencedFile("application/pdf", base64.b64encode(b"%PDF-1.7 tiny").decode("ascii"))
# Longer than one hashing chunk, so the streamed file crosses chunk boundaries.
_BIG = ReferencedFile(
    "image/jpeg", base64.b64encode(random.Random(7).randbytes(3_000_000)).decode()
)
# Not base64 at all: proves the twin escapes the file's text exactly as json.dumps would, so the
# digest never depends on the file happening to need no escaping.
_ODD = ReferencedFile("text/x-odd", 'q"uote\\back\nline\x00nul sep é 😀' * 50_000)
_FILES: dict[str, ReferencedFile] = {
    "a" * 64: _PNG,
    "b" * 64: _PDF,
    "c" * 64: _BIG,
    "d" * 64: _ODD,
}
_REF_PNG = BlobReference("a" * 64)
_REF_PDF = BlobReference("b" * 64)
_REF_BIG = BlobReference("c" * 64)
_REF_ODD = BlobReference("d" * 64)


def _inlined(value: Any) -> Any:
    """``value`` with every reference written as today's ``data:`` URI string."""
    if isinstance(value, BlobReference):
        file = _FILES[value.sha256]
        return f"data:{file.media_type};base64,{file.base64_text}"
    if isinstance(value, dict):
        return {k: _inlined(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_inlined(v) for v in value]
    return value


_SHAPES: dict[str, dict[str, Any]] = {
    "empty": {},
    "no reference at all": {"model": "m", "messages": [{"role": "user", "content": "hi"}]},
    "one picture part": {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": _REF_PNG}},
                    {"type": "text", "text": "what is this?"},
                ],
            }
        ]
    },
    "nested parts, keys out of order": {
        "z": {"y": [{"x": [_REF_PDF, {"b": 1, "a": [None, True, False]}]}]},
        "a": [[[]], {}, [{}]],
    },
    "unicode text beside a reference": {
        "text": 'café "quoted" \\ back\tslash \n new \x01     😀 \U0001f9ea',
        "ключ": "значение",
        "file": _REF_PNG,
    },
    "several references": {"parts": [_REF_PNG, _REF_PDF, _REF_BIG]},
    "the same reference twice": {"first": _REF_PNG, "again": [_REF_PNG], "pdf": _REF_PDF},
    "a file whose text needs escaping": {"odd": _REF_ODD, "after": "tail"},
    "numbers and literals": {
        "ints": [0, -1, 2**70, True],
        "floats": [0.1, -0.0, 1e300, 5e-324, 1.0, 2.5],
        "none": None,
    },
    "a tuple serialises as an array": {"t": (1, "two", (_REF_PNG,))},
    "a reference at the top of an array": {"files": [_REF_PNG]},
}


@pytest.mark.parametrize("shape", list(_SHAPES), ids=list(_SHAPES))
def test_the_twin_hashes_the_bytes_of_todays_canonical_form(shape: str) -> None:
    """Each shape keys by reference exactly as its inlined form keys today."""
    mapping: dict[str, Any] = _SHAPES[shape]

    assert canonical_digest_with_references(mapping, _FILES.get) == canonical_digest(
        _inlined(mapping)
    )


_TEXT_ALPHABET = 'ab Zé"\\/\n\t\x00\x1f\x7f é中😀{}[]:,'


def _random_text(rng: random.Random) -> str:
    """A short string drawn from characters JSON escapes, keeps raw, or encodes as UTF-8."""
    return "".join(rng.choice(_TEXT_ALPHABET) for _ in range(rng.randint(0, 12)))


def _random_tree(rng: random.Random, depth: int) -> Any:
    """One random JSON-shaped value with references sprinkled where strings could be."""
    roll: float = rng.random()
    if depth > 4 or roll < 0.35:
        return rng.choice(
            [
                _random_text(rng),
                rng.choice([_REF_PNG, _REF_PDF, _REF_ODD]),
                rng.randint(-(2**40), 2**40),
                rng.uniform(-1e6, 1e6),
                rng.choice([True, False, None]),
            ]
        )
    if roll < 0.65:
        return [_random_tree(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {_random_text(rng): _random_tree(rng, depth + 1) for _ in range(rng.randint(0, 4))}


@pytest.mark.parametrize("seed", range(200))
def test_the_twin_matches_on_random_trees(seed: int) -> None:
    """Property: for any tree, by-reference digest == today's digest of the inlined tree."""
    rng = random.Random(seed)
    mapping: dict[str, Any] = {"root": _random_tree(rng, 0), "file": _REF_PNG}

    assert canonical_digest_with_references(mapping, _FILES.get) == canonical_digest(
        _inlined(mapping)
    )


def _nested(depth: int) -> dict[str, Any]:
    """A mapping ``depth`` objects deep."""
    value: dict[str, Any] = {}
    for _ in range(depth):
        value = {"n": value}
    return value


@pytest.mark.parametrize(
    "bad",
    [{1: "a"}, {"x": float("nan")}, {"x": float("inf")}, {"x": object()}, _nested(70)],
    ids=["non-string key", "nan", "infinity", "unsupported type", "too deep"],
)
def test_the_twin_refuses_what_todays_form_refuses(bad: dict[Any, Any]) -> None:
    """Guard parity: what cannot be one exact byte string is refused by both, the same way."""
    with pytest.raises(CanonicalizationError):
        canonical_digest(bad)
    with pytest.raises(CanonicalizationError):
        canonical_digest_with_references({"file": _REF_PNG, "bad": bad}, _FILES.get)


def test_a_mapping_json_cannot_write_fails_the_twin_as_it_fails_today() -> None:
    """A read-only mapping passes the guard but not ``json.dumps``: both raise ``TypeError``."""
    odd: dict[str, Any] = {"m": MappingProxyType({"a": 1})}

    with pytest.raises(TypeError):
        canonical_digest(odd)
    with pytest.raises(TypeError):
        canonical_digest_with_references({**odd, "file": _REF_PNG}, _FILES.get)


def test_the_twin_does_not_mutate_its_input() -> None:
    """The request is still dispatched after keying, so the twin must leave it untouched."""
    mapping: dict[str, Any] = copy.deepcopy(_SHAPES["several references"])
    before: dict[str, Any] = copy.deepcopy(mapping)

    canonical_digest_with_references(mapping, _FILES.get)

    assert mapping == before
