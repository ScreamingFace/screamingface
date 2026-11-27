"""C17: the Engine's classifier catalog, `GET /v1/classifiers` (Unit 5.2).

FEATURE: Router Recipe extension. The SDK preflights a Router Recipe against classifier metadata
it can read only through the Engine. The Engine relays the caller's own Gateway list, fresh per
request, projected to `id`, `input_contracts` and `limits`.

STORY: as an SDK about to submit a Router Recipe, I ask the Engine which classifiers I may name and
which inputs and limits each takes, so a Router that cannot run is refused before submission.

INVARIANT: strict and no-inference. A row that breaks C7, or shares its ID with another row, is
omitted, never repaired; the list is never intersected with the Engine's routes; a body that is
encoded, over 1,000,000 bytes or not a list envelope is a fixed 502, never a partial success.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from classifier_catalog_support import (
    BOTH,
    CHOICE,
    CHOICE_LIMITS,
    IDENTITY,
    TEXT_LIMITS,
    TEXT_NULL,
    TRACE,
    gateway,
    json_answer,
    listed_rows,
    listing,
    projected,
)
from classifier_catalog_support import row as _row
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.catalog import build_catalog_service
from screamingface_engine.catalog.executable import ExecutableCatalog
from screamingface_engine.catalog.port import (
    CatalogError,
    CatalogRejected,
    CatalogUnavailable,
    ClassifierBadResponse,
    Credential,
)
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

_PRIVATE = {"Cache-Control": "private, no-store", "Vary": "X-Profile, X-User-Email"}
_MAX_BODY = 1_000_000


# --- the adapter ----------------------------------------------------------------------------------


async def test_the_callers_rows_are_projected_in_their_order() -> None:
    seen: list[httpx.Request] = []
    source = gateway(json_answer(200, listing(CHOICE, TEXT_NULL, BOTH)), seen)

    rows = await source.fetch_classifiers(Credential.derive(IDENTITY), traceparent=TRACE)

    assert rows == [projected(CHOICE), projected(TEXT_NULL), projected(BOTH)]
    (request,) = seen
    assert (request.method, request.url.path, request.url.query) == ("GET", "/v1/classifiers", b"")
    assert request.headers["X-User-Email"] == "alice@example.com"
    assert request.headers["Accept-Encoding"] == "identity"
    assert request.headers["traceparent"] == TRACE
    assert "authorization" not in request.headers
    assert "X-Profile" not in request.headers


async def test_an_empty_list_is_an_empty_success() -> None:
    assert await listed_rows(json_answer(200, listing())) == []


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(_row("x/y", ["image"], None), id="unknown-contract"),
        pytest.param(_row("x/y", ["choice", "text"], CHOICE_LIMITS), id="contracts-out-of-order"),
        pytest.param(_row("x/y", ["text", "text"], TEXT_LIMITS), id="repeated-contract"),
        pytest.param(_row("x/y", [], None), id="no-contract"),
        pytest.param(_row("x/y", "text", None), id="contracts-not-a-list"),
        pytest.param(_row("x/y", ["choice"], None), id="choice-without-limits"),
        pytest.param(_row("x/y", ["choice"], TEXT_LIMITS), id="choice-with-text-limits"),
        pytest.param(_row("x/y", ["text"], CHOICE_LIMITS), id="text-with-choice-limits"),
        pytest.param(
            _row("x/y", ["text"], {**TEXT_LIMITS, "contract": "classifier-limits-v2"}),
            id="unknown-limits-contract",
        ),
        pytest.param(
            _row("x/y", ["text"], {k: v for k, v in TEXT_LIMITS.items() if k != "max_labels"}),
            id="missing-limit",
        ),
        pytest.param(_row("x/y", ["text"], {**TEXT_LIMITS, "max_votes": 3}), id="unknown-limit"),
        pytest.param(_row("x/y", ["text"], {**TEXT_LIMITS, "max_labels": 0}), id="limit-zero"),
        pytest.param(
            _row("x/y", ["text"], {**TEXT_LIMITS, "max_labels": 2147483648}),
            id="limit-too-big",
        ),
        pytest.param(_row("x/y", ["text"], {**TEXT_LIMITS, "max_labels": True}), id="limit-bool"),
        pytest.param(_row("x/y", ["text"], {**TEXT_LIMITS, "max_labels": 8.0}), id="limit-float"),
        pytest.param(
            {k: v for k, v in TEXT_NULL.items() if k != "limits"} | {"id": "x/y"},
            id="no-limits-key",
        ),
        pytest.param(
            {k: v for k, v in TEXT_NULL.items() if k != "input_contracts"} | {"id": "x/y"},
            id="no-contracts-key",
        ),
        pytest.param(_row("", ["text"], None), id="empty-id"),
        pytest.param({**TEXT_NULL, "id": 7}, id="id-not-a-string"),
        pytest.param(["x/y"], id="row-not-an-object"),
    ],
)
async def test_a_row_that_breaks_c7_is_omitted_never_repaired(row: object) -> None:
    rows = await listed_rows(json_answer(200, listing(TEXT_NULL, row, CHOICE)))

    assert rows == [projected(TEXT_NULL), projected(CHOICE)]


async def test_the_largest_limit_is_usable() -> None:
    row = _row("x/y", ["text"], {**TEXT_LIMITS, "max_text_chars": 2147483647})

    assert await listed_rows(json_answer(200, listing(row))) == [projected(row)]


async def test_every_row_of_a_duplicated_id_is_omitted() -> None:
    twin = _row(CHOICE["id"], ["text"], None)
    broken_twin = _row(BOTH["id"], ["image"], None)

    rows = await listed_rows(json_answer(200, listing(CHOICE, TEXT_NULL, twin, BOTH, broken_twin)))

    assert rows == [projected(TEXT_NULL)]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"not json", id="not-json"),
        pytest.param(b'{"object": "list", "data": [NaN]}', id="non-json-constant"),
        pytest.param(b"[]", id="array"),
        pytest.param(b'{"data": []}', id="no-object"),
        pytest.param(b'{"object": "model", "data": []}', id="wrong-object"),
        pytest.param(b'{"object": "list"}', id="no-data"),
        pytest.param(b'{"object": "list", "data": {}}', id="data-not-a-list"),
        pytest.param(b"\xff\xfe", id="not-utf8"),
        pytest.param(b"[" * 100_000 + b"]" * 100_000, id="nested-past-the-decoder"),
    ],
)
async def test_a_malformed_envelope_is_a_fixed_502(content: bytes) -> None:
    with pytest.raises(ClassifierBadResponse) as caught:
        await listed_rows(lambda _: httpx.Response(200, content=content))

    assert (caught.value.status, str(caught.value)) == (502, ClassifierBadResponse.detail)


def _padded(size: int) -> bytes:
    """A valid one-row list of exactly ``size`` bytes."""
    head = json.dumps(listing(TEXT_NULL)).encode()
    return head[:-1] + b" " * (size - len(head)) + head[-1:]


async def test_a_body_of_exactly_the_bound_is_read() -> None:
    body = _padded(_MAX_BODY)
    assert len(body) == _MAX_BODY

    assert await listed_rows(lambda _: httpx.Response(200, content=body)) == [projected(TEXT_NULL)]


class _Chunks(httpx.AsyncByteStream):
    """A streamed body with no `Content-Length`, counting the chunks the reader pulled."""

    def __init__(self, body: bytes, size: int = 65536) -> None:
        self.chunks = [body[i : i + size] for i in range(0, len(body), size)]
        self.pulled = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.pulled += 1
            yield chunk


async def test_a_body_one_byte_past_the_bound_is_a_502_not_a_truncation() -> None:
    body = _padded(_MAX_BODY + 1)

    with pytest.raises(ClassifierBadResponse):
        await listed_rows(lambda _: httpx.Response(200, content=body))


async def test_a_streamed_body_is_cut_off_at_the_bound() -> None:
    stream = _Chunks(_padded(3 * _MAX_BODY))

    with pytest.raises(ClassifierBadResponse):
        await listed_rows(lambda _: httpx.Response(200, stream=stream))

    # WHY 16: 15 chunks of 64 KiB hold 983,040 bytes; the 16th passes the bound.
    assert stream.pulled == 16 < len(stream.chunks)


async def test_a_streamed_body_within_the_bound_is_read() -> None:
    stream = _Chunks(_padded(_MAX_BODY))

    assert await listed_rows(lambda _: httpx.Response(200, stream=stream)) == [projected(TEXT_NULL)]


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "identity, gzip"])
async def test_an_encoded_body_is_a_502(encoding: str) -> None:
    with pytest.raises(ClassifierBadResponse):
        await listed_rows(json_answer(200, listing(TEXT_NULL), **{"Content-Encoding": encoding}))


async def test_an_identity_encoded_body_is_read() -> None:
    answer = json_answer(200, listing(TEXT_NULL), **{"Content-Encoding": "identity"})

    assert await listed_rows(answer) == [projected(TEXT_NULL)]


@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_identity_keeps_the_catalog_mapping(status: int) -> None:
    with pytest.raises(CatalogRejected):
        await listed_rows(json_answer(status, {"detail": "no"}))


@pytest.mark.parametrize("status", [301, 400, 404, 409, 429, 500, 503])
async def test_any_other_status_is_the_fixed_502(status: int) -> None:
    with pytest.raises(ClassifierBadResponse):
        await listed_rows(json_answer(status, listing(TEXT_NULL)))


async def test_a_timeout_keeps_the_catalog_mapping() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(CatalogUnavailable):
        await listed_rows(answer)


async def test_a_transport_failure_is_the_fixed_502() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ClassifierBadResponse):
        await listed_rows(answer)


# --- the route ------------------------------------------------------------------------------------


class _Classifiers:
    def __init__(self, answer: list[dict[str, Any]] | CatalogError) -> None:
        self.answer = answer
        self.seen: list[tuple[Credential, str | None]] = []

    async def fetch_classifiers(
        self, credential: Credential, *, traceparent: str | None = None
    ) -> list[dict[str, Any]]:
        self.seen.append((credential, traceparent))
        if isinstance(self.answer, CatalogError):
            raise self.answer
        return self.answer


async def _get(app: Any, **headers: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get("/v1/classifiers", headers=headers)


def _app(source: object | None) -> Any:
    return create_app(
        Settings(jwt_secret="classifier-catalog-test"),
        stream=InMemoryEventStream(),
        classifiers=source,  # type: ignore[arg-type]
    )


async def test_the_route_lists_the_callers_classifiers_privately() -> None:
    source = _Classifiers([projected(CHOICE)])

    response = await _get(_app(source), traceparent=TRACE, **IDENTITY)

    assert response.status_code == 200
    assert response.json() == {"object": "list", "data": [projected(CHOICE)]}
    assert {k: response.headers[k] for k in _PRIVATE} == _PRIVATE
    assert "ETag" not in response.headers
    ((credential, traceparent),) = source.seen
    assert (credential.identity, traceparent) == (IDENTITY, TRACE)


async def test_a_stated_selector_is_refused_before_the_gateway() -> None:
    source = _Classifiers([])

    response = await _get(_app(source), **{"X-Profile": "research"})

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert {k: response.headers[k] for k in _PRIVATE} == _PRIVATE
    assert source.seen == []


async def test_an_unconfigured_deployment_is_a_private_503() -> None:
    response = await _get(_app(None))

    assert response.status_code == 503
    assert {k: response.headers[k] for k in _PRIVATE} == _PRIVATE


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (CatalogRejected(CatalogRejected.detail), 401),
        (ClassifierBadResponse("upstream said sk-secret-shaped"), 502),
        (CatalogUnavailable(CatalogUnavailable.detail), 504),
    ],
)
async def test_a_failure_is_a_private_problem_with_a_fixed_detail(
    error: CatalogError, status: int
) -> None:
    response = await _get(_app(_Classifiers(error)))

    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert {k: response.headers[k] for k in _PRIVATE} == _PRIVATE
    assert response.json()["detail"] == type(error).detail
    assert "secret" not in response.text
    assert ("WWW-Authenticate" in response.headers) is (status == 401)


async def test_every_request_reads_a_fresh_gateway_list() -> None:
    seen: list[httpx.Request] = []
    lists = iter([listing(TEXT_NULL), listing(CHOICE)])
    source = gateway(lambda _: httpx.Response(200, json=next(lists)), seen)
    app = _app(source)

    first, second = await _get(app), await _get(app)

    assert first.json()["data"] == [projected(TEXT_NULL)]
    assert second.json()["data"] == [projected(CHOICE)]
    assert len(seen) == 2


async def test_the_route_is_published_under_catalog() -> None:
    operation = _app(None).openapi()["paths"]["/v1/classifiers"]["get"]

    assert operation["tags"] == ["Catalog"]
    assert {"200", "400", "401", "502", "503", "504"} <= set(operation["responses"])


# --- the composition ------------------------------------------------------------------------------


async def test_the_executable_catalog_exposes_the_gateway_list_unbounded_by_its_routes() -> None:
    clients: list[httpx.AsyncClient] = []

    def client_factory(base_url: str) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            base_url=base_url,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=listing(CHOICE))),
        )
        clients.append(client)
        return client

    settings = Settings(jwt_secret="classifier-catalog-test", aigateway_base_url="http://gw.test")
    service = build_catalog_service(settings, client_factory=client_factory)
    assert service is not None
    catalog = ExecutableCatalog(service, frozenset({"openrouter/openai/gpt-5.5"}))

    source = catalog.classifier_source
    assert source is not None
    # WHY a classifier no route declares: C17 is no intersection with the Engine's chat routes.
    assert await source.fetch_classifiers(Credential.derive()) == [projected(CHOICE)]
    assert len(clients) == 1
    await service.aclose()


async def test_the_local_composition_wires_the_classifier_source() -> None:
    app = create_local_app(
        Settings(jwt_secret="classifier-catalog-test", aigateway_base_url="http://gw.test"),
        env={},
    )

    assert app.state.catalog is not None
    assert app.state.classifiers is not None
    assert app.state.classifiers is app.state.catalog.classifier_source
    await app.state.catalog.aclose()
    await app.state.job_runner.aclose()


# --- ambiguous and non-finite rows ----------------------------------------------------------------


def _raw_listing(*rows: str) -> bytes:
    """A list envelope around rows written as raw JSON text (repeated keys survive)."""
    good = [json.dumps(TEXT_NULL), *rows, json.dumps(CHOICE)]
    return ('{"object": "list", "data": [' + ", ".join(good) + "]}").encode()


_LIMITS_TEXT = json.dumps(TEXT_LIMITS)


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(json.dumps(_row("x/y", ["text"], None) | {"id": ["x/y"]}), id="id-a-list"),
        pytest.param(json.dumps(_row("x/y", ["text"], None) | {"id": {"x": 1}}), id="id-an-object"),
        pytest.param(
            '{"id": "x/y", "id": "x/z", "input_contracts": ["text"], "limits": null}',
            id="row-repeats-a-key",
        ),
        pytest.param(
            '{"id": "x/y", "input_contracts": ["text"], "limits": '
            + _LIMITS_TEXT[:-1]
            + ', "max_labels": 9}}',
            id="limits-repeat-a-key",
        ),
        pytest.param(
            '{"id": "x/y", "input_contracts": ["text"], "limits": '
            + _LIMITS_TEXT.replace('"max_labels": 32', '"max_labels": 1e999')
            + "}",
            id="limit-not-finite",
        ),
    ],
)
async def test_an_ambiguous_or_unhashable_row_is_omitted_and_the_rest_listed(row: str) -> None:
    rows = await listed_rows(lambda _: httpx.Response(200, content=_raw_listing(row)))

    # INVARIANT (C17): an unusable row is omitted, never a 500 and never the whole list.
    assert rows == [projected(TEXT_NULL), projected(CHOICE)]


async def test_an_envelope_that_repeats_a_key_is_the_fixed_502() -> None:
    content = b'{"object": "list", "data": [], "data": []}'

    with pytest.raises(ClassifierBadResponse) as caught:
        await listed_rows(lambda _: httpx.Response(200, content=content))

    assert (caught.value.status, str(caught.value)) == (502, ClassifierBadResponse.detail)
