"""G0 refresh guard inventory — every app site that builds a credential strategy is classified.

# FEATURE: OME-1138 D18, G0 part 2 (contract §5.3) — a strategy publishes a refresh unguarded
# unless the app binds its owner guard, so correctness rests on the inventory of build sites. This
# test pins that inventory: a NEW site fails here until its author decides whether it refreshes
# (then it must bind `guard_refresh`) or only persists/deletes (then it is listed below).
# AIDEV-NOTE: plugins and `core/plugin_base` are the factory layer itself and are not scanned. A
# dispatch target with no stored backing is ambient (no blob anyone owns), which is why
# `profile_authorize._guarded` passes it through.
"""

from __future__ import annotations

import ast
from pathlib import Path

import aigateway

SOURCE = Path(aigateway.__file__).parent
FACTORIES = frozenset(
    {
        "credential_strategy_from",
        "credential_strategy_for_connection",
        "_credential_strategy_for_app",
        "_credential_strategy_for_credential_name",
        "oauth_strategy_for",
        "credential_strategy_for",
        "api_key_strategy_for",
    }
)
GUARDS = frozenset({"guard_refresh", "_guarded"})

# Sites whose strategy can refresh: each binds the owner guard where it builds.
REFRESHING = frozenset(
    {
        "core.oauth.token_service:OAuthConnectionTokenService.get_token",
        "core.provider_access.connection_authority:_strategy_for",
        "core.provider_access.connection_facade:refresh_facade",
        "core.provider_access.profile_authorize:_strategy_for",
        "routes.auth:refresh_profile",
        "routes.oauth_connections:refresh_connection",
    }
)
# Thin builders the sites above and below go through.
BUILDERS = frozenset(
    {
        "core.provider_access.connection_locator:credential_strategy_for_connection",
        "routes.auth:_credential_strategy_for_app",
        "routes.auth:_credential_strategy_for_credential_name",
    }
)
# Sites that only persist, delete or read an address — they never call a refresh.
NO_REFRESH = frozenset(
    {
        "core.provider_access.connection_admin:ConnectionBackedCredentialAdmin.delete",
        "core.provider_access.connection_locator:credential_blob_address",
        "core.provider_access.connection_oauth:complete_connection_oauth",
        "core.provider_access.profile_admin:ProfileBackedCredentialAdmin._strategy",
        "routes.auth:_complete_oauth_for_app",
        "routes.auth:_persist_connection_credentials",
        "routes.oauth_connections:create_api_key_connection",
        "routes.oauth_connections:set_connection_api_key",
    }
)


def _aliases(tree: ast.Module, names: frozenset[str]) -> dict[str, str]:
    """`from x import factory as other` — the local name a module calls a factory or guard by."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in names and alias.asname:
                    found[alias.asname] = alias.name
    return found


def _called_names(fn: ast.AST, aliases: dict[str, str]) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(aliases.get(func.id, func.id))
            # WHY: `getattr(plugin, "oauth_strategy_for")(...)` builds without naming the call.
            if func.id == "getattr" and len(node.args) >= 2:
                attr = node.args[1]
                if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                    names.add(attr.value)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _functions(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Every function with its class-qualified name, so two `_strategy_for` never collide."""
    found: list[tuple[str, ast.AST]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                found.append((f"{prefix}{child.name}", child))
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def _strategy_build_sites() -> dict[str, set[str]]:
    sites: dict[str, set[str]] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        rel = path.relative_to(SOURCE).as_posix()
        if rel.startswith(("plugins/", "core/plugin_base/")):
            continue
        module = rel.removesuffix(".py").replace("/", ".")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _aliases(tree, FACTORIES | GUARDS)
        for name, node in _functions(tree):
            called = _called_names(node, aliases)
            if called & FACTORIES:
                sites[f"{module}:{name}"] = called
    return sites


def test_every_strategy_build_site_is_classified() -> None:
    sites = set(_strategy_build_sites())

    unclassified = sites - REFRESHING - BUILDERS - NO_REFRESH
    stale = (REFRESHING | BUILDERS | NO_REFRESH) - sites

    assert not unclassified, (
        f"new strategy build site(s) {sorted(unclassified)}: bind `guard_refresh` if the strategy "
        "can refresh (and list it in REFRESHING), otherwise list it in NO_REFRESH"
    )
    assert not stale, f"inventory lists sites that no longer build a strategy: {sorted(stale)}"


def test_every_refreshing_site_binds_the_owner_guard() -> None:
    sites = _strategy_build_sites()

    unguarded = sorted(site for site in REFRESHING if not sites.get(site, set()) & GUARDS)

    assert not unguarded, f"refreshing site(s) build a strategy without the guard: {unguarded}"


def test_no_refresh_site_calls_a_refresh() -> None:
    # INVARIANT: a NO_REFRESH site that started refreshing would publish unguarded.
    sites = _strategy_build_sites()
    refresh_calls = {
        "refresh",
        "refresh_credentials",
        "get_authorization_header",
        "get_token_with_expiry",
    }

    refreshing = sorted(site for site in NO_REFRESH if sites.get(site, set()) & refresh_calls)

    assert not refreshing, f"listed as NO_REFRESH but calls a refresh: {refreshing}"
