"""The chat turn route of a chat run (chat-run PRD CR-S1, CR-S4, CR-S6, CR-S7, CR-S8, CR-S18).

FEATURE: chat-run. The executor dispatches `/ensemble/chat/v1/turn` inside a chat run. The route
reads the CHAT_INPUT record, binds its text view to `$input`, runs the recipe as the Candidate
route does, and answers with one CHAT_RESULT record.

INVARIANT: a missing, corrupt or unknown record fails before any model call, and the route fails
closed outside a chat run (CR-24).
"""

from __future__ import annotations

import hashlib
import random
import string
from collections.abc import Callable

import pytest
from _chat_world import (
    REFUSE,
    RUN,
    Gateway,
    chat_store,
    chat_world,
    ingest_chat_input,
    run_turn,
)
from test_abstain_mark import _answered_evidence, _operations

from screamingface_engine.artifacts.blobs import (
    BLOB_REF_PREFIX,
    BlobScope,
    ScopedBlobReader,
    StoredBlob,
    encode_sidecar,
)
from screamingface_engine.artifacts.s3 import S3StorageError
from screamingface_engine.artifacts.wiring import BlobStoreNotConfigured
from screamingface_engine.benchmarks.contract import (
    OperationOutput,
    decode_candidate_invocation_record,
    encode_candidate_invocation,
)
from screamingface_engine.chat.input import CHAT_INPUT_MEDIA_TYPE
from screamingface_engine.chat.recipe import one_model_recipe
from screamingface_engine.chat.wire import canonical_json
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.attachment_parts import BlobReader
from screamingface_engine.world.chat_turn import (
    CHAT_TURN_ROUTE,
    chat_result_from_invocation,
    chat_run_scope,
    chat_turn_target,
    install_chat_turn,
)
from url4 import RelExpr, expr, render, src, text
from url4.core.errors import ResolutionError, Url4Error
from url4.peer import dispatch_direct
from url4.wire.subrequest import decode_subrequest_http, extract_expression_params

MODEL = "prov/a"
RECIPE = one_model_recipe(MODEL)
MESSAGES = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "Capital of France?"},
]
REF = BLOB_REF_PREFIX + "ab" * 32


def _invocation(output: str, finish_reason: str | None, refusal: str | None = None, **kw):
    return decode_candidate_invocation_record(
        encode_candidate_invocation(output, finish_reason, refusal, **kw)
    )


def _model_op(finish_reason: str | None) -> OperationOutput:
    return OperationOutput(
        operation_id="op_model_1", output="Paris", finish_reason=finish_reason, accounting=None
    )


# --- CR-6: the happy path ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_run_binds_text_view_to_input_and_returns_chat_result() -> None:
    gateway = Gateway({MODEL: "Paris"})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)

    async with chat_world(gateway) as node:
        result = await run_turn(node, RECIPE, ref, reader)

    assert result.status == "answered"
    assert result.content == "Paris"
    assert result.finish_reason == "stop"
    assert result.tool_calls == []
    assert result.final_step is not None
    assert result.final_step.binding == "model_1"
    assert result.final_step.model == MODEL
    assert result.final_step.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
    }
    assert len(gateway.seen) == 1
    sent = [(m["role"], m["content"]) for m in gateway.seen[0]["messages"]]
    assert sent == [(m["role"], m["content"]) for m in MESSAGES]


# --- CR-10, CR-12: the mapping of the Candidate Invocation ------------------------------------


def test_abstain_gives_abstained_status_and_empty_content() -> None:
    invocation = _invocation("", "stop", None, abstained=True)

    result = chat_result_from_invocation(invocation, None, abstain_reason="no_votes")

    assert result.status == "abstained"
    assert result.content == ""
    assert result.tool_calls == []
    assert result.finish_reason == "stop"
    assert result.abstain_reason == "no_votes"
    assert result.final_step is None


def test_refused_invocation_gives_refused_status_and_content_filter() -> None:
    invocation = _invocation("", "content_filter", "I cannot help.", status="refused")

    result = chat_result_from_invocation(invocation, None, abstain_reason=None)

    assert result.status == "refused"
    assert result.finish_reason == "content_filter"
    assert result.refusal == "I cannot help."
    assert result.content == ""


@pytest.mark.asyncio
async def test_refused_invocation_through_the_turn_route_gives_refused_status() -> None:
    gateway = Gateway({MODEL: REFUSE})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)

    async with chat_world(gateway) as node:
        result = await run_turn(node, RECIPE, ref, reader)

    assert result.status == "refused"
    assert result.finish_reason == "content_filter"
    assert result.content == ""


def test_the_finish_reason_of_the_final_model_step_passes_through() -> None:
    final = _model_op("length")
    invocation = _invocation("Paris", "length", operations=[final])

    result = chat_result_from_invocation(invocation, final, abstain_reason=None)

    assert result.status == "answered"
    assert result.content == "Paris"
    assert result.finish_reason == "length"


def test_a_reducer_final_step_gives_stop_and_no_final_step() -> None:
    (final,) = _operations(_answered_evidence(), output="x")
    final = final.model_copy(update={"finish_reason": "length"})
    invocation = _invocation("x", "stop", operations=[final])

    result = chat_result_from_invocation(invocation, final, abstain_reason=None)

    assert result.finish_reason == "stop"
    assert result.final_step is None


def test_no_attributed_final_operation_gives_stop_and_no_final_step() -> None:
    invocation = _invocation("pass", None, operations=[])

    result = chat_result_from_invocation(invocation, None, abstain_reason=None)

    assert result.status == "answered"
    assert result.content == "pass"
    assert result.finish_reason == "stop"
    assert result.final_step is None


def test_a_final_step_without_accounting_has_no_final_step() -> None:
    final = _model_op("stop")
    invocation = _invocation("Paris", "stop", operations=[final])

    result = chat_result_from_invocation(invocation, final, abstain_reason=None)

    assert result.final_step is None


# --- CR-13, CR-S8: the record is read before any model call -----------------------------------


def _not_configured() -> BlobReader:
    raise BlobStoreNotConfigured("no chat-input store")


def _corrupt_case() -> tuple[str, Callable[[], BlobReader]]:
    store, objects = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)
    sha = ref.removeprefix(BLOB_REF_PREFIX)
    key = f"{BlobScope.for_caller(None, RUN).key_prefix}/{sha}"
    objects.objects[key] = b"x" * len(objects.objects[key])
    return ref, reader


def _never_ingested_case() -> tuple[str, Callable[[], BlobReader]]:
    store, _ = chat_store()
    _, reader = ingest_chat_input(store, MESSAGES)
    return BLOB_REF_PREFIX + "0" * 64, reader


def _not_configured_case() -> tuple[str, Callable[[], BlobReader]]:
    return REF, _not_configured


def _no_prefix_case() -> tuple[str, Callable[[], BlobReader]]:
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)
    return "sha256:" + ref.removeprefix(BLOB_REF_PREFIX), reader


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        pytest.param(_never_ingested_case, id="never-ingested"),
        pytest.param(_corrupt_case, id="corrupt-data"),
        pytest.param(_not_configured_case, id="store-not-configured"),
        pytest.param(_no_prefix_case, id="no-blob-prefix"),
    ],
)
async def test_missing_or_corrupt_blob_fails_before_any_model_call(
    case: Callable[[], tuple[str, Callable[[], BlobReader]]],
) -> None:
    gateway = Gateway({MODEL: "Paris"})
    ref, reader = case()

    async with chat_world(gateway) as node:
        with pytest.raises(ResolutionError) as caught:
            await run_turn(node, RECIPE, ref, reader)

    assert caught.value.code == "chat_input_unavailable"
    assert caught.value.permanent is True
    assert str(caught.value) == "the chat input is not available"
    assert gateway.seen == []


class _FailingReader:
    """A reader whose store fails at read time, as a sick object store or disk does."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def read(self, digest: str) -> bytes | None:
        raise self._error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            S3StorageError("GET blobs/x could not reach object storage: http://secret.test"),
            id="s3-storage-error",
        ),
        pytest.param(OSError(5, "Input/output error: /secret/path"), id="os-error"),
    ],
)
async def test_a_storage_failure_fails_chat_input_unavailable_and_transient(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    gateway = Gateway({MODEL: "Paris"})

    async with chat_world(gateway) as node:
        with pytest.raises(ResolutionError) as caught:
            await run_turn(node, RECIPE, REF, lambda: _FailingReader(error))

    assert caught.value.code == "chat_input_unavailable"
    assert caught.value.permanent is False
    assert str(caught.value) == "the chat input is not available"
    assert gateway.seen == []
    assert type(error).__name__ in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.asyncio
async def test_unknown_schema_fails_chat_input_invalid_before_any_model_call() -> None:
    gateway = Gateway({MODEL: "Paris"})
    store, objects = chat_store()
    body = canonical_json({"schema": "screamingface.chat-input.v9", "messages": MESSAGES})
    sha = hashlib.sha256(body).hexdigest()
    scope = BlobScope.for_caller(None, RUN)
    objects.objects[f"{scope.key_prefix}/{sha}"] = body
    objects.objects[f"{scope.key_prefix}/{sha}.json"] = encode_sidecar(
        StoredBlob(sha, len(body), CHAT_INPUT_MEDIA_TYPE)
    )

    async with chat_world(gateway) as node:
        with pytest.raises(ResolutionError) as caught:
            await run_turn(
                node, RECIPE, BLOB_REF_PREFIX + sha, lambda: ScopedBlobReader(store, scope)
            )

    assert caught.value.code == "chat_input_invalid"
    assert caught.value.permanent is True
    assert gateway.seen == []


# --- CR-24: the route fails closed outside a chat run -----------------------------------------


@pytest.mark.asyncio
async def test_turn_route_outside_chat_run_fails_closed_before_any_work() -> None:
    gateway = Gateway({MODEL: "Paris"})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)
    calls: list[int] = []

    def counting() -> BlobReader:
        calls.append(1)
        return reader()

    # WHY a scope that has ended: the marker must be reset on exit, so a later call finds none.
    with chat_run_scope(counting):
        pass
    expression = render(
        expr(
            src(
                RelExpr(path=CHAT_TURN_ROUTE, context=ref, intent=text(RECIPE)),
                name="t",
                weight=0.0,
            ),
            intent=text("$t"),
        )
    )

    async with chat_world(gateway) as node:
        with request_scope(RequestScope(origin="run")):
            with pytest.raises(ResolutionError) as direct:
                await dispatch_direct(node, chat_turn_target(ref, RECIPE))
            with pytest.raises(Url4Error) as evaluated:
                await node.evaluate(expression)

    assert direct.value.code == "endpoint_not_found"
    assert direct.value.permanent is True
    assert evaluated.value.code == "endpoint_not_found"
    assert calls == []
    assert gateway.seen == []


@pytest.mark.asyncio
async def test_turn_route_inside_chat_run_refuses_a_nested_turn_before_any_work() -> None:
    gateway = Gateway({MODEL: "Paris"})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, MESSAGES)
    calls: list[int] = []

    def counting() -> BlobReader:
        calls.append(1)
        return reader()

    outer = render(
        expr(
            src(
                RelExpr(path=CHAT_TURN_ROUTE, context=ref, intent=text(RECIPE)),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )

    async with chat_world(gateway) as node:
        with pytest.raises(Url4Error) as caught:
            await run_turn(node, outer, ref, counting)

    assert caught.value.code == "endpoint_not_found"
    assert caught.value.permanent is True
    assert calls == [1]
    assert gateway.seen == []


# --- CR-27: the turn target keeps the recipe ---------------------------------------------------

_ALPHABET = string.printable + "'\"()!$&%+=?;#\\" + "Grüße 東京 é"


def _round_trip(recipe: str) -> None:
    target = chat_turn_target(REF, recipe)
    path, _, query = target.partition("?")
    params, q = extract_expression_params(query)
    assert q is not None
    context, intent = decode_subrequest_http(q)
    assert path == CHAT_TURN_ROUTE
    assert context == REF
    assert intent == recipe
    assert params == {}


def test_turn_target_round_trips_a_url4_with_quotes_and_special_characters() -> None:
    rng = random.Random(20261117)
    for _ in range(300):
        size = rng.randint(1, 400)
        _round_trip("".join(rng.choice(_ALPHABET) for _ in range(size)))
    _round_trip("".join(rng.choice(_ALPHABET) for _ in range(32_000)))


@pytest.mark.asyncio
async def test_install_chat_turn_is_idempotent() -> None:
    async with chat_world(Gateway({MODEL: "Paris"})) as node:
        install_chat_turn(node)
        install_chat_turn(node)

        assert CHAT_TURN_ROUTE in node.processor_routes()
        assert sum(1 for route in node.processor_routes() if route == CHAT_TURN_ROUTE) == 1
