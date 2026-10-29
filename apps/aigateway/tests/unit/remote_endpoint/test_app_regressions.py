"""What configured endpoints must NOT change: the unconfigured app and the layers.

# FEATURE: hosted BYOM Unit 0 — configured endpoints are additive. With no config the gateway is
# today's gateway; with a config, bundled providers, their auth routes and the provider listing
# are unchanged.
# INVARIANT: `core/` never imports a plugin; only the top-level composition names the adapter.

Retired at OME-1138 Stage E, E5c: `test_the_legacy_backfill_leaves_endpoint_pairs_untouched`
— the `migrate_profiles` backfill it ran is gone; successor: the import guard in
test_profile_index_offline_only.py.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

import aigateway
from aigateway.core.endpoint_access import PERMIT_ALL
from aigateway.core.loader import load_plugins
from aigateway.core.registry import ProviderRegistry

from .conftest import Harness, tenant_headers
from .fixtures import ACCOUNT_A, ENDPOINT_A, ENDPOINT_B, two_endpoint_document

_SRC = Path(inspect.getfile(aigateway)).resolve().parent
_ADAPTER = "aigateway.plugins.remote_endpoint"


def _bundled_ids() -> list[str]:
    registry = ProviderRegistry()
    load_plugins(registry)
    return sorted(p.custom_llm_provider for p in registry.all())


def _surface(client: TestClient) -> tuple[list[str], list[str], object]:
    """Registered provider IDs, mounted paths and the provider listing an account sees."""
    app = cast(FastAPI, client.app)
    ids = sorted(p.custom_llm_provider for p in app.state.providers.all())
    paths = sorted({getattr(route, "path", "") for route in app.routes})
    listing = client.get("/v1/providers", headers=tenant_headers(ACCOUNT_A))
    assert listing.status_code == 200, listing.text
    return ids, paths, listing.json()


def test_without_config_the_app_is_the_bundled_app(byom: Harness) -> None:
    with byom.start(None) as client:
        ids, paths, listing = _surface(client)
        assert cast(FastAPI, client.app).state.endpoint_access is PERMIT_ALL

    assert ids == _bundled_ids()
    with byom.start(two_endpoint_document()) as client:
        configured_ids, configured_paths, configured_listing = _surface(client)

    # INVARIANT: endpoints join the registry and nothing else — no auth route, no listing row.
    assert configured_ids == sorted([*ids, ENDPOINT_A, ENDPOINT_B])
    assert configured_paths == paths
    assert configured_listing == listing
    assert all(
        f"/v1/auth/{endpoint}" not in " ".join(paths) for endpoint in (ENDPOINT_A, ENDPOINT_B)
    )


# --- the layer boundary --------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    """Absolute names of every module `path` imports, relative imports resolved."""
    package = ".".join(("aigateway", *path.relative_to(_SRC).parent.parts))
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*parent, base]) if base else ".".join(parent)
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _sources(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_core_never_imports_a_plugin() -> None:
    offenders = {
        str(path.relative_to(_SRC)): sorted(
            n for n in _imported_modules(path) if n.startswith("aigateway.plugins")
        )
        for path in _sources(_SRC / "core")
    }

    assert {path: names for path, names in offenders.items() if names} == {}


def test_only_the_top_level_composition_names_the_adapter() -> None:
    adapter_dir = _SRC / "plugins" / "remote_endpoint"
    importers = sorted(
        str(path.relative_to(_SRC))
        for path in _sources(_SRC)
        if adapter_dir not in path.parents
        and any(n.startswith(_ADAPTER) for n in _imported_modules(path))
    )

    assert importers == ["provider_composition.py"]
