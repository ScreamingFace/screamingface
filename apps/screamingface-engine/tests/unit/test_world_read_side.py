"""F3 (prd/02): ``[data]``, ``[holdings]`` and ``[identities]`` become real.

# WHY this file exists. F3 widens the engine's declared world from models-only to url4's full
# read-side vocabulary (AC1, AC2). The engine deliberately does NOT re-implement provider
# semantics: it delegates to url4's own resolvers and registers the result on the SAME node
# that serves model routes, so url4 stays the single source of truth (prd/02 T5 refactor note).
#
# Two rejections are as load-bearing as the acceptances. A command-backed ``[data]`` provider is
# an exec surface with no sandbox on a network-reachable tier, so it is rejected at load with the
# path and kind named (AC3, T1) rather than skipped — a silently omitted mount is a production
# 404 with no explanation. ``[commands]`` stays rejected entirely, with a message that says the
# deferral is deliberate (AC4, T2).
#
# Under D8 every declared shelf is global to all callers of the sync surface. T7 (AC7) pins the
# startup log that makes that visibility visible rather than assumed.
"""

from __future__ import annotations

import logging
from typing import cast

import httpx
import pytest

from screamingface_engine.world.config import WorldConfig, WorldConfigError, parse_config
from screamingface_engine.world.factory import build_world
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.layer import FetchRequest, SupportsHoldings, fetch_result
from url4.peer.server import Url4Node

# A minimal declared aigateway world so the node that serves model routes exists. The F3 mounts
# register on THIS node, which is the whole point of "same node" in the PRD.
_AIGATEWAY = """
[aigateway]
default_route = "/m"
models = ["m"]
"""

_READ_SIDE = """
[data]
"/corpus" = { value = "hello corpus", media_type = "text/plain" }

[holdings]
default = { value = "global notes" }
science = { value = "science notes" }

[identities.alice]
default = { value = "alice default" }
"""


def _config(toml_text: str) -> WorldConfig:
    import tomllib

    return parse_config(tomllib.loads(toml_text), {}, registry=EMPTY_MODEL_WORLD)


async def _built_with(toml_text: str) -> tuple[Url4Node, object]:
    """Build the world from a TOML text, with a stub client (no network is touched)."""
    config = _config(toml_text)
    async with httpx.AsyncClient() as client:
        io, aclose = await build_world(env={}, config=config, client=client)
    assert isinstance(io, Url4Node), "the read-side mounts register on the aigateway node"
    return io, aclose


# --- T1: a command-backed [data] provider is rejected, not skipped --------------------------------


def test_command_backed_data_provider_is_rejected_naming_the_path_and_kind() -> None:
    with pytest.raises(WorldConfigError) as excinfo:
        _config(_AIGATEWAY + '\n[data]\n"/corpus" = { command = ["cat", "/etc/passwd"] }\n')

    message = str(excinfo.value)
    assert "/corpus" in message, message
    assert "command" in message, message


def test_command_backed_holdings_provider_is_rejected_naming_the_collection_and_kind() -> None:
    # R12 (test-plan §2): a `command` provider is an exec mount WHEREVER it is declared. The
    # shelf builders take the same ProviderSpec shape as `[data]`, and url4's `_provide` runs
    # `asyncio.create_subprocess_exec` for a command source regardless of the mount kind — so a
    # `[holdings]` command is the same unsandboxed subprocess on the same network-reachable node
    # tier. Reject it at load, naming the collection and kind, rather than at first read.
    with pytest.raises(WorldConfigError) as excinfo:
        _config(_AIGATEWAY + '\n[holdings]\nsecret = { command = ["cat", "/etc/shadow"] }\n')

    message = str(excinfo.value)
    assert "holdings" in message, message
    assert "secret" in message, message
    assert "command" in message, message


def test_command_backed_identity_shelf_provider_is_rejected_naming_the_collection_and_kind() -> (
    None
):
    # The identity shelf is the same exec surface one level deeper (identity -> collection); the
    # error must name BOTH so the operator knows which declaration to change.
    with pytest.raises(WorldConfigError) as excinfo:
        _config(
            _AIGATEWAY + '\n[identities.alice]\ndefault = { command = ["cat", "/etc/shadow"] }\n'
        )

    message = str(excinfo.value)
    assert "identities" in message, message
    assert "alice" in message, message
    assert "command" in message, message


# --- T2: [commands] stays rejected, and the message says why --------------------------------------


def test_commands_section_is_rejected_with_the_deferral_wording() -> None:
    with pytest.raises(WorldConfigError) as excinfo:
        _config(_AIGATEWAY + '\n[commands]\n"/run" = ["echo"]\n')

    message = str(excinfo.value).lower()
    assert "not supported" in message, message
    assert "deferred" in message, message


# --- T5: the three sections parse and resolve -----------------------------------------------------


def test_data_holdings_and_identities_parse_into_the_declared_world() -> None:
    config = _config(_AIGATEWAY + _READ_SIDE)

    assert set(config.data) == {"/corpus"}
    assert config.data["/corpus"].value == "hello corpus"
    assert config.data["/corpus"].media_type == "text/plain"
    assert config.holdings[None].value == "global notes"
    assert config.holdings["science"].value == "science notes"
    assert config.identities["alice"][None].value == "alice default"


@pytest.mark.asyncio
async def test_a_declared_data_route_is_a_mount_serving_its_content_and_media_type() -> None:
    io, aclose = await _built_with(_AIGATEWAY + _READ_SIDE)
    body = await io.fetch("/corpus", relative=True)
    result = await fetch_result(io, FetchRequest("/corpus", relative=True))
    if aclose is not None:
        await aclose()  # type: ignore[operator]

    assert body == "hello corpus"
    assert result.media_type == "text/plain"


@pytest.mark.asyncio
async def test_a_file_provider_is_read_per_request_so_edits_need_no_restart(
    tmp_path,
) -> None:
    path = tmp_path / "corpus.txt"
    path.write_text("from file", encoding="utf-8")
    io, aclose = await _built_with(_AIGATEWAY + f'\n[data]\n"/corpus" = {{ file = "{path}" }}\n')

    first = await io.fetch("/corpus", relative=True)
    path.write_text("edited", encoding="utf-8")
    second = await io.fetch("/corpus", relative=True)
    if aclose is not None:
        await aclose()  # type: ignore[operator]

    assert first == "from file"
    assert second == "edited"


@pytest.mark.asyncio
async def test_holdings_and_identity_shelves_resolve_and_unknown_identity_is_url4s_error() -> None:
    io, aclose = await _built_with(_AIGATEWAY + _READ_SIDE)
    holdings = cast(SupportsHoldings, io)

    default = await holdings.fetch_holdings(None, None)
    named = await holdings.fetch_holdings(None, "science")
    alice = await holdings.fetch_holdings("alice", None)
    with pytest.raises(ResolutionError) as excinfo:
        await holdings.fetch_holdings("nobody", None)
    if aclose is not None:
        await aclose()  # type: ignore[operator]

    assert default == "global notes"
    assert named == "science notes"
    assert alice == "alice default"
    assert excinfo.value.code == ErrorCode.UNKNOWN_IDENTITY


# --- T7: the declared shelves are logged, with the D8 visibility statement ------------------------


@pytest.mark.asyncio
async def test_declared_shelves_are_logged_with_their_global_visibility(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="screamingface_engine.world.factory"):
        _io, aclose = await _built_with(_AIGATEWAY + _READ_SIDE)
        if aclose is not None:
            await aclose()  # type: ignore[operator]

    text = caplog.text
    assert "science" in text, text
    assert "alice" in text, text
    assert "EVERY caller of the sync surface" in text, text


# --- FX-51: a read-side-only world (no [aigateway]) denies outbound and has a real teardown -------


@pytest.mark.asyncio
async def test_a_read_side_only_world_denies_outbound_and_returns_the_nodes_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``[data]``-only declaration has no ``[aigateway]`` table, so nothing here may reach an
    absolute URL — a lazily-created httpx adapter (``Url4Node``'s default when ``outbound`` is
    omitted) would silently ALLOW that (FX-51).

    WHY both checks: an ``example.invalid`` fetch fails DNS even through a real adapter, so a bare
    ``ResolutionError`` passed with the fix reverted (B3 review R1). The refusal must be the
    ``StaticIOLayer``'s own, and url4's owned-adapter factory must never be reached.

    The teardown is ``node.aclose`` (not ``None``) so this world has the shape every other world
    has; it closes only an adapter url4 OWNS, so with the injected ``StaticIOLayer`` it closes
    nothing — the ``StaticIOLayer`` is what removes the outbound path, not the teardown (R3).
    """
    import url4.peer._owned as owned

    built: list[object] = []

    def _no_owned_adapter() -> object:
        built.append(object())
        raise AssertionError("url4 built its own http adapter for a read-side-only world")

    monkeypatch.setattr(owned, "_http_io", _no_owned_adapter)
    config = _config('[data]\n"/corpus" = { value = "hello corpus" }\n')
    io, aclose = await build_world(env={}, config=config)

    with pytest.raises(ResolutionError, match="no fetch mapping"):
        await io.fetch("https://example.invalid/", relative=False)

    assert built == []
    assert aclose is not None
    await aclose()  # the node's own aclose; must not raise


# --- FX-58: `file` providers for holdings/identities, and the identity->default fallback ----------


@pytest.mark.asyncio
async def test_a_file_provider_is_read_per_request_for_a_holdings_shelf(tmp_path) -> None:
    path = tmp_path / "shelf.txt"
    path.write_text("from file", encoding="utf-8")
    io, aclose = await _built_with(_AIGATEWAY + f'\n[holdings]\ndefault = {{ file = "{path}" }}\n')
    holdings = cast(SupportsHoldings, io)

    first = await holdings.fetch_holdings(None, None)
    path.write_text("edited", encoding="utf-8")
    second = await holdings.fetch_holdings(None, None)
    if aclose is not None:
        await aclose()  # type: ignore[operator]

    assert first == "from file"
    assert second == "edited"


@pytest.mark.asyncio
async def test_a_file_provider_is_read_per_request_for_an_identity_shelf(tmp_path) -> None:
    path = tmp_path / "alice.txt"
    path.write_text("alice from file", encoding="utf-8")
    io, aclose = await _built_with(
        _AIGATEWAY + f'\n[identities.alice]\ndefault = {{ file = "{path}" }}\n'
    )
    holdings = cast(SupportsHoldings, io)

    first = await holdings.fetch_holdings("alice", None)
    path.write_text("alice edited", encoding="utf-8")
    second = await holdings.fetch_holdings("alice", None)
    if aclose is not None:
        await aclose()  # type: ignore[operator]

    assert first == "alice from file"
    assert second == "alice edited"


@pytest.mark.asyncio
async def test_an_identity_falls_back_to_its_own_default_for_an_undeclared_collection() -> None:
    """``alice`` declares only her ``default`` shelf. A request for a collection she never
    declared (``science``) falls back to HER default, not a global one and not an error — url4's
    exact-then-default rule (``resolve_shelf``), which ``make_identity_handler`` applies (FX-58).

    A GLOBAL ``[holdings]`` default is declared too (B3 review R10), so the test can tell "her
    own default" from "some default": the global one must lose."""

    io, aclose = await _built_with(
        _AIGATEWAY
        + '\n[holdings]\ndefault = { value = "global default" }\n'
        + '\n[identities.alice]\ndefault = { value = "alice default" }\n'
    )
    holdings = cast(SupportsHoldings, io)

    result = await holdings.fetch_holdings("alice", "science")
    if aclose is not None:
        await aclose()  # type: ignore[operator]

    assert result == "alice default"


# --- B3 review R2: a data route that collides with a benchmark endpoint is a config error -------


@pytest.mark.asyncio
async def test_a_data_route_at_a_benchmark_endpoint_is_a_world_config_error() -> None:
    """``/benchmarks/candidate`` is registered by the benchmark install, AFTER the read-side
    mounts. url4 refuses the duplicate with a raw ``ValueError``; the factory must name it as the
    engine's ``WorldConfigError``, like every other registration failure."""
    from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS

    config = _config(_AIGATEWAY + '\n[data]\n"/benchmarks/candidate" = { value = "shadow" }\n')
    async with httpx.AsyncClient() as client:
        with pytest.raises(WorldConfigError) as excinfo:
            await build_world(env={}, config=config, client=client, benchmarks=BUILTIN_BENCHMARKS)

    assert "/benchmarks/candidate" in str(excinfo.value)


# --- B3 review R5: the kind named in the refusal is the kind declared ---------------------------


def test_the_provider_refusal_lists_the_allowed_kinds() -> None:
    from screamingface_engine.world.config import ALLOWED_PROVIDER_KINDS

    with pytest.raises(WorldConfigError) as excinfo:
        _config(_AIGATEWAY + '\n[data]\n"/corpus" = { command = ["cat", "/etc/passwd"] }\n')

    message = str(excinfo.value)
    for kind in ALLOWED_PROVIDER_KINDS:
        assert repr(kind) in message, message


def test_a_provider_with_no_source_is_not_called_a_command() -> None:
    """Only a declared ``command`` is a command. A spec with no source at all (url4's parser never
    builds one today) must be refused under its own name, not mislabelled as an exec mount."""
    from screamingface_engine.world.config import _reject_disallowed_read_side_providers
    from url4.cli._config import ProviderSpec

    with pytest.raises(WorldConfigError) as excinfo:
        _reject_disallowed_read_side_providers({"/empty": ProviderSpec()}, {}, {})

    message = str(excinfo.value)
    assert "'/empty' ('unknown')" in message, message
    assert "'command'" not in message, message


def test_the_exec_mount_sentence_is_said_only_for_a_command_offender() -> None:
    """item 7 (B6 review): an ``unknown``-kind offender is not a command, so the message must not
    claim it is an exec mount either — only a genuine ``command`` offender gets that sentence."""
    from screamingface_engine.world.config import _reject_disallowed_read_side_providers
    from url4.cli._config import ProviderSpec

    with pytest.raises(WorldConfigError) as excinfo:
        _reject_disallowed_read_side_providers({"/empty": ProviderSpec()}, {}, {})

    assert "exec mount" not in str(excinfo.value), str(excinfo.value)

    with pytest.raises(WorldConfigError) as excinfo:
        _reject_disallowed_read_side_providers(
            {"/corpus": ProviderSpec(command=("cat", "/etc/passwd"))}, {}, {}
        )

    assert "exec mount with no sandbox" in str(excinfo.value)
