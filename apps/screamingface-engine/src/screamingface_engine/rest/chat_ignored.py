"""The request fields that the Engine ignored, for the reply (RR-S12, owner answer R1).

The reply names them in `screamingface.ignored_parameters`. INVARIANT: the names are request
data. No log line, metric label, span attribute or RequestFacts field may hold them.
"""

from __future__ import annotations

from typing import cast

import pydantic_core

from screamingface_engine.chat.wire import ChatCompletionRequest

__all__ = ["MAX_IGNORED_NAMES", "MAX_IGNORED_NAME_CHARS", "READ_PARAMETERS", "ignored_parameters"]

# INVARIANT (RR-S12): the Engine reads exactly the fields of the wire model, which has no aliases.
READ_PARAMETERS: frozenset[str] = frozenset(ChatCompletionRequest.model_fields)
# WHY: the proposed limits of RR-S12; the reply stays small.
MAX_IGNORED_NAME_CHARS = 64
MAX_IGNORED_NAMES = 32


def ignored_parameters(raw: bytes) -> tuple[str, ...]:
    """The sorted names of the top-level fields that are not null and not read by the Engine."""
    # WHY a second parse of the top level: the wire model drops unknown keys (the tests pin it),
    # and the record must never hold them. This parse runs BEFORE the main parse, so its
    # throw-away tree is freed before the parsed request and the record exist (CC-S35). A large
    # body is parsed in the worker thread.
    try:
        value: object = pydantic_core.from_json(raw)
    except ValueError:
        # WHY: a body that is not JSON gets its 400 from the main parse, which runs after this one.
        return ()
    if not isinstance(value, dict):
        return ()
    # WHY cast: the keys of a JSON object are always str.
    fields = cast("dict[str, object]", value)
    names = sorted(
        name
        for name, field in fields.items()
        if field is not None and name not in READ_PARAMETERS and len(name) <= MAX_IGNORED_NAME_CHARS
    )
    return tuple(names[:MAX_IGNORED_NAMES])
