"""Provider-access wiring (OME-1200, spec §3.1): `app.state.provider_access` is the port, and
chat reaches credentials only through it.

# INVARIANT: a substituted implementation on `app.state.provider_access` is what the routes call.
# WHY no shim tests: the A1 shims (`routes/chat_credentials.py`, `routes/chat_profile_defaults.py`)
# lost their last route importer at A2 (OME-1207) and were deleted at Stage E, E2b (OME-1209).
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from aigateway.core.provider_access import (
    ProfileBackedProviderAccess,
    Selector,
    TargetPending,
    provider_access_for,
)
from aigateway.routes import chat, chat_dispatch

# WHY parents[3]: <src>/aigateway/core/provider_access/<module>.py — three package dirs up.
_SRC = Path(inspect.getfile(ProfileBackedProviderAccess)).resolve().parents[3]


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


# --- names ----------------------------------------------------------------------------------


def test_the_chat_namespace_binds_the_accessor_the_suites_patch() -> None:
    """# INVARIANT (OME-1207): A1 pinned that chat's namespace still bound the three shim names
    the suites patched. A2 moved those call sites onto the port, so the name a suite reaches for
    is `provider_access_for` — bound in BOTH route namespaces, and the same object the port
    package exports. Patch `app.state.provider_access` (or this name) to steer chat's credentials;
    nothing else is a supported seam."""
    assert chat.provider_access_for is provider_access_for
    assert chat_dispatch.provider_access_for is provider_access_for


# --- wiring ---------------------------------------------------------------------------------


def test_the_app_holds_the_profile_backed_implementation_next_to_the_index(client) -> None:
    assert isinstance(client.app.state.provider_access, ProfileBackedProviderAccess)


class _PendingEverything:
    """A substitute implementation no empty Profile store could be mistaken for."""

    async def resolve(self, account_id, provider, selector, *, plugin, policy=None):
        raise TargetPending(provider, selector.name)


def test_provider_access_for_honours_a_substituted_implementation(authenticated_client) -> None:
    """# INVARIANT (F2): `app.state.provider_access` is THE port; a fake or a future backing put
    there must be what callers reach, never silently replaced by the Profile-backed default."""
    substitute = _PendingEverything()
    authenticated_client.app.state.provider_access = substitute
    plugin = authenticated_client.app.state.providers.get("anthropic")

    access = provider_access_for(authenticated_client.app)

    assert access is substitute
    with pytest.raises(TargetPending):
        authenticated_client.portal.call(
            lambda: access.resolve(
                "account", "anthropic", Selector.from_header(None), plugin=plugin
            )
        )


def test_provider_access_for_creates_the_profile_backed_default_only_when_absent() -> None:
    app = SimpleNamespace(state=SimpleNamespace())

    created = provider_access_for(app)

    assert isinstance(created, ProfileBackedProviderAccess)
    assert app.state.provider_access is created
    assert provider_access_for(app) is created


# --- the context stamp ----------------------------------------------------------------------


def test_the_context_stamp_is_byte_identical_to_the_legacy_context_identity(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    from provider_access_harness import ProfileBackedHarness

    harness = ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)
    harness.seed_profile()
    plugin = authenticated_client.app.state.providers.get("anthropic")

    target = harness.call(
        harness.access.resolve,
        harness.account_id,
        "anthropic",
        Selector.from_header(None),
        plugin=plugin,
    )
    profile = harness.call(
        authenticated_client.app.state.profile_index.get, harness.account_id, "anthropic", "default"
    )

    # OME-1207: A1 pinned this against `model_parameters._context_identity`. A2 deleted that
    # helper, so the pin is now the FORMULA itself — stronger than agreeing with a function that
    # could have drifted with it. These bytes feed the contract/context digests: changing them
    # silently re-identifies every published contract.
    assert target.context_stamp == (
        f"acct:{harness.account_id}|"
        f"prof:{profile.id}:{profile.state.value}:{profile.last_refreshed_at or '-'}"
    )


# --- size and layering --------------------------------------------------------------------------


def test_every_boundary_module_stays_within_the_file_size_limit() -> None:
    package = _SRC / "aigateway" / "core" / "provider_access"
    files = sorted(package.glob("*.py")) + [
        _SRC / "aigateway" / "routes" / "provider_access_http.py",
    ]
    oversized = {f.name: n for f in files if (n := len(f.read_text().splitlines())) > 450}

    assert files, "the package must exist"
    assert oversized == {}


def test_the_core_package_imports_no_routes_or_plugins() -> None:
    package = _SRC / "aigateway" / "core" / "provider_access"
    offenders = [
        f.name
        for f in package.glob("*.py")
        if "aigateway.routes" in f.read_text()
        or "from ..routes" in f.read_text()
        or "from ...routes" in f.read_text()
        or "aigateway.plugins" in f.read_text()
        or "from ...plugins" in f.read_text()
    ]

    assert offenders == []
