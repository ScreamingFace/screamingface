"""Compatibility shims and wiring (OME-1200, spec §3.1): `routes/chat_credentials.py` and
`routes/chat_profile_defaults.py` keep today's names, delegate to the port, and render refusals
through the edge table; `app.state.provider_access` is the Profile-backed implementation.

# INVARIANT (A1): no route call site changes, so every name a route or an existing test imports
# from the two shim modules must still exist and behave as before.
# AIDEV-NOTE (A2, OME-1207): the four consumers now call the port directly, so `chat_credentials`
# is no longer imported by any ROUTE — only by this suite, which is why it survives. It and the
# names below are deleted at Stage E (OME-1209) together with the legacy vocabulary.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException, Request

from aigateway.core.profile_models import ProfileDefaults
from aigateway.core.provider_access import (
    ProfileBackedProviderAccess,
    TargetPending,
    apply_defaults,
    auth_type_of,
    provider_access_for,
    reauth_url_for,
)
from aigateway.routes import chat, chat_credentials, chat_dispatch, chat_profile_defaults

# WHY parents[3]: <src>/aigateway/core/provider_access/<module>.py — three package dirs up.
_SRC = Path(inspect.getfile(ProfileBackedProviderAccess)).resolve().parents[3]


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


# --- names ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "_apply_defaults",
        "_credential_target_for_chat",
        "_inject_credentials",
        "resolved_auth_mode",
        "auth_mode_for_target",
        "_invalidate_profile_session",
        "_mark_profile_error_fresh",
        "_oauth_connection_store",
        "_reauth_url_for",
    ],
)
def test_chat_credentials_still_exports_every_name_a_route_imports(name: str) -> None:
    assert callable(getattr(chat_credentials, name))


def test_chat_credentials_re_exports_the_pure_helpers_by_identity() -> None:
    assert chat_credentials._apply_defaults is apply_defaults
    assert chat_credentials.auth_mode_for_target is auth_type_of
    assert chat_credentials._reauth_url_for is reauth_url_for


def test_chat_profile_defaults_still_exports_its_two_names() -> None:
    assert callable(chat_profile_defaults.profile_defaults_for_key)
    assert callable(chat_profile_defaults._parameter_rejection_exception)


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
    there must be what the shims call, never silently replaced by the Profile-backed default."""
    substitute = _PendingEverything()
    authenticated_client.app.state.provider_access = substitute
    request = cast(Request, SimpleNamespace(app=authenticated_client.app))
    # WHY outside the portal call: `client.get` is a blocking TestClient call and must not run
    # on the event-loop thread the portal hands the coroutine to.
    account_id = _account_id(authenticated_client)
    plugin = authenticated_client.app.state.providers.get("anthropic")

    assert provider_access_for(authenticated_client.app) is substitute
    with pytest.raises(HTTPException) as info:
        authenticated_client.portal.call(
            lambda: chat_credentials._credential_target_for_chat(
                request,
                account_id=account_id,
                provider="anthropic",
                profile_name="default",
                plugin=plugin,
            )
        )

    assert info.value.status_code == 409
    assert info.value.detail == {
        "code": "profile_pending_auth",
        "provider": "anthropic",
        "name": "default",
    }


def test_provider_access_for_creates_the_profile_backed_default_only_when_absent() -> None:
    app = SimpleNamespace(state=SimpleNamespace())

    created = provider_access_for(app)

    assert isinstance(created, ProfileBackedProviderAccess)
    assert app.state.provider_access is created
    assert provider_access_for(app) is created


# --- behaviour through the shims --------------------------------------------------------------


def test_the_shim_resolver_renders_a_missing_target_as_todays_404(authenticated_client) -> None:
    request = cast(Request, SimpleNamespace(app=authenticated_client.app))
    account_id = _account_id(authenticated_client)
    plugin = authenticated_client.app.state.providers.get("anthropic")

    with pytest.raises(HTTPException) as info:
        authenticated_client.portal.call(
            lambda: chat_credentials._credential_target_for_chat(
                request,
                account_id=account_id,
                provider="anthropic",
                profile_name="default",
                plugin=plugin,
            )
        )

    assert info.value.status_code == 404
    assert info.value.detail == {
        "code": "profile_not_found",
        "provider": "anthropic",
        "name": "default",
    }


def test_the_shim_resolver_keeps_the_datasheet_escape(authenticated_client) -> None:
    request = cast(Request, SimpleNamespace(app=authenticated_client.app))
    account_id = _account_id(authenticated_client)
    plugin = authenticated_client.app.state.providers.get("anthropic")

    result = authenticated_client.portal.call(
        lambda: chat_credentials._credential_target_for_chat(
            request,
            account_id=account_id,
            provider="anthropic",
            profile_name="default",
            plugin=plugin,
            missing_target_ok=True,
        )
    )

    assert result == (None, None, ProfileDefaults())


def test_the_shim_defaults_read_still_never_raises(authenticated_client, monkeypatch) -> None:
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(authenticated_client.app.state.profile_index, "get", _boom)
    request = cast(Request, SimpleNamespace(app=authenticated_client.app))

    result = authenticated_client.portal.call(
        lambda: chat_profile_defaults.profile_defaults_for_key(
            request, account_id="a", provider="anthropic", profile_name="default"
        )
    )

    assert result is None


def test_the_context_stamp_is_byte_identical_to_the_legacy_context_identity(
    authenticated_client, credential_blobs, monkeypatch
) -> None:
    from provider_access_harness import ProfileBackedHarness

    from aigateway.core.provider_access import Selector

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
        _SRC / "aigateway" / "routes" / "chat_credentials.py",
        _SRC / "aigateway" / "routes" / "chat_profile_defaults.py",
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
