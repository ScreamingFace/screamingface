"""Which half of the Request a command route receives on stdin.

FEATURE: a `[commands]` route can take the INTENT on stdin instead of the context.
STORY: as a benchmark author, my cross-row reducer receives the JSON array of every row result
as its intent — and argv cannot carry it.

WHY this exists at all: on deployed Linux, a single argv token is capped at `MAX_ARG_STRLEN`
(32 pages = 131,072 bytes), independently of `ARG_MAX`. A reducer payload crosses that at roughly
four DRACO cases, and the failure is `OSError [Errno 7] Argument list too long` at exec — the run
dies rather than degrading. Stdin is a pipe and has no such bound.

Its own module rather than an append to `test_serve_backends.py`: prior tests are append-only, so
a new surface earns a new file. The default-behaviour case is RESTATED here rather than edited
there — it is the invariant this change most needs to keep, and it must fail loudly in the module
that introduces the selector.
"""

from __future__ import annotations

import pytest

from url4.cli._serve import make_command_handler
from url4.peer.server import Request

pytestmark = pytest.mark.asyncio

_ECHO_STDIN = ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())"]

# Comfortably past MAX_ARG_STRLEN (131,072). Not a round guess: the point is to sit ABOVE the
# kernel's per-argument ceiling while staying far below `ARG_MAX`, so a failure can only be the
# single-token limit and never the total-size one.
_OVERSIZE = "v" * 200_000


def _req(context: str = "the data", intent: str = "do it") -> Request:
    return Request(path="/cmd", context=context, intent=intent, params={})


async def test_default_still_pipes_the_context() -> None:
    """INVARIANT: unchanged for every existing caller and every existing url4.json.

    `/read` is `["cat"]` and exists only to echo the piped context; a changed default would
    silently turn that bridge into an intent echo.
    """
    handler = make_command_handler(_ECHO_STDIN, timeout=5.0)

    assert await handler(_req(context="ctx", intent="int")) == "ctx"


async def test_stdin_intent_pipes_the_intent() -> None:
    handler = make_command_handler(_ECHO_STDIN, timeout=5.0, stdin="intent")

    assert await handler(_req(context="ctx", intent="int")) == "int"


async def test_stdin_intent_still_substitutes_context_into_argv() -> None:
    """The two channels are independent — choosing stdin must not withdraw a substitution.

    The DRACO reducer needs exactly this: the operation token arrives as `--operation {context}`
    while the payload comes up the pipe.
    """
    handler = make_command_handler(
        ["python3", "-c", "import sys; sys.stdout.write('{context}|' + sys.stdin.read())"],
        timeout=5.0,
        stdin="intent",
    )

    assert await handler(_req(context="aggregate", intent="[1,2]")) == "aggregate|[1,2]"


async def test_unknown_stdin_source_is_rejected() -> None:
    """Loud at construction. A silent fallback to the context would hand a reducer the literal
    operation token in place of its payload, and it would score an empty run as a success."""
    with pytest.raises(ValueError, match="stdin"):
        make_command_handler(_ECHO_STDIN, timeout=5.0, stdin="params")


async def test_payload_past_the_argv_ceiling_survives_on_stdin() -> None:
    """THE REGRESSION. This is the whole point of the change."""
    handler = make_command_handler(_ECHO_STDIN, timeout=30.0, stdin="intent")

    assert await handler(_req(intent=_OVERSIZE)) == _OVERSIZE
