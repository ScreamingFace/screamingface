"""OME-648 — the dynamic source revision is published, hashed, and agreed on.

FEATURE: profile-bound detailed parameter contract. A provider's ``source_revision``
versions the gateway's READING of a source, not merely the URL it dialed. The same
bytes can mean different things under a different reading, so the revision is part
of the contract's IDENTITY and part of its published metadata.

STORY: as a client that caches on ``contract_id``, I am never handed a contract whose
evidence was read from different documents, or under a different reading, while the
id I pinned stays the same.

INVARIANT (identity): a revision change moves BOTH opaque ids — even when the
resulting observations are byte-identical. A digest that omitted it would fail
DANGEROUSLY: a semantically reinterpreted contract served under a frozen id.
INVARIANT (agreement): the cache key is built from the ref a provider declares BEFORE
the fetch, while the evidence carries its own stamp. If those disagree, the entry
would be stored under a reading that did not produce it — so the attempt fails and
the honest stale/degraded path takes over.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ProviderDiscoverySnapshot,
    ProviderParameterObservation,
)
from aigateway.core.discovery_runtime import DiscoveryRuntime, static_discovery_outcome
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.core.parameter_discovery import (
    DiscoveryHttpClient,
    DiscoveryLimits,
    DiscoverySourceRef,
    RawResponse,
)
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache

_REF = DiscoverySourceRef(source="probe:models", revision="probe:reading-1")
_MODEL = "probe/model-a"

# The window a caller hands the composer. Deliberately NOT where the revision is
# published — see the module docstring in ``model_parameter_contract``.
_WINDOW: dict[str, Any] = {
    "observed_at": None,
    "expires_at": None,
    "stale": False,
    "degraded": False,
}


def _observation(path: str = "temperature") -> ProviderParameterObservation:
    return ProviderParameterObservation(
        request_path=path, support="supported", source="probe:models"
    )


def _rule(path: str = "temperature") -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=path,
        applicable_auth_modes=("api_key",),
        projection_kind="direct",
        cache_behavior="bypass",
        projection_revision="r1",
    )


def _document(*, source_revision: str | None) -> dict[str, Any]:
    """The SAME contract in every respect but the revision under which it was read."""
    auth_mode: AuthType = "api_key"
    return build_model_parameter_document(
        canonical_id="probe/model-a",
        gateway_provider="probe",
        auth_mode=auth_mode,
        scope="account_profile",
        context_identity="acct:a1|prof:p1:authenticated:-",
        rules=(_rule(),),
        observations=(_observation(),),
        tools=(),
        transport=(),
        freshness=dict(_WINDOW),
        source_revision=source_revision,
    )


# --- identity: the mutation the review's probe performed ---------------------


def test_a_revision_change_moves_both_opaque_ids_on_identical_observations() -> None:
    """The exact probe that failed review, now inverted.

    Two snapshots differing ONLY in ``source_revision`` previously produced
    byte-equal ``contract_id`` and ``context.revision``. Both must move, and the
    observations are held byte-identical so nothing else can explain the movement.
    """
    a = _document(source_revision="rev-a")
    b = _document(source_revision="rev-b")

    assert a["parameters"] == b["parameters"]  # the evidence really is identical
    assert a["contract_id"] != b["contract_id"]
    assert a["context"]["revision"] != b["context"]["revision"]


def test_the_two_opaque_ids_move_independently_of_each_other() -> None:
    # domain separation: the same input set must not collapse the two ids into one
    # value, or a client pinning one would be pinning the other by accident.
    doc = _document(source_revision="rev-a")
    assert doc["contract_id"].startswith("pc_")
    assert doc["context"]["revision"].startswith("ctx_")
    assert doc["contract_id"][3:] != doc["context"]["revision"][4:]


def test_appearing_and_disappearing_are_both_identity_changes() -> None:
    # a provider that GAINS a dynamic source, or loses one, has changed what the
    # contract means — "" and a real label must not hash alike.
    absent = _document(source_revision=None)
    present = _document(source_revision="rev-a")
    assert absent["contract_id"] != present["contract_id"]
    assert absent["context"]["revision"] != present["context"]["revision"]


# --- publication -------------------------------------------------------------


def test_the_revision_is_published_in_the_contract_context() -> None:
    doc = _document(source_revision="probe:reading-1")
    assert doc["context"]["source_revision"] == "probe:reading-1"


def test_the_key_is_present_and_null_when_there_is_no_dynamic_source() -> None:
    # INVARIANT: uniform shape. "this provider publishes no machine-readable source"
    # must be readable without a key-presence check, exactly as for the timestamps.
    context = _document(source_revision=None)["context"]
    assert "source_revision" in context
    assert context["source_revision"] is None


def test_the_published_revision_is_the_hashed_revision() -> None:
    """No drift between what is served and what is hashed.

    They come from one argument by construction; this pins that structurally, so a
    future edit that publishes one value and hashes another fails here rather than
    silently freezing an id over a contract that changed.
    """
    seen: set[tuple[str | None, str]] = set()
    for revision in ("rev-a", "rev-b", "rev-c", None):
        doc = _document(source_revision=revision)
        assert doc["context"]["source_revision"] == revision
        seen.add((doc["context"]["source_revision"], doc["contract_id"]))
    assert len({identity for _, identity in seen}) == 4


def test_the_freshness_window_is_left_exactly_as_the_caller_supplied_it() -> None:
    # the revision is identity metadata, and `freshness` is the one block excluded
    # from the digest. Publishing there would tell a reader the opposite.
    assert _document(source_revision="rev-a")["freshness"] == _WINDOW


def test_the_published_revision_carries_no_digest_inputs() -> None:
    # INVARIANT (privacy): the revision is a provider-authored source label. It must
    # never become a channel for the account/profile identity that is hashed beside it.
    doc = _document(source_revision="probe:reading-1")
    assert "acct:a1" not in doc["context"]["source_revision"]
    assert "p1" not in doc["context"]["source_revision"]


# --- agreement between the declared ref and the returned snapshot ------------


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def utc(self) -> datetime:
        return datetime(2026, 7, 28, tzinfo=UTC) + timedelta(seconds=self.t)


class _UnusedClient(DiscoveryHttpClient):
    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        raise AssertionError(f"the double answers in-process; nothing should dial {url}")


class _StampingPlugin:
    """Declares ``_REF`` but stamps its snapshot with whatever it was told to."""

    def __init__(self, stamped: str) -> None:
        self._stamped = stamped
        self.fetches = 0

    def chat_discovery_source(self, *, model: str) -> DiscoverySourceRef | None:
        return _REF

    async def discover_chat_parameter_snapshot(
        self, *, model: str, client: Any, limits: DiscoveryLimits | None = None
    ) -> ProviderDiscoverySnapshot | None:
        self.fetches += 1
        return ProviderDiscoverySnapshot(
            source_revision=self._stamped, model_observations=(_observation(),)
        )


def _runtime(clock: _Clock) -> DiscoveryRuntime:
    return DiscoveryRuntime(
        client=_UnusedClient(),
        cache=ObservationCache(
            clock=clock, limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
        now_utc=clock.utc,
    )


@pytest.mark.asyncio
async def test_an_agreeing_snapshot_is_served_normally() -> None:
    plugin = _StampingPlugin(_REF.revision)
    outcome = await _runtime(_Clock()).observe(plugin, model=_MODEL)
    assert outcome.snapshot is not None
    assert outcome.snapshot.source_revision == _REF.revision
    assert outcome.freshness["degraded"] is False


@pytest.mark.asyncio
async def test_a_snapshot_stamped_with_another_reading_is_refused() -> None:
    """The cache key asserts a reading the evidence does not support.

    Serving it would publish evidence gathered under one reading as though it were
    the declared one — and cache it there for every later request in the window.
    """
    plugin = _StampingPlugin("probe:reading-2")
    outcome = await _runtime(_Clock()).observe(plugin, model=_MODEL)

    assert plugin.fetches == 1  # the fetch happened; it is the STORE that is refused
    assert outcome.snapshot is None
    assert outcome.freshness["degraded"] is True
    # fail-closed: a degraded contract carries no window implying evidence behind it.
    assert outcome.freshness["observed_at"] is None
    assert outcome.freshness["expires_at"] is None


@pytest.mark.asyncio
async def test_the_mismatch_never_evicts_a_good_entry_in_favour_of_itself() -> None:
    # a rejected refresh must behave like any other failed attempt: the last good
    # evidence keeps being served (labelled stale once its fresh window closes),
    # never replaced by the disagreeing snapshot.
    clock = _Clock()
    runtime = _runtime(clock)
    good = await runtime.observe(_StampingPlugin(_REF.revision), model=_MODEL)
    assert good.snapshot is not None

    clock.t = 90.0  # past ttl_s, inside stale_ttl_s
    after = await runtime.observe(_StampingPlugin("probe:reading-2"), model=_MODEL)

    assert after.snapshot is not None
    assert after.snapshot.source_revision == _REF.revision
    assert after.freshness["stale"] is True
    assert after.freshness["degraded"] is False


@pytest.mark.asyncio
async def test_a_provider_with_no_declared_source_is_untouched_by_the_check() -> None:
    # the agreement rule applies to a declared source. Declaring none is the honest
    # answer for a provider that publishes nothing, and must stay a static outcome.
    class _Silent:
        def chat_discovery_source(self, *, model: str) -> DiscoverySourceRef | None:
            return None

        async def discover_chat_parameter_snapshot(
            self, *, model: str, client: Any, limits: DiscoveryLimits | None = None
        ) -> ProviderDiscoverySnapshot | None:
            raise AssertionError("no source was declared; nothing should be fetched")

    outcome = await _runtime(_Clock()).observe(_Silent(), model=_MODEL)
    assert outcome == static_discovery_outcome()


# --- production wiring: the route, not the composer --------------------------
#
# WHY this section exists: the composer tests above prove the field is published
# GIVEN the argument. They cannot prove the route supplies it — and a route that
# quietly dropped it is exactly the defect under repair here, which lived through
# review because every test stopped at the composer.


_ANTHROPIC_MODEL = "anthropic/claude-opus-4-8"
_OR_MODEL = "openrouter/google/gemini-3.6-flash"
_OR_UPSTREAM = "google/gemini-3.6-flash"


@pytest.fixture
def openrouter_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # patch the singleton INSTANCE: `load_plugins` hands the same object to every
    # app, so an env var set after import cannot reach it.
    from aigateway.plugins.openrouter_provider import plugin as plugin_module
    from aigateway.plugins.openrouter_provider.plugin import OpenRouterPluginSettings

    monkeypatch.setattr(
        plugin_module.PLUGIN,
        "settings",
        OpenRouterPluginSettings(enabled=True, default_models=[_OR_MODEL]),
    )


class _FixedDocuments(DiscoveryHttpClient):
    """Serves OpenRouter's two fixed public documents, in process."""

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        from aigateway.plugins.openrouter_provider.discovery import MODELS_URL, OPENAPI_URL

        bodies: dict[str, Any] = {
            MODELS_URL: {"data": [{"id": _OR_UPSTREAM, "supported_parameters": ["temperature"]}]},
            OPENAPI_URL: {
                "components": {"schemas": {"ChatRequest": {"properties": {"temperature": {}}}}}
            },
        }
        return RawResponse(
            status=200, content_type="application/json", body=json.dumps(bodies[url])
        )


async def _openrouter_contract(client: Any) -> dict[str, Any]:
    from fastapi import FastAPI

    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=_FixedDocuments(),
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    resp = client.get("/v1/model-parameters", params={"model": _OR_MODEL})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_the_route_publishes_the_providers_own_declared_revision(
    openrouter_enabled, authenticated_client
) -> None:
    from aigateway.plugins.openrouter_provider.discovery import SNAPSHOT_SOURCE_REVISION

    body = await _openrouter_contract(authenticated_client)

    # the real provider constant, through the real route — not a composer argument.
    assert body["context"]["source_revision"] == SNAPSHOT_SOURCE_REVISION


@pytest.mark.asyncio
async def test_the_route_publishes_null_for_a_provider_with_no_dynamic_source(
    authenticated_client,
) -> None:
    body = authenticated_client.get(
        "/v1/model-parameters", params={"model": _ANTHROPIC_MODEL}
    ).json()

    # anthropic declares no dynamic source: the honest value is null, and the KEY is
    # still present — which is the part a client can rely on without probing.
    assert "source_revision" in body["context"]
    assert body["context"]["source_revision"] is None


# --- the shipping providers actually agree -----------------------------------


def test_openrouter_declares_the_revision_its_snapshot_stamps() -> None:
    """A regression guard on the pairing the runtime check now enforces.

    A plugin names its revision twice — in the ref it declares BEFORE the fetch, and
    in the snapshot its discovery module returns. Bumping one without the other would
    otherwise surface as an unexplained permanently-degraded contract, since every
    refresh would be refused. WHY: Gemini and HuggingFace assert the same
    pairing at their own snapshot sites (``snapshot.source_revision == <constant>``);
    this pins the provider whose revision moved in OME-647.
    """
    from aigateway.plugins.openrouter_provider.discovery import SNAPSHOT_SOURCE_REVISION
    from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin

    ref = OpenRouterProviderPlugin().chat_discovery_source(model=_OR_MODEL)
    assert ref is not None
    assert ref.revision == SNAPSHOT_SOURCE_REVISION
