"""Outer operation boundary shared by synchronous and asynchronous entry points."""

import asyncio
import functools
import inspect
import logging
import os
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, cast

from screamingface._analytics import prompt, wiring
from screamingface._analytics.core import Coordinator, Operation
from screamingface._core.engine_origin import is_hosted_engine

_active: ContextVar[int | None] = ContextVar("analytics_operation", default=None)
_LOG = logging.getLogger(__name__)


def _begin(
    name: str, interface: str, args: tuple, kwargs: dict
) -> tuple[Coordinator, Operation] | None:
    try:
        return _prepare(name, interface, args, kwargs)
    except (OSError, ValueError, RuntimeError):
        _LOG.debug("Analytics operation skipped")
        return None


def _prepare(name: str, interface: str, args: tuple, kwargs: dict):
    core = wiring.coordinator()
    if core.store.read().choice != "accepted":
        return None
    owner = args[0] if args else None
    endpoint = getattr(owner, "_engine_url", None)
    candidate = args[1] if len(args) > 1 else kwargs.get("candidates")
    if endpoint is None and name == "evaluation":
        from screamingface._default_client import default_client

        endpoint = getattr(default_client(), "engine_url", None)
        candidate = args[0] if args else kwargs.get("candidates")
    if not isinstance(endpoint, str):
        return None
    workflow = (
        "submission"
        if name == "submission"
        else ("raw_url4" if isinstance(candidate, str) else "recipe")
    )
    operation = core.begin(
        name,
        workflow,
        interface,
        wiring.origin(),
        "hosted" if is_hosted_engine(endpoint) else "byok",
    )
    return (core, operation) if operation is not None else None


def _finish(record: tuple[Coordinator, Operation] | None, outcome: str | None) -> None:
    if record is not None and outcome is not None:
        try:
            record[0].finish(record[1], outcome)
        except (OSError, ValueError, RuntimeError):
            _LOG.debug("Analytics terminal event skipped")


def _settle(record: tuple[Coordinator, Operation] | None, outcome: str | None) -> None:
    """In Colab, wait (bounded) until queued analytics events have been handed to the browser."""
    # WHY: Colab answers a background eval_js only while this cell runs; an upload sent after
    # the call returned is lost and resets consent (2026-11-19 trace). A cancelled call does
    # not wait: the user asked to stop, and its terminal event stays best-effort. `outcome is
    # None` means `_outcome` could not read `.ok` off the result (e.g. a detached evaluate()
    # returns a Run, not a Report) — that is an UNKNOWN outcome, not a reason to skip: a
    # non-None record already queued its start event via `_begin`/`core.begin()`, and that
    # queued work still needs to reach the browser before the cell ends (OME-1974 review).
    if record is None or outcome == "cancelled" or wiring.origin() != "colab":
        return
    try:
        from screamingface._analytics.colab import bridge

        bridge().flush()
    except KeyboardInterrupt:
        # INVARIANT: the product call already finished, so Ctrl-C here only ends the optional
        # wait; the caller still returns the result or re-raises the real error (owner
        # decision on PR #1952, 2026-11-26). The async path lets CancelledError propagate:
        # swallowing it breaks asyncio.timeout() and TaskGroup cancellation.
        _LOG.debug("Analytics delivery wait interrupted")
    except Exception:
        # INVARIANT: optional analytics can never fail or block product work past the bound.
        _LOG.debug("Analytics delivery wait skipped")


async def _settle_async(record: tuple[Coordinator, Operation] | None, outcome: str | None) -> None:
    # WHY `outcome is None` still waits: see `_settle`'s docstring (e.g. a detached evaluate()).
    if record is None or outcome == "cancelled" or wiring.origin() != "colab":
        return
    from screamingface._analytics.colab import BRIDGE_TIMEOUT

    try:
        # WHY: the bounded wait must not block the caller's event loop, and must stay bounded
        # at the caller even when concurrent calls queue on the executor (same pattern as
        # before_evaluation_async). A timed-out background thread still finishes its own
        # bounded flush(); it is never cancelled.
        await asyncio.wait_for(asyncio.to_thread(_settle, record, outcome), timeout=BRIDGE_TIMEOUT)
    except (RuntimeError, TimeoutError):
        _LOG.debug("Analytics delivery wait skipped")


def _outcome(name: str, result: Any) -> str | None:
    try:
        succeeded = name != "evaluation" or result.ok
    except (AttributeError, ValueError, TypeError, RuntimeError):
        _LOG.debug("Analytics outcome unavailable")
        return None
    return "succeeded" if succeeded else "completed_with_failures"


def tracked[F: Callable[..., Any]](name: str) -> Callable[[F], F]:
    def decorate(function: F) -> F:
        if inspect.iscoroutinefunction(function):
            return cast(F, _async_wrapper(function, name))
        return cast(F, _sync_wrapper(function, name))

    return decorate


def _sync_wrapper(function: Callable, name: str):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        if _active.get() == os.getpid():
            return function(*args, **kwargs)
        if name == "evaluation":
            prompt.before_evaluation()
        record = _begin(name, "sync", args, kwargs)
        token = _active.set(os.getpid())
        try:
            result = function(*args, **kwargs)
        except BaseException as exc:
            outcome = (
                "cancelled"
                if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
                else "failed"
            )
            _finish(record, outcome)
            _settle(record, outcome)
            raise
        else:
            if record is not None:
                outcome = _outcome(name, result)
                _finish(record, outcome)
                _settle(record, outcome)
            return result
        finally:
            _active.reset(token)

    return wrapped


def _async_wrapper(function: Callable, name: str):
    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        if _active.get() == os.getpid():
            return await function(*args, **kwargs)
        if name == "evaluation":
            await prompt.before_evaluation_async()
        record = _begin(name, "async", args, kwargs)
        token = _active.set(os.getpid())
        try:
            result = await function(*args, **kwargs)
        except BaseException as exc:
            outcome = (
                "cancelled"
                if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
                else "failed"
            )
            _finish(record, outcome)
            await _settle_async(record, outcome)
            raise
        else:
            if record is not None:
                outcome = _outcome(name, result)
                _finish(record, outcome)
                await _settle_async(record, outcome)
            return result
        finally:
            _active.reset(token)

    return wrapped
