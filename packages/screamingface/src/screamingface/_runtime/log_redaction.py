"""Redact structural prompt carriers before they reach runtime.log (OME-1050).

FEATURE: local runtime log hygiene. ``capture_runtime_log`` makes runtime.log the process's
ENTIRE stdout/stderr sink: ``print``, ``warnings.warn``, ``logging.lastResort`` and uncaught
tracebacks all land there. So per-producer discipline cannot keep prompts out, and the sink
has to.

SCOPE (owner decision, option A). Only three STRUCTURAL carriers are redacted:

- url4 ``q=`` query values. A url4 expression carries the prompt as its intent text, and
  sub-fetch URLs and error messages interpolate it.
- litellm's ``Messages: `...` `` exception suffix.
- litellm's debug curl ``-d '...'`` request body.

Unmarked free text is OUT OF SCOPE. A prompt interpolated verbatim with no carrier around it,
such as a url4 parser error quoting the expression, is not detected. Partial redaction of free
text is unreliable and creates false confidence; that is the repo's established posture, in
``report_intake/classification/content.py``.

Two choke points, because neither covers the other:

- the record factory, which reaches every handler of every logger, not only this file;
- ``redact`` per line in ``RuntimeLog``, which is the only thing that sees ``print``, warnings
  and tracebacks, since none of those creates a ``LogRecord``.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Callable, Iterator
from typing import Any

REDACTED = "[REDACTED]"

# WHY the stop set `& # ' " newline` and NOT whitespace: an unencoded value may contain
# spaces, and stopping early would leak the rest. A quote or the next parameter is the end of
# the value; past that we would rather over-redact than leak.
_URL4_QUERY = re.compile(r"([?&]q=)[^&#'\"\n]*")
# litellm: `extra_information += f"\nMessages: `{messages}`"`. The repr runs to the end of
# its line.
_LITELLM_MESSAGES = re.compile(r"(\bMessages: ).*")
# litellm: `curl_command += f"-d '{body}'\n"`. Anchored on whitespace or the line start, so a
# token merely ending in "-d" is left alone.
_LITELLM_CURL_BODY = re.compile(r"(?<!\S)-d '.*")

_FLAG = "_screamingface_runtime_log_redaction"


def redact(text: str) -> str:
    """Replace every structural carrier's payload in ``text`` with ``REDACTED``."""
    text = _URL4_QUERY.sub(rf"\g<1>{REDACTED}", text)
    text = _LITELLM_MESSAGES.sub(rf"\g<1>{REDACTED}", text)
    return _LITELLM_CURL_BODY.sub(f"-d '{REDACTED}'", text)


def _chain_has_redaction(factory: object) -> bool:
    # WHY walk the chain and not just the top: aigateway installs its own wrappers through the
    # same hook, so a top-only check would wrap again under every interleaving. That growth is
    # the RecursionError aigateway's `factory_chain_has` exists to prevent (OME-938).
    seen: set[int] = set()
    while factory is not None and id(factory) not in seen:
        seen.add(id(factory))
        if getattr(factory, _FLAG, False):
            return True
        factory = getattr(factory, "__wrapped__", None)
    return False


def _wrap(previous: Callable[..., logging.LogRecord]) -> Callable[..., logging.LogRecord]:
    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        try:
            rendered = record.getMessage()
        except (TypeError, ValueError):
            # A malformed record: leave it intact for logging's own "--- Logging error ---".
            return record
        redacted = redact(rendered)
        if redacted != rendered:
            record.msg, record.args = redacted, ()
        return record

    setattr(factory, _FLAG, True)
    factory.__wrapped__ = previous  # type: ignore[attr-defined]
    return factory


@contextlib.contextmanager
def redacting_record_factory() -> Iterator[None]:
    """Wrap the installed record factory with redaction for the duration of the block.

    INVARIANT: it WRAPS and never replaces, so a factory installed earlier, such as aigateway's
    token redaction or correlation id, keeps running.
    """
    previous = logging.getLogRecordFactory()
    if _chain_has_redaction(previous):
        yield
        return
    ours = _wrap(previous)
    logging.setLogRecordFactory(ours)
    try:
        yield
    finally:
        # WHY only when still on top: if something wrapped us during the block, restoring
        # `previous` would silently drop its wrapper. Ours then stays in the chain, where it
        # only ever redacts.
        if logging.getLogRecordFactory() is ours:
            logging.setLogRecordFactory(previous)
