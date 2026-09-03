"""Caller authentication for Cloudflare Access-protected service origins."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import quote

import httpx
from nacl.public import PrivateKey

from screamingface._access.base import _ClientAuth, _TransportAuth  # noqa: F401
from screamingface._access.contract import (
    _REFRESH_SKEW_SECONDS,
    _access_audience,
    _access_authorization_url,
    _access_logout_url,
    _access_token,
    _AccessToken,
    _auth_error,
    _base64url_padded,
    _decrypt_transfer,
    _present_access_authorization,
    _present_access_logout,
    _raise_if_cancelled,
    _require_positive_timeout,
)
from screamingface._core.wire import _REPLAY_SAFE
from screamingface.errors import AuthenticationError

_ACCESS_TRANSFER_STORE = "https://login.cloudflareaccess.org"
_ACCESS_USER_AGENT = "screamingface-python/0.2"
_DEFAULT_LOGIN_TIMEOUT = 300.0
_TRANSFER_POLL_SECONDS = 2.0


@dataclass(slots=True, repr=False)
class _LoginAttempt:
    cancel: threading.Event
    done: threading.Event
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class _RequestAuthorization:
    generation: int
    token: str | None


class _AccessTokenStore:
    """Process-local Access credentials shared only by matching audiences."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, _AccessToken] = {}

    def usable(self, audience: str, now: float) -> str | None:
        with self._lock:
            token = self._tokens.get(audience)
            if token is None:
                return None
            if now + _REFRESH_SKEW_SECONDS >= token.expires_at:
                self._tokens.pop(audience, None)
                return None
            return token.value

    def put(self, audience: str, token: _AccessToken) -> None:
        with self._lock:
            self._tokens[audience] = token

    def discard(self, audience: str, *, token: str | None = None) -> None:
        with self._lock:
            current = self._tokens.get(audience)
            if current is not None and (token is None or current.value == token):
                self._tokens.pop(audience, None)

    def clear(self) -> None:
        with self._lock:
            self._tokens.clear()


_BrowserPresenter = Callable[[str], None]
_DiscoveryError = Callable[[str], BaseException]


def _access_discovery_error(origin: str) -> AuthenticationError:
    return AuthenticationError(
        f"Could not reach {origin} to discover Cloudflare Access authentication",
        code="access_discovery_unreachable",
        permanent=False,
    )


class _CloudflareAccessAuth(_ClientAuth):
    """Automatic encrypted browser login for a Cloudflare Access application."""

    def __init__(
        self,
        origin: str,
        *,
        access_transport: httpx.BaseTransport | None = None,
        browser_presenter: _BrowserPresenter | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        token_store: _AccessTokenStore | None = None,
        discovery_error: _DiscoveryError = _access_discovery_error,
    ) -> None:
        self._origin = origin
        self._access_http = httpx.Client(
            timeout=15.0,
            follow_redirects=False,
            headers={"User-Agent": _ACCESS_USER_AGENT},
            transport=access_transport,
        )
        self._present_browser = browser_presenter or _present_access_authorization
        self._present_logout = browser_presenter or _present_access_logout
        self._authorization_subscribers: list[_BrowserPresenter] = []
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self._token_store = token_store or _AccessTokenStore()
        self._owns_token_store = token_store is None
        self._discovery_error = discovery_error
        self._audience: str | None = None
        self._generation = 0
        self._browser_session_started = False
        self._login_attempt: _LoginAttempt | None = None
        self._closed = False

    @property
    def authenticated(self) -> bool:
        with self._lock:
            return not self._closed and self._usable_token() is not None

    @property
    def authenticating(self) -> bool:
        with self._lock:
            return not self._closed and self._login_attempt is not None

    def subscribe_authorization(self, presenter: _BrowserPresenter) -> Callable[[], None]:
        """Also deliver each authorization URL to ``presenter``; returns an unsubscribe.

        WHY: the built-in presenter writes the URL to stdout, which a notebook widget
        callback on a worker thread cannot surface (OME-930). A UI registers here to render
        the URL as a link instead. Subscribers are ADDITIVE — the constructor presenter
        still runs, so the terminal browser-open path is unchanged.
        INVARIANT: `_access` never imports a UI; presentation is always passed in.
        """

        with self._lock:
            self._authorization_subscribers.append(presenter)

        def unsubscribe() -> None:
            with self._lock:
                if presenter in self._authorization_subscribers:
                    self._authorization_subscribers.remove(presenter)

        return unsubscribe

    def _announce_authorization(self, authorization_url: str) -> bool:
        """Hand the URL to every subscriber; True if any took responsibility for it.

        WHY the return value: a subscriber renders the URL itself, so the built-in stdout
        narration becomes duplication the user has to read past. The terminal path has no
        subscriber and keeps printing, because there stdout IS the presentation.
        """

        with self._lock:
            subscribers = tuple(self._authorization_subscribers)
        presented = False
        for presenter in subscribers:
            try:
                presenter(authorization_url)
            except Exception:
                # INVARIANT: presentation never fails the login it is announcing. One bad
                # subscriber must not strand a login that is otherwise fine.
                continue
            presented = True
        # INVARIANT: only a presenter that actually ran counts. Reporting success for a
        # subscriber that raised would suppress the stdout fallback too, leaving the user
        # with no link and no printed URL — worse than the duplication that motivated it.
        return presented

    def login(self, *, timeout: float = _DEFAULT_LOGIN_TIMEOUT) -> None:
        _require_positive_timeout(timeout)
        attempt, owner = self._begin_login()
        if attempt is None:
            return
        if not owner:
            self._await_login(attempt, timeout)
            return
        error: BaseException | None = None
        try:
            response = self._discovery_response()
            _raise_if_cancelled(attempt.cancel)
            audience = _access_audience(response)
            if audience is None:
                raise _auth_error(
                    "The configured service does not advertise Cloudflare Access authentication",
                    code="access_not_advertised",
                    status=response.status_code,
                )
            with self._lock:
                self._audience = audience
                if self._usable_token() is not None:
                    return
            self._interactive_login(audience, timeout, attempt)
        except BaseException as exc:
            error = exc
            raise
        finally:
            self._finish_login(attempt, error)

    async def login_async(self, *, timeout: float = _DEFAULT_LOGIN_TIMEOUT) -> None:
        await self._cancellable_thread_call(self.login, timeout=timeout)

    def cancel_login(self) -> None:
        with self._lock:
            attempt = self._login_attempt
            if attempt is not None:
                attempt.cancel.set()
                self._login_attempt = None

    def access_required(self) -> bool:
        with self._lock:
            self._require_open()
            return _access_audience(self._discovery_response()) is not None

    def reauthenticate(self, *, timeout: float = _DEFAULT_LOGIN_TIMEOUT) -> None:
        with self._lock:
            self._require_open()
            if self._audience is not None:
                self._token_store.discard(self._audience)
                self._generation += 1
        self.login(timeout=timeout)

    async def reauthenticate_async(self, *, timeout: float = _DEFAULT_LOGIN_TIMEOUT) -> None:
        await self._cancellable_thread_call(self.reauthenticate, timeout=timeout)

    def logout(self) -> None:
        with self._lock:
            attempt = self._login_attempt
            if attempt is not None:
                attempt.cancel.set()
                self._login_attempt = None
            present_logout = self._browser_session_started or self._usable_token() is not None
            if self._audience is not None:
                self._token_store.discard(self._audience)
            self._generation += 1
            self._browser_session_started = False
        if present_logout:
            self._present_logout(_access_logout_url(self._origin))

    async def logout_async(self) -> None:
        await asyncio.to_thread(self.logout)

    def websocket_headers(self) -> Mapping[str, str]:
        with self._lock:
            token = self._usable_token()
            return {} if token is None else {"Cf-Access-Token": token}

    async def websocket_headers_async(self) -> Mapping[str, str]:
        return await asyncio.to_thread(self.websocket_headers)

    def close(self) -> None:
        attempt: _LoginAttempt | None
        with self._lock:
            if self._closed:
                return
            attempt = self._login_attempt
            if attempt is not None:
                attempt.cancel.set()
                self._login_attempt = None
            if self._owns_token_store:
                self._token_store.clear()
            self._generation += 1
            self._browser_session_started = False
            self._closed = True
        if attempt is not None:
            attempt.done.wait(_TRANSFER_POLL_SECONDS + 0.5)
        self._access_http.close()

    def sync_auth_flow(
        self,
        request: httpx.Request,
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.read()
        authorization = self._authorize_request(request)
        response = yield request
        audience = _access_audience(response)
        if audience is None:
            return
        response.read()
        self._authenticate_after_redirect(audience, authorization, _DEFAULT_LOGIN_TIMEOUT)
        _require_replay_safe(request, response)
        self._set_access_token(request)
        yield request

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        await request.aread()
        authorization = await asyncio.to_thread(self._authorize_request, request)
        response = yield request
        audience = _access_audience(response)
        if audience is None:
            return
        await response.aread()
        await self._cancellable_thread_call(
            self._authenticate_after_redirect,
            audience,
            authorization,
            _DEFAULT_LOGIN_TIMEOUT,
        )
        _require_replay_safe(request, response)
        self._set_access_token(request)
        yield request

    def _authorize_request(self, request: httpx.Request) -> _RequestAuthorization:
        with self._lock:
            self._require_open()
            token = self._usable_token()
            if token is not None:
                request.headers["Cf-Access-Token"] = token
            return _RequestAuthorization(self._generation, token)

    def _set_access_token(self, request: httpx.Request) -> None:
        with self._lock:
            token = self._usable_token()
            if token is None:
                raise _auth_error(
                    "Cloudflare Access login completed without a usable application token",
                    code="access_invalid_token",
                )
            request.headers["Cf-Access-Token"] = token

    def _usable_token(self) -> str | None:
        if self._audience is None:
            return None
        return self._token_store.usable(self._audience, self._clock())

    def _authenticate_after_redirect(
        self,
        audience: str,
        authorization: _RequestAuthorization,
        timeout: float,
    ) -> None:
        if self._adopt_cached_challenge(audience, authorization):
            return
        self._login_after_challenge(audience, timeout)

    def _adopt_cached_challenge(
        self,
        audience: str,
        authorization: _RequestAuthorization,
    ) -> bool:
        with self._lock:
            self._require_open()
            previous_audience = self._audience
            self._audience = audience
            current = self._usable_token()
            # A new origin first proves its Access audience via the challenge. Only then may
            # it reuse a credential learned from another origin with the same audience.
            reusable = current is not None and (
                authorization.generation != self._generation
                or authorization.token is None
                or current != authorization.token
            )
            if reusable:
                if authorization.generation == self._generation:
                    self._generation += 1
                return True
            if authorization.token is not None and previous_audience == audience:
                self._token_store.discard(audience, token=authorization.token)
                self._generation += 1
            return False

    def _login_after_challenge(self, audience: str, timeout: float) -> None:
        attempt, owner = self._begin_login()
        if attempt is None:
            return
        if not owner:
            self._await_login(attempt, timeout)
            return
        error: BaseException | None = None
        try:
            self._interactive_login(audience, timeout, attempt)
        except BaseException as exc:
            error = exc
            raise
        finally:
            self._finish_login(attempt, error)

    def _begin_login(self) -> tuple[_LoginAttempt | None, bool]:
        with self._lock:
            self._require_open()
            if self._usable_token() is not None:
                return None, False
            if self._login_attempt is not None:
                return self._login_attempt, False
            attempt = _LoginAttempt(threading.Event(), threading.Event())
            self._login_attempt = attempt
            return attempt, True

    def _finish_login(
        self,
        attempt: _LoginAttempt,
        error: BaseException | None,
    ) -> None:
        with self._lock:
            attempt.error = error
            if self._login_attempt is attempt:
                self._login_attempt = None
            attempt.done.set()

    def _await_login(self, attempt: _LoginAttempt, timeout: float) -> None:
        if not attempt.done.wait(timeout):
            raise _auth_error(
                "Timed out waiting for the active Cloudflare Access login",
                code="access_login_timeout",
                permanent=False,
            )
        if attempt.error is not None:
            raise attempt.error
        with self._lock:
            self._require_open()
            if self._usable_token() is None:
                raise _auth_error(
                    "Cloudflare Access login completed without a usable application token",
                    code="access_invalid_token",
                )

    async def _cancellable_thread_call(
        self,
        operation: Callable[..., None],
        /,
        *args: object,
        **kwargs: object,
    ) -> None:
        worker = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError as cancellation:
            self.cancel_login()
            try:
                await asyncio.shield(worker)
            except BaseException as cleanup_error:
                cancellation.add_note(
                    f"Background authentication cleanup raised {type(cleanup_error).__name__}"
                )
            raise

    def _discovery_response(self) -> httpx.Response:
        try:
            response = self._access_http.head(self._origin)
            if response.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
                response = self._access_http.get(self._origin)
            return response
        except httpx.HTTPError as exc:
            raise self._discovery_error(self._origin) from exc

    def _interactive_login(
        self,
        audience: str,
        timeout: float,
        attempt: _LoginAttempt,
    ) -> None:
        _raise_if_cancelled(attempt.cancel)
        private_key = PrivateKey.generate()
        public_key = _base64url_padded(bytes(private_key.public_key))
        authorization_url = _access_authorization_url(self._origin, audience, public_key)
        with self._lock:
            _raise_if_cancelled(attempt.cancel)
            self._require_open()
            self._browser_session_started = True
        presented = self._announce_authorization(authorization_url)
        if not presented:
            self._present_browser(authorization_url)
            print("Waiting for Cloudflare Access login to complete...")
        token = self._poll_transfer(private_key, public_key, timeout, attempt.cancel)
        access_token = _access_token(token, self._clock(), self._wall_clock())
        with self._lock:
            _raise_if_cancelled(attempt.cancel)
            self._require_open()
            if self._login_attempt is not attempt:
                _raise_if_cancelled(attempt.cancel)
                raise _auth_error(
                    "Cloudflare Access login was superseded",
                    code="access_login_cancelled",
                    permanent=False,
                )
            self._audience = audience
            self._token_store.put(audience, access_token)
            self._generation += 1
        if not presented:
            print("Cloudflare Access login complete.")

    def _poll_transfer(
        self,
        private_key: PrivateKey,
        public_key: str,
        timeout: float,
        cancel: threading.Event,
    ) -> str:
        deadline = self._clock() + timeout
        transfer_url = f"{_ACCESS_TRANSFER_STORE}/transfer/{quote(public_key, safe='')}"
        while self._clock() < deadline:
            _raise_if_cancelled(cancel)
            try:
                remaining = max(0.0, deadline - self._clock())
                response = self._access_http.get(
                    transfer_url,
                    timeout=min(_TRANSFER_POLL_SECONDS, remaining),
                )
            except httpx.TimeoutException:
                # Cloudflare may hold a transfer poll open while the user completes OTP.
                # The caller's login deadline, rather than one socket read, owns the wait.
                _raise_if_cancelled(cancel)
                remaining = max(0.0, deadline - self._clock())
                self._wait_for_next_poll(cancel, min(_TRANSFER_POLL_SECONDS, remaining))
                continue
            except httpx.HTTPError as exc:
                _raise_if_cancelled(cancel)
                raise _auth_error(
                    "Could not reach the Cloudflare Access login transfer service",
                    code="access_transfer_unreachable",
                    permanent=False,
                ) from exc
            _raise_if_cancelled(cancel)
            if response.status_code == HTTPStatus.OK and response.content:
                return _decrypt_transfer(response, private_key)
            if response.status_code not in {HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND}:
                raise _auth_error(
                    "Cloudflare Access rejected the browser login transfer",
                    code="access_transfer_rejected",
                    status=response.status_code,
                    permanent=response.status_code < 500,
                )
            remaining = max(0.0, deadline - self._clock())
            self._wait_for_next_poll(cancel, min(_TRANSFER_POLL_SECONDS, remaining))
        _raise_if_cancelled(cancel)
        raise _auth_error(
            "Timed out waiting for Cloudflare Access login",
            code="access_login_timeout",
            permanent=False,
        )

    def _wait_for_next_poll(self, cancel: threading.Event, seconds: float) -> None:
        if self._sleep is time.sleep:
            if cancel.wait(seconds):
                _raise_if_cancelled(cancel)
            return
        self._sleep(seconds)
        _raise_if_cancelled(cancel)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("ScreamingFace caller authentication is closed")


def _require_replay_safe(request: httpx.Request, response: httpx.Response) -> None:
    """Refuse to re-send a request the caller did not declare safe to repeat.

    WHY: the session is now repaired, so the caller's NEXT request carries a token — but
    this one may have already started billable work. ``GET /?q=`` starts a Run despite being
    a GET, and any generic layer that assumes GETs are replayable can double-fire it. Making
    replay an explicit, default-deny property of the request keeps that decision at the call
    site that knows the answer, rather than inferring it from a vendor's status code.
    """

    if request.extensions.get(_REPLAY_SAFE, False):
        return
    raise _auth_error(
        "Cloudflare Access re-authentication completed; reissue the request",
        code="access_reauthenticated",
        status=response.status_code,
        permanent=False,
    )


def _default_caller_auth(
    origin: str,
    *,
    token_store: _AccessTokenStore | None = None,
    discovery_error: _DiscoveryError = _access_discovery_error,
) -> _CloudflareAccessAuth:
    return _CloudflareAccessAuth(
        origin,
        token_store=token_store,
        discovery_error=discovery_error,
    )


_BUILTIN_CALLER_AUTH = _default_caller_auth


def _client_caller_auth(
    origin: str,
    *,
    token_store: _AccessTokenStore,
    discovery_error: _DiscoveryError = _access_discovery_error,
) -> _ClientAuth:
    """Construct one Client-owned origin adapter with explicit Access dependencies.

    The one-argument fallback preserves the existing private factory seam used by repository
    test doubles. Production always follows the fully injected path.
    """

    if _default_caller_auth is not _BUILTIN_CALLER_AUTH:
        return _default_caller_auth(origin)
    return _default_caller_auth(
        origin,
        token_store=token_store,
        discovery_error=discovery_error,
    )


__all__: list[str] = []
