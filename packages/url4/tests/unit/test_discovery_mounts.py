"""The mount table and the three `.well-known` documents (url4.discovery).

STORY: as a client I hardcode ONE url4 URL — the node's `/.well-known/url4-capabilities` —
and everything else is named inside it: which processors are mounted, where each one's
schema lives, and whether it is currently offered. As a node operator I declare that in
`url4.json`'s `mounts`, and a mount whose endpoint is down degrades to `unavailable`
rather than taking discovery down with it.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from url4.cli._serve import ConfigError, ServeConfig, build_asgi_app, build_node
from url4.discovery import (
    CAPABILITIES_PATH,
    CONFIG_PATH,
    POLICY_PATH,
    Discovery,
    Status,
)
from url4.discovery.resolver import MountTableError, TableResolver, read_mount_table

CMDS = {"/echo": ("cat",)}


# --- reading the table ------------------------------------------------------------


def test_absent_table_is_no_mounts() -> None:
    assert read_mount_table(None) == ()
    assert read_mount_table({}) == ()


def test_a_composed_mount_takes_its_id_from_the_plugin_fqn() -> None:
    (spec,) = read_mount_table({"/gpt": {"plugin": "https://github.com/x/apps/node-codex"}})
    assert (spec.path, spec.endpoint_id, spec.composed) == ("/gpt", "node-codex", True)


@pytest.mark.parametrize(
    "fqn",
    [
        "https://github.com/x/apps/node-codex@v1.2.0",
        "https://github.com/x/apps/node-codex@feat/stream",
        "https://github.com/x/apps/node-codex@" + "a" * 40,
    ],
)
def test_the_ref_never_changes_the_announced_id(fqn: str) -> None:
    """Deriving the id from the ref would make one plugin announce a different id per
    deployment, and a client correlating two mounts of the same plugin would see two."""
    (spec,) = read_mount_table({"/gpt": {"plugin": fqn}})
    assert spec.endpoint_id == "node-codex"


def test_a_foreign_mount_is_named_by_upstream() -> None:
    (spec,) = read_mount_table({"/vendor": {"upstream": "https://vendor.example", "foreign": True}})
    assert spec.composed is False
    assert spec.upstream == "https://vendor.example"


def test_an_upstream_alone_is_foreign_without_saying_so() -> None:
    (spec,) = read_mount_table({"/vendor": {"upstream": "https://vendor.example"}})
    assert spec.composed is False


@pytest.mark.parametrize(
    ("key", "match"),
    [
        ("gpt", "single leading-slash segment"),
        ("/a/b", "single leading-slash segment"),
        ("/", "single leading-slash segment"),
    ],
)
def test_a_mount_key_must_be_one_public_segment(key: str, match: str) -> None:
    # Keys are PUBLIC PATHS — one segment is what makes a routing collision inexpressible.
    with pytest.raises(MountTableError, match=match):
        read_mount_table({key: {"plugin": "x/p"}})


def test_plugin_and_upstream_together_are_rejected() -> None:
    # A composed mount learns its address by launching; a foreign one is told it. Both
    # would leave "which address wins" undefined at fetch time.
    with pytest.raises(MountTableError, match="both `plugin` and `upstream`"):
        read_mount_table({"/x": {"plugin": "x/p", "upstream": "https://u.example"}})


def test_neither_plugin_nor_upstream_is_rejected() -> None:
    with pytest.raises(MountTableError, match="neither"):
        read_mount_table({"/x": {}})


def test_the_same_plugin_may_be_mounted_twice() -> None:
    """Two instances of one plugin at different paths is the design's own example
    (`/anthropic` and `/claude-fast`), so it must not read as a duplicate."""
    specs = read_mount_table(
        {
            "/anthropic": {"plugin": "x/node-anthropic"},
            "/claude-fast": {"plugin": "x/node-anthropic"},
        }
    )
    assert [s.path for s in specs] == ["/anthropic", "/claude-fast"]
    assert {s.endpoint_id for s in specs} == {"node-anthropic"}


# --- validation against the rest of the node --------------------------------------


def test_a_mount_may_not_shadow_a_command_or_data_route() -> None:
    (spec,) = read_mount_table({"/echo": {"plugin": "x/p"}})
    with pytest.raises(ConfigError, match="clash with declared routes"):
        ServeConfig(commands=CMDS, mounts=(spec,)).validate()


def test_a_mount_may_not_take_a_reserved_path() -> None:
    (spec,) = read_mount_table({"/healthz": {"plugin": "x/p"}})
    with pytest.raises(ConfigError, match="clash with reserved"):
        ServeConfig(commands=CMDS, mounts=(spec,)).validate()


# --- resolving: the probe ---------------------------------------------------------

CARD_OK = json.dumps(
    {
        "url4_version": 1,
        "node": "url4://e.example",
        "status": "ok",
        "config_schema": CONFIG_PATH,
        "intent_processors": [],
    }
)
SCHEMA = json.dumps({"$id": "url4-config", "type": "object", "properties": {}})


def _resolver(responses: dict[str, str], specs):
    async def fetch(url: str) -> str:
        try:
            return responses[url]
        except KeyError:
            raise OSError(f"unreachable: {url}") from None

    return TableResolver(specs, fetch, base_url="http://node.example")


def _run(coro):
    return asyncio.run(coro)


def test_a_healthy_composed_mount_carries_its_served_schema() -> None:
    specs = read_mount_table({"/gpt": {"plugin": "x/node-codex"}})
    resolver = _resolver(
        {
            f"http://node.example/gpt{CAPABILITIES_PATH}": CARD_OK,
            f"http://node.example/gpt{CONFIG_PATH}": SCHEMA,
        },
        specs,
    )
    (mount,) = _run(resolver(None))
    assert mount.status is Status.OK
    assert mount.served_schema == json.loads(SCHEMA)


def test_an_unreachable_endpoint_degrades_to_unavailable() -> None:
    """Discovery that 500s because one endpoint is down tells a client nothing about the
    others. A failed probe is data, not an error."""
    specs = read_mount_table({"/gpt": {"plugin": "x/node-codex"}})
    (mount,) = _run(_resolver({}, specs)(None))
    assert mount.status is Status.UNAVAILABLE
    assert mount.served_schema is None


def test_a_card_that_says_degraded_fails_the_probe() -> None:
    bad = json.dumps(
        {
            "url4_version": 1,
            "node": "url4://e",
            "status": "degraded",
            "config_schema": CONFIG_PATH,
            "intent_processors": [],
        }
    )
    specs = read_mount_table({"/gpt": {"plugin": "x/node-codex"}})
    resolver = _resolver(
        {
            f"http://node.example/gpt{CAPABILITIES_PATH}": bad,
            f"http://node.example/gpt{CONFIG_PATH}": SCHEMA,
        },
        specs,
    )
    (mount,) = _run(resolver(None))
    assert mount.status is Status.UNAVAILABLE


def test_an_unparseable_card_fails_the_probe_rather_than_raising() -> None:
    specs = read_mount_table({"/gpt": {"plugin": "x/node-codex"}})
    resolver = _resolver({f"http://node.example/gpt{CAPABILITIES_PATH}": "not json"}, specs)
    (mount,) = _run(resolver(None))
    assert mount.status is Status.UNAVAILABLE


def test_a_foreign_mount_is_announced_without_a_schema_and_never_fetched() -> None:
    """The node did not compose it, so it cannot vouch for what the endpoint serves — but
    a client still needs to know the path exists."""
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        fetched.append(url)
        return CARD_OK

    specs = read_mount_table({"/vendor": {"upstream": "https://v.example"}})
    (mount,) = _run(TableResolver(specs, fetch, base_url="http://node.example")(None))
    assert mount.status is Status.UNAVAILABLE
    assert fetched == []


def test_one_dead_mount_does_not_hide_a_live_one() -> None:
    specs = read_mount_table(
        {"/gpt": {"plugin": "x/node-codex"}, "/dead": {"plugin": "x/node-gone"}}
    )
    resolver = _resolver(
        {
            f"http://node.example/gpt{CAPABILITIES_PATH}": CARD_OK,
            f"http://node.example/gpt{CONFIG_PATH}": SCHEMA,
        },
        specs,
    )
    by_path = {m.path: m for m in _run(resolver(None))}
    assert by_path["/gpt"].status is Status.OK
    assert by_path["/dead"].status is Status.UNAVAILABLE


# --- the served surface -----------------------------------------------------------


def _app(mounts_table: dict, responses: dict):
    """A node with a mount table, served through the real ASGI wrapper."""
    specs = read_mount_table(mounts_table)
    config = ServeConfig(commands=CMDS, mounts=specs)
    config.validate()
    discovery = Discovery("http://node.example", _resolver(responses, specs))
    return build_asgi_app(build_node(config), config, discovery=discovery)


def _get(app, path: str, *, method: str = "GET", headers: list | None = None):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "headers": headers or []}
    _run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


LIVE = {
    f"http://node.example/gpt{CAPABILITIES_PATH}": CARD_OK,
    f"http://node.example/gpt{CONFIG_PATH}": SCHEMA,
}
TABLE = {"/gpt": {"plugin": "x/node-codex"}, "/vendor": {"upstream": "https://v.example"}}


def test_the_card_names_every_mount_and_its_status() -> None:
    status, _, body = _get(_app(TABLE, LIVE), CAPABILITIES_PATH)
    assert status == 200
    card = json.loads(body)
    by_path = {p["path"]: p for p in card["intent_processors"]}
    assert by_path["/gpt"]["status"] == "ok"
    assert by_path["/vendor"]["status"] == "unavailable"
    assert by_path["/gpt"]["config_schema"].endswith("/url4-config/gpt")


def test_the_bundle_embeds_only_the_composed_mounts() -> None:
    status, _, body = _get(_app(TABLE, LIVE), CONFIG_PATH)
    assert status == 200
    bundle = json.loads(body)
    assert set(bundle["$defs"]) == {"gpt"}  # /vendor was never fetched


def test_a_mount_resource_is_byte_identical_to_its_copy_in_the_bundle() -> None:
    """Identical BY CONSTRUCTION: build_bundle embeds what mount_resource returns."""
    app = _app(TABLE, LIVE)
    _, _, alone = _get(app, f"{CONFIG_PATH}/gpt")
    _, _, whole = _get(app, CONFIG_PATH)
    assert json.loads(alone) == json.loads(whole)["$defs"]["gpt"]


def test_an_unknown_mount_is_404() -> None:
    status, _, _ = _get(_app(TABLE, LIVE), f"{CONFIG_PATH}/nope")
    assert status == 404


def test_the_policy_path_is_reserved_here_but_not_served() -> None:
    # The policy registry belongs to the ENDPOINT. 404 says the path is known and this
    # node does not answer it, which is different from the route not existing.
    status, _, _ = _get(_app(TABLE, LIVE), POLICY_PATH)
    assert status == 404


def test_a_write_verb_is_405_not_404() -> None:
    status, _, _ = _get(_app(TABLE, LIVE), CAPABILITIES_PATH, method="POST")
    assert status == 405


def test_head_sends_the_headers_without_the_body() -> None:
    status, headers, body = _get(_app(TABLE, LIVE), CAPABILITIES_PATH, method="HEAD")
    assert status == 200
    assert body == b""
    assert b"etag" in {k.lower() for k in headers}


def test_the_etag_round_trips_to_a_304() -> None:
    app = _app(TABLE, LIVE)
    _, headers, _ = _get(app, CAPABILITIES_PATH)
    etag = headers[b"etag"]
    status, _, body = _get(app, CAPABILITIES_PATH, headers=[(b"if-none-match", etag)])
    assert status == 304
    assert body == b""


def test_discovery_announces_vary_on_the_identity_headers() -> None:
    _, headers, _ = _get(_app(TABLE, LIVE), CAPABILITIES_PATH)
    vary = headers[b"vary"].decode()
    assert "X-Profile" in vary and "X-User-Email" in vary


def test_an_identified_caller_gets_a_private_cache_directive() -> None:
    anon = _get(_app(TABLE, LIVE), CAPABILITIES_PATH)[1][b"cache-control"]
    named = _get(_app(TABLE, LIVE), CAPABILITIES_PATH, headers=[(b"x-profile", b"acme")])[1][
        b"cache-control"
    ]
    assert b"public" in anon
    assert b"private" in named


def test_the_eval_surface_still_answers_with_discovery_mounted() -> None:
    """The wrapper intercepts three paths and nothing else."""
    status, _, _ = _get(_app(TABLE, LIVE), "/healthz")
    assert status == 200
