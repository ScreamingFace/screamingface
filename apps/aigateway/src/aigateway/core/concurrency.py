"""Per-provider concurrency guardrail for upstream dispatches.

Bounds how many concurrent calls hit a given upstream provider at once via
an :class:`asyncio.Semaphore` registry kept on ``app.state``. Wraps the
retry loop in :mod:`aigateway.routes.chat` so a quota reset isn't
immediately re-exhausted by a thundering herd of concurrent siblings (the
url4 collection-fan-out failure mode that pure reactive retry could not
absorb).

``limit <= 0`` disables the cap (an async-no-op context).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


def _provider_match_keys(provider: str) -> set[str]:
    """Override keys that should match a derived ``provider`` string.

    The gateway derives ``provider`` from the model prefix
    (``routes/chat.py``: ``model.split("/", 1)[0]``), which for Gemini is
    ``gemini-cli`` (model ``gemini-cli/gemini-2.5-flash``). Operators
    naturally write the *family* name ``gemini`` in the override, so accept
    both the full provider string and its ``-cli``-stripped family name.
    Matching is exact (after lowercasing) on either form — an arbitrary
    prefix like ``gem`` must not match.
    """
    p = provider.lower()
    keys = {p}
    if p.endswith("-cli"):
        keys.add(p.removesuffix("-cli"))
    return keys


def effective_provider_limit(settings: Any, provider: str) -> int:
    """Return the concurrency cap that should apply to ``provider``.

    Uses ``provider_max_concurrency_overrides`` keyed by either the full
    derived provider string (e.g. ``gemini-cli``) or its family name
    (``gemini``), case-insensitive, when present; otherwise falls back to the
    global ``provider_max_concurrency``. ``0`` means "unlimited" — see
    :func:`provider_slot`.
    """
    overrides = getattr(settings, "provider_max_concurrency_overrides", None) or {}
    match_keys = _provider_match_keys(provider)
    for override_key, override_value in overrides.items():
        if override_key.lower() in match_keys:
            return int(override_value)
    return int(settings.provider_max_concurrency)


def _registry(app: Any) -> dict[str, asyncio.Semaphore]:
    reg = getattr(app.state, "provider_semaphores", None)
    if reg is None:
        reg = {}
        app.state.provider_semaphores = reg
    return reg


def _get_or_create_semaphore(app: Any, provider: str, limit: int) -> asyncio.Semaphore:
    reg = _registry(app)
    sem = reg.get(provider)
    # ``_sf_limit`` records the size the semaphore was created with so a
    # config change (e.g. raising AIGW_PROVIDER_MAX_CONCURRENCY) rebuilds it
    # rather than silently keeping the old cap.
    if sem is None or getattr(sem, "_sf_limit", None) != limit:
        sem = asyncio.Semaphore(limit)
        sem._sf_limit = limit  # type: ignore[attr-defined]
        reg[provider] = sem
        # WHY: the limit in force is otherwise invisible — a typo'd
        # AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES silently falls back to the
        # default and resurfaces as mystery queueing (OME-889). One line per
        # provider per process (re-logged only on a limit change); structured
        # admission telemetry is OME-886's territory.
        logger.info("provider concurrency limit applied provider=%s limit=%d", provider, limit)
    return sem


@asynccontextmanager
async def provider_slot(
    app: Any, provider: str, limit: int, *, timeout_s: float | None = None
) -> AsyncIterator[None]:
    """Acquire a concurrency slot for ``provider`` for the duration of the block.

    With ``limit <= 0`` the guardrail is disabled and entry is immediate.
    Otherwise an ``asyncio.Semaphore(limit)`` keyed by provider gates entry;
    the slot is held across the entire ``with`` body, so wrapping retry means
    a provider's concurrent-pressure ceiling includes retry attempts.
    """
    if limit <= 0:
        yield
        return
    sem = _get_or_create_semaphore(app, provider, limit)
    # Only admission consumes this deadline. Cancellation during acquire is handled
    # by asyncio.Semaphore; a successfully acquired slot is always released below.
    async with asyncio.timeout(timeout_s) as admission:
        await sem.acquire()
    try:
        # WHY: a semaphore wakeup may run before an overdue timeout callback.
        # Refuse expired admission even then, while still releasing the acquired slot.
        deadline = admission.when()
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError
        yield
    finally:
        sem.release()
