from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from screamingface._runtime import source as runtime_source
from screamingface._runtime.config import RuntimeConfig, default_data_dir

_STATE_VERSION = 1
_PORT_DEFAULTS = {"gateway": 9105, "scoreboard": 9106, "engine": 9108}
_BENCHMARKS = ("draco", "ifeval", "healthbench", "gdpval")
# WHY 15: enough to carry the failing import plus its traceback into the `up` error;
# short enough that the message stays readable where it lands (OME-1036).
_STARTUP_LOG_TAIL_LINES = 15


def _parser() -> argparse.ArgumentParser:  # noqa: PLR0915
    parser = argparse.ArgumentParser(prog="screamingface")
    parser.add_argument(
        "--version", action="version", version=importlib.metadata.version("screamingface")
    )
    _add_data_dir(parser, default=default_data_dir())
    commands = parser.add_subparsers(dest="command", required=True)
    up = commands.add_parser("up", help="Start the local runtime")
    _add_data_dir(up)
    up.add_argument("--foreground", action="store_true")
    _add_port_options(up)
    down = commands.add_parser("down", help="Stop the local runtime")
    _add_data_dir(down)
    restart = commands.add_parser("restart", help="Restart the local runtime")
    _add_data_dir(restart)
    restart.add_argument("--foreground", action="store_true")
    _add_port_options(restart)
    doctor = commands.add_parser("doctor", help="Diagnose the local runtime")
    _add_data_dir(doctor)
    status = commands.add_parser("status", help="Show local runtime status")
    _add_data_dir(status)
    status.add_argument("--json", action="store_true", dest="json_output")
    logs = commands.add_parser("logs", help="Read local runtime logs")
    _add_data_dir(logs)
    logs.add_argument("--tail", type=int, default=100)
    logs.add_argument("--no-follow", action="store_true")
    logs.add_argument(
        "--service",
        choices=("all", "gateway", "scoreboard", "engine", "supervisor"),
        default="all",
    )
    prepare = commands.add_parser("prepare", help="Download benchmark assets")
    _add_data_dir(prepare)
    prepare.add_argument("benchmark", nargs="?", choices=_BENCHMARKS)
    prepare.add_argument("--all", action="store_true", dest="all_benchmarks")
    prepare.add_argument("--list", action="store_true", dest="list_benchmarks")
    prepare.add_argument("--force", action="store_true")
    serve = commands.add_parser("_serve", help=argparse.SUPPRESS)
    _add_data_dir(serve)
    serve.add_argument("--owner-token", required=True)
    serve.add_argument("--background", action="store_true")
    _add_port_options(serve)
    scoreboard = commands.add_parser("_scoreboard", help=argparse.SUPPRESS)
    _add_data_dir(scoreboard)
    scoreboard.add_argument("--scoreboard-port", type=int, default=9106)
    commands._choices_actions = [  # noqa: SLF001
        action
        for action in commands._choices_actions  # noqa: SLF001
        if action.dest not in {"_serve", "_scoreboard"}
    ]
    return parser


def _add_data_dir(parser: argparse.ArgumentParser, *, default: Path | None = None) -> None:
    if default is None:
        parser.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
    else:
        parser.add_argument("--data-dir", type=Path, default=default)


def _add_port_options(parser: argparse.ArgumentParser) -> None:
    for service in _PORT_DEFAULTS:
        parser.add_argument(f"--{service}-port", type=int, default=None)


def main(argv: list[str] | None = None) -> None:  # noqa: C901, PLR0912
    args = _parser().parse_args(argv)
    try:
        # WHY before dispatch: every command that imports runtime apps (up/serve
        # children, status, doctor, prepare) must see the live checkout code, not a
        # stale build-time copy in site-packages (OME-1001). `down` and `logs` are
        # exempt: they import no runtime apps, and a broken SCREAMINGFACE_RUNTIME_SOURCE
        # must never lock the user out of recovery (mirrors the recovery-command rule
        # for invalid port environments in _config).
        if args.command not in {"down", "logs"}:
            runtime_source.activate(runtime_source.resolve_source(os.environ))
        config = _config(args)
        if args.command == "up":
            _up(config, foreground=args.foreground)
        elif args.command == "restart":
            _restart(config, args, foreground=args.foreground)
        elif args.command == "down":
            _down(config)
        elif args.command == "status":
            raise SystemExit(_print_status(config, json_output=args.json_output))
        elif args.command == "logs":
            _logs(config, tail=args.tail, follow=not args.no_follow, service=args.service)
        elif args.command == "doctor":
            raise SystemExit(_doctor(config))
        elif args.command == "prepare":
            _prepare(
                config,
                args.benchmark,
                all_benchmarks=args.all_benchmarks,
                list_benchmarks=args.list_benchmarks,
                force=args.force,
            )
        elif args.command == "_serve":
            _serve(config, args.owner_token, foreground=not args.background)
        elif args.command == "_scoreboard":
            from screamingface._runtime.server import run_scoreboard

            run_scoreboard(config)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        raise SystemExit(f"screamingface: {exc}") from None


def _config(args: argparse.Namespace) -> RuntimeConfig:
    values: dict[str, int] = {}
    use_port_environment = args.command in {
        "up",
        "restart",
        "status",
        "doctor",
        "_serve",
        "_scoreboard",
    }
    for service, fallback in _PORT_DEFAULTS.items():
        argument = getattr(args, f"{service}_port", None)
        configured = (
            os.getenv(f"SCREAMINGFACE_{service.upper()}_PORT") if use_port_environment else None
        )
        values[service] = (
            argument if argument is not None else _environment_port(configured, fallback)
        )
    return RuntimeConfig(
        data_dir=args.data_dir,
        gateway_port=values["gateway"],
        scoreboard_port=values["scoreboard"],
        engine_port=values["engine"],
    )


def _environment_port(value: str | None, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"runtime port must be an integer, got {value!r}") from None


def _up(config: RuntimeConfig, *, foreground: bool) -> None:  # noqa: PLR0915
    from screamingface._runtime.server import require_runtime_extra

    require_runtime_extra()
    state = _read_state(config)
    owned = bool(state and _verify_owner(state))
    if owned:
        # WHY before the health split: the partially-healthy advice below points at
        # `restart`, which tears the stack down — another checkout's stack must be
        # refused on EVERY owned branch, not only the all-healthy one.
        _ensure_adoptable(state)
        health = _health(_state_services(state))
        if all(health.values()):
            print("ScreamingFace is already running.")
            _print_urls(_state_services(state), config.log_path)
            return
        raise RuntimeError(
            "the owned runtime is only partially healthy; run `screamingface logs` "
            "then `screamingface restart`"
        )
    if state:
        config.state_path.unlink(missing_ok=True)
    occupied = [port for port in _ports(config) if _port_open(port)]
    if occupied:
        raise RuntimeError(f"required port(s) already in use by another process: {occupied}")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    token = os.urandom(16).hex()
    if foreground:
        _serve(config, token, foreground=True)
        return

    command = [
        sys.executable,
        "-m",
        "screamingface._runtime.cli",
        "--data-dir",
        str(config.data_dir),
        "_serve",
        "--owner-token",
        token,
        "--background",
        "--gateway-port",
        str(config.gateway_port),
        "--scoreboard-port",
        str(config.scoreboard_port),
        "--engine-port",
        str(config.engine_port),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        _wait_ready(process, config, timeout=90)
    except Exception:
        state = _read_state(config)
        if state and _verify_owner(state):
            _request_shutdown(state)
        raise
    print("ScreamingFace is ready.")
    _print_urls(config.services, config.log_path)


def _ensure_adoptable(state: dict[str, object] | None) -> None:
    """Refuse to adopt a healthy stack that another checkout (or install) owns.

    INVARIANT (OME-1001): two worktrees must not silently share one stack — adopting
    another checkout's services would run benchmarks against that branch's code and
    produce results that look right but aren't.
    """

    recorded = state.get("source") if state else None
    if not isinstance(recorded, dict):
        # Pre-OME-1001 state carries no source record; there is no identity to compare.
        return
    ours = runtime_source.state_record(runtime_source.resolve_source(os.environ))
    if recorded == dict(ours):
        return
    owner = recorded.get("root") or recorded.get("mode") or "unknown source"
    raise RuntimeError(
        f"the running stack is owned by another source ({owner}); "
        "run `screamingface down` to stop it first"
    )


def _serve(config: RuntimeConfig, token: str, *, foreground: bool) -> None:
    from screamingface._runtime.runtime_logging import capture_runtime_log

    with capture_runtime_log(config.log_path, foreground=foreground):
        try:
            _serve_logged(config, token)
        except ImportError as exc:
            # WHY a branch of its own (OME-1036): a missing runtime dependency otherwise
            # reaches the log as a bare module error with no remediation. Any import the
            # preflight list missed still lands with the fix attached.
            print(
                f'SCREAMINGFACE_RUNTIME_ERROR {exc} — install "screamingface[runtime]"',
                file=sys.stderr,
                flush=True,
            )
            raise
        except Exception as exc:
            print(f"SCREAMINGFACE_RUNTIME_ERROR {exc}", file=sys.stderr, flush=True)
            raise


def _serve_logged(config: RuntimeConfig, token: str) -> None:
    shutdown = threading.Event()
    control = _control_server(token, shutdown)
    started_at = datetime.now(UTC).isoformat()
    state = {
        "schema_version": _STATE_VERSION,
        "pid": os.getpid(),
        "process_started_at": time.time(),
        "started_at": started_at,
        "owner_token": token,
        "control_url": f"http://127.0.0.1:{control.server_port}",
        "services": config.services,
        "log_path": str(config.log_path),
        "source": runtime_source.state_record(runtime_source.resolve_source(os.environ)),
    }
    _write_state(config, state)
    control_thread = threading.Thread(target=control.serve_forever, daemon=True)
    control_thread.start()
    try:
        _run_server(config, shutdown)
    finally:
        control.shutdown()
        control.server_close()
        control_thread.join(timeout=2)
        _remove_owned_state(config, token)


def _run_server(config: RuntimeConfig, shutdown: threading.Event) -> None:
    import asyncio

    from screamingface._runtime.server import run

    asyncio.run(run(config, shutdown))


def _down(config: RuntimeConfig) -> None:
    state = _read_state(config)
    if not state:
        if config.state_path.exists():
            raise RuntimeError(f"invalid runtime state: {config.state_path}")
        print("ScreamingFace is not running.")
        return
    if not _verify_owner(state):
        config.state_path.unlink(missing_ok=True)
        print("Removed stale runtime state; no owned ScreamingFace runtime was stopped.")
        return
    _request_shutdown(state)
    for _ in range(100):
        if not _verify_owner(state):
            config.state_path.unlink(missing_ok=True)
            print("ScreamingFace stopped.")
            return
        time.sleep(0.1)
    raise RuntimeError(f"runtime did not stop; inspect {config.log_path}")


def _restart(config: RuntimeConfig, args: argparse.Namespace, *, foreground: bool) -> None:
    state = _read_state(config)
    # INVARIANT: restart = down + up, so it must refuse a foreign stack the same way
    # `up` does — otherwise it silently replaces another checkout's running services.
    if state and _verify_owner(state):
        _ensure_adoptable(state)
    if state:
        services = _state_services(state)
        stored = {name: _url_port(url) for name, url in services.items()}
        values = {}
        for service, fallback in _PORT_DEFAULTS.items():
            explicit = getattr(args, f"{service}_port", None)
            environment = os.getenv(f"SCREAMINGFACE_{service.upper()}_PORT")
            values[service] = (
                explicit
                if explicit is not None
                else _environment_port(environment, stored.get(service, fallback))
            )
        config = RuntimeConfig(
            data_dir=config.data_dir,
            gateway_port=values["gateway"],
            scoreboard_port=values["scoreboard"],
            engine_port=values["engine"],
        )
    _down(config)
    _up(config, foreground=foreground)


def _print_status(config: RuntimeConfig, *, json_output: bool = False) -> int:
    state = _read_state(config)
    stored_services = _state_services(state)
    state_valid = not config.state_path.exists() or bool(state and stored_services)
    services = stored_services if state_valid and state else config.services
    health = _health(services)
    owned = bool(state_valid and state and _verify_owner(state))
    if not state_valid:
        label, code = "invalid runtime state", 1
    elif owned and all(health.values()):
        label, code = "running", 0
    elif owned:
        label, code = "partially healthy", 1
    elif any(health.values()) or any(_port_open(port) for port in _service_ports(services)):
        label, code = "foreign processes occupy runtime ports", 2
    else:
        label, code = "stopped", 1
    if json_output:
        payload = {
            "schema": "screamingface.runtime-status.v1",
            "status": label.replace(" ", "_"),
            "ownership_verified": owned,
            "state_valid": state_valid,
            "pid": state.get("pid") if state else None,
            "started_at": state.get("started_at") if state else None,
            "data_dir": str(config.data_dir),
            "services": {
                name: {"url": url, "healthy": health[name]} for name, url in services.items()
            },
            "log_path": str(config.log_path),
            "benchmarks": _benchmark_statuses(config),
        }
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return code
    print(f"ScreamingFace: {label}")
    for name, ready in health.items():
        print(f"  {name:10} {'UP' if ready else 'down':4}  {services[name]}")
    print(f"  logs       {config.log_path}")
    return code


def _logs(  # noqa: C901, PLR0912, PLR0915
    config: RuntimeConfig, *, tail: int, follow: bool, service: str = "all"
) -> None:
    if tail < 0:
        raise RuntimeError("--tail must be zero or greater")
    if not config.log_path.exists():
        raise RuntimeError(f"no runtime log exists at {config.log_path}")
    history: deque[str] = deque(maxlen=tail)
    for path in _log_paths(config.log_path):
        with path.open(encoding="utf-8", errors="replace") as stream:
            history.extend(line for line in stream if _log_line_matches(line, service))
    for line in history:
        print(line, end="")
    if not follow:
        return
    stream = config.log_path.open(encoding="utf-8", errors="replace")
    stream.seek(0, 2)
    identity = _file_identity(config.log_path)
    try:
        while True:
            line = stream.readline()
            if line:
                if _log_line_matches(line, service):
                    print(line, end="", flush=True)
                continue
            current = _file_identity(config.log_path)
            if current != identity and current != (-1, -1):
                stream.close()
                stream = config.log_path.open(encoding="utf-8", errors="replace")
                identity = current
                continue
            time.sleep(0.2)
    finally:
        stream.close()


def _log_paths(path: Path) -> tuple[Path, ...]:
    from screamingface._runtime.runtime_logging import LOG_BACKUPS

    rotated = tuple(
        candidate
        for index in range(LOG_BACKUPS, 0, -1)
        if (candidate := path.with_name(f"{path.name}.{index}")).exists()
    )
    return (*rotated, path)


def _log_line_matches(line: str, service: str) -> bool:
    return service == "all" or f"[{service}]" in line


def _file_identity(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return -1, -1
    return stat.st_dev, stat.st_ino


def _prepare(
    config: RuntimeConfig,
    benchmark: str | None,
    *,
    all_benchmarks: bool,
    list_benchmarks: bool = False,
    force: bool = False,
) -> None:
    if list_benchmarks:
        if all_benchmarks or benchmark is not None or force:
            raise RuntimeError("--list cannot be combined with a benchmark, --all, or --force")
        for name, status in _benchmark_statuses(config).items():
            print(f"{name:12} {status}")
        return
    if all_benchmarks == (benchmark is not None):
        raise RuntimeError("choose one benchmark or pass --all")
    from screamingface._runtime.server import require_runtime_extra

    require_runtime_extra()
    selected = _BENCHMARKS if all_benchmarks else (benchmark,)
    config.assets_dir.mkdir(parents=True, exist_ok=True)
    # WHY: the preparer child is a fresh interpreter with no sys.path activation of
    # its own — PYTHONPATH is how a checkout's live engine code reaches it.
    child_env = runtime_source.child_environment(
        runtime_source.resolve_source(os.environ), os.environ
    )
    for name in selected:
        destination = config.assets_dir / str(name)
        if not force and _benchmark_status(config, str(name)) == "prepared":
            print(f"{name} is already prepared at {destination}")
            continue
        manifest = _benchmark_manifest_path(destination)
        manifest.unlink(missing_ok=True)
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    f"screamingface_engine.benchmarks.{name}.prepare",
                    "--out",
                    str(destination),
                ],
                check=True,
                env=child_env,
            )
            files = _validate_benchmark_output(str(name), destination)
            _write_json_atomic(
                manifest,
                {
                    "schema": "screamingface.benchmark-assets.v1",
                    "benchmark": name,
                    "fingerprint": _benchmark_fingerprint(str(name)),
                    "screamingface_version": importlib.metadata.version("screamingface"),
                    "prepared_at": datetime.now(UTC).isoformat(),
                    "validated_files": files,
                },
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            manifest.unlink(missing_ok=True)
            raise RuntimeError(f"failed to prepare {name} in {destination}: {exc}") from None
    print(f"Benchmark assets ready at {config.assets_dir}")


def _benchmark_statuses(config: RuntimeConfig) -> dict[str, str]:
    return {name: _benchmark_status(config, name) for name in _BENCHMARKS}


def _doctor(config: RuntimeConfig) -> int:  # noqa: C901, PLR0912, PLR0915
    checks: list[tuple[str, str, str]] = []
    try:
        from screamingface._runtime.server import require_runtime_extra

        require_runtime_extra()
    except RuntimeError as exc:
        checks.append(("fail", "runtime dependencies", str(exc)))
    else:
        checks.append(("pass", "runtime dependencies", "installed"))

    writable = _writable_location(config.data_dir)
    checks.append(
        (
            "pass" if writable else "fail",
            "data directory",
            f"{config.data_dir} is {'writable' if writable else 'not writable'}",
        )
    )

    state = _read_state(config)
    state_exists = config.state_path.exists()
    services = _state_services(state) if state else config.services
    owned = bool(state and _verify_owner(state))
    if state_exists and state is None:
        checks.append(("fail", "runtime state", f"invalid JSON in {config.state_path}"))
    elif state and not _state_services(state):
        checks.append(("fail", "runtime state", "unsupported or incomplete state document"))
    elif state and not owned:
        checks.append(("fail", "runtime state", "ownership could not be verified"))
    elif owned:
        checks.append(("pass", "runtime state", "ownership verified"))
    else:
        checks.append(("warn", "runtime state", "runtime is stopped"))

    health = _health(services)
    if owned:
        for name, healthy in health.items():
            checks.append(("pass" if healthy else "fail", f"{name} health", services[name]))
    else:
        occupied = [port for port in _service_ports(services) if _port_open(port)]
        checks.append(
            (
                "fail" if occupied else "pass",
                "runtime ports",
                f"occupied by foreign processes: {occupied}" if occupied else "available",
            )
        )

    if health.get("engine"):
        for label, path in (("model discovery", "/v1/models"), ("connections", "/v1/connections")):
            try:
                payload = _get_json(f"{services['engine']}{path}")
            except RuntimeError as exc:
                checks.append(("fail", label, str(exc)))
                continue
            if label == "connections" and not _has_connections(payload):
                checks.append(("warn", label, "no provider connection is configured"))
            else:
                checks.append(("pass", label, "endpoint responded"))
    else:
        checks.append(("warn", "API discovery", "Engine is not running"))

    statuses = _benchmark_statuses(config)
    for name, status in statuses.items():
        severity = "pass" if status == "prepared" else "warn" if status == "missing" else "fail"
        checks.append((severity, f"{name} assets", status))

    for severity, label, detail in checks:
        print(f"{severity.upper():4}  {label:22} {detail}")
    return 1 if any(severity == "fail" for severity, _, _ in checks) else 0


def _writable_location(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK)


def _get_json(url: str) -> object:
    try:
        with urlopen(url, timeout=1) as response:  # noqa: S310
            return json.load(response)
    except (OSError, URLError, ValueError) as exc:
        raise RuntimeError(f"{url} did not return valid JSON") from exc


def _has_connections(payload: object) -> bool:
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        data = payload.get("data")
        entries = data if isinstance(data, list) else []
    else:
        return False
    return any(
        isinstance(entry, dict) and entry.get("status") not in {None, "not_connected"}
        for entry in entries
    )


def _benchmark_status(config: RuntimeConfig, name: str) -> str:  # noqa: PLR0911
    destination = config.assets_dir / name
    if not destination.exists():
        return "missing"
    try:
        manifest = json.loads(_benchmark_manifest_path(destination).read_text())
    except (OSError, json.JSONDecodeError):
        return "incomplete"
    if not isinstance(manifest, dict) or manifest.get("fingerprint") != _benchmark_fingerprint(
        name
    ):
        return "stale"
    try:
        _validate_benchmark_output(name, destination)
    except RuntimeError:
        return "incomplete"
    return "prepared"


def _benchmark_manifest_path(destination: Path) -> Path:
    return destination / ".screamingface-prepare.json"


def _benchmark_fingerprint(name: str) -> str:
    preparation = importlib.import_module(f"screamingface_engine.benchmarks.{name}.prepare")
    revision = getattr(preparation, "DATASET_REVISION", None)
    if not isinstance(revision, str) or not revision:
        raise RuntimeError(f"{name} does not declare a dataset revision")
    return f"{name}:{revision}"


def _validate_benchmark_output(name: str, destination: Path) -> list[str]:
    required = {
        "draco": ("cases.json", "criteria", "rubrics"),
        "ifeval": ("cases.json", "instructions", "nltk_data"),
        "healthbench": ("cases.json", "rubrics"),
        # WHY no reference directory here: GDPval's reference documents are flattened to text at
        # build time and baked INTO cases.json, so the downloaded originals are a build cache
        # rather than a served asset.
        "gdpval": ("cases.json", "rubrics"),
    }[name]
    missing = [relative for relative in required if not (destination / relative).exists()]
    if missing:
        raise RuntimeError(f"prepared output is missing {missing}")
    try:
        cases = json.loads((destination / "cases.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("prepared cases.json is unreadable") from exc
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("prepared cases.json contains no cases")
    return list(required)


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _runtime_log_tail(path: Path, *, limit: int = _STARTUP_LOG_TAIL_LINES) -> str:
    """The last runtime log lines, for errors raised where the log is not on screen.

    Returns "" when the log is unreadable or absent — the caller's message already
    points at the log path, so a missing file must not mask the startup failure itself.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            return "".join(deque(stream, maxlen=limit)).rstrip("\n")
    except OSError:
        return ""


def _wait_ready(process: subprocess.Popen[bytes], config: RuntimeConfig, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            # WHY the tail (OME-1036): the child dies in the background with its cause in
            # the log file; repeating the last lines here puts the cause where the user is
            # already looking instead of sending them hunting for a file.
            tail = _runtime_log_tail(config.log_path)
            raise RuntimeError(
                "runtime exited during startup"
                + (f":\n{tail}" if tail else "; inspect the runtime log")
            )
        state = _read_state(config)
        if all(_health(config.services).values()) and state is not None and _verify_owner(state):
            return
        time.sleep(0.2)
    raise RuntimeError("runtime did not become ready within 90 seconds")


def _health(services: dict[str, str]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for name, base_url in services.items():
        url = f"{base_url}/healthz"
        try:
            with urlopen(url, timeout=0.3) as response:  # noqa: S310
                result[name] = response.status == 200
        except (OSError, URLError):
            result[name] = False
    return result


def _port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        alive = False
    except PermissionError:
        alive = True
    except OSError:
        alive = False
    else:
        alive = True
    return alive


def _read_state(config: RuntimeConfig) -> dict[str, object] | None:
    try:
        value = json.loads(config.state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_state(config: RuntimeConfig, state: dict[str, object]) -> None:
    _write_json_atomic(config.state_path, state)


def _remove_owned_state(config: RuntimeConfig, token: str) -> None:
    state = _read_state(config)
    if state and state.get("owner_token") == token:
        config.state_path.unlink(missing_ok=True)


def _print_urls(services: dict[str, str], log_path: Path) -> None:
    for name, url in services.items():
        print(f"  {name.title():10} {url}")
    print(f"  Logs       {log_path}")
    print(f"  export SCREAMINGFACE_ENGINE_URL={services['engine']}")
    print(f"  export SCREAMINGFACE_SCOREBOARD_URL={services['scoreboard']}")


def _ports(config: RuntimeConfig) -> tuple[int, int, int]:
    return config.gateway_port, config.scoreboard_port, config.engine_port


def _service_ports(services: dict[str, str]) -> tuple[int, ...]:
    return tuple(_url_port(url) for url in services.values())


def _url_port(url: str) -> int:
    from urllib.parse import urlsplit

    port = urlsplit(url).port
    if port is None:
        raise ValueError(f"runtime service URL has no port: {url}")
    return port


def _state_services(state: dict[str, object] | None) -> dict[str, str]:
    if not state or state.get("schema_version") != _STATE_VERSION:
        return {}
    value = state.get("services")
    if not isinstance(value, dict):
        return {}
    services = {str(name): str(url) for name, url in value.items()}
    return services if set(services) == set(_PORT_DEFAULTS) else {}


def _verify_owner(state: dict[str, object]) -> bool:
    control_url = state.get("control_url")
    token = state.get("owner_token")
    pid = state.get("pid")
    if not isinstance(control_url, str) or not isinstance(token, str) or not isinstance(pid, int):
        return False
    try:
        request = Request(f"{control_url}/identity", headers={"Authorization": f"Bearer {token}"})
        with urlopen(request, timeout=0.5) as response:  # noqa: S310
            payload = json.load(response)
    except (OSError, URLError, ValueError):
        return False
    return isinstance(payload, dict) and payload == {
        "pid": pid,
        "owner_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


def _request_shutdown(state: dict[str, object]) -> None:
    control_url = state["control_url"]
    token = state["owner_token"]
    request = Request(
        f"{control_url}/shutdown",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=2):  # noqa: S310
            return
    except (OSError, URLError) as exc:
        raise RuntimeError("owned runtime rejected the shutdown request") from exc


def _control_server(token: str, shutdown: threading.Event) -> ThreadingHTTPServer:
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/identity" or not self._authorized():
                self.send_error(404)
                return
            self._json({"pid": os.getpid(), "owner_token_sha256": token_hash})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/shutdown" or not self._authorized():
                self.send_error(404)
                return
            self._json({"status": "stopping"})
            shutdown.set()

        def _authorized(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {token}"

        def _json(self, value: dict[str, Any]) -> None:
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


if __name__ == "__main__":
    main()
