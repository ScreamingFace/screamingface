"""A non-default Engine never silently pairs with the hosted Scoreboard (e2e workbench U1)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import screamingface as sf
from screamingface import _default_client
from screamingface.client import DEFAULT_ENGINE_URL, DEFAULT_SCOREBOARD_URL


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SCREAMINGFACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SCREAMINGFACE_ENGINE_URL", raising=False)
    monkeypatch.delenv("SCREAMINGFACE_SCOREBOARD_URL", raising=False)
    monkeypatch.setattr(_default_client, "_client", None)
    yield
    if _default_client._client is not None:
        _default_client._client.close()
    monkeypatch.setattr(_default_client, "_client", None)


def test_configure_with_a_non_default_engine_and_no_scoreboard_raises(isolated: None) -> None:
    with pytest.raises(ValueError, match="scoreboard_url") as caught:
        sf.configure(engine_url="http://127.0.0.1:9108")
    assert "http://127.0.0.1:9108" in str(caught.value)


def test_a_failed_configure_keeps_the_previous_default_client_open(isolated: None) -> None:
    before = sf.configure(
        engine_url="https://first.example", scoreboard_url="https://first-board.example"
    )
    with pytest.raises(ValueError):
        sf.configure(engine_url="https://second.example")
    assert before.closed is False
    assert _default_client.default_client() is before


@pytest.mark.parametrize(
    "spelling",
    [
        DEFAULT_ENGINE_URL,
        DEFAULT_ENGINE_URL + "/",
        DEFAULT_ENGINE_URL.upper(),
        DEFAULT_ENGINE_URL + ":443",
        DEFAULT_ENGINE_URL.upper() + ":443/",
    ],
)
def test_the_default_engine_in_any_spelling_pairs_with_the_default_scoreboard(
    isolated: None, spelling: str
) -> None:
    client = sf.configure(engine_url=spelling)
    assert client.scoreboard_url == DEFAULT_SCOREBOARD_URL


@pytest.mark.parametrize(
    "engine_url",
    [
        "https://fusion.screamingface.ai:8443",
        "http://fusion.screamingface.ai",
        "http://fusion.screamingface.ai:443",
    ],
)
def test_a_non_default_port_or_scheme_is_not_the_hosted_engine(
    isolated: None, engine_url: str
) -> None:
    with pytest.raises(ValueError, match="scoreboard_url"):
        sf.configure(engine_url=engine_url)


def test_configure_with_both_urls_is_unchanged(isolated: None) -> None:
    client = sf.configure(
        engine_url="http://127.0.0.1:9108", scoreboard_url="http://127.0.0.1:9106"
    )
    assert (client.engine_url, client.scoreboard_url) == (
        "http://127.0.0.1:9108",
        "http://127.0.0.1:9106",
    )


def test_engine_env_var_without_scoreboard_env_var_raises_on_first_use(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_ENGINE_URL", "https://preview.example")
    with pytest.raises(ValueError, match="SCREAMINGFACE_SCOREBOARD_URL"):
        _default_client.default_client()


def test_both_env_vars_build_the_default_client(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_ENGINE_URL", "https://preview.example")
    monkeypatch.setenv("SCREAMINGFACE_SCOREBOARD_URL", "https://preview-board.example")
    client = _default_client.default_client()
    assert client.scoreboard_url == "https://preview-board.example"
