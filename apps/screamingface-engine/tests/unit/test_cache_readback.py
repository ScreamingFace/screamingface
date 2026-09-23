"""Batch 7 — reading the gateway's cache answer back onto the run's spans.

FEATURE: url4 per-run cache policy (spec §7, D7 — mandatory observability).
STORY: as an operator who turned caching on, every span tells me whether that call hit, missed
or bypassed the cache and — when it did not hit — the gateway's own word for why, so "I asked
for no caching and something still cached" is an answerable question.

**Why it is mandatory rather than nice-to-have.** A hit costs nothing upstream, but
`_report_usage` bills it exactly like a fresh call. Without the outcome beside it, enabling the
cache makes the cost taxonomy wrong in the direction that HIDES savings — so nobody reports it.

Three layers, because the signal crosses three seams — the same shape
`test_finish_reason_capture.py` uses, and for the same reason:

  0. `runner/cache_readback.py` parses the response headers into a `CacheOutcome`;
  1. the connector reports it beside `_report_usage` (`ModelResponse`);
  2. `_RunState` folds it onto the owning span, which carries it on the wire as
     `SpanData.cache_status` / `cache_reason` (the wire shape itself is pinned by
     `test_protocol_cache.py`).

**Two sources, in preference order (spec §2.2, §7).** `Cache-Status` (RFC 9211) is the Standards
Track field for exactly this fact and is read FIRST; the ad hoc `X-AIGW-Cache*` triple aigateway
emits today is the fallback. Preferring the standard costs nothing now and means url4 needs no
change the day the gateway adopts it. The list may carry one member per cache that touched the
response — aigateway, an Envoy sidecar, a CDN — so selecting the AIGATEWAY member rather than
blindly the first is a correctness test, not a style one: reading a CDN's `hit` as aigateway's
answer would report a cache saving that never happened.

**The D11 branches (spec §3.5).** `max-age` is honoured, but the two upstream halves that would
make it work are missing: the gateway accepts no freshness bound and reports no age. So a hit
whose age cannot be established is re-issued with an explicit opt-out — never served stale — and
the honoured path is written here, dormant, against a gateway that reports `Age`.

A separate module rather than an append to `test_aigateway_connector.py`: the repo's append-only
gate compares file status, so growing an existing test file reads as "a prior test was modified"
even when the diff is purely additive.
"""

from __future__ import annotations

import json

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.runner.executor import _RunState
from screamingface_engine.world.cache_readback import (
    CacheOutcome,
    CacheStatus,
    read_cache_outcome,
    requires_revalidation,
)
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.dag import run as url4_run
from url4.observe import ModelResponse, NodeFinished, NodeStarted, ObservationEvent
from url4.streaming.interfaces import Traced
from url4.streaming.protocol import CachePolicy, SpanData

_MODEL = "anthropic/claude-haiku-4-5"

# The four reasons aigateway v2 can give for not using the cache. They are ITS vocabulary and the
# whole point of carrying the field verbatim: `opted_out` means url4 asked for no cache and got
# none, while `unsupported_control` means url4 sent a key v2 does not know and silently lost every
# hit. Collapsing them would hide the second behind the first.
_V2_REASONS = ["opted_out", "malformed_controls", "unsupported_control", "disabled"]


# ── layer 0: the header parse ─────────────────────────────────────────────────────────────


def test_cache_status_reports_a_hit() -> None:
    outcome = read_cache_outcome({"Cache-Status": "aigateway; hit"})

    assert outcome.status == "hit"


@pytest.mark.parametrize(
    ("fwd", "status"),
    [
        # RFC 9211 §2.2's defined tokens. `bypass` is the only one that means "the cache was not
        # consulted at all"; every other forward reason means it was consulted and had nothing.
        ("bypass", "bypass"),
        ("miss", "miss"),
        ("uri-miss", "miss"),
        ("vary-miss", "miss"),
        ("stale", "miss"),
        ("request", "miss"),
        ("method", "miss"),
        ("partial", "miss"),
    ],
)
def test_a_forwarded_request_maps_its_token_to_a_status_and_keeps_it_as_the_reason(
    fwd: str, status: str
) -> None:
    outcome = read_cache_outcome({"Cache-Status": f"aigateway; fwd={fwd}"})

    assert (outcome.status, outcome.reason) == (status, fwd)


@pytest.mark.parametrize("reason", _V2_REASONS)
def test_detail_supplies_the_reason_verbatim_when_present(reason: str) -> None:
    # INVARIANT: `detail` is where a cache puts its OWN word for the outcome, so it outranks the
    # generic `fwd` token — which says only that the request was forwarded, never why.
    outcome = read_cache_outcome({"Cache-Status": f'aigateway; fwd=bypass; detail="{reason}"'})

    assert (outcome.status, outcome.reason) == ("bypass", reason)


def test_the_aigateway_member_is_selected_not_the_first_one() -> None:
    # INVARIANT: the field is a LIST — one member per cache that handled the response. Taking the
    # first would read a CDN's hit as aigateway's answer and report a saving that never happened.
    outcome = read_cache_outcome(
        {"Cache-Status": 'ExampleCDN; hit; ttl=376, aigateway; fwd=bypass; detail="opted_out"'}
    )

    assert (outcome.status, outcome.reason) == ("bypass", "opted_out")


def test_the_aigateway_member_is_found_wherever_it_sits_in_the_list() -> None:
    # RFC 9211 orders the list origin-closest first, so aigateway normally leads — but the rule is
    # a SHOULD, and an intermediary that prepends must not change what url4 reads.
    outcome = read_cache_outcome({"Cache-Status": "aigateway; hit, ExampleCDN; fwd=miss"})

    assert outcome.status == "hit"


def test_a_quoted_member_name_containing_a_comma_does_not_split_the_list() -> None:
    # Boundary: RFC 8941 String members may contain the list separator. A naive `split(",")` reads
    # `"CDN, Inc."` as two members and then finds no aigateway member at all.
    outcome = read_cache_outcome({"Cache-Status": '"CDN, Inc."; fwd=miss, "aigateway"; hit'})

    assert outcome.status == "hit"


def test_an_escaped_quote_inside_a_string_does_not_end_it() -> None:
    # Boundary: RFC 8941 §3.3.3 allows `\"` and `\\` inside a String. A parser that ends the
    # string at the escaped quote leaves the rest of the field looking unquoted — and then the
    # comma inside it splits the list, and the aigateway member is never found.
    outcome = read_cache_outcome({"Cache-Status": '"CDN \\", Inc."; hit, aigateway; fwd=miss'})

    assert (outcome.status, outcome.reason) == ("miss", "miss")


def test_escapes_inside_a_reason_are_resolved_not_carried() -> None:
    # The reason is published verbatim onto a span, so it must be the string the cache MEANT —
    # transport escaping is the wire's business, not the reader's.
    outcome = read_cache_outcome(
        {"Cache-Status": '"aigateway"; fwd=bypass; detail="say \\"no\\" \\\\ twice"'}
    )

    assert outcome.reason == 'say "no" \\ twice'


def test_a_list_naming_only_other_caches_reports_nothing_for_aigateway() -> None:
    # Boundary: an Envoy hit is not a gateway hit. Reporting it as one would attribute a saving to
    # the wrong cache and, worse, mark a real provider dispatch as free.
    outcome = read_cache_outcome({"Cache-Status": "ExampleCDN; hit, Envoy; fwd=miss"})

    assert outcome.status is None


def test_cache_status_wins_over_the_legacy_triple_when_both_are_present() -> None:
    # The forward-compatibility guarantee: on the day aigateway emits both, the standard field is
    # what url4 believes, so adopting it upstream needs no change here.
    outcome = read_cache_outcome(
        {
            "Cache-Status": "aigateway; hit",
            "X-AIGW-Cache": "bypass",
            "X-AIGW-Cache-Reason": "disabled",
        }
    )

    assert (outcome.status, outcome.reason) == ("hit", None)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        ",,,",
        ";;;",
        "aigateway",  # a member that states neither hit nor fwd says nothing at all
        '"unterminated; hit',
        "aigateway; hit=?0",  # an explicit NOT-a-hit, with no forward reason to fall back on
        "=;=,=",
    ],
)
def test_an_unusable_cache_status_falls_back_to_the_legacy_triple(raw: str) -> None:
    # INVARIANT: falling back rather than failing. The signal exists in the other field; dropping
    # it because the preferred one was garbage would lose the outcome for no reason.
    outcome = read_cache_outcome(
        {"Cache-Status": raw, "X-AIGW-Cache": "miss", "X-AIGW-Cache-Reason": "not_requested"}
    )

    assert (outcome.status, outcome.reason) == ("miss", "not_requested")


@pytest.mark.parametrize("status", ["hit", "miss", "bypass"])
def test_the_legacy_triple_reports_every_status(status: str) -> None:
    outcome = read_cache_outcome({"X-AIGW-Cache": status})

    assert outcome.status == status


@pytest.mark.parametrize("reason", _V2_REASONS)
def test_the_legacy_triples_reason_is_carried_verbatim(reason: str) -> None:
    outcome = read_cache_outcome({"X-AIGW-Cache": "bypass", "X-AIGW-Cache-Reason": reason})

    assert outcome.reason == reason


def test_an_unrecognised_legacy_status_is_dropped_rather_than_invented() -> None:
    # Boundary: the wire field is a free string. A value outside the protocol's closed vocabulary
    # cannot be put on a span, and guessing which of the three it meant would be a fabrication.
    outcome = read_cache_outcome({"X-AIGW-Cache": "warmed"})

    assert outcome.status is None


@pytest.mark.parametrize("status", ["hit", "miss"])
def test_the_cache_key_is_recorded_for_a_hit_or_a_miss(status: str) -> None:
    # The key is a hash PREFIX by construction (aigateway truncates to 12 chars) — never prompt or
    # response content, which is what makes it safe to carry at all (spec §8.4).
    outcome = read_cache_outcome({"X-AIGW-Cache": status, "X-AIGW-Cache-Key": "a1b2c3d4e5f6"})

    assert outcome.key == "a1b2c3d4e5f6"


def test_a_key_arriving_with_a_bypass_is_dropped() -> None:
    # INVARIANT: a bypassed request has no entry, so a key on it identifies nothing. aigateway sets
    # the header only for hit/miss; url4 re-states the rule rather than trusting the sender.
    outcome = read_cache_outcome({"X-AIGW-Cache": "bypass", "X-AIGW-Cache-Key": "a1b2c3d4e5f6"})

    assert outcome.key is None


def test_the_key_is_read_from_cache_status_too() -> None:
    outcome = read_cache_outcome({"Cache-Status": 'aigateway; hit; key="a1b2c3d4e5f6"'})

    assert outcome.key == "a1b2c3d4e5f6"


def test_no_cache_headers_at_all_degrade_to_nothing_reported() -> None:
    # The ordinary case for an older gateway, and for every non-cache error path. It must produce
    # an absence, not a crash and not a fabricated status.
    assert read_cache_outcome({}) == CacheOutcome(status=None, reason=None, key=None, age_s=None)


def test_header_names_are_matched_case_insensitively() -> None:
    # RFC 9110 §5.1: field names are case-insensitive. `httpx.Headers` already honours that; a
    # plain mapping handed in by a caller does not, and the parse must not depend on which it got.
    outcome = read_cache_outcome({"cache-status": "aigateway; hit"})

    assert outcome.status == "hit"


@pytest.mark.parametrize(
    "headers",
    [
        {"Cache-Status": "aigateway; hit; key="},
        {"Cache-Status": "aigateway; ttl=; fwd="},
        {"Cache-Status": "aigateway;;; hit"},
        {"Cache-Status": "aigateway; hit; detail=\\"},
        {"Cache-Status": "аigateway; hit"},  # Cyrillic а — a lookalike, not our member
        {"Cache-Status": "aigateway; hit" * 500},
        {"X-AIGW-Cache": ""},
        {"X-AIGW-Cache": "hit", "X-AIGW-Cache-Reason": ""},
        {"Age": "not-a-number"},
    ],
)
def test_hostile_or_malformed_headers_never_raise(headers: dict[str, str]) -> None:
    # INVARIANT: this parse runs on the response path of every gateway call. A cache outcome is an
    # observation about a call, never a term of it — failing a run over one would trade a missing
    # telemetry field for a dead ensemble.
    read_cache_outcome(headers)


def test_the_age_header_is_read_as_whole_seconds() -> None:
    outcome = read_cache_outcome({"X-AIGW-Cache": "hit", "Age": "42"})

    assert outcome.age_s == 42


@pytest.mark.parametrize("raw", ["", "-1", "1.5", "abc", "9 9"])
def test_an_unusable_age_is_no_age_at_all(raw: str) -> None:
    # Boundary: RFC 9111 §5.1 defines `Age` as a non-negative integer. Anything else is unusable,
    # and an unusable age must read as "unknown" — which is the conservative direction, since an
    # unknown age is exactly what makes a freshness bound unenforceable.
    outcome = read_cache_outcome({"X-AIGW-Cache": "hit", "Age": raw})

    assert outcome.age_s is None


# ── layer 0b: the D11 freshness decision ──────────────────────────────────────────────────


def _outcome(status: CacheStatus | None, *, age_s: int | None = None) -> CacheOutcome:
    return CacheOutcome(status=status, reason=None, key=None, age_s=age_s)


@pytest.mark.parametrize("status", ["hit", "miss", "bypass", None])
def test_a_run_that_stated_no_bound_never_revalidates(status: CacheStatus | None) -> None:
    # INVARIANT: the D1 default participates and asks for nothing, so the overwhelming majority of
    # runs must pay nothing for D11 existing.
    assert requires_revalidation(CachePolicy(participate=True), _outcome(status)) is False


def test_a_hit_of_unknown_age_is_refused_because_the_bound_cannot_be_honoured() -> None:
    # THE PATH THAT ACTUALLY SHIPS (plan §6). aigateway reports no age, so a stored answer cannot
    # be proven within the caller's bound — and serving it anyway would be a silent stale serve of
    # a corpus that never expires.
    assert requires_revalidation(CachePolicy(max_age=60), _outcome("hit")) is True


@pytest.mark.parametrize("status", ["miss", "bypass"])
def test_a_freshly_generated_answer_is_never_revalidated(status: CacheStatus) -> None:
    # INVARIANT: a miss or a bypass IS the fresh answer — age zero, within every bound. Re-issuing
    # there would double the cost of a bound that was already honoured, on every call of the run.
    assert requires_revalidation(CachePolicy(max_age=60), _outcome(status)) is False


def test_a_hit_within_the_bound_is_a_legitimate_hit() -> None:
    # DORMANT until aigateway reports `Age` — written now so the day it does, D11 is a branch that
    # already works rather than a redesign.
    assert requires_revalidation(CachePolicy(max_age=60), _outcome("hit", age_s=10)) is False


def test_a_hit_exactly_at_the_bound_is_still_within_it() -> None:
    # RFC 9111 §5.2.1.1: max-age asks for an age "less than or equal to" N.
    assert requires_revalidation(CachePolicy(max_age=60), _outcome("hit", age_s=60)) is False


def test_a_hit_beyond_the_bound_is_refused() -> None:
    assert requires_revalidation(CachePolicy(max_age=60), _outcome("hit", age_s=61)) is True


def test_a_zero_bound_refuses_every_stored_answer() -> None:
    # Boundary: `max-age=0` is the strictest bound a caller can state, and it must not be confused
    # with having stated nothing — the parse edge preserves it for exactly this reason.
    assert requires_revalidation(CachePolicy(max_age=0), _outcome("hit", age_s=1)) is True


# ── layer 1: the connector reports what it read ───────────────────────────────────────────


class _Gateway:
    """A chat-completions endpoint serving `(json, headers)` pairs in order, recording every
    request body so a re-issue is provable rather than inferred."""

    def __init__(self, turns: list[tuple[dict, dict[str, str]]]) -> None:
        self._turns = turns
        self._index = 0
        self.bodies: list[dict] = []

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        self.bodies.append(json.loads(request.content))
        body, headers = self._turns[min(self._index, len(self._turns) - 1)]
        self._index += 1
        return httpx.Response(200, json=body, headers=headers)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    @property
    def responses(self) -> list[ModelResponse]:
        return [e for e in self.events if isinstance(e, ModelResponse)]


def _completion(content: str = "an answer", **extra: object) -> dict:
    message: dict = {"role": "assistant", "content": content, **extra}
    return {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


async def _run_against(
    gateway: _Gateway, *, cache: CachePolicy | None = None
) -> tuple[str, _Recorder]:
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL),), default_model=_MODEL)
    rec = _Recorder()
    async with gateway.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        # F2: the cache policy travels in the request scope, not on the world.
        with request_scope(
            RequestScope(origin="run", cache=cache if cache is not None else CachePolicy())
        ):
            result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec)
    return result, rec


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["hit", "miss", "bypass"])
async def test_the_connector_reports_the_legacy_triples_status(status: str) -> None:
    gateway = _Gateway([(_completion(), {"X-AIGW-Cache": status, "X-AIGW-Cache-Reason": "r"})])

    _, rec = await _run_against(gateway)

    assert [(r.cache_status, r.cache_reason) for r in rec.responses] == [(status, "r")]


@pytest.mark.asyncio
async def test_the_connector_prefers_cache_status_over_the_triple() -> None:
    gateway = _Gateway(
        [(_completion(), {"Cache-Status": "aigateway; hit", "X-AIGW-Cache": "miss"})]
    )

    _, rec = await _run_against(gateway)

    assert rec.responses[0].cache_status == "hit"


@pytest.mark.asyncio
async def test_a_gateway_that_reports_no_cache_headers_still_completes_the_run() -> None:
    # INVARIANT: degrade to None, never crash — an older gateway, or any path that answered
    # without reaching the cache at all.
    gateway = _Gateway([(_completion(), {})])

    result, rec = await _run_against(gateway)

    assert result == "an answer"
    assert (rec.responses[0].cache_status, rec.responses[0].cache_reason) == (None, None)


@pytest.mark.asyncio
async def test_a_hit_of_unknown_age_under_a_bound_is_re_issued_as_an_opt_out() -> None:
    # THE D11-INERT PATH, end to end (plan test 2c). The caller asked for a freshness bound; the
    # gateway can neither accept one nor report an age, so the stored answer is refused and the
    # call is re-issued with an explicit opt-out. The run's outcome is the SECOND answer.
    gateway = _Gateway(
        [
            (_completion("stale answer"), {"X-AIGW-Cache": "hit"}),
            (
                _completion("fresh answer"),
                {"X-AIGW-Cache": "bypass", "X-AIGW-Cache-Reason": "opted_out"},
            ),
        ]
    )

    result, rec = await _run_against(gateway, cache=CachePolicy(max_age=60))

    assert result == "fresh answer"
    assert len(gateway.bodies) == 2
    # INVARIANT (spec §1.0): the re-issue is still bound by the closed grammar — `use-cache` and
    # nothing else, or the request would bypass for the wrong reason.
    assert gateway.bodies[0].get("cache") is None
    assert gateway.bodies[1]["cache"] == {"use-cache": False}
    assert [(r.cache_status, r.cache_reason) for r in rec.responses] == [("bypass", "opted_out")]


@pytest.mark.asyncio
async def test_the_discarded_answer_is_never_billed() -> None:
    # INVARIANT: the refused response is read for its headers and thrown away. Reporting its usage
    # too would bill one turn twice — the precise error class this whole batch exists to prevent.
    gateway = _Gateway(
        [
            (_completion("stale answer"), {"X-AIGW-Cache": "hit"}),
            (_completion("fresh answer"), {"X-AIGW-Cache": "bypass"}),
        ]
    )

    _, rec = await _run_against(gateway, cache=CachePolicy(max_age=60))

    assert len(rec.responses) == 1


@pytest.mark.asyncio
async def test_a_hit_within_the_bound_is_served_without_a_second_call() -> None:
    # DORMANT until aigateway reports `Age` (plan test 2d) — the honoured half of D11.
    gateway = _Gateway([(_completion(), {"X-AIGW-Cache": "hit", "Age": "10"})])

    _, rec = await _run_against(gateway, cache=CachePolicy(max_age=60))

    assert len(gateway.bodies) == 1
    assert rec.responses[0].cache_status == "hit"


@pytest.mark.asyncio
async def test_a_hit_beyond_the_bound_is_re_issued() -> None:
    gateway = _Gateway(
        [
            (_completion("month-old answer"), {"X-AIGW-Cache": "hit", "Age": "600"}),
            (_completion("fresh answer"), {"X-AIGW-Cache": "bypass"}),
        ]
    )

    result, _ = await _run_against(gateway, cache=CachePolicy(max_age=60))

    assert result == "fresh answer"


@pytest.mark.asyncio
async def test_a_miss_under_a_bound_costs_no_second_call() -> None:
    # INVARIANT: a miss IS the fresh answer. Re-issuing it would double the cost of every call a
    # bounded run makes, for an answer that already satisfied the bound.
    gateway = _Gateway([(_completion(), {"X-AIGW-Cache": "miss"})])

    _, _ = await _run_against(gateway, cache=CachePolicy(max_age=60))

    assert len(gateway.bodies) == 1


@pytest.mark.asyncio
async def test_a_run_without_a_bound_never_makes_a_second_call_on_a_hit() -> None:
    # Regression guard for the default path: D11 must be invisible to the run that states nothing.
    gateway = _Gateway([(_completion(), {"X-AIGW-Cache": "hit"})])

    _, rec = await _run_against(gateway)

    assert len(gateway.bodies) == 1
    assert rec.responses[0].cache_status == "hit"


@pytest.mark.asyncio
async def test_every_round_trip_of_a_tool_turn_reports_its_own_outcome() -> None:
    # One turn is several independently-keyed gateway calls; a continuation that missed after a
    # first call that hit is two facts, and collapsing them would misreport the turn's cost.
    tool_call = {"id": "c1", "type": "function", "function": {"name": "nope", "arguments": "{}"}}
    gateway = _Gateway(
        [
            (
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [tool_call],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
                {"X-AIGW-Cache": "hit"},
            ),
            (_completion("final answer"), {"X-AIGW-Cache": "miss"}),
        ]
    )
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL),), default_model=_MODEL)
    rec = _Recorder()
    async with gateway.client() as client, httpx.AsyncClient() as tavily:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key="tvly-test", tavily_client=tavily
        )
        result = await url4_run(f"/{_MODEL}(ctx)!go", io=world.node, observer=rec)

    assert result == "final answer"
    assert [r.cache_status for r in rec.responses] == ["hit", "miss"]


# ── layer 2: the span carries it ──────────────────────────────────────────────────────────


def _span_frames(state: _RunState, events: list[ObservationEvent]) -> list[SpanData]:
    frames: list[SpanData] = []
    for event in events:
        for frame in state.map(event):
            payload = frame.payload if isinstance(frame, Traced) else frame
            if isinstance(payload, SpanData):
                frames.append(payload)
    return frames


@pytest.mark.parametrize("status", ["hit", "miss", "bypass"])
def test_the_outcome_reaches_the_span_frame(status: CacheStatus) -> None:
    spans = _span_frames(
        _RunState(),
        [
            NodeStarted("span1", None, "Node", "detail"),
            ModelResponse("span1", "stop", None, status, "opted_out"),
            NodeFinished("span1", "ok", 1),
        ],
    )

    assert (spans[0].cache_status, spans[0].cache_reason) == (status, "opted_out")


def test_a_span_that_called_no_model_reports_no_cache_outcome() -> None:
    # Boundary: most nodes never call a gateway, so the attribute must be ABSENT rather than a
    # fabricated "bypass" — which would read as "the cache refused this", a claim nobody made.
    spans = _span_frames(
        _RunState(),
        [NodeStarted("span1", None, "Node", "detail"), NodeFinished("span1", "ok", 1)],
    )

    assert (spans[0].cache_status, spans[0].cache_reason) == (None, None)


def test_the_last_round_trips_outcome_is_the_spans_outcome() -> None:
    # The span carries ONE status while a turn may be several calls, so a rule is unavoidable.
    # Last-wins, matching `refusal` on this same fold: the final round trip is the one that
    # produced the answer the span returns.
    spans = _span_frames(
        _RunState(),
        [
            NodeStarted("span1", None, "Node", "detail"),
            ModelResponse("span1", "tool_calls", None, "hit", None),
            ModelResponse("span1", "stop", None, "miss", "not_requested"),
            NodeFinished("span1", "ok", 1),
        ],
    )

    assert (spans[0].cache_status, spans[0].cache_reason) == ("miss", "not_requested")


def test_a_round_trip_reporting_no_outcome_does_not_erase_an_earlier_one() -> None:
    # Boundary: "nothing reported" is not "no cache involved". A second call whose headers were
    # missing must leave the first call's answer standing rather than blanking it.
    spans = _span_frames(
        _RunState(),
        [
            NodeStarted("span1", None, "Node", "detail"),
            ModelResponse("span1", "tool_calls", None, "hit", None),
            ModelResponse("span1", "stop", None, None, None),
            NodeFinished("span1", "ok", 1),
        ],
    )

    assert spans[0].cache_status == "hit"


def test_an_outcome_for_an_unknown_span_is_dropped_not_fabricated() -> None:
    # Mirrors `_fold_usage`'s guard: an event for a span this run never opened must not invent one.
    assert _RunState().map(ModelResponse("ghost", "stop", None, "hit", None)) == []


# ── the retry flag: carried, never inferred ───────────────────────────────────────────────


def test_an_outcome_defaults_to_not_retried() -> None:
    """Every existing construction site omits the flag, so the default must be the safe one."""
    assert CacheOutcome(status="hit", reason=None, key=None, age_s=None).retried is False


def test_read_cache_outcome_passes_the_retried_flag_through() -> None:
    # `read_cache_outcome` never derives this fact from the headers — only `_post_completion`
    # knows a retry happened, and the flag is a plain passthrough onto the parsed outcome.
    outcome = read_cache_outcome({"X-AIGW-Cache": "hit"}, retried=True)

    assert outcome.retried is True
