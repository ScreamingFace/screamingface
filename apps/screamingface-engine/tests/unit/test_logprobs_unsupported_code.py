"""The `logprobs_unsupported` code is declared, permanent and engine-authored (E4b part 3, P13).

Pins LC#10: the code is in the declared vocabulary and in the engine's reserved codes, the class
helper mints it as permanent with the fixed text, and the fixed text is published verbatim.
A separate module (append-only gate).
"""

from __future__ import annotations

from logprobs_support import FIXED_TEXT

from screamingface_engine.benchmarks.contract import (
    DECLARED_FAILURE_CODES,
    is_declared_failure_code,
)
from screamingface_engine.benchmarks.failure_classes import logprobs_unsupported
from screamingface_engine.error_text import (
    ENGINE_ERROR_CODES,
    ENGINE_RESERVED_CODES,
    public_message,
)


def test_logprobs_unsupported_is_a_declared_permanent_engine_code() -> None:
    assert "logprobs_unsupported" in DECLARED_FAILURE_CODES
    assert is_declared_failure_code("logprobs_unsupported")
    assert "logprobs_unsupported" in ENGINE_ERROR_CODES
    assert "logprobs_unsupported" in ENGINE_RESERVED_CODES
    error = logprobs_unsupported()
    assert (error.code, error.permanent, str(error)) == (
        "logprobs_unsupported",
        True,
        FIXED_TEXT,
    )


def test_the_fixed_text_is_published_verbatim() -> None:
    """CHAR: the fixed text is short and passes the public message gate unchanged."""
    assert len(FIXED_TEXT) <= 200
    assert public_message(FIXED_TEXT, default="withheld") == FIXED_TEXT
