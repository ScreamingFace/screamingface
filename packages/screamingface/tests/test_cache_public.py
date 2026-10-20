"""`sf.cache.pull_from_remote`, the public door (epic OME-1311, spec decision 14).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a user of a local engine, one call copies the community cache into my local gateway.

Pinned here: `models` is a sequence of names (one bare string is refused), sorted and de-duplicated
so the same filter is the same pull; the rows land in the data dir's gateway database; the source is
the production Engine unless `url` says otherwise — never the Engine runs go to; and one pull
travels end to end through a real `Client` session and its page source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import screamingface as sf
from screamingface._cache import local as local_module
from screamingface._cache import pull as pull_module
from screamingface._cache.pages import PAGE_SCHEMA
from screamingface.cache import PullResult, pull_from_remote
from screamingface.client import DEFAULT_ENGINE_URL


@pytest.fixture(autouse=True)
def _fresh_cursors(monkeypatch: pytest.MonkeyPatch) -> None:
    pull_module._CURSORS.clear()
    monkeypatch.setattr(pull_module, "_SESSIONS", {})
    monkeypatch.setattr("screamingface._default_client._client", None)


def _recording(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def pull_into(models: tuple[str, ...], **kwargs: Any) -> PullResult:
        calls.append({"models": models, **kwargs})
        return PullResult(0, 0, 0, False, True)

    monkeypatch.setattr(pull_module, "pull_into", pull_into)
    return calls


def test_sf_cache_is_the_public_namespace() -> None:
    assert sf.cache.pull_from_remote is pull_from_remote
    assert "cache" in sf.__all__


def test_models_are_sorted_and_deduplicated_into_one_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_DATA_DIR", str(tmp_path))
    calls = _recording(monkeypatch)

    pull_from_remote(["m2", "m1", "m2"], url="https://dev.engine.test", progress=False)
    pull_from_remote()

    assert calls == [
        {
            "models": ("m1", "m2"),
            "url": "https://dev.engine.test",
            "data_dir": tmp_path,
            "progress": False,
        },
        {"models": (), "url": None, "data_dir": tmp_path, "progress": None},
    ]


@pytest.mark.parametrize("bad", ["openrouter/m", [""], [None], [1]])
def test_models_must_be_a_sequence_of_names(bad: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _recording(monkeypatch)

    with pytest.raises(TypeError, match="models"):
        pull_from_remote(bad)


class _Gateway:
    identity = "aigateway.sqlite3"

    def __init__(self, database: Path, *, empty: PullResult) -> None:
        self.database = database
        self.rows: list[str] = []

    def prepare(self) -> None:
        return None

    def check(self, remote: Any, result: PullResult) -> None:
        return None

    def load(self, rows: Any, result: PullResult) -> tuple[int, int]:
        self.rows.extend(row["key_hash"] for row in rows)
        return len(rows), 0


def test_a_pull_travels_through_a_real_client_session_to_the_production_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[httpx.Request] = []
    page = "\n".join(
        [
            json.dumps(
                {"schema": PAGE_SCHEMA, "revisions": {"parameter_contract": "p1"}, "remaining": 2}
            ),
            json.dumps({"key_hash": "a" * 64}),
            json.dumps({"key_hash": "b" * 64}),
            '{"next": null}',
        ]
    )

    def engine(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=page, headers={"content-type": "application/x-ndjson"})

    real_client = sf.Client
    built: list[str] = []

    def client(*, engine_url: str) -> sf.Client:
        built.append(engine_url)
        return real_client(engine_url=engine_url, http_transport=httpx.MockTransport(engine))

    gateways: list[_Gateway] = []

    def gateway(database: Path, *, empty: PullResult) -> _Gateway:
        gateways.append(_Gateway(database, empty=empty))
        return gateways[-1]

    monkeypatch.setattr("screamingface.client.Client", client)
    monkeypatch.setattr(local_module, "LocalGateway", gateway)
    # INVARIANT (spec decision 14): the Engine runs go to is not where the cache comes from.
    monkeypatch.setenv("SCREAMINGFACE_ENGINE_URL", "http://127.0.0.1:9108")

    result = pull_module.pull_into(("m1",), url=None, data_dir=tmp_path, progress=False)

    assert built == [DEFAULT_ENGINE_URL]
    assert seen[0].url.params.multi_items() == [("model", "m1"), ("count", "true")]
    assert gateways[0].database == tmp_path / "aigateway.sqlite3"
    assert gateways[0].rows == ["a" * 64, "b" * 64]
    assert result == PullResult(rows_read=2, rows_added=2, pages=1, resumed=False, complete=True)


# --- sign-in and source (PR #1446 review, round 2) ------------------------------------------------


def _counting_clients(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[sf.Client]:
    page = "\n".join([json.dumps({"schema": PAGE_SCHEMA, "revisions": {}}), '{"next": null}'])
    real_client = sf.Client
    built: list[sf.Client] = []

    def client(*, engine_url: str) -> sf.Client:
        built.append(
            real_client(
                engine_url=engine_url,
                http_transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=page)),
            )
        )
        return built[-1]

    monkeypatch.setattr("screamingface.client.Client", client)
    monkeypatch.setattr(local_module, "LocalGateway", _Gateway)
    return built


def test_every_pull_in_a_process_shares_one_signed_in_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # WHY: the Access token lives in the Client; a Client per call would sign in per call.
    built = _counting_clients(monkeypatch, tmp_path)

    pull_module.pull_into((), url=None, data_dir=tmp_path, progress=False)
    pull_module.pull_into(("m1",), url=None, data_dir=tmp_path, progress=False)

    assert len(built) == 1
    assert not built[0].closed


def test_a_pull_reuses_the_default_client_already_signed_in_to_that_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = _counting_clients(monkeypatch, tmp_path)
    shared = sf.Client(engine_url="HTTPS://FUSION.SCREAMINGFACE.AI:443/")
    monkeypatch.setattr("screamingface._default_client._client", shared)

    assert pull_module._session(DEFAULT_ENGINE_URL) is shared
    assert built == []


def test_a_default_client_on_another_engine_is_not_the_pulls_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = _counting_clients(monkeypatch, tmp_path)
    local = sf.Client(engine_url="http://127.0.0.1:9108")
    monkeypatch.setattr("screamingface._default_client._client", local)

    pull_module.pull_into((), url=None, data_dir=tmp_path, progress=False)

    assert [client.engine_url for client in built] == [DEFAULT_ENGINE_URL]


def test_a_blank_url_is_refused_rather_than_read_as_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = _counting_clients(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="engine_url"):
        pull_module.pull_into((), url="", data_dir=tmp_path, progress=False)

    assert built == []
