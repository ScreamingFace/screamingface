"""Outer operation boundary shared by synchronous and asynchronous entry points."""

import asyncio
import functools
import inspect
import logging
import os
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, cast

from screamingface._analytics import wiring
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
    if not isinstance(endpoint, str) or wiring.origin() == "colab":
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
        record = _begin(name, "sync", args, kwargs)
        token = _active.set(os.getpid())
        try:
            result = function(*args, **kwargs)
        except BaseException as exc:
            _finish(
                record,
                "cancelled"
                if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
                else "failed",
            )
            raise
        else:
            if record is not None:
                _finish(record, _outcome(name, result))
            return result
        finally:
            _active.reset(token)

    return wrapped


def _async_wrapper(function: Callable, name: str):
    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        if _active.get() == os.getpid():
            return await function(*args, **kwargs)
        record = _begin(name, "async", args, kwargs)
        token = _active.set(os.getpid())
        try:
            result = await function(*args, **kwargs)
        except BaseException as exc:
            _finish(
                record,
                "cancelled"
                if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
                else "failed",
            )
            raise
        else:
            if record is not None:
                _finish(record, _outcome(name, result))
            return result
        finally:
            _active.reset(token)

    return wrapped
