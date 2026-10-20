"""The Profile-backed reader is gone (OME-1209, Stage E, E4a; spec §9 Q8).

# FEATURE: Stage E plan §3 E4a — the Connection-backed port is the only `ProviderAccess`; the
# Profile-backed parent, its Profile-target authorize and refresh branches and the row-11 shadow
# proof are deleted, so nothing on the read path can hand a Profile document back as authority.
# INVARIANT: a quarantined pair's refusal renders the D18 pair body on every route, so chat, model
# parameters and the successor admin API agree on one code.
# WHY a test of absence: the behaviour suites prove no read consults the index; this pins that the
# machinery that did cannot be imported back by accident.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from aigateway.core import provider_access
from aigateway.core.provider_access import (
    ConnectionBackedProviderAccess,
    PairConflict,
    PairNotManageable,
    provider_access_for,
    refresh_guard,
)
from aigateway.routes.provider_access_http import (
    pair_conflict_detail,
    render_refusal,
    render_successor_refusal,
)


@pytest.mark.parametrize(
    "module",
    ["aigateway.core.provider_access.profile_backed", "aigateway.core.provider_access.pair_shadow"],
)
def test_the_profile_reader_modules_no_longer_import(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


@pytest.mark.parametrize(
    "name", ["ProfileBackedProviderAccess", "ProfileRefreshOwner", "mark_profile_error_fresh"]
)
def test_the_provider_access_package_exports_no_profile_reader(name: str) -> None:
    assert not hasattr(provider_access, name)
    assert name not in provider_access.__all__


def test_a_refresh_is_owned_by_a_connection_only() -> None:
    assert not hasattr(refresh_guard, "ProfileRefreshOwner")
    assert refresh_guard.RefreshOwner is refresh_guard.ConnectionRefreshOwner


def test_the_connection_backed_port_has_no_parent_implementation() -> None:
    assert ConnectionBackedProviderAccess.__mro__[1:] == (object,)


def test_provider_access_for_fills_an_absent_slot_with_the_connection_backed_port() -> None:
    app = SimpleNamespace(state=SimpleNamespace())

    access = provider_access_for(app)

    assert isinstance(access, ConnectionBackedProviderAccess)
    assert app.state.provider_access is access
    assert provider_access_for(app) is access


def test_a_quarantined_pair_renders_one_body_on_the_legacy_and_successor_routes() -> None:
    refusal = PairNotManageable("anthropic", "unresolved")

    legacy = render_refusal(refusal)
    successor = render_successor_refusal(refusal)

    assert (legacy.status_code, successor.status_code) == (409, 409)
    expected = pair_conflict_detail(PairConflict("anthropic", "unresolved"))
    assert legacy.detail == successor.detail == expected
