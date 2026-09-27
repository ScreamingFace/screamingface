"""MNT-24 / MC-D13: `serve --local` serves its mounts through the SAME route code as the
deployed App — a direct run on the in-process runner against the shared node — and lists them
in `/openapi.json`. The eval path stays the node's own surface (PRD 04 §6)."""

from pathlib import Path

from fastapi.testclient import TestClient

from screamingface_engine import job_env
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app

_WORLD = (
    "[aigateway]\n"
    'base_url = "http://aigateway.invalid"\n'
    'default_route = "/anthropic/claude-haiku-4-5"\n'
    "\n[data]\n"
    '"/corpus/papers" = { value = "rows of papers", media_type = "text/plain" }\n'
)


def test_local_mounts_use_inprocess_runner_and_openapi(tmp_path: Path) -> None:
    world = tmp_path / "url4.toml"
    world.write_text(_WORLD)
    app = create_local_app(Settings(jwt_secret="s" * 32), env={job_env.RUNNER_CONFIG: str(world)})
    with TestClient(app) as client:
        response = client.get("/corpus/papers")
        schema = client.get("/openapi.json").json()
        runner = app.state.job_runner
    # Anonymous, as local mode has always served (no edge verifies a caller on loopback).
    assert response.status_code == 200, response.text
    assert response.text == "rows of papers"
    assert response.headers["content-type"].startswith("text/plain")
    assert schema["paths"]["/corpus/papers"]["get"]["tags"] == ["Mounts"]
    # The call was a RUN on the in-process runner: it is in the runner's task table.
    assert len(runner._tasks) == 1  # noqa: SLF001
