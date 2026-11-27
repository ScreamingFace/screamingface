"""A chat content part may name a Case file by blob reference (OME-1970, PR 5).

FEATURE: Case files by blob reference. The Engine uploads each Case file once per run
(`PUT /v1/blobs/sha256/{digest}`, PR 4); each model call then carries a **reference part**, the
inline part's shape with ``blob:sha256/<64 hex>`` where the ``data:`` URI stood, plus the file's
type and size in ``x_media_type`` and ``x_size``.

INVARIANT under test: every admission check that judges an inline part judges a reference part
the same way (role, file and modality policy); an adapter never meets one, because the swap
inside the upstream slot turns it back into exactly the inline part; and a file outside the
caller's run, or one the store dropped, is ``blob_unknown`` (503, not permanent) before any
upstream spend.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any, cast

import pytest

from aigateway.core.blob_refs import (
    BLOB_UNKNOWN_CODE,
    BlobUnknown,
    RunFiles,
    key_form,
    references_in,
)
from aigateway.core.content_parts import (
    BlobRefPart,
    UnsupportedContentPart,
    check_input_modalities,
    check_messages,
    parse_blob_reference,
    parse_content,
    provider_media_refusal,
    text_only,
)
from aigateway.core.media_intake import refuse_remote_media
from aigateway.core.media_store import BlobScope, MediaStore, StoredMedia
from aigateway.core.request_cache.reference_digest import BlobReference

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 40
PDF = b"%PDF-1.7\n" + b"page " * 40
PNG_SHA = hashlib.sha256(PNG).hexdigest()
PDF_SHA = hashlib.sha256(PDF).hexdigest()
PNG_B64 = base64.b64encode(PNG).decode("ascii")
PDF_B64 = base64.b64encode(PDF).decode("ascii")
CALLER = "11111111-1111-1111-1111-111111111111"
# Stand-ins for two runs' random tokens (the Engine mints `secrets.token_urlsafe(32)`).
RUN_1 = "run1-" + "A" * 38
RUN_2 = "run2-" + "B" * 38


def _image_ref(**overrides: Any) -> dict[str, Any]:
    part: dict[str, Any] = {
        "type": "image_url",
        "image_url": {"url": f"blob:sha256/{PNG_SHA}", "detail": "high"},
        "x_media_type": "image/png",
        "x_size": len(PNG),
    }
    part.update(overrides)
    return part


def _file_ref(**overrides: Any) -> dict[str, Any]:
    part: dict[str, Any] = {
        "type": "file",
        "file": {"file_data": f"blob:sha256/{PDF_SHA}", "filename": "case.pdf"},
        "x_media_type": "application/pdf",
        "x_size": len(PDF),
    }
    part.update(overrides)
    return part


def _inline_image() -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{PNG_B64}", "detail": "high"},
    }


def _inline_file() -> dict[str, Any]:
    return {
        "type": "file",
        "file": {"file_data": f"data:application/pdf;base64,{PDF_B64}", "filename": "case.pdf"},
    }


def _body(*parts: dict[str, Any], role: str = "user") -> dict[str, Any]:
    return {
        "model": "fake/model",
        "messages": [
            {"role": role, "content": [{"type": "text", "text": "what is shown?"}, *parts]}
        ],
    }


def _store_with(*files: tuple[str, StoredMedia], token: str = RUN_1) -> MediaStore:
    store = MediaStore(max_bytes=10_000_000, scope_ttl_seconds=600)
    scope: BlobScope | None = BlobScope.of(CALLER, token)
    assert scope is not None
    for digest, media in files:
        store.put(scope, digest, media)
    return store


def _png_media() -> StoredMedia:
    return StoredMedia(media_type="image/png", size_bytes=len(PNG), base64_text=PNG_B64)


def _pdf_media() -> StoredMedia:
    return StoredMedia(media_type="application/pdf", size_bytes=len(PDF), base64_text=PDF_B64)


def _run_files(store: MediaStore, token: str | None = RUN_1) -> RunFiles:
    return RunFiles(store, BlobScope.of(CALLER, token))


# --- the wire part ----------------------------------------------------------------------------


def test_an_image_reference_part_parses_with_its_declared_type_size_and_detail() -> None:
    part = parse_blob_reference(_image_ref(), provider="fake")

    assert part == BlobRefPart(
        kind="image", mime="image/png", sha256=PNG_SHA, size_bytes=len(PNG), detail="high"
    )


def test_a_file_reference_part_parses_with_its_filename() -> None:
    part = parse_blob_reference(_file_ref(), provider="fake")

    assert part == BlobRefPart(
        kind="file",
        mime="application/pdf",
        sha256=PDF_SHA,
        size_bytes=len(PDF),
        filename="case.pdf",
    )


def test_an_inline_part_is_not_a_reference() -> None:
    assert parse_blob_reference(_inline_image(), provider="fake") is None
    assert parse_blob_reference(_inline_file(), provider="fake") is None


@pytest.mark.parametrize(
    "part",
    [
        # Not exactly 64 lowercase hex characters: one file must have one name.
        _image_ref(image_url={"url": f"blob:sha256/{PNG_SHA.upper()}"}),
        _image_ref(image_url={"url": f"blob:sha256/{PNG_SHA[:63]}"}),
        _image_ref(image_url={"url": f"blob:md5/{PNG_SHA}"}),
        # x_media_type is required, and must fit the part type, as an inline part's MIME must.
        {k: v for k, v in _image_ref().items() if k != "x_media_type"},
        _image_ref(x_media_type="application/pdf"),
        _file_ref(x_media_type="image/png"),
        _image_ref(x_media_type=7),
        # x_size is the decoded size: a positive integer, never a bool or a string.
        {k: v for k, v in _image_ref().items() if k != "x_size"},
        _image_ref(x_size=0),
        _image_ref(x_size=True),
        _image_ref(x_size="300"),
        # WHY a closed shape: any other key would ride to the provider beside the swapped file,
        # or change the cache key away from the inline request's.
        _image_ref(x_extra="1"),
        _image_ref(image_url={"url": f"blob:sha256/{PNG_SHA}", "file_id": "f"}),
        _file_ref(file={"file_data": f"blob:sha256/{PDF_SHA}", "file_id": "file-1"}),
        _image_ref(image_url={"url": f"blob:sha256/{PNG_SHA}", "detail": "huge"}),
    ],
)
def test_a_malformed_reference_part_is_refused_with_the_typed_422(part: dict[str, Any]) -> None:
    with pytest.raises(UnsupportedContentPart) as refused:
        parse_blob_reference(part, provider="fake")

    assert refused.value.status_code == 422
    assert refused.value.info["code"] == "unsupported_content_part"


# --- admission accepts it, under the same policy as an inline part -----------------------------


def test_the_data_only_guard_admits_a_reference_it_never_fetches() -> None:
    # WHY: `blob:` is not a URL; the file is in the gateway's own memory.
    refuse_remote_media(
        _body(_image_ref(), _file_ref())["messages"],
        provider="fake",
        allow_remote_image_urls=False,
    )


def test_the_data_only_guard_still_refuses_a_malformed_reference() -> None:
    with pytest.raises(UnsupportedContentPart):
        refuse_remote_media(
            _body(_image_ref(x_size=-1))["messages"], provider="fake", allow_remote_image_urls=False
        )


def test_check_messages_admits_a_reference_where_media_is_allowed() -> None:
    check_messages(
        _body(_image_ref(), _file_ref())["messages"],
        provider="gemini",
        media_roles=frozenset({"user"}),
        allow_remote_images=False,
    )


def test_check_messages_applies_the_role_and_file_policy_to_a_reference() -> None:
    with pytest.raises(UnsupportedContentPart, match="media in a system message"):
        check_messages(
            _body(_image_ref(), role="system")["messages"],
            provider="gemini",
            media_roles=frozenset({"user"}),
            allow_remote_images=False,
        )
    # Ollama carries images but drops file parts: a PDF reference is refused, as inline is.
    with pytest.raises(UnsupportedContentPart, match="files_unsupported"):
        check_messages(
            _body(_file_ref())["messages"],
            provider="ollama",
            media_roles=frozenset({"user"}),
            allow_remote_images=False,
            allow_files=False,
        )


def test_a_system_slot_refuses_a_reference_as_media() -> None:
    with pytest.raises(UnsupportedContentPart, match="media in a system message"):
        text_only([_image_ref()], provider="anthropic", role="system")


def test_the_modality_backstop_judges_a_reference_by_its_part_type() -> None:
    with pytest.raises(UnsupportedContentPart, match="modality_unsupported pdf"):
        check_input_modalities(
            _body(_file_ref())["messages"], provider="fake", modalities=["text", "image"]
        )
    check_input_modalities(
        _body(_image_ref())["messages"], provider="fake", modalities=["text", "image"]
    )


def test_a_providers_415_names_the_references_declared_type() -> None:
    refusal = provider_media_refusal(415, _body(_image_ref())["messages"], provider="fake")

    assert refusal is not None
    assert refusal.info["reason"] == "provider_unsupported_media image/png"


def test_an_adapter_never_carries_an_unresolved_reference() -> None:
    # INVARIANT: the swap runs before any adapter; a reference reaching one is refused, never
    # sent upstream as text.
    with pytest.raises(UnsupportedContentPart, match="unresolved_blob_reference"):
        parse_content([_image_ref()], provider="gemini")


# --- the request's references, its key form and the swap ---------------------------------------


def test_references_in_lists_every_reference_part_in_order() -> None:
    refs = references_in(
        _body(_file_ref(), _inline_image(), _image_ref())["messages"], provider="f"
    )

    assert [ref.sha256 for ref in refs] == [PDF_SHA, PNG_SHA]


def test_the_key_form_is_the_inline_part_with_a_blob_reference_where_the_uri_stood() -> None:
    body = _body(_image_ref(), _file_ref())

    keyed = key_form(body)

    # WHY no `x_` keys: an inline part has none, and the key must be the inline request's.
    assert keyed["messages"][0]["content"][1:] == [
        {"type": "image_url", "image_url": {"url": BlobReference(PNG_SHA), "detail": "high"}},
        {"type": "file", "file": {"file_data": BlobReference(PDF_SHA), "filename": "case.pdf"}},
    ]
    assert body == _body(_image_ref(), _file_ref()), "the caller's body is not modified"


def test_the_swap_gives_exactly_the_inline_request() -> None:
    files = _run_files(_store_with((PNG_SHA, _png_media()), (PDF_SHA, _pdf_media())))
    body = _body(_image_ref(), _file_ref())

    assert files.inline(body) == _body(_inline_image(), _inline_file())
    assert body == _body(_image_ref(), _file_ref()), "the caller's body is not modified"


def test_the_scope_check_passes_for_this_runs_files() -> None:
    files = _run_files(_store_with((PNG_SHA, _png_media())))

    files.require(references_in(_body(_image_ref())["messages"], provider="f"), provider="f")


@pytest.mark.parametrize("token", [RUN_2, None, "   "])
def test_another_runs_token_or_no_token_is_blob_unknown(token: str | None) -> None:
    files = _run_files(_store_with((PNG_SHA, _png_media())), token=token)

    with pytest.raises(BlobUnknown) as unknown:
        files.require(references_in(_body(_image_ref())["messages"], provider="f"), provider="f")

    # WHY 503: "not permanent" — the Engine uploads the file again and repeats the call (PR 8).
    assert unknown.value.status_code == 503
    detail = cast("dict[str, str]", unknown.value.detail)
    assert detail["code"] == BLOB_UNKNOWN_CODE == "blob_unknown"
    # INVARIANT: the refusal names the file by a prefix only, never the token or the bytes.
    assert RUN_1 not in str(unknown.value.detail)
    assert PNG_B64[:40] not in str(unknown.value.detail)


def test_a_file_never_uploaded_is_blob_unknown() -> None:
    files = _run_files(_store_with((PDF_SHA, _pdf_media())))

    with pytest.raises(BlobUnknown):
        files.require(references_in(_body(_image_ref())["messages"], provider="f"), provider="f")


@pytest.mark.parametrize(
    "part",
    [_image_ref(x_media_type="image/jpeg"), _image_ref(x_size=len(PNG) + 1)],
)
def test_a_reference_whose_type_or_size_differs_from_the_stored_file_is_refused(
    part: dict[str, Any],
) -> None:
    # WHY: the key and the provider request use the stored file's type, so a request labelled
    # otherwise would be keyed and sent as something it did not say.
    files = _run_files(_store_with((PNG_SHA, _png_media())))

    with pytest.raises(UnsupportedContentPart, match="blob_reference_mismatch"):
        files.require(references_in(_body(part)["messages"], provider="f"), provider="f")


def _forget_everything(scope: BlobScope | None, digest: str) -> StoredMedia | None:
    """Stands in for `MediaStore.get` once the store has dropped every file."""
    return None


def test_a_file_dropped_after_the_scope_check_is_blob_unknown_at_the_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store_with((PNG_SHA, _png_media()))
    files = _run_files(store)
    files.require(references_in(_body(_image_ref())["messages"], provider="f"), provider="f")
    monkeypatch.setattr(store, "get", _forget_everything)

    with pytest.raises(BlobUnknown):
        files.inline(_body(_image_ref()))


def test_the_lookup_reads_the_store_live_until_the_swap(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store_with((PNG_SHA, _png_media()))
    files = _run_files(store)
    assert files.lookup(PNG_SHA) is not None
    with monkeypatch.context() as dropped:
        dropped.setattr(store, "get", _forget_everything)
        assert files.lookup(PNG_SHA) is None, "before the swap, a dropped file is gone"

    files.inline(_body(_image_ref()))
    monkeypatch.setattr(store, "get", _forget_everything)

    # WHY: the frozen-copy capture after the provider call keys the file the call actually sent.
    found = files.lookup(PNG_SHA)
    assert found is not None and found.base64_text == PNG_B64
