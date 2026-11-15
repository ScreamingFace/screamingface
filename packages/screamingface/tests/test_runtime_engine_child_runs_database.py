"""The child-process Engine keeps its Runs in the Client's data dir, as the in-process one does
(OME-1785, E5 P1 spec D2)."""

from __future__ import annotations

from pathlib import Path

from screamingface._runtime import server
from screamingface._runtime.config import RuntimeConfig


def test_the_engine_child_gets_the_runs_database_in_the_data_dir(tmp_path: Path) -> None:
    config = RuntimeConfig(data_dir=tmp_path, engine_port=9111, gateway_port=9105)

    environment = server._engine_child_environment(config, {"HOME": "/home/u"})

    assert environment["URL4_CLOUD_DATABASE_URL"] == config.engine_database_url
    assert str(tmp_path.resolve()) in config.engine_database_url
