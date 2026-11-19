"""The image input matrix's url4 path client (image input matrix spec §3.3, plan Task 3).

One call sends one committed fixture to one model as a url4 attachment
(``/<model>(src=<url>;accept=<type>)!'<prompt>'``) straight at the local Engine, and returns
what came back; ``image_matrix`` decides what that means.

WHY Engine-direct (plan spike S0): the SDK's ``evaluate(url4=…)`` only replays a
Benchmark-owned evaluation URL4, so a bare model call has no SDK route. The Engine runs any
expression: ``POST /token`` mints a capability (no auth), and ``GET /?q=`` with that
capability in ``URL4-Capability`` (NOT ``Authorization``, OME-556) holds until the run ends,
bounded by ``sync_max_wait_s`` (``screamingface_engine.rest.routes``).

WHY a client-minted ``traceparent``: the Engine adopts a strictly valid one, so the cell's
trace id is known before the call and the trace-chain verdict can look it up even when the
run fails without a body.

INVARIANT: unknown is never a pass. A 202 (the run outlived the sync bound), an empty 200, a
failed mint or a dead connection each come back as an error code, never as an answer.

NOTE ``spend_usd`` is always ``None`` here: the synchronous response carries only the Result
body or a problem; the run's cost is the separate ``cost.usage`` stream event. The notebook
reads spend from the trace evidence, not from this call.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from urllib.parse import quote

import httpx
from url4 import Expression, RelExpr, Source, Url, Url4Error, build, render, src, text

# jsDelivr, not raw.githubusercontent.com: raw serves `.pdf` as application/octet-stream (nosniff),
# which the Engine refuses as an attachment type before any model call. jsDelivr serves the same
# bytes at the same commit with the real Content-Type.
FIXTURE_REPO: Final = "https://cdn.jsdelivr.net/gh/ScreamingFace/screamingface"
CAPABILITY_HEADER: Final = "URL4-Capability"
# The codes this client authors for outcomes the Engine did not name.
SYNC_TIMEOUT: Final = "sync_timeout"
EMPTY_RESULT: Final = "empty_result"
TOKEN_MINT_FAILED: Final = "token_mint_failed"
TRANSPORT_ERROR: Final = "transport_error"


class FixtureError(Exception):
    """A fixture URL that does not serve the committed bytes: a setup error, before any spend."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"fixture {url}: {reason}")
        self.url = url
        self.reason = reason


@dataclass(frozen=True)
class Url4Outcome:
    """What one attachment call returned. Exactly one of ``answer`` / ``error_code`` is set."""

    trace_id: str
    answer: str | None
    error_code: str | None
    spend_usd: Decimal | None = None


def fixture_url(ref: str, path: str) -> str:
    """The commit-pinned jsDelivr URL of a repo-relative fixture ``path`` at ``ref``."""
    if not ref.strip() or not path or path.startswith("/"):
        raise ValueError(f"need a ref and a repo-relative path, got ref={ref!r} path={path!r}")
    return f"{FIXTURE_REPO}@{quote(ref, safe='')}/{quote(path)}"


def verify_fixture(client: httpx.Client, url: str, sha256: str) -> None:
    """Raise :class:`FixtureError` unless ``url`` serves bytes whose digest is ``sha256``.

    WHY before any model call (Review Focus 3): a stale ``FIXTURE_REF`` would otherwise read
    as every model failing to see the picture, and spend money proving nothing.
    """
    try:
        response = client.get(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise FixtureError(url, f"unreachable ({type(exc).__name__})") from exc
    if response.status_code != 200:
        raise FixtureError(url, f"HTTP {response.status_code}")
    digest = hashlib.sha256(response.content).hexdigest()
    if digest != sha256:
        raise FixtureError(url, f"sha256 {digest} does not match the manifest's {sha256}")


def route_id(model: str) -> str:
    """The url4 route form of a gateway id: ``:`` escaped as ``~``.

    WHY: a url4 path segment admits no ``:``, so the Engine routes a gateway id like
    ``huggingface/<org>/<model>:<provider>`` as ``…~<provider>`` (OME-873,
    ``screamingface_engine.world.models.registry.encode_route_id``), and the SDK's ``sf.Model``
    takes the same form (``sf.models.list()``). A no-op on an id without a colon.
    """
    return model.replace(":", "~")


def attachment_expression(model: str, url: str, media_type: str, prompt: str) -> str:
    """``/<model>(src=<url>;accept=<type>)!'<prompt>'``, built with url4 and round-trip checked.

    The context keeps the explicit ``src=`` marker, the exact shape the Engine's own test runs
    (``test_fair_share_fetch_bytes.py``); a sugar call's context is raw text, so the marker is
    added here and the round trip proves it parses to the one attachment source. Raises
    ``ValueError`` when the text would not parse back to the call it was built from — a model
    id or URL url4 would read differently must fail here, not as a confusing refusal.
    """
    attachment = Source(value=Url(url), annotations=(("accept", media_type),))
    try:
        context = f"src={render(src(url, accept=media_type))}"
        call = RelExpr(path=f"/{route_id(model)}", context=context, intent=text(prompt))
        expression = render(call)
        # A top-level relative call parses as the one source of an intent-less carrier.
        tree = build(expression)
        inner = build(f"({context})!'x'")
    except Url4Error as exc:
        raise ValueError(f"url4 expression does not round-trip for {model} {url}: {exc}") from exc
    if (
        not isinstance(tree, Expression)
        or tree.sources != (call,)
        or not isinstance(inner, Expression)
        or inner.sources != (attachment,)
    ):
        raise ValueError(f"url4 expression does not round-trip: {expression!r}")
    return expression


def _traceparent() -> tuple[str, str]:
    """A fresh sampled W3C traceparent and its trace id (``token_hex`` is never all-zero in
    practice; the Engine would mint its own for an all-zero one, breaking the chain visibly)."""
    trace_id = secrets.token_hex(16)
    return f"00-{trace_id}-{secrets.token_hex(8)}-01", trace_id


def _mint(client: httpx.Client, engine_url: str) -> str | None:
    response = client.post(f"{engine_url}/token")
    if response.status_code != 200:
        return None
    try:
        token = response.json().get("token")
    except ValueError:
        return None
    return token if isinstance(token, str) and token else None


def _problem_code(response: httpx.Response) -> str:
    """An RFC 9457 problem's ``code``, or ``http_<status>`` when it names none."""
    try:
        body = response.json()
    except ValueError:
        body = None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) and code else f"http_{response.status_code}"


def _error_code(response: httpx.Response) -> str | None:
    """``None`` for a 200 with a body (the answer); otherwise the code the cell reports."""
    if response.status_code == 202:
        return SYNC_TIMEOUT
    if response.status_code == 200:
        return None if response.text else EMPTY_RESULT
    return _problem_code(response)


def _outcome(response: httpx.Response, trace_id: str) -> Url4Outcome:
    code = _error_code(response)
    return Url4Outcome(trace_id, response.text if code is None else None, code)


def run_attachment(
    client: httpx.Client,
    engine_url: str,
    model: str,
    url: str,
    media_type: str,
    prompt: str,
) -> Url4Outcome:
    """Run one attachment call on the Engine at ``engine_url`` and report what came back."""
    expression = attachment_expression(model, url, media_type, prompt)
    traceparent, trace_id = _traceparent()
    engine = engine_url.rstrip("/")
    try:
        token = _mint(client, engine)
        if token is None:
            return Url4Outcome(trace_id, None, TOKEN_MINT_FAILED)
        response = client.get(
            f"{engine}/",
            params={"q": expression},
            headers={CAPABILITY_HEADER: token, "traceparent": traceparent},
        )
    except httpx.HTTPError:
        return Url4Outcome(trace_id, None, TRANSPORT_ERROR)
    return _outcome(response, trace_id)
