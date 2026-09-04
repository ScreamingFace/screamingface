"""OME-1026 F1 — the route boundary that makes an account-scoped response unshareable.

FEATURE: private responses that no intermediary may reuse. An endpoint whose body is
scoped to one account must carry ``Cache-Control: private, no-store`` and a ``Vary``
naming every identity input, on EVERY response it can produce.

INVARIANT (why this is a route class and not endpoint code): ``CurrentAccount`` is a
FastAPI dependency, and FastAPI solves dependencies BEFORE calling the endpoint. An
authentication failure therefore never enters the endpoint body, so a policy applied
there is structurally invisible to every 401 and 403 the route can emit. A route
class wraps dependency resolution itself, which is the only layer inside the
application that sees both the solved-successfully response and the raise.

INVARIANT (``Vary`` names the identity input of every auth mode): ``jwt`` mode
identifies the caller by ``Authorization``; ``cloudflare_headers`` mode by
``X-User-Email``. In header mode two accounts issue byte-identical request lines for
the same URL, so omitting that header would leave their responses interchangeable to
a shared cache. The token is imported from the auth path rather than spelled here, so
the two cannot drift.

# WHY ``no-store`` on top of ``private``: ``private`` still permits the caller's own
# agent to write a credential-derived body to disk, and gives a misconfigured
# intermediary nothing to obey. ``no-store`` forbids writing the body down at all.
# AIDEV-NOTE: adding a dependency to a route that uses this class needs no work here —
# a new pre-handler raise is covered automatically. That is the whole point of putting
# the policy at the boundary rather than in each handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from fastapi import HTTPException
from fastapi.routing import APIRoute

from ..core.auth.cloudflare_identity import HEADER_USER_EMAIL

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterator, MutableMapping, Sequence
    from typing import Any

    from fastapi import Request, Response


class _HeaderMap(Protocol):
    """The header mutations this policy needs.

    # WHY a protocol and not ``MutableMapping[str, str]``: the two header containers
    # this policy writes to are a plain ``dict`` (``HTTPException.headers``) and
    # Starlette's ``MutableHeaders``, and the latter implements exactly these four
    # methods without registering as a ``MutableMapping``. Structural typing is what
    # actually describes the requirement.
    """

    def __getitem__(self, key: str, /) -> str: ...
    def __setitem__(self, key: str, value: str, /) -> None: ...
    def __delitem__(self, key: str, /) -> None: ...
    def __iter__(self) -> Iterator[str]: ...


CACHE_CONTROL = "private, no-store"

_IDENTITY_VARY: tuple[str, ...] = ("Authorization", HEADER_USER_EMAIL)


def merge_vary(existing: str | None, tokens: Sequence[str]) -> str:
    """``existing`` plus ``tokens``, as a case-insensitive, order-preserving union.

    INVARIANT (adversarial B1): ``Vary`` is a SET of field names, so this policy may
    only ADD to it. Assigning the header — what ``headers.update()`` and
    ``MutableHeaders.__setitem__`` do — replaces every existing value, and a response
    that had declared ``Vary: Cookie`` came out declaring that it does NOT vary on
    Cookie. That is worse than a missing policy: it actively invites a shared cache to
    serve one session's body to another.

    # WHY existing tokens keep their position and spelling: the merge is a pure
    # addition, so a caller that already declared a token gets it back byte-identical.
    # HTTP field names are case-insensitive, so the dedup is too.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for token in [*_split_vary(existing), *tokens]:
        folded = token.lower()
        if folded in seen:
            continue
        seen.add(folded)
        merged.append(token)
    return ", ".join(merged)


def _split_vary(value: str | None) -> list[str]:
    if not value:
        return []
    return [token.strip() for token in value.split(",") if token.strip()]


# The request-scope marker: the ``Vary`` tokens of the private route this request was
# matched to, or absent for every other route. Written by the route class BEFORE
# dependency solving, read by the application's exception handlers.
# WHY the tokens and not a boolean: each private route declares its own extra inputs
# (``/v1/model-parameters`` also varies on ``X-Profile``), so a global constant in the
# error boundary would understate one route's cache key the moment a route is added.
PRIVATE_CACHE_SCOPE_KEY = "aigw_private_cache_vary"


def apply_private_cache_policy(headers: _HeaderMap, tokens: Sequence[str]) -> None:
    """Stamp the private policy onto ``headers``, in place.

    ``Cache-Control`` is OWNED by this policy — an error may never be emitted with a
    weaker directive than the success response. ``Vary`` is MERGED (see
    :func:`merge_vary`). Every other header, including a raiser's ``WWW-Authenticate``
    or ``Retry-After``, is left untouched.

    # AIDEV-NOTE: accepts a plain ``dict`` (``HTTPException.headers``) as well as a
    # Starlette ``MutableHeaders``. A dict compares keys case-SENSITIVELY, so a raiser
    # spelling ``vary`` in lower case would otherwise end up with two ``Vary`` headers
    # — one of them the truncated one. Case variants are collected and collapsed.
    """
    existing = _take(headers, "Vary")
    _take(headers, "Cache-Control")
    headers["Cache-Control"] = CACHE_CONTROL
    headers["Vary"] = merge_vary(existing, tokens)


def _take(headers: _HeaderMap, name: str) -> str | None:
    """Remove every case spelling of ``name``, returning the values joined."""
    folded = name.lower()
    found = [headers[key] for key in list(headers) if key.lower() == folded]
    for key in [key for key in list(headers) if key.lower() == folded]:
        del headers[key]
    return ", ".join(value for value in found if value) or None


def stamp_private_cache_policy(request: Request, response: Response) -> Response:
    """Apply the policy to ``response`` IF ``request`` was matched to a private route.

    This is the half of the boundary the route class cannot reach: a
    ``RequestValidationError`` 422 and an unexpected 500 are rendered by the
    APPLICATION's exception handlers, after the route handler has already unwound.
    Starlette renders the 500 in ``ServerErrorMiddleware`` — outside every user
    middleware, writing with the original ``send`` — so a send-wrapping middleware
    could not observe it either. The application's own handlers are the only layer
    that sees the final rendered response, and the scope marker is what tells them the
    route was private.
    """
    # AIDEV-NOTE: the scope is read through ``getattr`` because the merged suite drives
    # these handlers directly with a request stub carrying only ``state``
    # (``tests/unit/usage_accounting/test_accounting_seam.py``). No scope means no route
    # match, which is the same answer as an unmarked scope: leave the headers alone.
    scope: MutableMapping[str, Any] | None = getattr(request, "scope", None)
    tokens = None if scope is None else scope.get(PRIVATE_CACHE_SCOPE_KEY)
    if tokens:
        apply_private_cache_policy(response.headers, tokens)
    return response


class PrivateCacheRoute(APIRoute):
    """An ``APIRoute`` that stamps the private cache policy on every response.

    Use :func:`private_cache_route` to build one; subclasses declare additional
    request inputs the response varies on through :attr:`extra_vary`.
    """

    extra_vary: tuple[str, ...] = ()

    @classmethod
    def vary_tokens(cls) -> tuple[str, ...]:
        """Every request input this route's response is keyed on."""
        return (*_IDENTITY_VARY, *cls.extra_vary)

    @classmethod
    def policy(cls) -> dict[str, str]:
        return {"Cache-Control": CACHE_CONTROL, "Vary": ", ".join(cls.vary_tokens())}

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()
        tokens = self.vary_tokens()

        async def handler(request: Request) -> Response:
            # INVARIANT (adversarial B1): mark the scope FIRST. Everything below can
            # raise something this function does not render — a ``RequestValidationError``
            # from dependency solving, any unexpected exception from the endpoint — and
            # the marker is how the application's exception handlers learn that the
            # response they are about to render belongs to a private route. Marking
            # after ``original`` would cover exactly the cases that never needed it.
            request.scope[PRIVATE_CACHE_SCOPE_KEY] = tokens
            try:
                response = await original(request)
            except HTTPException as exc:
                # AIDEV-NOTE: ``exc.headers`` is the channel that reaches an
                # ``HTTPException`` response — it is rendered from the EXCEPTION's
                # headers, not from any response object. Merged rather than assigned,
                # so a raiser's own headers survive while this policy wins on the keys
                # it owns: an error can never be emitted with a weaker cache directive
                # than the success response.
                merged = dict(exc.headers or {})
                apply_private_cache_policy(merged, tokens)
                exc.headers = merged
                raise
            apply_private_cache_policy(response.headers, tokens)
            return response

        return handler


def private_cache_route(*extra_vary: str) -> type[PrivateCacheRoute]:
    """A :class:`PrivateCacheRoute` subclass whose ``Vary`` also names ``extra_vary``."""

    class _Route(PrivateCacheRoute):
        pass

    _Route.extra_vary = tuple(extra_vary)
    return _Route
