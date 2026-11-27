"""The chat-run marker: bound by the executor for the whole evaluation of one chat run.

The chat turn route reads its input through the bound reader factory, and the final-step endpoint
checks that the marker is bound before any other work (contracts C7).
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from screamingface_engine.world.attachment_parts import BlobReader

__all__ = ["chat_run_reader", "chat_run_scope"]

# WHY a ContextVar holding a factory: the marker exists only inside a chat run, and the handler
# builds the reader lazily, so a store that is not configured fails INSIDE the run.
_chat_run: contextvars.ContextVar[Callable[[], BlobReader] | None] = contextvars.ContextVar(
    "screamingface_engine_chat_run", default=None
)


@contextmanager
def chat_run_scope(reader: Callable[[], BlobReader]) -> Iterator[None]:
    """Mark the enclosed calls as one chat run that reads its input through `reader`."""
    token = _chat_run.set(reader)
    try:
        yield
    finally:
        _chat_run.reset(token)


def chat_run_reader() -> Callable[[], BlobReader] | None:
    """The bound reader factory, or None outside a chat run."""
    return _chat_run.get()
