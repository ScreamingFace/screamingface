"""ScoreboardProcess: the real scoreboard as a third stack process (unit E2E, OME-1307).

Mental model: the same shape as ``cache_seeded.CacheSeededGateway`` for the scoreboard. A
Postgres testcontainer of its own (never shared with the gateway), the scoreboard's own
Tortoise migrations, the benchmark seed from the running engine, then ``uvicorn`` in
``cloudflare_headers`` mode (D5) with the E14 keys, flags and archive dir.

Stages of ``start()``, in execution order:

1. **Postgres** - ``postgres:16-alpine``. WHY not sqlite: the publish worker leases with
   ``SELECT ... FOR UPDATE SKIP LOCKED`` (PB-D2), which sqlite does not have.
2. **Migrate** and **seed** - the scoreboard's own commands, the same ones its deploy jobs run.
3. **App** - ``scoreboard.main:create_app`` as a subprocess from ``apps/scoreboard``'s own venv.
4. **Board preparation** - the WIRING admin route makes the board redistributable (D6), and
   ``case_count`` is cleared by SQL (test-only, see ``_clear_case_count``).

INVARIANT: the clean-environment rule of ``_local_proc``. The child gets ``clean_env`` plus the
variables set here, never the shell, and no provider key.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

from ._local_proc import (
    ManagedProcess,
    clean_env,
    free_port,
    refuse_secret_env,
    repo_root,
    sync_project,
    venv_bin,
)
from .identity import EDGE_NETWORK, FORWARDED_ALLOW_IPS_E2E, edge_http

SCOREBOARD_ADMIN: Final = "e2e-scoreboard-admin@e2e.example"


class ScoreboardProcess:
    """The real scoreboard on a free loopback port, with its own Postgres."""

    def __init__(
        self,
        *,
        work_dir: Path,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        refuse_secret_env(extra_env)
        self._work_dir = work_dir
        self._extra_env = dict(extra_env or {})
        self._container: Any = None
        self._process: ManagedProcess | None = None

    def start(self, *, engine_url: str, board: str) -> str:
        """Boot everything and return the scoreboard base URL."""
        try:
            database_url = self._start_postgres()
            self._migrate_and_seed(database_url, engine_url)
            base_url = self._start_app(database_url)
            self._prepare_board(base_url, board)
        except BaseException:
            self.stop()
            raise
        return base_url

    def stop(self) -> None:
        if self._process is not None:
            self._process.stop()
            self._process = None
        if self._container is not None:
            self._container.stop()
            self._container = None

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

    # -- Stage 2: migrate and seed ---------------------------------------------------

    def _migrate_and_seed(self, database_url: str, engine_url: str) -> None:
        scoreboard_dir = repo_root() / "apps" / "scoreboard"
        sync_project(scoreboard_dir)
        python = str(venv_bin(scoreboard_dir, "python"))
        env = clean_env({"SCOREBOARD_DATABASE_URL": database_url})
        subprocess.run(
            [python, "-m", "tortoise", "-c", "scoreboard.db.TORTOISE_CONFIG", "migrate"],
            cwd=scoreboard_dir,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        seeded = subprocess.run(
            [python, "-m", "scoreboard.seed", "--engine-url", engine_url],
            cwd=scoreboard_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        if seeded.returncode != 0:
            raise RuntimeError(
                f"scoreboard seed exited with {seeded.returncode}\n{seeded.stdout}\n{seeded.stderr}"
            )

    # -- Stage 3: the app ---------------------------------------------------------------

    def _start_app(self, database_url: str) -> str:
        scoreboard_dir = repo_root() / "apps" / "scoreboard"
        port = free_port()
        env = clean_env(
            {
                "SCOREBOARD_DATABASE_URL": database_url,
                # FEATURE: OME-1307 (E14) E2E, D5: the production identity mode.
                "SCOREBOARD_AUTH_MODE": "cloudflare_headers",
                "SCOREBOARD_ALLOWED_NETWORKS": EDGE_NETWORK,
                "FORWARDED_ALLOW_IPS": FORWARDED_ALLOW_IPS_E2E,
                "SCOREBOARD_ADMIN_EMAILS": SCOREBOARD_ADMIN,
                # WHY in extra_env: the code default of the clustering flag is False, and with
                # it off `POST /v1/scores` runs the legacy path and ignores the receipt.
                **self._extra_env,
            }
        )
        self._process = ManagedProcess(
            name="scoreboard",
            command=[
                str(venv_bin(scoreboard_dir, "uvicorn")),
                "--factory",
                "scoreboard.main:create_app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            env=env,
            cwd=scoreboard_dir,
            log_path=self._work_dir / "scoreboard.log",
        )
        base_url = f"http://127.0.0.1:{port}"
        self._process.start(f"{base_url}/healthz")
        return base_url

    # -- Stage 4: board preparation -------------------------------------------------------

    def _prepare_board(self, base_url: str, board: str) -> None:
        self._set_redistributable_by_route(base_url, board)
        self._set_board_columns(board)

    def _set_redistributable_by_route(self, base_url: str, board: str) -> None:
        # WHY the route first: D6 makes it the product path, so E2E proves it.
        with edge_http(base_url, SCOREBOARD_ADMIN) as client:
            response = client.put(
                f"/v1/admin/benchmarks/{board}/redistributable",
                json={"redistributable": True, "reason": "e2e"},
            )
        if (
            not 200 <= response.status_code < 300
            or response.json().get("redistributable") is not True
        ):
            raise RuntimeError(
                f"the redistributable admin route answered {response.status_code}: {response.text}"
            )

    def _set_board_columns(self, board: str) -> None:
        # WHY case_count = NULL: the golden replays 50 cases (`limit: 50`), and the leaderboard
        # hides a run with fewer cases than `case_count`. With NULL the filter is off. No
        # product path sets it, and none is needed. Test-only SQL, run inside the container.
        container = self._container
        exit_code, output = container.exec(
            [
                "psql",
                "-U",
                container.username,
                "-d",
                container.dbname,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f"UPDATE benchmarks SET case_count = NULL WHERE id = '{board}'",
            ]
        )
        if exit_code != 0 or b"UPDATE 1" not in output:
            raise RuntimeError(f"board preparation failed ({exit_code}): {output.decode()}")
