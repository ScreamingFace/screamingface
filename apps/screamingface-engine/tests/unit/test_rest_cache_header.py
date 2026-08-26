"""`parse_cache_control` — the HTTP carrier for a run's cache intent (plan Batch 3, spec §5.1).

Every directive collapses to participate / opt-out **at this edge**; none is forwarded verbatim.
That is the point of the module and the reason these tests are correctness tests rather than
parser trivia: aigateway v2's cache-control grammar is CLOSED to one key, `use-cache`, and any
other key inside the `cache` object makes the whole request BYPASS silently (spec §1.0). A
`no-store` forwarded as itself would opt the caller out for the WRONG reason
(`unsupported_control` instead of `opted_out`); a forwarded `max-age` would lose caching
altogether with nothing raised anywhere.

`max-age` is the one directive that is **preserved rather than collapsed** (spec §3.5, plan §6):
url4 can neither ask the gateway for a freshness bound nor read an entry's age today, so the
directive degrades to an opt-out at read-back — but the VALUE survives this edge, so the day
either upstream blocker lifts the change is a branch, not a redesign.

TWO NEVERS this module owes its callers:

- **never 4xx.** A cache directive is an optimisation hint. Failing a whole ensemble run over a
  malformed one would trade a cheap missed hit for a dead run.
- **never invent intent.** Garbage and unknown directives return `None` — "not stated" — which
  converges to the D1 default, not to some parser-chosen policy.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.rest.cache_header import parse_cache_control
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol import CachePolicy

# --- the plan's Batch 3 table, row by row --------------------------------------------


def test_absent_header_states_nothing() -> None:
    """Plan Batch 3 test 3 — `None`, NOT a default-constructed policy.

    The distinction is load-bearing rather than stylistic: precedence between the HTTP and frame
    carriers can only prefer a stated policy over silence if silence has its own value, and a
    `CachePolicy()` here would read as "the header spoke" and shadow the frame's declaration.
    """
    assert parse_cache_control(None) is None


def test_a_present_but_empty_header_states_nothing() -> None:
    """An empty field-value carries no directive, so it declares nothing — the same as absent.
    Distinguishing them would give an empty header a meaning no caller intended by sending it.
    """
    assert parse_cache_control("") is None


def test_no_store_opts_out() -> None:
    """Spec §5.1. The caller means "do not use the cache"; url4 maps it to v2's ONLY opt-out."""
    assert parse_cache_control("no-store") == CachePolicy(participate=False)


def test_no_cache_opts_out_identically() -> None:
    """v2 has no read-only/write-only lane (spec §5.1), so "don't serve me a stored answer" can
    only be honoured by not participating at all. Mapping it to anything else would be a promise
    the upstream cannot keep.
    """
    assert parse_cache_control("no-cache") == CachePolicy(participate=False)


def test_max_age_participates_and_preserves_the_bound() -> None:
    """Plan Batch 3 table + §6 — the directive is **preserved, not collapsed**.

    r5 proposed collapsing `max-age` to an opt-out here. The owner locked the opposite (D11): the
    run participates and carries the bound, so read-back can honour it the moment the gateway
    reports an age. Collapsing at this edge would destroy the number before anything could use it.
    """
    assert parse_cache_control("max-age=60") == CachePolicy(participate=True, max_age=60)


def test_max_age_zero_is_a_bound_not_an_absence() -> None:
    """`0` is falsy and a truthiness test would silently drop it — turning "only a brand-new
    answer will do" into "said nothing", which resolves to the ON default and serves an
    arbitrarily old one. The strictest possible request would become the loosest outcome.
    """
    assert parse_cache_control("max-age=0") == CachePolicy(participate=True, max_age=0)


def test_url4_use_cache_participates_explicitly() -> None:
    """Spec §5.1 — the extension token. Rarely needed now that ON is the default, but it is how a
    caller states participation rather than merely failing to forbid it, which matters when the
    frame carrier declared an opt-out and the header must be able to override it.
    """
    assert parse_cache_control("url4-use-cache") == CachePolicy(participate=True)


# --- combining, and the safe side of a conflict --------------------------------------


def test_directives_that_agree_combine() -> None:
    """Plan Batch 3 test 2. Both say participate, and the bound survives alongside the token."""
    assert parse_cache_control("url4-use-cache, max-age=60") == CachePolicy(
        participate=True, max_age=60
    )


@pytest.mark.parametrize(
    "raw",
    [
        "max-age=60, no-store",
        "no-store, max-age=60",
        "url4-use-cache, no-cache",
        "no-cache, url4-use-cache",
        "no-store, url4-use-cache, max-age=5",
    ],
    ids=repr,
)
def test_conflicting_directives_resolve_to_opt_out(raw: str) -> None:
    """Plan Batch 3 test 2 — conflicts resolve to the SAFE side, regardless of order.

    Opting out is safe because its worst case is a missed cache hit; participating against a
    caller who asked not to is unsafe because its worst case is a stale or shared answer they
    explicitly refused. Order-independence is asserted deliberately: last-wins would make the
    outcome depend on how an intermediary happened to concatenate the field.
    """
    assert parse_cache_control(raw) == CachePolicy(participate=False)


def test_opting_out_drops_the_freshness_bound() -> None:
    """A bound on a run that does not participate is meaningless, and carrying it would invent a
    fourth state — "opted out, but only for 60s" — that nothing downstream can act on. Keeping
    `max_age` set only alongside `participate=True` is what makes the read-back branch total.
    """
    policy = parse_cache_control("no-store, max-age=60")

    assert policy is not None
    assert policy.max_age is None


def test_the_tighter_of_two_bounds_wins() -> None:
    """A repeated directive is a conflict like any other, so it resolves conservatively: the
    smaller bound is the one that admits fewer stale answers. First-wins or last-wins would let
    a duplicate appended by an intermediary LOOSEN what the caller asked for.
    """
    assert parse_cache_control("max-age=600, max-age=60") == CachePolicy(
        participate=True, max_age=60
    )
    assert parse_cache_control("max-age=60, max-age=600") == CachePolicy(
        participate=True, max_age=60
    )


# --- tolerance: garbage in, silence out ----------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "   ",
        ",,,",
        "=",
        "===",
        "no-store=",  # a valueless directive spelled with a stray `=`
        "\x00\x01",
        "max-age",  # no argument at all
        "max-age=",
        "max-age=abc",
        "max-age=6 0",
        "max-age=1e3",
        "max-age=-5",
        "max-age=1.5",
        "max-age=" + "9" * 400,  # absurd but numeric — must not be special-cased into a crash
        "totally unrelated text",
        "private, s-maxage=30, stale-while-revalidate=10",
    ],
    ids=repr,
)
def test_garbage_never_raises(raw: str) -> None:
    """Plan Batch 3 test 4, at the parser. This function is called on a header a caller — or any
    proxy between them — controls, so every input must produce a value rather than an exception.
    The route-level half of this guarantee is asserted further down.
    """
    parse_cache_control(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "   ",
        ",,,",
        "=",
        "max-age",
        "max-age=",
        "max-age=abc",
        "max-age=-5",
        "max-age=1.5",
        "totally unrelated text",
        "private, s-maxage=30",
    ],
    ids=repr,
)
def test_undecipherable_input_states_nothing_rather_than_guessing(raw: str) -> None:
    """Garbage must resolve to "not stated" — `None` — so the run falls through to the D1
    default. Any other choice invents an intent the caller never expressed: guessing opt-out
    would silently cost every hit for a typo, and guessing a default-constructed policy would
    let a malformed header shadow a perfectly good one on the frame carrier.
    """
    assert parse_cache_control(raw) is None


def test_a_malformed_max_age_drops_only_itself() -> None:
    """Plan Batch 3 test 5. One unusable directive must not take a valid neighbour down with it —
    the caller still said `url4-use-cache`, and honouring it costs nothing.
    """
    assert parse_cache_control("max-age=abc, url4-use-cache") == CachePolicy(participate=True)


def test_unknown_directives_are_dropped_without_disturbing_known_ones() -> None:
    """Plan Batch 3 test 5. `Cache-Control` is an open vocabulary that intermediaries add to
    (D6 accepts intermediary participation), so an unrecognised member is ordinary traffic, not
    an error.
    """
    assert parse_cache_control("private, immutable, max-age=60, no-transform") == CachePolicy(
        participate=True, max_age=60
    )


def test_only_if_cached_is_rejected_by_being_ignored() -> None:
    """Spec §8.3 — rejected, and "rejected" means IGNORED, never enforced and never fatal.

    RFC 9111 requires `504` when nothing is cached. A url4 run fans out to many gateway calls, so
    honouring it would let one uncached leaf kill an entire ensemble; there is no present use
    case worth that. It therefore lands as an unknown directive and states nothing on its own.
    """
    assert parse_cache_control("only-if-cached") is None
    assert parse_cache_control("only-if-cached, max-age=60") == CachePolicy(
        participate=True, max_age=60
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NO-STORE", CachePolicy(participate=False)),
        ("No-Cache", CachePolicy(participate=False)),
        ("MAX-AGE=60", CachePolicy(participate=True, max_age=60)),
        ("URL4-Use-Cache", CachePolicy(participate=True)),
    ],
    ids=repr,
)
def test_directive_names_are_case_insensitive(raw: str, expected: CachePolicy) -> None:
    """Field-value directive names are case-insensitive, and the codebase already normalises this
    way in `_parse_prefer`. A caller whose HTTP client upper-cases would otherwise have their
    opt-out silently dropped — the failure mode this whole design exists to prevent.
    """
    assert parse_cache_control(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["  no-store  ", "\tno-store", "no-store ,", ", no-store", "no-store,,"],
    ids=repr,
)
def test_surrounding_whitespace_and_empty_members_are_tolerated(raw: str) -> None:
    """Whitespace around list members and stray separators are how real clients and proxies
    serialise this field; none of it changes what was said.
    """
    assert parse_cache_control(raw) == CachePolicy(participate=False)


def test_a_quoted_argument_is_accepted() -> None:
    """The argument of a directive may be given as a quoted-string, so `max-age="60"` is the same
    request as `max-age=60`. Rejecting it would discard a well-formed bound.
    """
    assert parse_cache_control('max-age="60"') == CachePolicy(participate=True, max_age=60)


# --- the invariant the whole batch is here to keep -----------------------------------

_CORPUS = [
    None,
    "",
    "no-store",
    "no-cache",
    "max-age=0",
    "max-age=60",
    "url4-use-cache",
    "url4-use-cache, max-age=60",
    "no-store, max-age=60",
    "max-age=abc",
    "only-if-cached",
    "private, immutable",
    ",,,",
    "\x00",
]


@pytest.mark.parametrize("raw", _CORPUS, ids=repr)
def test_a_bound_is_only_ever_carried_by_a_participating_policy(raw: str | None) -> None:
    """The structural invariant every consumer of this parser may rely on: `max_age` is set only
    when `participate` is `True`. It keeps the read-back branch total — there is no "opted out
    with a bound" case to reason about — and it is asserted over a corpus rather than at the two
    happy paths, because the way it breaks is a new directive setting one field and not the other.
    """
    policy = parse_cache_control(raw)

    assert policy is None or policy.max_age is None or policy.participate is True


@pytest.mark.parametrize("raw", _CORPUS, ids=repr)
def test_the_parser_only_ever_yields_a_policy_or_silence(raw: str | None) -> None:
    """`CachePolicy` is `extra="forbid"`, so a parser that tried to smuggle a directive through as
    an extra field would raise here rather than reach the gateway. This asserts the return type is
    exactly that closed model — the type on which the "only `use-cache` ever ships" guarantee in
    `runner/cache.py` depends.
    """
    policy = parse_cache_control(raw)

    assert policy is None or isinstance(policy, CachePolicy)


# --- the route carrier ---------------------------------------------------------------

SECRET = "cache-header-unit-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 8, 5, 9, 0, 0, tzinfo=UTC)


def _app(runner: RecordingJobRunner) -> FastAPI:
    return create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, sync_max_wait_s=5.0),
        stream=InMemoryEventStream(),
        job_runner=runner,
        clock=lambda: T0,
        interest=FixedGate(True),
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _cap(topic: str) -> dict[str, str]:
    return {"URL4-Capability": JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(topic, T0)}


@pytest.mark.parametrize(
    "cache_control",
    ["no-store", "no-cache", "max-age=60", "url4-use-cache", "private, immutable"],
    ids=repr,
)
@pytest.mark.asyncio
async def test_a_cache_control_header_never_stops_the_run_from_starting(
    cache_control: str,
) -> None:
    """The header is declared on `start_run`, so FastAPI extracts it — and extracting it must
    change nothing about whether the run is scheduled. `no-cache` is the load-bearing case: a
    browser hard-refresh sends it unprompted, and D6 deliberately accepts the standard field, so
    ordinary traffic carries it whether or not the caller meant anything by it.
    """
    runner = RecordingJobRunner()
    async with _client(_app(runner)) as client:
        resp = await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={**_cap("topic-cc"), "Prefer": "respond-async", "Cache-Control": cache_control},
        )

    assert resp.status_code == 202
    assert [run[0] for run in runner.scheduled] == ["topic-cc"]


@pytest.mark.parametrize(
    "cache_control",
    ["max-age=abc", ",,,", "=", "totally unrelated text", "max-age=-5"],
    ids=repr,
)
@pytest.mark.asyncio
async def test_a_malformed_cache_control_header_is_never_4xx(cache_control: str) -> None:
    """Plan Batch 3 test 4, at the route — the half that the parser alone cannot prove.

    A cache directive is a hint about cost, not a term of the request. Rejecting a run because a
    proxy appended something unparseable would convert a free missed hit into a failed ensemble.
    """
    runner = RecordingJobRunner()
    async with _client(_app(runner)) as client:
        resp = await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                **_cap("topic-cc-bad"),
                "Prefer": "respond-async",
                "Cache-Control": cache_control,
            },
        )

    assert resp.status_code == 202
    assert runner.scheduled


def test_the_start_route_documents_the_cache_control_header() -> None:
    """The header is a public contract, so it belongs in the generated OpenAPI beside `X-Profile`
    and `Prefer` — a caller cannot opt a run out of a shared, permanent, global cache using a
    knob nothing tells them exists.
    """
    schema = _app(RecordingJobRunner()).openapi()

    params = schema["paths"]["/"]["get"]["parameters"]
    declared = {p["name"]: p for p in params if p["in"] == "header"}

    assert "Cache-Control" in declared
    assert declared["Cache-Control"]["required"] is False
    assert declared["Cache-Control"]["description"]
