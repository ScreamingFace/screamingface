"""OME-1026 — the process-wide sink for unexpected background-discovery errors.

FEATURE: a background programming error cannot pass silently. A refresh nobody awaits
that raises something other than ``DiscoveryError`` is a bug, and this module is where
it waits to be observed — by test teardown, or by an operator reading it.

WHY it is its own module and not part of :mod:`aigateway.core.background_refresh`: the
manager owns per-app TASKS and dies with its app; this owns PROCESS-wide diagnostics
and their thread-safety. They are used together and change for different reasons.

INVARIANT (adversarial B3): what is retained is a sanitized immutable record, never
the exception — see :class:`UnexpectedRecord`. Every read-modify-write of the two
channels happens under one lock, so the cap is exact and the dropped count lossless.

INVARIANT (last-mile): the observed marker is part of that protected state, not a
separate flag. Observation and recording linearize under the one sink lock, so an
observed error is never left retained and an unobserved one is never lost.
"""

from __future__ import annotations

import logging
import threading
from typing import NamedTuple

logger = logging.getLogger(__name__)

# WHY 32 (F6): the sink exists to REVEAL an unbounded-allocation class of bug, so it
# must not be one. The first few retained errors carry all the diagnostic value; past
# that the count is what matters, and it is logged.
_MAX_RETAINED_UNEXPECTED = 32

# INVARIANT (F6): an unexpected exception from a background refresh is RETAINED here
# until something observes it. Logging alone is not observation: the suite's no-egress
# tripwire raises ``AssertionError`` inside a task nobody awaited, so a test that
# genuinely reached the internet would otherwise pass green with a log line nobody read.
#
# INVARIANT (adversarial B3 — what is retained must be safe to retain): a RECORD, never
# the exception. Keeping the exception kept its ``__traceback__``, hence every frame it
# unwound through, hence those frames' locals — and a credentialed refresh has an
# ``x-api-key`` in exactly such a local. An independent probe read one back out of this
# sink. The record below is a bounded immutable tuple of strings and an int, so there is
# nothing to read out.
#
# INVARIANT (adversarial B3 — exact under concurrency): producers reach this module from
# the app's event-loop thread while test bodies and ``TestClient`` teardown read it from
# another. Every read-modify-write of the two channels happens under ``_sink_lock``, so
# the cap is exact (33 retained against a cap of 32 was reproduced without it) and the
# dropped count is lossless (two drops recorded one increment). The lock sections are
# synchronous and small, and nothing awaits while holding it.
#
# INVARIANT (last-mile — the marker is part of the protected state): the observed MARKER
# and the retained RECORD encode one fact, "is this error still owed an observer?", so
# both halves are read and written under this same lock. Protecting only the list left
# the pair inconsistent:
#
#     producer reads the marker as False   (outside the lock)
#     observer stamps the marker and scans an empty list
#     producer appends its record          (nobody will ever remove it)
#
# which failed teardown for an error a caller had already observed. Under one lock the
# two operations linearize: observation first means the producer sees the marker and
# does not append; recording first means the observation finds the record and removes
# it. Both orders end with nothing retained, and neither holds the lock across I/O.
_sink_lock = threading.Lock()


class UnexpectedRecord(NamedTuple):
    """One background programming error, sanitized down to what is safe to keep.

    ``key`` is the cache identity rendered as a bounded string — ownership metadata
    only, never a credential. ``type_name`` names the bug class, which is the whole
    diagnosis an operator acts on. ``token`` is the exception's identity, used ONLY to
    match a later :func:`mark_observed` while the owning task is still alive; it is not
    a reference and cannot be dereferenced.
    """

    key: str
    type_name: str
    token: int


_retained_unexpected: list[UnexpectedRecord] = []
_dropped_unexpected = 0

# A retained key is a diagnostic string, so it is bounded like any other log field.
_MAX_KEY_CHARS = 200

# Marker attribute stamped on an exception that already reached a caller.
# WHY an attribute on the exception rather than a module-level set: a set of exceptions
# would pin them — and their tracebacks' frame locals, which may hold an auth context —
# alive for the process's lifetime, and built-in exceptions like ``AssertionError``
# cannot be weak-referenced, so a ``WeakSet`` is not available either. The marker lives
# and dies with the exception object and is invisible to anything that re-raises it.
_OBSERVED_ATTR = "_aigw_discovery_observed"


def _safe_key(key: object) -> str:
    """The identity as a bounded string.

    # WHY string-ifying rather than keeping the key object: the key is a tuple of
    # ownership metadata today, but retaining an arbitrary object is how a future key
    # type would quietly pull whatever it references into a process-lifetime sink.
    """
    return str(key)[:_MAX_KEY_CHARS]


def mark_observed(exc: BaseException) -> None:
    """Record that ``exc`` was surfaced to a caller, so the sink need not retain it.

    The explicit observation point. A refresh whose bug was re-raised to an awaiting
    request has already failed loudly; retaining it as well would make the suite's
    teardown assertion fire for an error a test deliberately asserted.

    # AIDEV-NOTE: the done-callback that fills the sink runs BEFORE an awaiting caller
    # resumes (it is registered at task creation, and callbacks fire in order), so this
    # must both remember the exception AND remove an already-retained record.
    # WHY matching on ``id(exc)`` is sound here: the caller holding ``exc`` keeps it
    # alive across this call, so the identity cannot have been reused. The sink itself
    # holds no reference — that is the point.
    # INVARIANT (last-mile): setting the marker and removing the record happen in ONE
    # lock section — see the protocol note at ``_sink_lock``. Stamping the marker
    # before taking the lock let a producer that had already read it as False append
    # afterwards, leaving a record for an error this call just observed.
    """
    token = id(exc)
    with _sink_lock:
        setattr(exc, _OBSERVED_ATTR, True)
        for index, record in enumerate(_retained_unexpected):
            if record.token == token:
                del _retained_unexpected[index]
                return


def take_unexpected() -> tuple[UnexpectedRecord, ...]:
    """Drain and return the retained background programming errors.

    Called by test teardown (and available to operators) as the observation point that
    turns a silent background bug into a failure.

    # INVARIANT (F6): this drains the retained RECORDS and deliberately leaves
    # ``dropped_unexpected()`` alone. Resetting it here — as this used to — erased the
    # only evidence that the sink had overflowed, so a burst of 40 failures could end
    # with an empty retained list and a zeroed counter: green, in the worst case.
    # Clearing the count is a separate, explicit statement (``reset_unexpected``).
    """
    with _sink_lock:
        drained = tuple(_retained_unexpected)
        _retained_unexpected.clear()
    return drained


def dropped_unexpected() -> int:
    """How many unexpected background errors exceeded the retention cap.

    Past ``_MAX_RETAINED_UNEXPECTED`` the sink can only count, and the count is the
    whole evidence that anything was lost — so it is readable on its own and is not
    cleared by draining the records.
    """
    with _sink_lock:
        return _dropped_unexpected


def drain_unexpected() -> tuple[tuple[UnexpectedRecord, ...], int]:
    """Atomically take BOTH channels and reset them: ``(records, dropped)``.

    # INVARIANT (adversarial B3): draining must be atomic with respect to producers.
    # Reading the records and clearing the counter in two steps let an error recorded
    # in between be cleared without ever being reported — reproduced as 30 errors lost
    # across 200 rounds. One lock section makes each error either fully reported or
    # still in the sink, never neither.
    """
    global _dropped_unexpected
    with _sink_lock:
        records = tuple(_retained_unexpected)
        dropped = _dropped_unexpected
        _retained_unexpected.clear()
        _dropped_unexpected = 0
    return records, dropped


def reset_unexpected() -> None:
    """Clear BOTH channels: the retained records and the dropped count.

    Test isolation, stated explicitly. One test's leak must not be attributed to the
    next, and — unlike ``take_unexpected`` — this says out loud that the overflow
    evidence is being discarded on purpose.
    """
    drain_unexpected()


def assert_no_unexpected(context: str = "") -> None:
    """Fail if background discovery work left an unobserved programming error.

    The observation point the retention above waits for. Called from test teardown so
    a bug in a refresh nobody awaited — the no-egress tripwire above all — fails the
    run instead of scrolling past in a log. Draining is part of failing: one leaked
    error must not cascade into every later test in the session.

    # INVARIANT (F6): BOTH channels fail this check. A retained record is one this
    # process can describe; a dropped one is one it can only count — and the counting
    # case is the SEVERE one, because reaching it means the failures came faster than
    # the sink could hold them. Checking the list alone made the loudest situation the
    # quietest.
    # INVARIANT (adversarial B3): the message is a report surface, so it carries the
    # sanitized record only. ``str(exc)`` used to be interpolated here, which put
    # upstream text — and anything a provider echoed into an error message — into an
    # assertion that lands in CI logs.
    """
    retained, dropped = drain_unexpected()
    if not retained and dropped == 0:
        return
    where = f" during {context}" if context else ""
    parts = [f"{record.key}: {record.type_name}" for record in retained]
    if dropped:
        parts.append(f"+{dropped} more dropped past the retention cap")
    raise AssertionError(f"unexpected background discovery error(s){where}: {', '.join(parts)}")


def record_unexpected(key: object, exc: BaseException) -> None:
    """Report — and sanitize — one unexpected background failure.

    The manager's default ``on_error``. Logged for operators and retained as a record
    for the observation point above.
    """
    # Sanitized like ModelCatalog's: the TYPE names the bug class for operators, the
    # message may carry upstream content and is dropped. ``exc_info`` is deliberately
    # NOT passed — a traceback would render frame locals in some configurations, and
    # this path can be holding a credential-bearing auth context.
    global _dropped_unexpected
    type_name = type(exc).__name__
    logger.error(
        "background discovery refresh failed unexpectedly key=%s type=%s",
        key,
        type_name,
    )
    # INVARIANT (last-mile): the marker is read in the SAME lock section that appends,
    # so an observation cannot land between the two — see the protocol note at
    # ``_sink_lock``. The record is built outside the lock on purpose: it is pure
    # sanitization of arguments this call already owns, and the section stays minimal.
    record = UnexpectedRecord(_safe_key(key), type_name, id(exc))
    with _sink_lock:
        if getattr(exc, _OBSERVED_ATTR, False):
            return
        if len(_retained_unexpected) >= _MAX_RETAINED_UNEXPECTED:
            _dropped_unexpected += 1
            return
        _retained_unexpected.append(record)


# The producer's original private name, kept as an alias: a test in this unit imports it,
# and the rename exists only so the producer has a public name the sink's own tests can
# drive from several threads (OME-1026 adversarial B3).
_log_unexpected = record_unexpected
