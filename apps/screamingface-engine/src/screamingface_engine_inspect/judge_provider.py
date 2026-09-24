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

    Stage 1 — scope checks: the bound :class:`JudgeTransport` (a ContextVar the
              aggregate wiring binds around grading) must exist — unbound refuses
              loudly, a judge call may NEVER leave the engine except through the
              node's model route; a tool-bearing call refuses (plain chat only);
              and any config field outside the transport allowlist refuses by
              name — the wire carries only the row's pinned params.
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
    #: The board the judge grades for (OME-1240 observability): with it set, every
    #: judge call registers against its Case's evidence, so the run's payload-free
    #: grading join attributes the judge's tokens/cost/latency per Case.
    benchmark_id: str | None = None


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
        """Send one judge call through the node's model route.

        Args:
            input: the judge's chat messages (plain chat only — see Stage 2).
            tools: refused when non-empty — a judge that asked for tools would
                otherwise grade WITHOUT them, silently.
            tool_choice: ignored; meaningless once ``tools`` is refused.
            config: inspect's per-call settings; only transport-level fields are
                allowed (Stage 1) — grade-affecting ones belong in the row's
                pinned params.

        Returns:
            The completion text as inspect's ``ModelOutput``.
        """
        # Stage 1 — the wall socket must be plugged in, and the call must be
        # within scope: no tools, no grade-affecting config outside the pins.
        transport: JudgeTransport | None = _transport.get()
        if transport is None:
            raise RuntimeError(
                "no judge transport is bound — a judge call may only leave the "
                "engine through the node's declared model route (OME-1240)"
            )
        if tools:
            raise RuntimeError(
                "the judge asked for tools — judge prompts are plain chat (§7 "
                "scope); a call graded without its requested tools would be a "
                "silently different exam (OME-1240)"
            )
        _refuse_config_overrides(config)
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
        _register_against_the_case(transport, "/" + self.model_name, context)
        completion: str = await transport.fetch(target)
        if not completion.strip():
            # A blank completion can never be a grade — refuse loudly; a scorer
            # coercing silence into a score is a silently wrong exam.
            raise RuntimeError(f"the gateway judge at {self.model_name!r} returned an empty reply")
        # Stage 4 — their output form, the text verbatim.
        return ModelOutput.from_content(model=self.model_name, content=completion)


#: GenerateConfig fields that change DELIVERY, never the grade — the only ones an
#: eval may set. Everything else is ALLOWLIST-refused by name: the wire carries only
#: the JudgeSpec's pinned params, so any other field would be dropped silently and
#: the judge would grade a different exam (persistbench's reasoning_effort="high"
#: is the live example). A forbidden-list here would go stale on every inspect
#: field addition; the allowlist refuses new fields by default.
_TRANSPORT_CONFIG_FIELDS = frozenset(
    {
        "max_retries",
        "timeout",
        "attempt_timeout",
        "stream_idle_timeout",
        "max_connections",
        "adaptive_connections",
        "batch",
    }
)


def _refuse_config_overrides(config: GenerateConfig) -> None:
    """Refuse any eval-supplied setting outside the transport allowlist, by name.

    WHY allow-then-refuse (never a forbidden list): the transport sends only the
    JudgeSpec's pinned params, so an unlisted field is a field the judge silently
    ignores — and inspect adds fields over time. A plain ``model.generate(...)``
    delivers zero set fields (verified 2026-09-24), so defaults never trip this.
    """

    overridden: list[str] = sorted(
        name
        for name, value in config.model_dump().items()
        if value is not None and name not in _TRANSPORT_CONFIG_FIELDS
    )
    if overridden:
        raise RuntimeError(
            f"the eval supplies judge settings {overridden} the wire does not carry — "
            "grade-affecting settings belong in the board row's pinned params "
            "(JudgeSpec.params); pin them there instead (OME-1240)"
        )


def _register_against_the_case(transport: JudgeTransport, path: str, context: str) -> None:
    """Key this judge call to its Case's evidence for the run's accounting join.

    The identity must be byte-identical to what the connector records
    (``operation_call_identity`` on the decoded Request): the path, the decoded
    params, the envelope context, and the empty intent the wire carries when
    ``encode_subrequest`` is given none. The owner names the shim's fixed
    evidence shape (one check "1", sequence 1). A no-op outside a run's capture
    or when the transport carries no board — tests and the check surface stay
    join-free.
    """

    from screamingface_engine.grading_accounting import (
        GradingEvidenceOwner,
        register_grading_request,
    )
    from screamingface_engine.grading_call_scope import current_grading_case

    case_id: int | str | None = current_grading_case()
    if transport.benchmark_id is None or case_id is None:
        return
    register_grading_request(
        GradingEvidenceOwner(
            benchmark_id=transport.benchmark_id,
            case_id=case_id,
            check_id="1",
            sequence=1,
        ),
        path=path,
        params=dict(transport.params),
        context=context,
        intent="",
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
