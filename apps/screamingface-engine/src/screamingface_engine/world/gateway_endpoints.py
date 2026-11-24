"""The Engine's own request-addressed endpoints on a Gateway world: `/classify`, `/route-answer`.

FEATURE (OME-1795, OME-1822): `factory._gateway_world` installs both right after the declared
model routes, so each is a direct mount, and a declared model at either route fails composition.

WHY its own module (OME-1822 review, C3): registering an endpoint speaks url4, the node, its
request and its error type, which `classification.py` and `routing.py` may not import
(`tests/unit/test_url4_executor.py` pins the importers); and `factory.py` builds the world
rather than describing each Engine endpoint on it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from screamingface_engine.world.classification import CLASSIFY_ROUTE, ClassificationEndpoint
from screamingface_engine.world.config import WorldConfigError
from screamingface_engine.world.connector import AigatewayConfig, AigatewayWorld, _GatewayRefusal
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.routing import ROUTE_ANSWER_ROUTE, RoutedAnswerEndpoint, not_found
from screamingface_engine.world.routing_config import RoutingBranch, RoutingProfile
from url4.core.errors import ErrorCode, ResolutionError
from url4.peer.server import Request, Url4Node
from url4.wire.subrequest import encode_subrequest

ROUTED_CALL_FAILED_MESSAGE = "the routed answer failed after its classifier or branch call was sent"
"""The one message of a relayed classifier or branch failure (spec 3.5)."""


def install_gateway_endpoints(
    world: AigatewayWorld, cfg: AigatewayConfig, profiles: Mapping[str, RoutingProfile]
) -> None:
    """Register `/classify`, then `/route-answer`, on the world node.

    Raises:
        WorldConfigError: a declared model takes either route; nothing after it registers.
    """
    _install_classification(world, cfg)
    _install_routing(world, cfg, profiles)


def _install_classification(world: AigatewayWorld, cfg: AigatewayConfig) -> None:
    """Register `/classify` on the world node, over the node's own Gateway client (spec E9).

    INVARIANT (E2): a declared model whose route is `/classify` fails composition here, named,
    before anything registers. Skipping the endpoint instead would leave a world without
    classification and nothing saying why.

    Raises:
        WorldConfigError: a declared model takes the `/classify` route.
    """
    # WHY the world's own client: it is the one the chat calls and the frozen-copy open and seal
    # use, so a classification carries the same identity, trace and transport limits.
    endpoint = ClassificationEndpoint(world._client, cfg)
    _register(world.node, CLASSIFY_ROUTE, "classification", endpoint)


def _install_routing(
    world: AigatewayWorld, cfg: AigatewayConfig, profiles: Mapping[str, RoutingProfile]
) -> None:
    """Register `/route-answer`; a branch is a nested call of its own chat route (spec 4.1)."""
    node = world.node

    async def branch(choice: RoutingBranch, text: str) -> str:
        # WHY a nested dispatch: the branch is the ordinary chat route, with its scope, cache
        # policy, limits and refusals. No intent sends the input as the one user message.
        params = (("max_tokens", str(choice.max_tokens)), ("web_search", "false"))
        target = encode_subrequest("/" + choice.model, text, None, params)
        try:
            return await node.fetch(target, relative=True)
        except _GatewayRefusal:
            # INVARIANT (review P3): a Gateway answer is relayed, never the hiding below,
            # whatever code its body names.
            raise
        except ResolutionError as exc:
            # INVARIANT: an ungranted private branch answers url4's undeclared route, whose
            # message names the path; the caller learns only that the profile is not theirs.
            if exc.code != ErrorCode.ENDPOINT_NOT_FOUND:
                raise
            raise not_found() from None

    endpoint = RoutedAnswerEndpoint(world._client, cfg, profiles, branch)

    async def routed(context: str, intent: str, params: Mapping[str, str]) -> str:
        try:
            return await endpoint(context, intent, params)
        except ResolutionError as exc:
            # WHY every url4 error here: the handler's own refusals are `RunnerRequestError`, and
            # the preflight reads raise nothing else, so one here answers the classifier or the
            # branch call, which was already sent.
            # WHY `from None`: a logged traceback would print the cause, and its upstream text.
            raise _relayed(exc) from None

    _register(node, ROUTE_ANSWER_ROUTE, "routed answers", routed)


def _relayed(exc: ResolutionError) -> ResolutionError:
    """``exc`` as a routed answer relays it: its permanence, an Engine code, a fixed message.

    INVARIANT (OME-1822 review, spec 3.5 and 6.1 C9): no relayed text crosses. The Gateway, or a
    proxy in front of it, wrote a refusal's message, and the Engine's own failure of a sent call
    can quote the answer or the transport error behind it. Any of them can name a key, an origin,
    a path or a private model ID, and no screen tells a private model ID from a plain word, so the
    message is always `ROUTED_CALL_FAILED_MESSAGE`. This runs before the error becomes the run's
    terminal error, so the envelope, the run's events and the runner's terminal log read the same
    text. The connector's own model-call log line, which reads the lifted code inside the branch
    call, is the separate connector unit's (spec 9).

    INVARIANT (review P3 and C9): a Gateway refusal never keeps its body's code, whatever it names:
    it takes the connector's `aigateway_http_<status>`, so it neither leaks, nor reads as a
    refusal of the caller's request, nor borrows an Engine diagnosis such as `model_token_cap`.
    The Engine's own code for a sent call (`aigateway_bad_response`, `model_token_cap` from a
    `length` answer, `timeout`) is not a refusal and is kept.
    """
    code = exc.code
    if isinstance(exc, _GatewayRefusal):
        code = f"aigateway_http_{exc.status}"
    return ResolutionError(ROUTED_CALL_FAILED_MESSAGE, code=code, permanent=exc.permanent)


def _register(
    node: Url4Node,
    route: str,
    purpose: str,
    endpoint: Callable[[str, str, Mapping[str, str]], Awaitable[str]],
) -> None:
    """Register a request-addressed endpoint, refused when a declared model takes its route."""
    if route in node.processor_routes():
        raise WorldConfigError(
            f"the declared model {route[1:]!r} takes the route {route}, which "
            f"the Engine reserves for {purpose}"
        )

    async def handle(request: Request) -> str:
        try:
            return await endpoint(request.context, request.intent, request.params)
        except RunnerRequestError as exc:
            # The url4 half of the handler's stable codes, as `connector._ModelEndpoint` does.
            raise ResolutionError(str(exc), code=exc.code, permanent=exc.permanent) from exc

    node.endpoint(route)(handle)


__all__ = ["install_gateway_endpoints"]
