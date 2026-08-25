"""CacheSeededGateway — the happy-path replay backend (OME-961).

Mental model: the REAL aigateway, booted the way production boots it, whose only source
of model answers is a pre-loaded response cache. Nothing is faked: real Postgres (a
testcontainer), real migrations, the real ``/v1/admin/cache/snapshots`` upload route
(OME-951/952), the real pre-credential cache stage on ``/v1/chat/completions``.

Stages of ``start()``, in execution order:

1. **Postgres** — a ``postgres:16-alpine`` testcontainer, then the gateway's own
   Tortoise migrations (``python -m tortoise -c aigateway.db.TORTOISE_CONFIG migrate``,
   the exact invocation the Helm migrate job and aigateway's Postgres tests use).
2. **Gateway** — ``uvicorn aigateway.main:app`` as a subprocess from
   ``apps/aigateway``'s own venv, on a free loopback port. The environment is built
   from scratch (see ``_local_proc.clean_env``): auth ``disabled`` (loopback-only —
   admin routes answer without headers, the engine calls anonymously), request cache
   ON, openrouter plugin ON (participation gates both cache reads and writes),
   discovery OFF (no public-catalog egress), and **zero provider keys** — the gateway
   cannot spend because there is nothing to spend with.
3. **Seed** — the snapshot (a gzip'd single-table pg_dump COPY block) is uploaded
   through the admin route with its manifest sidecar, and the job is polled to a
   terminal state. Anything but ``complete`` fails the boot loudly — including a
   ``refused``/``revision_mismatch``, which is the guard saying the fixture was
   recorded under different cache-key semantics and must be re-generated.

After that, a request whose fingerprint is in the snapshot is served from the cache
(``X-AIGW-Cache: hit``) before any credential is resolved; any other request falls
through to credential resolution and dies as ``404 profile_not_found`` — the loud
zero-spend miss the whole harness is built around.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

import httpx

from ._local_proc import (
    ManagedProcess,
    clean_env,
    free_port,
    repo_root,
    sync_project,
    venv_bin,
)

ADMIN_ROLE_EMAIL: Final = "e2e-replay-admin@localhost"
_UPLOAD_TIMEOUT_SECONDS: Final = 120.0


class SnapshotLoadFailed(RuntimeError):
    """The admin upload job did not reach ``complete`` — the fixture cannot serve."""


class CacheSeededGateway:
    """``ReplayBackend`` adapter: real gateway + Postgres + snapshot-seeded cache.

    Args:
        snapshot: ``<board>.snapshot.gz`` — gzip'd single-table pg_dump of
            ``request_cache_entries`` (the OME-951 format).
        manifest: the ``.manifest.json`` revision-guard sidecar, or ``None`` to load
            unverified (the job then carries the ``revisions_unverified`` warning).
        work_dir: where child logs land (a pytest ``tmp_path`` works).
    """

    def __init__(self, *, snapshot: Path, manifest: Path | None, work_dir: Path) -> None:
        self._snapshot = snapshot
        self._manifest = manifest
        self._work_dir = work_dir
        self._container: Any = None
        self._process: ManagedProcess | None = None
        self._base_url: str | None = None

    async def start(self) -> str:
        return await asyncio.to_thread(self.start_sync)

    async def stop(self) -> None:
        await asyncio.to_thread(self.stop_sync)

    # The sync twins exist because the SDK client under test is synchronous; test
    # fixtures may call these directly instead of wrapping an event loop.
    def start_sync(self) -> str:
        try:
            database_url = self._start_postgres()
            self._migrate(database_url)
            self._base_url = self._start_gateway(database_url)
            self._upload_snapshot(self._base_url)
        except BaseException:
            self.stop_sync()
            raise
        return self._base_url

    def stop_sync(self) -> None:
        if self._process is not None:
            self._process.stop()
            self._process = None
        if self._container is not None:
            self._container.stop()
            self._container = None
        self._base_url = None

    # -- Stage 1: Postgres ---------------------------------------------------------

    def _start_postgres(self) -> str:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver=None)
        container.start()
        self._container = container
        password = quote(container.password, safe="")
        return (
            f"postgres://{container.username}:{password}"
            f"@{container.get_container_host_ip()}:{container.get_exposed_port(5432)}"
            f"/{container.dbname}"
        )

    def _migrate(self, database_url: str) -> None:
        import subprocess

        gateway_dir = repo_root() / "apps" / "aigateway"
        sync_project(gateway_dir)
        subprocess.run(
            [
                str(venv_bin(gateway_dir, "python")),
                "-m",
                "tortoise",
                "-c",
                "aigateway.db.TORTOISE_CONFIG",
                "migrate",
            ],
            cwd=gateway_dir,
            env=clean_env({"AIGATEWAY_DATABASE_URL": database_url}),
            check=True,
            capture_output=True,
            text=True,
        )

    # -- Stage 2: the gateway process ----------------------------------------------

    def _start_gateway(self, database_url: str) -> str:
        gateway_dir = repo_root() / "apps" / "aigateway"
        port = free_port()
        env = clean_env(
            {
                "AIGATEWAY_DATABASE_URL": database_url,
                # Loopback-only anonymous mode: the engine calls with no credential,
                # and /v1/admin answers this process without identity headers.
                "AIGW_AUTH_MODE": "disabled",
                "AIGATEWAY_ADMIN_EMAILS": ADMIN_ROLE_EMAIL,
                "AIGW_REQUEST_CACHE_ENABLED": "true",
                # Participation gates cache READS too — off would disable replay.
                "AIGW_OPENROUTER_ENABLED": "true",
                # No public-catalog egress from tests.
                "AIGW_DISCOVERY_ENABLED": "false",
                # Deliberately absent: every provider key. Spend is impossible.
            }
        )
        self._process = ManagedProcess(
            name="aigateway",
            command=[
                str(venv_bin(gateway_dir, "uvicorn")),
                "aigateway.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            env=env,
            cwd=gateway_dir,
            log_path=self._work_dir / "aigateway.log",
        )
        base_url = f"http://127.0.0.1:{port}"
        self._process.start(f"{base_url}/healthz")
        return base_url

    # -- Stage 3: seed the cache through the admin route -----------------------------

    def _upload_snapshot(self, base_url: str) -> None:
        files: list[tuple[str, tuple[str, bytes, str]]] = [
            (
                "snapshot",
                (self._snapshot.name, self._snapshot.read_bytes(), "application/gzip"),
            )
        ]
        if self._manifest is not None:
            files.append(
                (
                    "manifest",
                    (self._manifest.name, self._manifest.read_bytes(), "application/json"),
                )
            )
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            accepted = client.post("/v1/admin/cache/snapshots", files=files, data={"mode": "merge"})
            if accepted.status_code != 202:
                raise SnapshotLoadFailed(
                    f"snapshot upload was not accepted: {accepted.status_code} {accepted.text}"
                )
            job_id = accepted.json()["id"]
            job = self._poll_job(client, job_id)
        if job["state"] != "complete":
            raise SnapshotLoadFailed(
                f"snapshot load ended as {job['state']!r} "
                f"(refusal={job.get('refusal')!r}, error={job.get('error')!r}); "
                f"a revision refusal means the fixture must be re-generated against "
                f"this gateway's cache-key revisions"
            )

    def _poll_job(self, client: httpx.Client, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + _UPLOAD_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            job = client.get(f"/v1/admin/cache/snapshots/jobs/{job_id}").json()
            if job.get("finished_at") is not None:
                return job
            time.sleep(0.05)
        raise SnapshotLoadFailed(f"snapshot load job {job_id} did not finish in time")
