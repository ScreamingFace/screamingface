"""The chat-input store: a second BlobStore on the run blob objects, for CHAT_INPUT records only.

FEATURE: chat-run (erd §1.1). The store has its own policy: one media type, and a schema check in
place of the signature check. The App and the Runner build it with one function
(`artifacts.wiring.chat_input_store_from_values`), so the two halves agree on the policy.

WHY a separate store: the public PUT /blob route keeps the attachment store. A chat input is
never an attachment, and an attachment is never read as a chat input.
"""

from __future__ import annotations

from screamingface_engine.artifacts.blob_objects import BlobObjects
from screamingface_engine.artifacts.blob_schema import BlobPolicy
from screamingface_engine.artifacts.blobs import BlobStore
from screamingface_engine.chat.input import (
    CHAT_INPUT_MEDIA_TYPE,
    MAX_CHAT_INPUT_BYTES,
    ChatInputError,
    decode_chat_input,
)

__all__ = ["CHAT_INPUT_POLICY", "chat_input_store", "is_chat_input_record"]


def is_chat_input_record(body: bytes) -> bool:
    """Whether `body` parses as a CHAT_INPUT record."""
    try:
        decode_chat_input(body)
    except ChatInputError:
        return False
    return True


CHAT_INPUT_POLICY = BlobPolicy(
    max_bytes=MAX_CHAT_INPUT_BYTES,
    media_types=frozenset({CHAT_INPUT_MEDIA_TYPE}),
    verify_signature=False,
    content_check=is_chat_input_record,
)


def chat_input_store(objects: BlobObjects) -> BlobStore:
    """The chat-input store over `objects`, under CHAT_INPUT_POLICY."""
    return BlobStore(objects, CHAT_INPUT_POLICY)
