"""Real SDK + loopback Engine simulator, no model calls. Requires the dev environment.

Use a fresh --directory; optional --source reuses a check_report_memory fixture.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import httpx  # noqa: E402
import protocol_server as protocol  # noqa: E402
from check_report_memory import fixture  # noqa: E402
from test_client_run import BENCHMARK, _engine  # noqa: E402

import screamingface as sf  # noqa: E402


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Simulator(protocol._Server):
    def __init__(self, source: Path, cases: int) -> None:
        self.source, self.sha256, self.size = source, digest(source), source.stat().st_size
        self.benchmark = dict(
            BENCHMARK, id="contracteval", revision="memory-fixture", case_count=cases
        )
        self.urls: dict[str, str] = {}
        self.ready = threading.Condition()
        self.state = protocol.ProtocolState()
        ThreadingHTTPServer.__init__(self, ("127.0.0.1", 0), Handler)


class Handler(protocol._Handler):
    server: Simulator

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/v1/benchmarks/contracteval":
            self._json(HTTPStatus.OK, self.server.benchmark)
        elif path.startswith("/v1/"):
            response = _engine(httpx.Request("GET", "http://fixture" + self.path))
            self._raw(
                HTTPStatus(response.status_code), response.content, media_type="application/json"
            )
        else:
            super().do_GET()

    def _start(self) -> None:
        token = self.headers.get("URL4-Capability", "")
        with self.server.ready:
            self.server.urls[token] = parse_qs(urlsplit(self.path).query)["q"][0]
            self.server.ready.notify_all()
        super()._start()

    def _stream_run(self, token: str) -> None:
        with self.server.ready:
            assert self.server.ready.wait_for(lambda: token in self.server.urls, timeout=10)
            url4 = self.server.urls[token]
        frames = list(protocol._run_frames())
        frames[0]["data"] = {"url4": url4}
        frames[2] = protocol._frame(
            "ai.url4.result",
            {
                "body": None,
                "media_type": None,
                "artifact": {
                    "id": self.server.sha256,
                    "size_bytes": self.server.size,
                    "sha256": self.server.sha256,
                },
            },
            3,
        )
        for frame in frames:
            frame["subject"] = f"run-{token}"
            frame["source"] = f"/trace/run-{token}/node/root"
            protocol._send_server_text_frame(self.wfile, json.dumps(frame))
        with self.server.state.lock:
            self.server.state.expired_tokens.append(token)

    def _artifact(self) -> None:
        token, state = self.headers.get("URL4-Capability"), self.server.state
        with state.lock:
            assert token in state.minted_tokens and token not in state.expired_tokens
            state.artifact_requests.append((self.path, token))
        assert urlsplit(self.path).path == "/artifacts/" + self.server.sha256
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(self.server.size))
        self.end_headers()
        # INVARIANT: neither simulator nor client buffers the artifact body in RAM.
        with self.server.source.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                self.wfile.write(chunk)


def worker(args: argparse.Namespace) -> None:
    root = args.directory
    os.environ["SCREAMINGFACE_RESULTS_DIR"] = str(root)
    started = time.monotonic()
    if args.worker == "crash_decode":
        from screamingface._results import cases

        original = cases._insert_cases

        def crash(events, db):
            original(events, db)
            os._exit(73)

        cases._insert_cases = crash
    if args.worker in {"evaluate", "crash_decode"}:
        with sf.Client(engine_url=args.engine_url) as client:
            report = client.evaluate(
                [sf.Model("provider/opus", name=f"candidate-{i}") for i in range(args.candidates)],
                benchmark="contracteval",
                progress=False,
            )
    else:
        saved = sf.reports.list(directory=root)
        assert len(saved) == 1
        report = sf.reports.get(saved[0].id, directory=root)
    measure(args, report, started)


def measure(args: argparse.Namespace, report: sf.Report, started: float) -> None:
    root = args.directory
    assert len(report.candidates) == args.candidates
    for candidate in report.candidates:
        assert len(candidate.cases) == args.cases
        assert candidate.cases[0].input == "x" * args.prompt_bytes
        assert candidate.cases[-1].output == f"answer {args.cases - 1}"
    if args.worker == "crash_export":
        interrupt_export(report, root)
    target = report.export(root / (args.worker + ".json"))
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    evidence = {
        "candidates": len(report.candidates),
        "cases": sum(len(c.cases) for c in report.candidates),
        "export_bytes": target.stat().st_size,
        "export_sha256": digest(target),
        "peak_rss_bytes": peak_bytes,
        "elapsed_seconds": time.monotonic() - started,
    }
    assert peak_bytes < 512 * 1024 * 1024, evidence
    (root / (args.worker + "-metrics.json")).write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence), flush=True)


def interrupt_export(report: sf.Report, root: Path) -> None:
    from screamingface import _report_export

    original = _report_export.iter_report_json

    def interrupted(value):
        written = 0
        for chunk in original(value):
            yield chunk
            written += len(chunk.encode("utf-8"))
            if written > 1024:
                (root / "export-interrupted.json").write_text(
                    json.dumps({"generated_bytes": written})
                )
                os._exit(74)

    _report_export.iter_report_json = interrupted
    report.export(root / "offline.json")
    raise AssertionError("export did not reach interruption point")


def launch(args: argparse.Namespace, mode: str, directory: Path, url: str) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        mode,
        "--directory",
        str(directory),
        "--engine-url",
        url,
        "--candidates",
        str(args.candidates),
        "--cases",
        str(args.cases),
        "--prompt-bytes",
        str(args.prompt_bytes),
    ]
    with (directory / (mode + ".log")).open("w") as log:
        return subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, timeout=1200
        ).returncode


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidates", type=int, default=11)
    parser.add_argument("--cases", type=int, default=4182)
    parser.add_argument("--prompt-bytes", type=int, default=48000)
    parser.add_argument(
        "--worker",
        choices=["evaluate", "crash_decode", "crash_export", "local", "remote", "offline"],
    )
    parser.add_argument("--engine-url", default="")
    return parser.parse_args()


def main() -> None:
    args = arguments()
    if args.worker:
        worker(args)
        return
    root = args.directory
    assert not root.exists() or not any(root.iterdir()), "Use a fresh output directory"
    root.mkdir(parents=True, exist_ok=True)
    if args.source is None:
        fixture(root / "source", 1, args.cases, args.prompt_bytes)
        args.source = root / "source/fixture.json"
    server = Simulator(args.source, args.cases)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    normal, crashed = root / "normal", root / "crashed"
    try:
        code, before, after, downloads = online(args, server, normal, crashed, url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    finish(args, server, crashed, normal, url, code, before, after, downloads)


def online(args, server, normal, crashed, url):
    assert launch(args, "evaluate", normal, url) == 0, (normal / "evaluate.log").read_text()
    code = launch(args, "crash_decode", crashed, url)
    assert code == 73, (crashed / "crash_decode.log").read_text()
    requests = len(server.state.artifact_requests)
    assert launch(args, "local", crashed, url) == 0, (crashed / "local.log").read_text()
    assert len(server.state.artifact_requests) == requests
    from screamingface._results.store import ResultStore

    # Preserve evidence, but require re-fetch through the saved remote claims.
    for saved in ResultStore(crashed).list():
        if saved.path.exists():
            saved.path.rename(saved.path.with_suffix(".withheld"))
        index = saved.path.with_suffix(".sqlite3")
        if index.exists():
            index.rename(index.with_suffix(".withheld-index"))
    before = server.state.start_attempts
    assert launch(args, "remote", crashed, url) == 0, (crashed / "remote.log").read_text()
    after, downloads = server.state.start_attempts, len(server.state.artifact_requests)
    assert before == after == 2 * args.candidates
    assert downloads == 3 * args.candidates
    return code, before, after, downloads


def finish(args, server, crashed, normal, url, code, before, after, downloads):
    assert launch(args, "offline", crashed, url) == 0, (crashed / "offline.log").read_text()
    remote = json.loads((crashed / "remote-metrics.json").read_text())
    offline = json.loads((crashed / "offline-metrics.json").read_text())
    local = json.loads((crashed / "local-metrics.json").read_text())
    assert local["export_sha256"] == remote["export_sha256"] == offline["export_sha256"]
    code_export = launch(args, "crash_export", crashed, url)
    assert code_export == 74, (crashed / "crash_export.log").read_text()
    assert digest(crashed / "offline.json") == offline["export_sha256"]
    assert launch(args, "offline", crashed, url) == 0, (crashed / "offline.log").read_text()
    evidence = {
        "local_recovery": local,
        "export_exit_code": code_export,
        "normal": json.loads((normal / "evaluate-metrics.json").read_text()),
        "decode_exit_code": code,
        "remote_recovery": remote,
        "offline_recovery": offline,
        "run_starts_before_recovery": before,
        "run_starts_after_recovery": after,
        "artifact_downloads": downloads,
        "source_bytes": server.size,
    }
    (args.directory / "validation.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == "__main__":
    main()
