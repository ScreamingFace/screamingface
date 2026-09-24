# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""The gateway-backed judge provider — an imported eval's judge is one of OUR calls.

Think of it as a switchboard plug: an imported scorer asks inspect for a model named
``screamingface/<gateway-model-id>`` and, instead of dialing OpenAI or Anthropic
directly, the call comes out of the engine's own wall socket — the node route the
aigateway connector serves. There it is routed, metered into the run's usage sink
(and so into ``cost_usd``), and identity-stamped like every other model call in the
run. FEATURE: model-graded imported benchmarks grade through our gateway (OME-1240).

Stages, in execution order (see :meth:`_GatewayJudgeModelAPI.generate`):

    Stage 1 — read the bound :class:`JudgeTransport` (a ContextVar the aggregate
              wiring binds around grading). Unbound → refuse loudly: a judge call
              may NEVER leave the engine except through the node's model route.
    Stage 2 — fold the judge's chat messages into the candidate input envelope
              (``screamingface.candidate-input.v1``), the exact shape the
              connector's ``_messages`` decoder reads. Tool messages refuse —
              judge prompts are plain chat (§7 scope).
    Stage 3 — encode the sub-request URL (``/<model>?[params&]q=(envelope)``,
              the wire codec's own encoder) and fetch it through the transport.
              The route is the model name's tail verbatim: ``screamingface/x/y``
              dials route ``/x/y`` — no second mapping to drift.
    Stage 4 — return the completion text as inspect's ``ModelOutput``. Errors
              propagate: the shim's Stage-3 catch turns them into the Case's
              named ``scorer_error``, never an aborted aggregate.

INVARIANT: this module never talks HTTP and holds no credentials — the transport's
fetch is the node's in-process dispatch, and everything past it (auth, retries,
metering, identity headers) is the connector's one implementation.
"""

from __future__ import annotations

import contextvars
import json
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from inspect_ai.model import ChatMessage, GenerateConfig, ModelAPI, ModelOutput, modelapi
from inspect_ai.tool import ToolChoice, ToolInfo

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from url4.wire.subrequest import encode_subrequest

#: One in-process node fetch: a relative sub-request URL in, the completion text out.
JudgeFetch = Callable[[str], Awaitable[str]]

#: inspect's provider-registry key: scorer model strings spell ``screamingface/<route>``.
PROVIDER_NAME = "screamingface"

#: Chat roles the candidate input envelope admits — the connector's own closed set
#: minus "developer", which inspect's message types never produce.
_ENVELOPE_ROLES = frozenset({"system", "user", "assistant"})


@dataclass(frozen=True, slots=True)
class JudgeTransport:
    """One run's judge wall socket: the node's fetch plus the judge's pinned params.

    Attributes:
        fetch: the node's in-process relative fetch (``Url4Node.fetch`` bound with
            ``relative=True``) — the ONLY exit a judge call has.
        params: protocol params pinned at import time (e.g. ``temperature``),
            emitted on the wire before ``q=``; part of the judge's exam identity.
    """

    fetch: JudgeFetch
    params: Sequence[tuple[str, str]] = ()


_transport: contextvars.ContextVar[JudgeTransport | None] = contextvars.ContextVar(
    "screamingface_judge_transport", default=None
)


@contextmanager
def bound_judge_transport(transport: JudgeTransport) -> Iterator[None]:
    """Bind the judge wall socket for the duration of one grading pass.

    INVARIANT: the binding never leaks past its context — the next board's grade
    starts unplugged, so a board that pins no judge cannot ride another's socket.
    """

    token: contextvars.Token[JudgeTransport | None] = _transport.set(transport)
    try:
        yield
    finally:
        _transport.reset(token)


@modelapi(name=PROVIDER_NAME)
def screamingface() -> type[ModelAPI]:
    """Register the provider under inspect's registry key (their factory idiom)."""

    return _GatewayJudgeModelAPI


class _GatewayJudgeModelAPI(ModelAPI):
    """inspect's ModelAPI face over the node's model route (see the module doc)."""

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # Stage 1 — the wall socket must be plugged in.
        transport: JudgeTransport | None = _transport.get()
        if transport is None:
            raise RuntimeError(
                "no judge transport is bound — a judge call may only leave the "
                "engine through the node's declared model route (OME-1240)"
            )
        _refuse_sampling_overrides(config)
        # Stage 2-3 — envelope the messages, dial the route.
        context: str = json.dumps(
            {
                "schema": CANDIDATE_INPUT_SCHEMA,
                "messages": [_message(message) for message in input],
            },
            separators=(",", ":"),
        )
        target: str = encode_subrequest(
            "/" + self.model_name, context, None, tuple(transport.params)
        )
        completion: str = await transport.fetch(target)
        if not completion.strip():
            # A blank completion can never be a grade — refuse loudly; a scorer
            # coercing silence into a score is a silently wrong exam.
            raise RuntimeError(f"the gateway judge at {self.model_name!r} returned an empty reply")
        # Stage 4 — their output form, the text verbatim.
        return ModelOutput.from_content(model=self.model_name, content=completion)


#: GenerateConfig sampling fields an eval might set — the judge's sampling identity
#: is the ROW's pinned params, so an eval-supplied value would be silently dropped.
_SAMPLING_FIELDS = (
    "temperature",
    "top_p",
    "top_k",
    "max_tokens",
    "seed",
    "stop_seqs",
    "frequency_penalty",
    "presence_penalty",
    "logit_bias",
    "num_choices",
)


def _refuse_sampling_overrides(config: GenerateConfig) -> None:
    """Refuse eval-supplied sampling settings by name — never drop them silently.

    WHY: the transport sends only the JudgeSpec's pinned params; accepting a config
    the wire never carries would grade with different sampling than the eval asked
    for, silently. None of the pinned evals sets one today.
    """

    overridden: list[str] = [
        name for name in _SAMPLING_FIELDS if getattr(config, name, None) is not None
    ]
    if overridden:
        raise RuntimeError(
            f"the eval supplies judge sampling settings {overridden} — the judge's "
            "sampling identity is the board row's pinned params (JudgeSpec.params); "
            "pin them there instead (OME-1240)"
        )


def _message(message: ChatMessage) -> dict[str, str]:
    """Project one inspect chat message into the envelope's ``{role, content}`` row."""

    role: str = message.role
    if role not in _ENVELOPE_ROLES:
        raise TypeError(
            f"judge prompts are plain chat — a {role!r} message (e.g. a tool result) "
            "cannot cross the candidate input envelope (§7 scope)"
        )
    return {"role": role, "content": message.text}


__all__ = ["PROVIDER_NAME", "JudgeFetch", "JudgeTransport", "bound_judge_transport"]
