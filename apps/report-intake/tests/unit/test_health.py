"""`/healthz` is the answer to "is this process alive", and nothing else.

INVARIANT: it depends on no storage, no settings, and no caller class. A liveness probe that can
fail for an external reason turns one bad dependency into a restart loop across every replica,
and a liveness probe behind an auth check is how a pod ends up failing its own kubelet probe.
"""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from report_intake.config import Settings
from report_intake.main import create_app
from report_intake.routes import health


def test_healthz_answers_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_answers_a_caller_that_is_not_on_the_loopback(
    hermetic_environment: None,
    database_url: str,
) -> None:
    """The kubelet dials the Pod IP, not 127.0.0.1.

    Shipped now rather than with the local-only middleware OME-1011 adds, because that
    middleware is copied from one that gates EVERY path and requires a loopback peer — under
    which a deployed pod 403s its own liveness probe and CrashLoopBackOffs. This test is what
    turns that from a deploy-time discovery into a red build.
    """
    with TestClient(
        create_app(Settings(database_url=database_url)),
        base_url="http://report-intake.svc",
        client=("10.42.0.1", 41000),
    ) as probe:
        response = probe.get("/healthz")

    assert response.status_code == 200


def test_healthz_imports_nothing_that_could_fail_with_the_database() -> None:
    """Structural, because the invariant is about what the module may ever reach, not about what
    today's one-line handler happens to do. A storage import added here is invisible until a
    database goes down and takes every replica with it.
    """
    module = ast.parse(Path(health.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(module)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert imported == {"__future__", "fastapi"}
