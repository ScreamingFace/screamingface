"""B4 hardening of the request scope (04-review-fixes FX-60, FX-64, FX-65, FX-66).

# WHY this file exists. `test_request_scope.py` pins the scope's contract (T1-T6). These tests
# close the gaps the unit 1 review found in it: the scope must own the values it holds (FX-65),
# every producer must say which surface it is (FX-66), the trace has ONE carrier (FX-64), and no
# scope value may survive a call on any long-lived object (FX-60).
"""

from __future__ import annotations

import dataclasses
import json
import sys
import types
from collections.abc import Iterable, Mapping
from typing import Any, cast

import pytest
from test_aigateway_connector import _MockAigateway

from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world.connector import (
    AigatewayConfig,
    _ModelEndpoint,
    build_aigateway_world,
)
from url4.dag import run as url4_run
from url4.streaming.protocol import CachePolicy

MODEL = "anthropic/claude-haiku-4-5"

# --- FX-65: the scope owns what it holds ------------------------------------------------------


def test_mutating_the_callers_identity_dict_does_not_change_the_scope() -> None:
    """A producer's dict is still the caller's object; a later write to it must not reach a
    scope a concurrent handler is reading."""
    identity = {"X-User-Email": "a@x.test"}
    scope = RequestScope(identity_headers=identity, origin="run")

    identity["X-User-Email"] = "mallory@x.test"
    identity["X-Extra"] = "1"

    assert dict(scope.identity_headers) == {"X-User-Email": "a@x.test"}


def test_the_scopes_identity_mapping_cannot_be_mutated() -> None:
    scope = RequestScope(identity_headers={"X-User-Email": "a@x.test"}, origin="run")

    with pytest.raises(TypeError):
        scope.identity_headers["X-User-Email"] = "mallory@x.test"  # pyright: ignore[reportIndexIssue]

    assert scope.identity_headers["X-User-Email"] == "a@x.test"


def test_mutating_the_callers_cache_policy_does_not_change_the_scope() -> None:
    """`CachePolicy` is a mutable pydantic model, so the scope keeps its own copy."""
    policy = CachePolicy(participate=False, max_age=60)
    scope = RequestScope(cache=policy, origin="run")

    policy.participate = True
    policy.max_age = 1

    assert scope.cache is not policy
    assert scope.cache.participate is False
    assert scope.cache.max_age == 60


# --- FX-66: every producer names its surface --------------------------------------------------


def test_origin_has_no_default() -> None:
    """A scope that does not say "sync" or "run" would be counted and keyed as the run path by
    default — the silent choice FX-66 removes. Every constructor must state it."""
    (origin,) = [f for f in dataclasses.fields(RequestScope) if f.name == "origin"]

    assert origin.default is dataclasses.MISSING
    assert origin.default_factory is dataclasses.MISSING


# --- FX-64: one trace carrier ------------------------------------------------------------------


def test_the_scope_carries_no_trace() -> None:
    """The trace lives in `trace_scope` only. A second copy on the scope let the connector prefer
    one carrier on the sync path and the other on the run path (U1-L1)."""
    assert "traceparent" not in {f.name for f in dataclasses.fields(RequestScope)}


def test_the_sync_trace_producer_is_as_strict_as_valid_traceparent() -> None:
    from screamingface_engine.request_scope import trace_from_headers

    good = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    trace = trace_from_headers({"traceparent": f"  {good}  "})

    assert trace is not None
    assert (trace.trace_id, trace.root_span_id) == ("a" * 32, "b" * 16)
    assert trace_from_headers({}) is None
    assert trace_from_headers({"traceparent": "00-" + "0" * 32 + "-" + "b" * 16 + "-01"}) is None
    assert trace_from_headers({"traceparent": "not-a-traceparent"}) is None


def test_the_sync_path_re_emits_the_trace_sampled() -> None:
    """An inbound unsampled traceparent (`-00`) goes out sampled (`-01`), same trace id (item 4).

    `format_traceparent` always writes `01` — the same rendering `lifecycle.run` / the ensemble
    path has always sent — so the sync surface must not forward a caller's `-00` downstream.
    """
    from screamingface_engine.request_scope import trace_from_headers
    from screamingface_engine.trace_scope import current_traceparent, run_trace_scope

    trace_id = "a" * 32
    span_id = "b" * 16
    inbound = f"00-{trace_id}-{span_id}-00"

    trace = trace_from_headers({"traceparent": inbound})
    assert trace is not None
    with run_trace_scope(trace):
        outbound = current_traceparent()

    assert outbound == f"00-{trace_id}-{span_id}-01"


# --- FX-60: no scope value survives a call on any long-lived object ----------------------------

# INVARIANT: the handler's slots are WORLD-level only — the aigateway client and config, the route
# table, and the optional Tavily client and key. A new slot is a place a future contributor can
# park a caller's value between requests, so the set is pinned EXACTLY, not by a denylist of names
# (the old T2 test's name denylist let `self._last_seed` through, U1-H1).
_HANDLER_SLOTS = frozenset({"_cfg", "_http_client", "_routes", "_tavily_api_key", "_tavily_http"})

# Values no world, handler or module could hold by coincidence, so a hit can only be a leak.
_IDENTITY = "sentinel-identity-5c1f9e@x.test"
_PROFILE = "sentinel-profile-5c1f9e"
_SEED = 739_104_562
_MAX_AGE = 604_871


_STRING_SENTINELS = (_IDENTITY, _PROFILE, str(_SEED))
_NUMBER_SENTINELS = (_SEED, _MAX_AGE)
# Never descended into: they lead into the stub gateway (through the mock transport's handler)
# and the whole import graph, neither of which is caller state the world holds.
_OPAQUE = (
    types.ModuleType,
    types.FunctionType,
    types.MethodType,
    types.BuiltinFunctionType,
    float,
    type(None),
    # item 8 (B6 review): widening the module set to every `screamingface_engine.*` module
    # (not only `world*`) put CLASS objects in a module's globals within reach for the first
    # time — e.g. a Pydantic `BaseModel` subclass, or `BaseModel` itself, imported by name at
    # module scope elsewhere in the package. A class is shared code, never per-request state,
    # and walking one's attributes can trigger a descriptor that only behaves on an INSTANCE
    # (Pydantic's `__pydantic_validator__` raises `PydanticUserError` when read off the class).
    type,
)


def _leaks(roots: Iterable[tuple[str, object]]) -> list[str]:
    """Every path under ``roots`` that reaches a sentinel value.

    Walks containers, instance ``__dict__``s and ``__slots__``; see ``_OPAQUE`` for what it
    deliberately does not enter.
    """
    found: list[str] = []
    seen: set[int] = set()
    pending: list[tuple[str, object]] = list(roots)
    while pending:
        path, value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if _is_sentinel(value):
            found.append(path)
        pending.extend(_children(path, value))
    return found


def _is_sentinel(value: object) -> bool:
    if isinstance(value, bytes):
        value = value.decode("latin-1")
    if isinstance(value, str):
        return any(sentinel in value for sentinel in _STRING_SENTINELS)
    return isinstance(value, int) and not isinstance(value, bool) and value in _NUMBER_SENTINELS


def _children(path: str, value: object) -> list[tuple[str, object]]:
    children: list[tuple[str, object]] = []
    if isinstance(value, (str, bytes, int, *_OPAQUE)):
        pass
    elif isinstance(value, Mapping):
        for key, item in list(value.items()):
            children += [(f"{path}[{key!r}].key", key), (f"{path}[{key!r}]", item)]
    elif isinstance(value, list | tuple | set | frozenset):
        children += [(f"{path}[{index}]", item) for index, item in enumerate(value)]
    else:
        children += _attributes(path, value)
    return children


def _attributes(path: str, value: object) -> list[tuple[str, object]]:
    names = set(getattr(value, "__dict__", {}))
    for klass in type(value).__mro__:
        slots = klass.__dict__.get("__slots__", ())
        names.update((slots,) if isinstance(slots, str) else slots)
    found: list[tuple[str, object]] = []
    for name in sorted(names):
        try:
            found.append((f"{path}.{name}", getattr(value, name)))
        except AttributeError:  # an unset slot holds nothing
            continue
    return found


def _engine_modules() -> list[tuple[str, object]]:
    """Every loaded ``screamingface_engine.*`` module (item 8, B6 review).

    WHY every module and not only ``world*`` (U1-H1's original scope): a scope value can leak
    into ANY module's globals a request touches, not only the world package's — the original
    scan would miss a leak into, say, ``job_env`` or ``logs`` entirely. No module here is
    excluded as "a cache of constants" today: `job_env` holds Job env variable NAMES and pure
    readers, and every other engine module is either stateless or already covered by the
    handler/world roots. A module that legitimately needs to cache a resolved value would earn
    a documented skip here, not a silent one.
    """
    return [
        (name, module)
        for name, module in sorted(sys.modules.items())
        if name == "screamingface_engine" or name.startswith("screamingface_engine.")
    ]


def test_the_model_handlers_slots_are_exactly_the_world_level_allowlist() -> None:
    assert frozenset(_ModelEndpoint.__slots__) == _HANDLER_SLOTS
    assert not hasattr(_ModelEndpoint(**_handler_fields()), "__dict__")


def _handler_fields() -> dict[str, Any]:
    return {
        "http_client": None,
        "cfg": AigatewayConfig(),
        "routes": {},
        "tavily_http": None,
        "tavily_api_key": None,
    }


@pytest.mark.asyncio
async def test_no_scope_value_survives_a_call_on_the_handler_the_world_or_module_globals() -> None:
    """A structural scan, so the regression cannot hide under a new name (U1-H1).

    The call runs as a SYNC request so the seed really reaches the outbound body (outside a
    Candidate invocation only the sync surface stamps it), then every long-lived object is
    scanned for the sentinels once the call has returned.
    """
    gw = _MockAigateway((MODEL,))
    cfg = AigatewayConfig(models=gw.models, default_model=MODEL)
    scope = RequestScope(
        identity_headers={"X-User-Email": _IDENTITY},
        profile=_PROFILE,
        answer_seed=_SEED,
        # `max_age` never reaches the wire (it is applied at read-back, `world/cache.py`), so the
        # opt-out is what proves the directive left; the sentinel age is what a stash would keep.
        cache=CachePolicy(participate=False, max_age=_MAX_AGE),
        origin="sync",
    )

    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        try:
            with request_scope(scope):
                await url4_run(f"/{MODEL}('ctx')!'go'", io=world.node)

            # The sentinels really left on the call — otherwise a clean scan proves nothing.
            (outbound,) = gw.posts_to(MODEL)
            assert outbound.headers["X-User-Email"] == _IDENTITY
            assert outbound.headers["X-Profile"] == _PROFILE
            body = json.loads(outbound.content)
            assert body["seed"] == _SEED
            assert body["cache"] == {"use-cache": False}

            handler = cast(Any, world.node)._endpoints[f"/{MODEL}"]
            # item 8 (B6 review): every LOADED `screamingface_engine.*` module, not only
            # `world*` — see `_engine_modules`.
            modules = _engine_modules()
            roots: list[tuple[str, object]] = [("handler", handler), ("world", world)]
            roots += [(f"{name}.<globals>", vars(module)) for name, module in modules]
            assert _leaks(roots) == []
        finally:
            await world.aclose()


def test_the_module_scan_reaches_every_engine_module_not_only_world() -> None:
    """Pins the scan's own coverage (item 8, B6 review): a leak OUTSIDE `world*` must be caught.

    `job_env` holds only Job env variable names and pure readers, so it would never legitimately
    hold a request value — a write there is unambiguously a leak, which is exactly why it is the
    module a mutant plants one in. Confirmed RED against a scan narrowed to `world*` before this
    fix (the mutant landed outside its scope and the scan reported no leaks).
    """
    import screamingface_engine.job_env as job_env_module

    mutant = cast(Any, job_env_module)
    mutant._LAST = _PROFILE
    try:
        roots = [(f"{name}.<globals>", vars(module)) for name, module in _engine_modules()]
        assert any(path.endswith("['_LAST']") for path in _leaks(roots))
    finally:
        del mutant._LAST
