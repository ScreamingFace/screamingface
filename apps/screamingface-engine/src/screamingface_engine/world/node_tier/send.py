"""The node tier's response plumbing: observe, buffer, then decide what the caller receives.

FEATURE (unit 3, prd/03 §2.4; 04-review-fixes §2.2): url4's node writes a whole response into
:class:`_SpillSend`, which only buffers it. After url4 returns, :meth:`_SpillSend.finish` decides
the answer — inline, a spill and ``303``, ``413``, or ``502`` — and applies the two status fixes
the sync surface needs. :class:`_ObservedSend` then records the status and rewords a 504.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, MutableMapping, Sequence
from typing import Any

from screamingface_engine.artifacts import (
    ArtifactWriter,
    ResultDelivery,
    allowed_result_bytes,
    decide_result_delivery,
)
from screamingface_engine.artifacts.signing import signed_artifact_path
from screamingface_engine.world.wire import AsgiSend, send_url4_error, write
from url4.core.errors import ErrorCode

logger = logging.getLogger(__package__)

# Engine-added error codes (contracts.md C1/C5): `result_too_large` mirrors the run path's code
# for the same refusal; `artifact_spill_failed` names the failed deposit as the cause of a 502.
_RESULT_TOO_LARGE = "result_too_large"
_ARTIFACT_SPILL_FAILED = "artifact_spill_failed"

# url4's admission refusal (`url4.cli._serve._serve_http`). It is not an `ErrorCode` member —
# url4 writes it as a literal — so the engine names it once, here. The tier's own gate (§2.2a)
# answers with the same envelope, so a caller cannot tell which gate shed it.
_OVERLOADED = "overloaded"
_OVERLOADED_MESSAGE = "server at capacity, retry shortly"
_URL4_CODES = frozenset(code.value for code in ErrorCode)


class _ObservedSend:
    """Wraps the ASGI ``send`` to record the status and reword the 504 body.

    WHY the reword lives at the send boundary: url4's wrapper is the timeout OWNER (it decides
    when a request has exceeded its budget), but the engine owns the MESSAGE the sync contract
    promises (AC6 — long work belongs on the ensemble path). Intercepting the one message url4
    emits keeps the timeout mechanic url4's and the wording the engine's; re-implementing the
    timeout to change a string would be the thing `build_asgi_app` exists to prevent.
    """

    __slots__ = ("_send", "_timeout", "_rewrite", "_status", "_code")

    def __init__(self, send: AsgiSend, timeout: float) -> None:
        self._send = send
        self._timeout = timeout
        self._rewrite = False
        self._status = 0
        self._code: str | None = None

    @property
    def status(self) -> int:
        return self._status

    @property
    def code(self) -> str | None:
        """The final ``error.code`` the caller received, or None for a success or a bare body."""
        return self._code

    async def __call__(self, message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self._status = int(message.get("status", 0))
            if self._status == 504:
                self._rewrite = True
                message = {
                    **message,
                    "headers": [
                        (name, value)
                        for name, value in message.get("headers", ())
                        if name.lower() != b"content-length"
                    ],
                }
        elif message["type"] == "http.response.body" and self._rewrite:
            self._rewrite = False
            message = {
                **message,
                "body": _timeout_body(self._timeout),
                "more_body": False,
            }
        if message["type"] == "http.response.body" and self._status >= 400:
            # Only an error body is parsed: error envelopes are small by construction, and a
            # success body may be up to the hard cap.
            self._code = _error_code(message.get("body", b""))
        await self._send(message)


class _SpillSend:
    """Buffer one sync response; :meth:`finish` delivers it inline, spilled, or refused (D9, C5).

    FEATURE (unit 3, prd/03 §2.4): a body over 512 KiB is written to the artifact store and the
    caller gets ``303 See Other`` with a short-lived signed ``Location``; a body over the hard
    cap is ``413`` and NOTHING is written; a failed or late deposit is ``502`` and the body is
    NEVER returned inline — falling back would defeat the memory protection the caps exist for.

    WHY a pure buffer, with the decision in ``finish`` (§2.2, NT-H2): url4's wrapper runs the
    node under ``asyncio.timeout`` and sends its own 504 only when no response has started. A
    spill that ran inside that timeout and was cut off left the caller with NO response. The
    tier calls ``finish`` after url4 returns, so the spill runs outside url4's budget, under its
    own ``spill_timeout_s``.

    # INVARIANT: a response that is not a 2xx is forwarded (after the status fixes). Error
    # envelopes are small by construction, and spilling one would replace a meaningful
    # ``error.code`` with a redirect the caller cannot interpret.
    """

    __slots__ = (
        "_send",
        "_store",
        "_inline_cap",
        "_hard_cap",
        "_signing_key",
        "_ttl_s",
        "_clock",
        "_spill_timeout_s",
        "_retry_after_s",
        "_status",
        "_headers",
        "_chunks",
        "_started",
    )

    def __init__(
        self,
        send: AsgiSend,
        *,
        store: ArtifactWriter | None,
        inline_cap: int,
        hard_cap: int,
        signing_key: str,
        ttl_s: int,
        clock: Callable[[], float],
        spill_timeout_s: float,
        retry_after_s: int,
    ) -> None:
        self._send = send
        self._store = store
        self._inline_cap = inline_cap
        self._hard_cap = hard_cap
        self._signing_key = signing_key
        self._ttl_s = ttl_s
        self._clock = clock
        self._spill_timeout_s = spill_timeout_s
        self._retry_after_s = retry_after_s
        self._status = 0
        self._headers: list[tuple[bytes, bytes]] = []
        # WHY a list of chunks (FX-11): one `b"".join` at the end is the only copy; appending
        # to a bytearray and then taking `bytes(...)` copied a 64 MiB body twice.
        self._chunks: list[bytes] = []
        self._started = False

    async def __call__(self, message: MutableMapping[str, Any]) -> None:
        kind = message["type"]
        if kind == "http.response.start":
            self._status = int(message.get("status", 0))
            self._headers = list(message.get("headers", ()))
            self._chunks = []
            self._started = True
        elif kind == "http.response.body":
            self._chunks.append(message.get("body", b""))

    async def finish(self) -> None:
        """Deliver the buffered response. Call once, after the inner app has returned."""
        if not self._started:
            # AIDEV-NOTE: url4 always answers (its wrapper sends a 504 when the node did not).
            # A silent inner app is a bug, and a 500 envelope beats no response at all.
            await send_url4_error(
                self._send, 500, ErrorCode.INTERNAL_ERROR, "the node produced no response"
            )
            return
        body = b"".join(self._chunks)
        self._chunks = []
        status, headers = _remap(self._status, self._headers, body, self._retry_after_s)
        decision = decide_result_delivery(
            len(body),
            inline_cap=self._inline_cap,
            hard_cap=self._hard_cap,
            spill_available=self._store is not None,
        )
        if not _is_success(status) or decision is ResultDelivery.INLINE:
            await write(self._send, status, headers, body)
            return
        if decision is ResultDelivery.TOO_LARGE:
            allowed = allowed_result_bytes(
                self._inline_cap, self._hard_cap, spill_available=self._store is not None
            )
            await send_url4_error(
                self._send,
                413,
                _RESULT_TOO_LARGE,
                f"sync response is {len(body)} bytes, cap is {allowed} bytes — the result is "
                "too large to deliver; reduce the request or use the ensemble path",
            )
            return
        await self._deliver_spilled(body)

    async def _deliver_spilled(self, body: bytes) -> None:
        try:
            # WHY a worker thread: the write hashes and may push to object storage — sync, and
            # blocking the loop here would stall every concurrent request for the deposit.
            # AIDEV-NOTE: on timeout the thread cannot be stopped; a late write may still land
            # an orphan artifact, which the store's sweep reclaims. The caller gets a 502 now.
            location = await asyncio.wait_for(
                asyncio.to_thread(self._spill, body), self._spill_timeout_s
            )
        except TimeoutError:
            logger.error(
                "artifact spill exceeded %gs for a %d-byte sync response",
                self._spill_timeout_s,
                len(body),
            )
            await self._spill_failed()
            return
        except Exception:
            logger.exception("artifact spill failed for a %d-byte sync response", len(body))
            await self._spill_failed()
            return
        await write(
            self._send,
            303,
            [(b"location", location.encode("latin-1")), (b"content-length", b"0")],
            b"",
        )

    async def _spill_failed(self) -> None:
        await send_url4_error(
            self._send,
            502,
            _ARTIFACT_SPILL_FAILED,
            "the response could not be parked in artifact storage; it is NOT returned "
            "inline, because that would defeat the size cap it exceeded",
        )

    def _spill(self, body: bytes) -> str:
        """Park the complete body and sign its redirect URL. Blocking; runs in a thread."""
        # INVARIANT (FX-9): never park what cannot be signed. An unsigned artifact is
        # unfetchable, so writing it only fills the store. `build_node_tier` refuses an empty
        # key at boot; this guards a tier constructed directly.
        if not self._signing_key:
            raise ValueError("artifact signing key is empty — refusing to park the response")
        assert self._store is not None
        ref = self._store.write_bytes(body)
        return signed_artifact_path(
            ref.id, key=self._signing_key, ttl_s=self._ttl_s, now=self._clock
        )


def _remap(
    status: int, headers: Sequence[tuple[bytes, bytes]], body: bytes, retry_after_s: int
) -> tuple[int, list[tuple[bytes, bytes]]]:
    """The two status fixes the sync surface needs on url4's answer (§2.2, FX-3, FX-12).

    - url4 answers ``500`` for a permanent `ResolutionError`. On a direct hit that error always
      comes from the downstream (aigateway or a data provider), so a ``500`` whose ``error.code``
      is NOT a url4 `ErrorCode` becomes ``502``; code and message are kept.
    - url4's overload ``503`` hardcodes ``Retry-After: 1``; the tier's setting replaces it.
    """
    if status == 500:
        code = _error_code(body)
        if code is not None and code not in _URL4_CODES:
            return 502, list(headers)
    elif status == 503 and _error_code(body) == _OVERLOADED:
        kept = [(name, value) for name, value in headers if name.lower() != b"retry-after"]
        return status, [*kept, (b"retry-after", str(retry_after_s).encode())]
    return status, list(headers)


def _error_code(body: bytes) -> str | None:
    """The ``error.code`` of a url4 envelope, or None when the body is not one."""
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def _is_success(status: int) -> bool:
    return 200 <= status < 300


def _timeout_body(timeout: float) -> bytes:
    payload = {
        "error": {
            "code": str(ErrorCode.TIMEOUT),
            "message": (
                f"sync request exceeded the {timeout:g}s budget — long-running work belongs on "
                "the ensemble path (POST /token, attach the WebSocket, then GET /?q=<expression>)"
            ),
        }
    }
    return json.dumps(payload).encode()
