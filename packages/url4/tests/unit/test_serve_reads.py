"""Read-side registries for `url4 serve` (url4._serve): reads.data/holdings/identities.

STORY: as an operator I declare my node's read surface in url4.json alongside my
`routes.commands`: `reads.data` routes serve plain reads (so bare relative URIs
resolve), `reads.holdings` backs `@`, and `reads.identities.<name>` backs `@name` — each
from an inline value, a live-read file, or an operator-owned command (doctrine N4 for
reads). Bad declarations fail before bind; missing shelves fail per-source with the
node's own error semantics.

PORTED FROM url4.json (OME-1183). Only the declaration half of this module changed: the
helper now takes a dict, the three registries moved under `reads`, and argv is an array.
Everything below "resolution behavior through the node" builds a ServeConfig directly and
is copied verbatim — it never saw a config file.
"""

from __future__ import annotations

import json

import pytest

from url4.cli._serve import ConfigError, ProviderSpec, ServeConfig, build_node, resolve
from url4.core.errors import ResolutionError

CMDS = {"/echo": ("cat",)}


def _resolve(tmp_path, payload: dict):
    """Merge the payload over a minimal valid node and resolve it.

    Takes a dict rather than file text: JSON fixtures are data, so a test declares the
    shape it means instead of a string that has to parse first.
    """
    path = tmp_path / "url4.json"
    path.write_text(json.dumps({**BASE, **payload}), encoding="utf-8")
    return resolve({}, {}, path)


BASE = {"routes": {"commands": {"/echo": ["cat"]}}}


# --- parsing -----------------------------------------------------------------------


def test_provider_forms_parse(tmp_path) -> None:
    config = _resolve(
        tmp_path,
        {
            "reads": {
                "data": {
                    "/inline": "plain text",
                    "/object": {"value": "objected"},
                    "/filed": {"file": "corpus.md", "media_type": "text/markdown"},
                    "/gen": {"command": ["printf", "x"]},
                }
            }
        },
    )
    assert config.data["/inline"] == ProviderSpec(value="plain text")
    assert config.data["/object"] == ProviderSpec(value="objected")
    assert config.data["/filed"] == ProviderSpec(file="corpus.md", media_type="text/markdown")
    assert config.data["/gen"] == ProviderSpec(command=("printf", "x"))


def test_holdings_default_key_normalizes_to_none(tmp_path) -> None:
    config = _resolve(
        tmp_path, {"reads": {"holdings": {"default": "MINE", "science": {"value": "SCI"}}}}
    )
    assert config.holdings[None] == ProviderSpec(value="MINE")
    assert config.holdings["science"] == ProviderSpec(value="SCI")


def test_identities_parse_nested_shelves(tmp_path) -> None:
    config = _resolve(
        tmp_path,
        {
            "reads": {
                "identities": {"emily": {"default": "E-DEFAULT", "notes": {"value": "E-NOTES"}}}
            }
        },
    )
    assert config.identities["emily"][None] == ProviderSpec(value="E-DEFAULT")
    assert config.identities["emily"]["notes"] == ProviderSpec(value="E-NOTES")


# --- declaration errors (fail before bind) -----------------------------------------


@pytest.mark.parametrize(
    ("reads", "match"),
    [
        ({"data": {"/x": {}}}, "exactly one of value/file/command"),
        ({"data": {"/x": {"value": "a", "file": "b"}}}, "exactly one of value/file/command"),
        ({"data": {"/x": 5}}, "must be a string or an object"),
        ({"data": {"/x": {"value": "a", "nope": 1}}}, "unknown keys"),
        ({"data": {"/x": {"command": []}}}, "has an empty command argv"),
        ({"holdings": {"science": {"value": "a", "media_type": "text/csv"}}}, "unknown keys"),
        ({"identities": {"emily": {"": "x"}}}, "collection name cannot be empty"),
    ],
)
def test_bad_provider_declarations(tmp_path, reads: dict, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _resolve(tmp_path, {"reads": reads})


@pytest.mark.parametrize(
    ("reads", "match"),
    [
        ({"data": "not-an-object"}, "reads.data must be an object"),
        ({"holdings": "not-an-object"}, "reads.holdings must be an object"),
        ({"identities": "not-an-object"}, "reads.identities must be an object"),
    ],
)
def test_registry_declared_as_scalar_is_rejected(tmp_path, reads: dict, match: str) -> None:
    # A registry key written as a scalar instead of an object is a plausible typo; it
    # must fail as a clean pre-bind ConfigError.
    #
    # The TOML version of this test had to place the scalar BEFORE [commands], because a
    # bare key after a table header would have belonged to that table rather than the
    # document root. JSON has no such ordering hazard, so the constraint is gone and the
    # fixture simply says what it means.
    with pytest.raises(ConfigError, match=match):
        _resolve(tmp_path, {"reads": reads})


def test_identity_declared_as_scalar_is_rejected(tmp_path) -> None:
    with pytest.raises(ConfigError, match="reads.identities.emily must be an object"):
        _resolve(tmp_path, {"reads": {"identities": {"emily": "not-an-object"}}})


def test_read_command_argv_string_form_is_rejected(tmp_path) -> None:
    """The argv rule is the same on the read side as on the command side — a provider's
    `command` is doctrine N4 applied to reads, so it gets the same array-only treatment
    and the same paste-ready error."""
    with pytest.raises(ConfigError) as exc:
        _resolve(tmp_path, {"reads": {"data": {"/x": {"command": "printf x"}}}})
    assert '["printf", "x"]' in str(exc.value)


def test_validate_rejects_clashing_and_invalid_paths() -> None:
    spec = ProviderSpec(value="x")
    with pytest.raises(ConfigError, match="data path 'nope'"):
        ServeConfig(commands=CMDS, data={"nope": spec}).validate()
    with pytest.raises(ConfigError, match="clash with command routes"):
        ServeConfig(commands=CMDS, data={"/echo": spec}).validate()
    with pytest.raises(ConfigError, match="clash with reserved"):
        ServeConfig(commands=CMDS, data={"/healthz": spec}).validate()
    with pytest.raises(ConfigError, match="identity name '9bad!'"):
        ServeConfig(commands=CMDS, identities={"9bad!": {None: spec}}).validate()


# --- resolution behavior through the node ------------------------------------------

pytestmark_async = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_data_route_serves_bare_relative_uri() -> None:
    config = ServeConfig(commands=CMDS, data={"/rubrics/42": ProviderSpec(value="RUBRIC-42")})
    node = build_node(config)
    result = await node.evaluate("(/rubrics/42)!''")
    assert "RUBRIC-42" in result.text


@pytest.mark.asyncio
async def test_file_provider_reads_live(tmp_path) -> None:
    corpus = tmp_path / "corpus.md"
    corpus.write_text("FIRST", encoding="utf-8")
    config = ServeConfig(commands=CMDS, data={"/corpus": ProviderSpec(file=str(corpus))})
    node = build_node(config)
    assert "FIRST" in (await node.evaluate("(/corpus)!''")).text
    corpus.write_text("SECOND", encoding="utf-8")  # live: no rebuild, no restart
    assert "SECOND" in (await node.evaluate("(/corpus)!''")).text


@pytest.mark.asyncio
async def test_file_provider_missing_file_is_resolution_error(tmp_path) -> None:
    config = ServeConfig(
        commands=CMDS, data={"/gone": ProviderSpec(file=str(tmp_path / "missing.md"))}
    )
    node = build_node(config)
    with pytest.raises(ResolutionError, match="cannot be read"):
        await node.evaluate("(/gone)!''")


@pytest.mark.asyncio
async def test_media_type_drives_collection_parsing() -> None:
    # A one-line JSON array served as text/plain would line-split into ONE
    # element; the declared media type makes it parse as three (spec §5.3.7).
    rows = '[{"n": "a"}, {"n": "b"}, {"n": "c"}]'
    config = ServeConfig(
        commands=CMDS,
        data={"/rows": ProviderSpec(value=rows, media_type="application/json")},
    )
    node = build_node(config)
    result = await node.evaluate("/rows*(x=$item.n, /echo(got: $item.n)!'noop')!''")
    assert result.text.count("got:") == 3


@pytest.mark.asyncio
async def test_self_holdings_default_and_scoped_shelves() -> None:
    config = ServeConfig(
        commands=CMDS,
        holdings={None: ProviderSpec(value="DEFAULT-SHELF"), "sci": ProviderSpec(value="SCI")},
    )
    node = build_node(config)
    assert await node.fetch_holdings(None, None) == "DEFAULT-SHELF"
    assert await node.fetch_holdings(None, "sci") == "SCI"
    # Undeclared collection falls back to the default shelf (node semantics).
    assert await node.fetch_holdings(None, "other") == "DEFAULT-SHELF"


@pytest.mark.asyncio
async def test_identity_shelves_mirror_self_holdings_fallback() -> None:
    config = ServeConfig(
        commands=CMDS,
        identities={
            "emily": {None: ProviderSpec(value="E-DEF"), "notes": ProviderSpec(value="E-NOTES")},
            "andrew": {"published": ProviderSpec(value="A-PUB")},
        },
    )
    node = build_node(config)
    assert await node.fetch_holdings("emily", "notes") == "E-NOTES"
    assert await node.fetch_holdings("emily", "drafts") == "E-DEF"  # default fallback
    assert await node.fetch_holdings("andrew", "published") == "A-PUB"
    with pytest.raises(ResolutionError, match="serves no holdings"):
        await node.fetch_holdings("andrew", "private")  # no default shelf declared
    with pytest.raises(ResolutionError, match="unknown identity"):
        await node.fetch_holdings("nobody", None)  # node's own error, untouched


@pytest.mark.asyncio
async def test_command_provider_receives_collection_substitution() -> None:
    argv = ("python3", "-c", "import sys; sys.stdout.write('shelf=' + sys.argv[1])", "{collection}")
    config = ServeConfig(commands=CMDS, holdings={None: ProviderSpec(command=argv)})
    node = build_node(config)
    assert await node.fetch_holdings(None, "science") == "shelf=science"
    assert await node.fetch_holdings(None, None) == "shelf="


@pytest.mark.asyncio
async def test_holdings_resolve_through_expressions() -> None:
    # End-to-end: `@` and `@emily/notes` inside expressions, through the engine.
    config = ServeConfig(
        commands=CMDS,
        holdings={None: ProviderSpec(value="NODE-CORPUS")},
        identities={"emily": {"notes": ProviderSpec(value="EMILY-NOTES")}},
    )
    node = build_node(config)
    result = await node.evaluate("(@, @emily/notes)!'compare'")
    assert "NODE-CORPUS" in result.text
    assert "EMILY-NOTES" in result.text
