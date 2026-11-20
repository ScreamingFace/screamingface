"""The chat turn route of POST /v1/chat/completions (chat-run PRD, contracts C6 and C7).

FEATURE: chat-run. The executor dispatches `/ensemble/chat/v1/turn` as ONE observed node, with
the blob ref of the CHAT_INPUT record as context and the Candidate URL4 as intent (erd §2.2). The
handler reads the record, binds its text view to `$input`, evaluates the recipe as the Candidate
route does, and answers with one CHAT_RESULT record (erd §2.4).
INVARIANT: the route works only inside a chat run, where the executor binds the chat-run marker.
Outside one it fails closed before any read or model call (CR-S18). A nested turn inside a chat
run (a recipe that names the turn route) also fails closed before any read or model call.
INVARIANT: no log carries the content of a message. A log names a code and a digest only.
INVARIANT: the route binds no retrieval policy (CR-S16): each model step keeps its own route.
FEATURE: tool-calls §3.2. With client tools, the handler re-points each final model step of the
run's copy of the recipe to the final-step route, binds the turn for that endpoint, and reads the
tool calls, the provider finish_reason and the usage of the final step from its collector.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable

from screamingface_engine.artifacts.blob_schema import blob_ref_digest
from screamingface_engine.artifacts.blobs import BlobError
from screamingface_engine.artifacts.s3 import S3StorageError
from screamingface_engine.artifacts.wiring import BlobStoreNotConfigured
from screamingface_engine.benchmarks.contract import (
    CandidateInvocation,
    OperationOutput,
    decode_candidate_invocation_record,
)
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.benchmarks.operation_outputs import (
    final_operation,
    final_operation_abstain_reason,
)
from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.chat.input import ChatInput, ChatInputError, decode_chat_input
from screamingface_engine.chat.recipe import (
    RecipeRefusal,
    RepointError,
    check_recipe,
    repoint_final_steps,
)
from screamingface_engine.chat.result import (
    ChatResult,
    FinalStep,
    encode_chat_result,
    finish_reason_of,
)
from screamingface_engine.chat.views import text_view
from screamingface_engine.operation_accounting import OperationAccounting
from screamingface_engine.world.attachment_parts import BlobReader
from screamingface_engine.world.chat_final import FinalCall, FinalTurn, final_turn_scope
from screamingface_engine.world.chat_marker import chat_run_reader, chat_run_scope
from url4.core.errors import ErrorCode, ResolutionError
from url4.observe import Observer
from url4.peer import dispatch_direct
from url4.peer.server import Request, Url4Node
from url4.wire.subrequest import encode_subrequest

__all__ = [
    "CHAT_INPUT_INVALID",
    "CHAT_INPUT_UNAVAILABLE",
    "CHAT_TURN_ROUTE",
    "ChatTurnRoute",
    "chat_result_from_invocation",
    "chat_run_scope",
    "chat_turn_target",
    "dispatch_chat_turn",
    "install_chat_turn",
    "read_chat_input",
    "tools_expression",
]

CHAT_TURN_ROUTE = "/ensemble/chat/v1/turn"
CHAT_INPUT_UNAVAILABLE = "chat_input_unavailable"
CHAT_INPUT_INVALID = "chat_input_invalid"

_logger = logging.getLogger(__name__)

# WHY a second marker: a chat run runs ONE turn. The reader marker stays bound for the whole
# evaluation, because the final-step endpoint needs it inside the same evaluation (contracts C7),
# so it cannot tell an outer turn from a nested one.
_turn_entered: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "screamingface_engine_chat_turn_entered", default=False
)


def chat_turn_target(input_ref: str, recipe: str) -> str:
    """The turn target: the blob ref as context and the Candidate URL4 as intent (erd §2.2)."""
    return encode_subrequest(CHAT_TURN_ROUTE, input_ref, recipe, quote=True)


def _unavailable(*, permanent: bool = True) -> ResolutionError:
    return ResolutionError(
        "the chat input is not available", code=CHAT_INPUT_UNAVAILABLE, permanent=permanent
    )


def _invalid() -> ResolutionError:
    return ResolutionError(
        "the chat input is not a valid chat-input record", code=CHAT_INPUT_INVALID, permanent=True
    )


async def _read_bytes(reader: Callable[[], BlobReader], digest: str) -> bytes | None:
    """The stored bytes of `digest`, or None when the record cannot be read for good.

    Raises:
        ResolutionError: `chat_input_unavailable`, NOT permanent, when the store fails at read
            time: `S3StorageError` (the S3 backend could not serve the GET) or `OSError` (the
            filesystem backend could not open or read the file).
    """
    try:
        return await reader().read(digest)
    except (BlobStoreNotConfigured, BlobError, ValueError):
        return None
    except (S3StorageError, OSError) as exc:
        # INVARIANT: the log names the exception class only; its text can hold a URL or a key.
        _logger.warning(
            "chat input unreadable code=%s digest=%s error=%s",
            CHAT_INPUT_UNAVAILABLE,
            digest,
            type(exc).__name__,
        )
        raise _unavailable(permanent=False) from None


async def read_chat_input(reader: Callable[[], BlobReader], input_ref: str) -> ChatInput:
    """The CHAT_INPUT record of `input_ref`, read through the run-scoped reader.

    Raises:
        ResolutionError: `chat_input_unavailable` when the record cannot be read (no store, an
            absent blob, store corruption); `chat_input_invalid` when its bytes are not a
            valid record. Both are permanent and carry a fixed message. A store failure at read
            time is `chat_input_unavailable` too, with the same message, but not permanent.
    """
    digest = blob_ref_digest(input_ref)
    if digest is None:
        _logger.warning("chat input refused code=%s: not a blob ref", CHAT_INPUT_UNAVAILABLE)
        raise _unavailable()
    data = await _read_bytes(reader, digest)
    if data is None:
        _logger.warning("chat input refused code=%s digest=%s", CHAT_INPUT_UNAVAILABLE, digest)
        raise _unavailable() from None
    try:
        return decode_chat_input(data)
    except ChatInputError:
        _logger.warning("chat input refused code=%s digest=%s", CHAT_INPUT_INVALID, digest)
        raise _invalid() from None


def tools_expression(recipe: str) -> str:
    """The run's copy of `recipe` with each final model step on the final-step route (§3.2).

    The `model` value of the client is not changed. A recipe with no final model step (each
    final position is an outcome) is returned as it is.

    Raises:
        ResolutionError: permanent; the code of the recipe check when it refuses the recipe, or
            `internal_error` when the re-point cannot prove its copy.
    """
    try:
        checked = check_recipe(recipe, with_tools=True)
        models = [position for position in checked.positions if position.kind == "model"]
        return repoint_final_steps(checked.root, models) if models else recipe
    except RecipeRefusal as exc:
        raise ResolutionError(exc.message, code=exc.code, permanent=True) from None
    except RepointError:
        raise ResolutionError(
            "the recipe could not be prepared for tools", code="internal_error", permanent=True
        ) from None


def _step(binding: str, accounting: OperationAccounting | None) -> FinalStep | None:
    """The facts of one final model step, or None when it has no accounting or request model."""
    if accounting is None or not accounting.request_model:
        return None
    usage = accounting.usage
    prompt, completion = usage.input_tokens, usage.output_tokens
    total = prompt + completion if prompt is not None and completion is not None else None
    return FinalStep(
        binding=binding,
        model=accounting.request_model,
        usage={"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total},
    )


def _final_step(final: OperationOutput | None) -> FinalStep | None:
    """The facts of the final model step, or None for a reducer or a step with no accounting."""
    if final is None or final.combine is not None:
        return None
    return _step(final.operation_id.removeprefix("op_"), final.accounting)


def _answered(
    invocation: CandidateInvocation,
    final: OperationOutput | None,
    final_call: FinalCall | None,
    step: FinalStep | None,
) -> ChatResult:
    """The answered result: with tools, the tool calls and finish_reason of the final call."""
    if final_call is not None:
        tool_calls = list(final_call.tool_calls)
        provider = final_call.finish_reason
    else:
        tool_calls = []
        # WHY: a reducer, or no single attributed final operation (final is None), has no
        # provider value and no tool call, so the value is "stop" and final_step is null (§2.4).
        provider = None if final is None or final.combine is not None else final.finish_reason
    return ChatResult(
        status="answered",
        content=invocation.output,
        tool_calls=tool_calls,
        finish_reason=finish_reason_of(provider, tool_calls),
        final_step=step,
    )


def chat_result_from_invocation(
    invocation: CandidateInvocation,
    final: OperationOutput | None,
    *,
    abstain_reason: str | None,
    final_call: FinalCall | None = None,
) -> ChatResult:
    """The CHAT_RESULT of one Candidate Invocation and its final operation (erd §2.4).

    With tools, `final_call` is the one call of the final-step endpoint: it gives the tool calls,
    the provider finish_reason and the final step.
    """
    step = (
        _final_step(final)
        if final_call is None
        else _step(final_call.binding, final_call.accounting)
    )
    if invocation.status == "refused":
        return ChatResult(
            status="refused",
            finish_reason="content_filter",
            refusal=invocation.refusal,
            final_step=step,
        )
    if invocation.abstained:
        return ChatResult(
            status="abstained", finish_reason="stop", abstain_reason=abstain_reason, final_step=step
        )
    return _answered(invocation, final, final_call, step)


class ChatTurnRoute:
    """The handler of the turn route: one CHAT_INPUT record in, one CHAT_RESULT out."""

    __slots__ = ("_node",)

    def __init__(self, node: Url4Node) -> None:
        self._node = node

    async def __call__(self, request: Request) -> str:
        reader = chat_run_reader()
        if reader is None:
            raise ResolutionError(
                "the chat turn route runs only in a chat run",
                code=ErrorCode.ENDPOINT_NOT_FOUND,
                permanent=True,
            )
        if _turn_entered.get():
            raise ResolutionError(
                "the chat turn route runs once per chat run",
                code=ErrorCode.ENDPOINT_NOT_FOUND,
                permanent=True,
            )
        token = _turn_entered.set(True)
        try:
            return await self._run_turn(reader, request)
        finally:
            _turn_entered.reset(token)

    async def _run_turn(self, reader: Callable[[], BlobReader], request: Request) -> str:
        record = await read_chat_input(reader, request.context)
        view = text_view(record.messages, record.tools)
        turn = (
            FinalTurn(tuple(record.messages), tuple(record.tools), view) if record.tools else None
        )
        # INVARIANT: with no tools the run evaluates the recipe as built (CR-7 parity).
        expression = request.intent if turn is None else tools_expression(request.intent)
        # INVARIANT: an error of the evaluation propagates unchanged, so the terminal frame
        # carries its Engine code (CR-S5).
        with candidate_invocation_scope(), final_turn_scope(turn):
            envelope = await evaluate_candidate_recipe(
                self._node, expression, view, isolate_operation_calls=True
            )
        invocation = decode_candidate_invocation_record(envelope)
        final = final_operation(expression, invocation.operations)
        reason = (
            final_operation_abstain_reason(expression, invocation.operations)
            if invocation.abstained
            else None
        )
        call = turn.calls.result() if turn is not None else None
        result = chat_result_from_invocation(
            invocation, final, abstain_reason=reason, final_call=call
        )
        return encode_chat_result(result).decode("utf-8")


def install_chat_turn(node: Url4Node) -> None:
    """Register the turn route once per URL4 world (mirrors install_combine_runtime)."""
    if CHAT_TURN_ROUTE not in node.processor_routes():
        node.endpoint(CHAT_TURN_ROUTE)(ChatTurnRoute(node))


async def dispatch_chat_turn(
    node: object,
    recipe: str,
    *,
    chat_input: str | None,
    reader: Callable[[], BlobReader] | None,
    observer: Observer,
    trace_id: str | None,
    root_span_id: str | None,
) -> str:
    """Run the turn route of a chat run as ONE observed node, with `observer` (contracts C7)."""
    if not isinstance(node, Url4Node):
        raise ResolutionError(
            "a chat run needs a url4 node world", code="internal_error", permanent=True
        )
    if chat_input is None or reader is None:
        raise _unavailable()
    with chat_run_scope(reader):
        result = await dispatch_direct(
            node,
            chat_turn_target(chat_input, recipe),
            observer=observer,
            trace_id=trace_id,
            root_span_id=root_span_id,
        )
    return result.body
