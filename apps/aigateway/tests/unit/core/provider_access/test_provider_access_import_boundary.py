"""The import boundary A2 establishes (OME-1207): who may name a legacy Profile row.

# FEATURE: OME-1138 — deprecate Profiles and converge on Connections. A2 moved chat, model
# parameters, admission and dispatch-failure marking onto `core/provider_access`; this test is
# what keeps them there, and what stops a NEW module from reaching around the port.
# INVARIANT: outside the owners listed in `_OWNERS`, no module under `src/aigateway/` imports
# `Profile`, `ProfileState`, `ProfileIndexStore` or `OAuthConnection`. Everything else those
# legacy modules export — `AuthMode`, `AuthType`, `ProfileDefaults`, `credential_name_for` — is
# core vocabulary the port itself re-exports, so it is deliberately NOT banned.
# AIDEV-NOTE: this checks the SOURCE, not runtime behaviour. A module that imports the row lazily
# inside a function is still a direct dependency, and the AST walk sees it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import aigateway

_SRC = Path(inspect.getfile(aigateway)).resolve().parent

# The legacy row, its state enum, its index store and the Connection row. Naming any of these
# outside an owner is the coupling A2 removed.
_BANNED = frozenset({"Profile", "ProfileState", "ProfileIndexStore", "OAuthConnection"})

# WHY an allow-list keyed by path, with a reason each: every entry is a promise about WHEN it
# goes away, so the boundary cannot quietly widen. Paths are relative to `src/aigateway/`.
_OWNERS: dict[str, str] = {
    # The boundary itself and the legacy modules it adapts — these ARE the compatibility window.
    "core/provider_access/": "the port and its Profile-backed implementation; Stage B swaps it",
    "core/profile_models.py": "the legacy row and its value types",
    "core/profile_index.py": "the legacy index store",
    "core/oauth/": "the Connection row, its store and the OAuth flows",
    # Management surfaces reduced to shells at A3 and retired at Stage E (OME-1209).
    "routes/auth.py": "legacy Profile management routes; shells at A3, retired at Stage E",
    "routes/admin.py": "tenant admin listing; moves onto the admin port at A3",
    "routes/oauth_connections.py": "Connection-native management routes; owner of that row",
    "core/admin_schemas.py": (
        "the legacy admin listing's WIRE schema — `AdminProfileOut.state` is `ProfileState`, so "
        "changing it would change OpenAPI; moves onto the admin port at A3 with `routes/admin.py`"
    ),
    "routes/chat_credentials.py": (
        "A1 re-export shim, still imported by the A1 shim suite; deleted at Stage E with the "
        "legacy names (OME-1209)"
    ),
    # Wiring and bootstrap: they CONSTRUCT the store, they do not resolve credentials with it.
    "main.py": "builds `app.state.profile_index` at startup; moves with the backing at Stage B",
    "core/plugin_base/": "the provider contract's own type surface",
    "plugins/anthropic_provider/bootstrap.py": (
        "seeds a Profile for the bundled Anthropic credential; migrates with the backing at Stage B"
    ),
    "plugins/anthropic_provider/plugin.py": (
        "calls its own bootstrap with an injected index store; same removal point as the "
        "bootstrap above"
    ),
    "migrations/": "schema history — the rows as they were when each migration ran",
}

# The four consumers this unit migrated. Listed explicitly so the test fails loudly if one is
# renamed away rather than silently covering nothing.
_MIGRATED = (
    "routes/chat.py",
    "routes/model_parameters.py",
    "routes/model_admission.py",
    "routes/chat_dispatch.py",
)


def _is_owner(relative: str) -> bool:
    return (
        any(
            relative == owner or relative.startswith(owner)
            for owner in _OWNERS
            if owner.endswith("/")
        )
        or relative in _OWNERS
    )


def _banned_imports(path: Path) -> list[str]:
    """Every banned name this module imports, however it spells the import."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.extend(alias.name for alias in node.names if alias.name in _BANNED)
        elif isinstance(node, ast.Import):
            # `import aigateway.core.profile_index as ...` reaches the store just as directly.
            found.extend(
                alias.name
                for alias in node.names
                if alias.name.endswith((".profile_index", ".oauth.models"))
            )
    return sorted(set(found))


def _modules() -> list[Path]:
    return sorted(path for path in _SRC.rglob("*.py") if path.is_file())


def test_the_source_tree_is_actually_being_scanned() -> None:
    # WHY: every assertion below is vacuously true over an empty walk.
    assert len(_modules()) > 100


@pytest.mark.parametrize("relative", _MIGRATED)
def test_a_migrated_consumer_names_no_legacy_profile_row(relative: str) -> None:
    """The A2 acceptance itself: these four ask the port, never the store."""
    path = _SRC / relative
    assert path.is_file(), f"{relative} moved — re-point this boundary test at its new home"

    assert _banned_imports(path) == []


def test_no_module_outside_the_documented_owners_imports_a_legacy_profile_row() -> None:
    """The boundary, repo-wide: a NEW consumer cannot reach around the port either."""
    offenders = {
        str(path.relative_to(_SRC)): _banned_imports(path)
        for path in _modules()
        if not _is_owner(str(path.relative_to(_SRC)))
    }

    assert {name: names for name, names in offenders.items() if names} == {}


def test_every_owner_exemption_names_a_real_file_and_a_reason() -> None:
    """An allow-list entry that no longer matches anything is a stale promise — delete it."""
    for owner, reason in _OWNERS.items():
        assert reason.strip(), f"{owner} is exempted without a reason"
        assert (_SRC / owner).exists(), f"{owner} no longer exists — drop its exemption"
