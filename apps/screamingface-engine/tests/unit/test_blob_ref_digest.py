"""One ref-to-digest rule for the run blob store.

FEATURE: chat-run. A `blob:sha256/<hex>` ref maps to its `sha256:<hex>` digest in one place.
"""

from __future__ import annotations

from screamingface_engine.artifacts.blob_schema import StoredBlob, blob_ref_digest


def test_blob_ref_digest_maps_a_ref_to_its_digest() -> None:
    sha = "ab" * 32

    assert blob_ref_digest("blob:sha256/" + sha) == "sha256:" + sha
    assert blob_ref_digest(StoredBlob(sha, 3, "application/pdf").ref) == "sha256:" + sha


def test_blob_ref_digest_refuses_a_value_that_is_not_a_blob_ref() -> None:
    assert blob_ref_digest("sha256:" + "ab" * 32) is None
    assert blob_ref_digest("") is None
