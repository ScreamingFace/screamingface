"""Default-on analytics with best-effort notice; every explicit opt-out wins."""

import asyncio
import logging
import os
import sys
import threading

from screamingface._analytics.local import LocalConsentStore, config_path
from screamingface._analytics.wiring import origin

NOTICE = (
    "ScreamingFace collects anonymous usage analytics (API usage, SDK versioning, and your "
    "local-or-hosted engine preference) to help us build a better API. It does not store "
    "any fusion, prompts, outputs, scores, or keys. It's on by default; turn it off anytime "
    "with `sf.analytics.disable()` (or set `DO_NOT_TRACK=1`)."
)
_shown = False
_pid = os.getpid()
_lock = threading.RLock()
_LOG = logging.getLogger(__name__)


def show_notice(environment: str) -> None:
    stream = sys.stderr if environment == "python" else sys.stdout
    try:
        if stream is not None:
            print(NOTICE, file=stream, flush=True)
    except (OSError, ValueError, RuntimeError):
        # WHY: redirected/closed notebook or script output is not an opt-out.
        pass


def _offer() -> None:
    global _shown
    from screamingface import analytics

    if analytics._disabled():
        return
    environment = origin()
    if environment == "colab":
        from screamingface._analytics.colab import bridge

        bridge().ensure_setup()
        _shown = True
    elif not _shown:
        store = LocalConsentStore(config_path())
        if not analytics._session_only and store.missing():
            show_notice(environment)
            _shown = True
            store.enroll(lambda: not analytics._disabled())


def offer() -> None:
    global _pid, _lock, _shown
    if _pid != os.getpid():
        _pid, _lock = os.getpid(), threading.RLock()
        # WHY: the child gets a fresh Colab bridge and needs its own setup attempt.
        _shown = False
    try:
        with _lock:
            _offer()
    except Exception:
        # INVARIANT: optional setup cannot break import/product work. Do not log
        # preference paths or exception details; BaseException interruptions propagate.
        _LOG.debug("Analytics setup skipped")


def wait_for_setup(generation: int | None = None) -> None:
    from screamingface import analytics

    if origin() == "colab" and not analytics._disabled():
        from screamingface._analytics.colab import bridge

        selected = bridge()
        try:
            if generation is None:
                selected.wait_for_setup()
            else:
                selected.wait_for_generation(generation)
        except Exception:
            # INVARIANT: failed optional setup cannot fail the evaluation or let
            # an in-flight reply enable tracking later. Interruptions propagate.
            selected.expire_setup(generation, reason="unavailable")
            _LOG.debug("Analytics setup skipped")


def before_evaluation() -> None:
    offer()
    wait_for_setup()


async def before_evaluation_async() -> None:
    from screamingface import analytics

    if analytics._disabled():
        return
    if origin() != "colab":
        if not _shown:
            # WHY: preference locks and disk writes must not block the event loop.
            try:
                await asyncio.to_thread(offer)
            except RuntimeError:
                # An unavailable executor is also an optional setup failure.
                _LOG.debug("Analytics setup skipped")
        return
    # Colab only queues browser work here; it never opens local preference files.
    offer()
    from screamingface._analytics.colab import BRIDGE_TIMEOUT, bridge

    selected = bridge()
    generation = selected.setup_token()
    try:
        if generation is not None:
            # WHY: include executor queue delay without blocking Colab's event loop.
            await asyncio.wait_for(
                asyncio.to_thread(wait_for_setup, generation), timeout=BRIDGE_TIMEOUT
            )
    except Exception as exc:
        # Includes timeout and executor failure; BaseException cancellation escapes.
        selected.expire_setup(
            generation, reason="timeout" if isinstance(exc, TimeoutError) else "unavailable"
        )
        _LOG.debug("Analytics setup skipped")
