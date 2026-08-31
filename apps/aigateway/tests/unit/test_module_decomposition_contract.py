"""OME-1026 adversarial B6 — the decomposition contract of the files this pass split.

FEATURE: source files small enough to be reviewed and reasoned about, with the served
API and the suite's instrumentation seams unchanged by the split.

STORY: as the next agent to touch ``routes.auth`` or the OpenRouter plugin, I can move a
helper without silently deleting a route or disarming a monkeypatch, because these tests
fail the moment either happens.

INVARIANT (why the seam test exists at all): ``monkeypatch.setattr`` rebinds a name in
ONE module's namespace, and a function only observes that rebinding if it resolves the
name from THAT module's globals. Moving a function to a new module therefore relocates
which patches can reach it — and nothing else in the toolchain notices. Two merged tests
depend on exactly this:

  * ``tests/integration/test_lifecycle_postgres_races.py`` patches
    ``routes.auth.credential_strategy_from`` to keep a Postgres race test off the
    network, which only works while the strategy builder is defined in ``routes.auth``.
  * ``tests/unit/openrouter/test_openrouter_routing_policy_route_rejections.py`` patches
    ``openrouter_provider.plugin.build_provider_policy``, which only works while
    ``prepare_chat_body`` is defined in that module.

Both patches raise ``AttributeError`` if the name disappears, but neither notices if the
name is present and no longer consulted. These tests pin the seams directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.routes import auth as auth_module
from aigateway.routes import oauth_callbacks, profile_routes

_SRC = Path(__file__).resolve().parents[2] / "src" / "aigateway"

# INVARIANT (OME-1026 last-mile — the claim is now EXACT): every hand-maintained
# source file in the package is bounded, not a hand-listed subset of them. A list had
# to be kept in sync with the diff by hand, and it silently under-claimed: a file this
# pass touched but nobody added to the list was simply not checked.
#
# The four entries below are PRE-EXISTING debt, each byte-identical to ``origin/main``
# and untouched by this pass. They are pinned at their current size rather than
# waived, so they can shrink but never grow — which is what makes the exemption safe to
# leave in place. Splitting one is its own unit of work with its own tests.
_SIZE_LIMIT = 450
_PRE_EXISTING_OVERSIZED = {
    "plugins/antigravity_provider/chat_handler.py": 610,
    "plugins/taxonomy/types.py": 533,
    "routes/chat.py": 522,
    "routes/oauth_connections.py": 521,
}


def _source_files() -> list[str]:
    return sorted(
        str(path.relative_to(_SRC))
        for path in _SRC.rglob("*.py")
        if "__pycache__" not in path.parts
    )


# The auth surface the merged suite imports from ``routes.auth``. Every entry is an
# import in ``tests/unit/test_auth_routes.py``; several helpers now live in the modules
# the split created, so the names must stay reachable at this path.
_AUTH_SURFACE = (
    "_close_loopback_callback",
    "_complete_oauth_for_app",
    "_connection_label",
    "_expire_loopback_callback",
    "_handle_loopback_callback",
    "_http_response",
    "_loopback_host_allowed",
    "close_loopback_callbacks",
    "start_oauth",
    "upsert_api_key_profile",
)

# The 14 declarations ``routes.auth`` carried before the split, now spread across three
# routers. Byte-identical paths and methods: the split is invisible from outside.
_AUTH_ROUTE_DECLARATIONS = frozenset(
    {
        ("DELETE", "/v1/auth/{provider}/profiles/{name}"),
        ("GET", "/auth/callback"),
        ("GET", "/callback"),
        ("GET", "/oauth2callback"),
        ("GET", "/v1/auth/profiles"),
        ("GET", "/v1/auth/{provider}/callback"),
        ("GET", "/v1/auth/{provider}/profiles"),
        ("GET", "/v1/auth/{provider}/profiles/{name}"),
        ("GET", "/v1/auth/{provider}/profiles/{name}/status"),
        ("PATCH", "/v1/auth/{provider}/profiles/{name}"),
        ("POST", "/v1/auth/{provider}/exchange-code"),
        ("POST", "/v1/auth/{provider}/profiles"),
        ("POST", "/v1/auth/{provider}/profiles/{name}/refresh"),
        ("PUT", "/v1/auth/{provider}/profiles/{name}/api-key"),
    }
)


@pytest.mark.parametrize("relative", _source_files())
def test_every_hand_maintained_source_file_is_within_the_size_limit(relative: str) -> None:
    """Every file, so a touched file cannot escape the bound by being unlisted."""
    lines = len((_SRC / relative).read_text().splitlines())
    pinned = _PRE_EXISTING_OVERSIZED.get(relative)
    if pinned is None:
        assert lines <= _SIZE_LIMIT, f"{relative} is {lines} physical lines (limit {_SIZE_LIMIT})"
        return
    # Pinned pre-existing debt: it may shrink, never grow.
    assert lines <= pinned, (
        f"{relative} grew to {lines} lines from a pinned {pinned}; it is already over the "
        f"{_SIZE_LIMIT}-line limit, so adding to it is the one thing that is not allowed"
    )


def test_the_oversized_inventory_names_only_files_that_are_really_oversized() -> None:
    """The exemption list cannot quietly acquire a file that is already compliant.

    Without this, a future pass could add a compliant file to the pin map and thereby
    give it a private, larger budget — the exact hole the exact-claim rewrite closed.
    """
    for relative, pinned in _PRE_EXISTING_OVERSIZED.items():
        path = _SRC / relative
        assert path.exists(), f"{relative} is pinned but missing — update the inventory"
        assert pinned > _SIZE_LIMIT, f"{relative} is pinned at {pinned}, which is not oversized"


@pytest.mark.parametrize("name", _AUTH_SURFACE)
def test_the_auth_module_still_exposes_the_name_the_suite_imports(name: str) -> None:
    assert hasattr(auth_module, name), (
        f"routes.auth no longer exposes {name!r}; the merged suite imports it from there"
    )


def test_the_three_auth_routers_declare_exactly_the_pre_split_route_set() -> None:
    """No path gained, lost, or renamed by moving handlers between modules."""
    declared: set[tuple[str, str]] = set()
    for router in (auth_module.router, profile_routes.router, oauth_callbacks.router):
        for route in router.routes:
            for method in sorted(getattr(route, "methods", set()) or set()):
                declared.add((method, getattr(route, "path", "")))
    assert declared == set(_AUTH_ROUTE_DECLARATIONS)


def test_each_split_router_carries_part_of_the_set_and_none_carries_all_of_it() -> None:
    """Guards the reverse mistake: a "split" that left everything in one router.

    Without this, ``test_the_three_auth_routers_declare_exactly_the_pre_split_route_set``
    would still pass if a later change moved every handler back into ``routes.auth``.
    """
    sizes = {
        "auth": len(auth_module.router.routes),
        "profile_routes": len(profile_routes.router.routes),
        "oauth_callbacks": len(oauth_callbacks.router.routes),
    }
    assert all(count > 0 for count in sizes.values()), sizes
    assert max(sizes.values()) < len(_AUTH_ROUTE_DECLARATIONS), sizes


def test_the_credential_strategy_seam_still_resolves_inside_routes_auth() -> None:
    """The Postgres race test's substitution point (see the module docstring).

    ``hasattr`` alone is not enough — the name must be the one the BUILDER consults, so
    this asserts the builder is defined in this module too. A builder that moved away
    would leave the patch pointing at an unread global and put that test on the network.
    """
    assert hasattr(auth_module, "credential_strategy_from")
    builder = auth_module._credential_strategy_for_credential_name  # noqa: SLF001
    assert builder.__module__ == auth_module.__name__
    assert "credential_strategy_from" in builder.__code__.co_names


def test_the_connection_store_seam_still_resolves_inside_routes_auth() -> None:
    """``routes.auth.OAuthConnectionStore.complete_pending`` is patched by dotted path.

    That patch mutates the shared class, so only the NAME has to resolve here — but it
    has to resolve, and ruff deletes an unused import unless it is a marked re-export.
    """
    from aigateway.routes.oauth_connection_completion import OAuthConnectionStore

    assert auth_module.OAuthConnectionStore is OAuthConnectionStore


def test_the_routing_policy_seam_still_resolves_inside_the_openrouter_plugin() -> None:
    """``prepare_chat_body`` must keep consulting the plugin module's own global."""
    assert hasattr(openrouter_plugin_module, "build_provider_policy")
    prepare = openrouter_plugin_module.OpenRouterProviderPlugin.prepare_chat_body
    assert prepare.__module__ == openrouter_plugin_module.__name__
    assert "build_provider_policy" in prepare.__code__.co_names


@pytest.mark.parametrize(
    "name",
    (
        "GLOBAL_CACHE_ADAPTER_REVISION",
        "OFFICIAL_API_BASE",
        "OpenRouterProviderPlugin",
        "PLUGIN",
        "_embedded_error_status",
        "_top_level_error_is_meaningful",
    ),
)
def test_the_openrouter_plugin_module_keeps_its_imported_surface(name: str) -> None:
    assert hasattr(openrouter_plugin_module, name)
