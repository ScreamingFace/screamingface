"""`/readyz` answers from one seam, `app.state.readiness_check`.

`OME-1008` filled that seam with a real storage probe, so the interesting cases moved: readiness
is now a claim about the database this pod is pointed at, and the two ways it can be wrong are
(a) the database is unreachable and (b) the migration has not been applied. The second is the
ordinary state of a freshly deployed pod, because this service never migrates itself — so it has
to keep that pod out of the load balancer rather than let a rollout succeed into a service that
cannot serve.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from report_intake.config import Settings
from report_intake.main import create_app
from report_intake.routes.ready import ReadinessCheck


@contextmanager
def _serving(database_url: str, check: ReadinessCheck | None = None) -> Generator[TestClient]:
    app = create_app(Settings(database_url=database_url))
    if check is not None:
        app.state.readiness_check = check
    with TestClient(app) as test_client:
        yield test_client


def _registered_paths(routes: Iterable[object]) -> list[str]:
    """Every path the app serves, flattened.

    `app.routes` is not that list on its own: starlette wraps an `include_router` behind a
    delegating entry that exposes the real routes only through `original_router`. Counting the
    top level alone finds zero `/readyz` and passes for the wrong reason.
    """
    paths: list[str] = []
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.append(path)
        nested = getattr(route, "routes", None)
        if nested is None:
            nested = getattr(getattr(route, "original_router", None), "routes", None)
        if nested is not None:
            paths.extend(_registered_paths(nested))
    return paths


def test_readyz_reports_ready_once_the_reports_table_is_queryable(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_fails_closed_against_a_database_whose_migration_has_not_run(
    hermetic_environment: None, tmp_path: Path
) -> None:
    """The pod-just-deployed case, and the reason the probe queries the TABLE rather than the
    connection: an empty sqlite file connects perfectly and cannot serve a single report."""
    with _serving(f"sqlite://{tmp_path / 'unmigrated.sqlite3'}") as probe:
        response = probe.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}


def test_readyz_reports_unready_when_an_installed_probe_says_no(
    hermetic_environment: None, database_url: str
) -> None:
    """The seam still governs: whatever sits at `app.state.readiness_check` is the answer, even
    with a perfectly healthy database behind it."""

    async def storage_is_gone() -> bool:
        return False

    with _serving(database_url, storage_is_gone) as probe:
        response = probe.get("/readyz")

    assert response.status_code == 503


def test_installing_a_probe_replaces_the_seam_rather_than_adding_a_second_route(
    hermetic_environment: None, database_url: str
) -> None:
    """Guards the "one `/readyz`" invariant.

    A second registration is not an import error: FastAPI accepts both routes and serves
    whichever was registered first, so a `/readyz` added beside a storage module because this one
    looked like a stub would answer from neither place predictably.
    """
    app = create_app(Settings(database_url=database_url))

    assert _registered_paths(app.routes).count("/readyz") == 1


def test_the_installed_probe_is_the_stores_own_reachability_check(
    hermetic_environment: None, database_url: str
) -> None:
    """`create_app` fills the seam from the store rather than from a closure written beside it,
    so "is this pod ready" and "can the store answer" cannot drift into two different questions.
    """
    app = create_app(Settings(database_url=database_url))

    assert app.state.readiness_check == app.state.report_store.is_reachable
