# E2E workbench · Unit 4 — local web UI: bundle viewer + run launcher

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A loopback-only web page where a developer picks a target (`replay` | `local`) and notebooks, starts the **same** pytest lane CI runs, watches its output live, and reads every evidence bundle (verdict, trace chain, log excerpts, executed notebook, cost) without opening files by hand.

**Architecture:** A dev-only FastAPI app in `packages/screamingface/tests/e2e/workbench/ui/`, started with `uv run --extra runtime python -m workbench.ui`. Four small modules:
- `bundles.py` reads bundles from disk.
- `render.py` turns an executed notebook into sandboxed HTML.
- `runs.py` spawns and streams one pytest run at a time.
- `app.py` wires routes and server-rendered HTML.

The UI never executes notebooks itself (spec §2 D4). It only launches `pytest tests/e2e/workbench/test_notebooks.py` with the workbench env vars and views what that writes.

**Tech Stack:** Python 3.12, FastAPI + uvicorn (already in the `runtime` extra), `nbconvert` (new **dev-group** dependency, for notebook HTML), `fastapi.testclient`, pytest. No JS framework. A few lines of inline JS subscribe to a Server-Sent Events stream.

**Spec:** `docs/spec/2026-10-16-e2e-notebook-workbench.md` §3.5 (updated by Task 1 of this plan).
**Depends on:** Unit 2 (the `e2e-notebook-workbench` branch: `runner.py`, `bundle.py`, `evidence.py`, `targets.py`, `conftest.py`).

## Owner decisions (2026-10-17)

- **Dev-only, next to the workbench.** It lives in `tests/e2e/workbench/ui/` and never ships in the SDK wheel. The spec's `screamingface workbench` CLI name is dropped. The entry points are `python -m workbench.ui` and a `just workbench-ui` recipe.
- **First version = viewer + launcher.** Hosted and preview targets, and their Access login (option B), wait for unit 3. No target that needs a login is offered.

## Global Constraints

- **Network exposure:** bind to `127.0.0.1` only. Refuse any request whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` (DNS-rebinding guard).
- **Request forgery:** every state-changing route (`POST /runs`, `POST /runs/{id}/cancel`) requires a per-launch random token (`secrets.token_urlsafe(32)`). The token is printed once in the startup URL and sent as the `X-Workbench-Token` header (or a hidden form field). Without it the route returns 403.
- **Keys:** the UI never accepts or displays a provider key or Access token. Paid runs read `OPENROUTER_API_KEY` from the UI process's own environment only.
- **Paid opt-in:** a `local` run needs both of the following, otherwise 400 with the reason:
  - an explicit "spends real tokens" checkbox (`confirm_paid=true`)
  - `OPENROUTER_API_KEY` present in the UI process environment
- **Concurrency:** one run at a time. The `local` target binds fixed ports 9105/9106/9108, so a second `POST /runs` while one is active returns 409.
- **Untrusted HTML:** executed-notebook outputs are untrusted. Render them only inside `<iframe sandbox="" srcdoc="…">`: no scripts, no same-origin, no forms. Escape everything else with `html.escape`.
- **Paths:** every bundle path from a URL is resolved and must stay inside the configured output root. Anything else returns 404, never a file read.
- **No new runtime dependencies.** `nbconvert` goes in the `dev` dependency group only.
- **Gates** (from `packages/screamingface`): `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`. Coverage does not measure `tests/`, so UI unit tests must be meaningful on their own.

## Review Focus

1. **A run that dies mid-way still shows its partial output, exit code and any bundles it wrote.** The run page never hangs on "running" after the process exits.
2. **Cancel kills the whole process group** (pytest, kernel, `screamingface up`, engine). Afterwards ports 9105/9106/9108 are free and the target's teardown ran.
3. **Bundles from an unzipped CI artifact** (`workbench-evidence/…`) display the same as local ones, including a bundle whose `trace.json` is missing or malformed. That one shows as "unreadable", it does not crash the page.
4. **A hostile notebook output** (`<script>`, `<img onerror>`, a `javascript:` link) does not execute in the UI origin.
5. **A browser on another site cannot start a run.** A cross-origin POST without the token gets 403.

---

### Task 1: Spec + dependency + package skeleton

**Files:**
- Modify: `docs/spec/2026-10-16-e2e-notebook-workbench.md` §3.5. Replace the `screamingface workbench` text with the dev-only location and the two owner decisions above, plus the security constraints.
- Modify: `packages/screamingface/pyproject.toml`. Add `"nbconvert>=7.16"` to the `dev` dependency group, next to `nbclient`/`nbformat`.
- Create: `packages/screamingface/tests/e2e/workbench/ui/__init__.py` (empty)
- Create: `packages/screamingface/tests/e2e/workbench/ui/test_ui_skeleton.py`

- [ ] **Step 1: Failing test.**

```python
# tests/e2e/workbench/ui/test_ui_skeleton.py
def test_nbconvert_is_importable_in_the_dev_env() -> None:
    from nbconvert import HTMLExporter  # noqa: F401
```

- [ ] **Step 2:** Run `uv run pytest tests/e2e/workbench/ui -q`. Expected: FAIL with `ModuleNotFoundError: nbconvert`.
- [ ] **Step 3:** Add the dependency, then run `uv lock && uv sync`.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** Commit `chore(e2e): workbench UI skeleton and nbconvert dev dependency`. Include the spec §3.5 edit.

---

### Task 2: `bundles.py` — discover and load bundles safely

**Files:**
- Create: `packages/screamingface/tests/e2e/workbench/ui/bundles.py`
- Create: `packages/screamingface/tests/e2e/workbench/ui/test_bundles.py`

**Interfaces (Produces):**

```python
@dataclass(frozen=True)
class BundleSummary:
    key: str                 # path relative to root, posix, e.g. "runs/20261017-101500-ab12/replay/quickstart"
    target: str
    notebook: str
    passed: bool | None      # None when trace.json is missing/unreadable
    trace_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    modified: float          # mtime of trace.json (or of the dir)

@dataclass(frozen=True)
class BundleDetail:
    summary: BundleSummary
    trace: dict[str, Any] | None
    logs: dict[str, str]     # hop name -> text (already redacted by the bundle writer)
    notebook_path: Path | None

def discover(root: Path, *, max_depth: int = 4) -> list[BundleSummary]   # newest first
def load(root: Path, key: str) -> BundleDetail                           # raises BundleNotFound
class BundleNotFound(LookupError): ...
```

A bundle is any directory under `root` that contains `trace.json` or `executed.ipynb`. `target` and `notebook` are the last two path components. Discovery stops at `max_depth` and does not follow symlinks.

- [ ] **Step 1: Failing tests.**

```python
# tests/e2e/workbench/ui/test_bundles.py
import json
import os
from pathlib import Path

import pytest

from workbench.ui.bundles import BundleNotFound, discover, load


def _bundle(root: Path, rel: str, trace: object | None) -> Path:
    d = root / rel
    (d / "logs").mkdir(parents=True)
    if trace is not None:
        (d / "trace.json").write_text(trace if isinstance(trace, str) else json.dumps(trace))
    (d / "logs" / "engine.txt").write_text("trace_id=abc")
    return d


def test_discovers_local_and_run_scoped_bundles_newest_first(tmp_path: Path) -> None:
    old = _bundle(tmp_path, "replay/quickstart", {"passed": True, "trace_ids": ["a" * 32], "reasons": []})
    new = _bundle(tmp_path, "runs/r1/local/quickstart", {"passed": False, "trace_ids": [], "reasons": ["x"]})
    os.utime(old / "trace.json", (1, 1))
    found = discover(tmp_path)
    assert [b.key for b in found] == ["runs/r1/local/quickstart", "replay/quickstart"]
    assert found[0].passed is False and found[0].reasons == ("x",)
    assert (found[1].target, found[1].notebook) == ("replay", "quickstart")


def test_a_malformed_trace_is_listed_as_unreadable_not_raised(tmp_path: Path) -> None:
    _bundle(tmp_path, "replay/broken", "{not json")
    (only,) = discover(tmp_path)
    assert only.passed is None


def test_load_returns_logs_and_notebook_path(tmp_path: Path) -> None:
    d = _bundle(tmp_path, "replay/quickstart", {"passed": True, "trace_ids": [], "reasons": []})
    (d / "executed.ipynb").write_text("{}")
    detail = load(tmp_path, "replay/quickstart")
    assert detail.logs == {"engine": "trace_id=abc"}
    assert detail.notebook_path == d / "executed.ipynb"


@pytest.mark.parametrize("key", ["../etc", "/etc/passwd", "replay/../../x", "replay/quickstart/../../.."])
def test_keys_outside_the_root_are_not_found(tmp_path: Path, key: str) -> None:
    _bundle(tmp_path, "replay/quickstart", {"passed": True})
    with pytest.raises(BundleNotFound):
        load(tmp_path, key)


def test_symlinked_directories_are_not_followed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    _bundle(outside, "replay/leak", {"passed": True})
    (tmp_path / "link").symlink_to(outside)
    assert discover(tmp_path) == []
```

- [ ] **Step 2:** Run `uv run pytest tests/e2e/workbench/ui/test_bundles.py -q`. Expected: FAIL with `ModuleNotFoundError: workbench.ui.bundles`.
- [ ] **Step 3: Implement.**

```python
# tests/e2e/workbench/ui/bundles.py
"""Read workbench evidence bundles from disk for the UI (spec §3.3 layout). Read-only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MARKERS = ("trace.json", "executed.ipynb")


class BundleNotFound(LookupError):
    """The key does not name a bundle inside the root."""


@dataclass(frozen=True)
class BundleSummary:
    key: str
    target: str
    notebook: str
    passed: bool | None
    trace_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    modified: float


@dataclass(frozen=True)
class BundleDetail:
    summary: BundleSummary
    trace: dict[str, Any] | None
    logs: dict[str, str]
    notebook_path: Path | None


def _read_trace(directory: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((directory / "trace.json").read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _summary(root: Path, directory: Path) -> BundleSummary:
    trace = _read_trace(directory)
    marker = directory / "trace.json"
    modified = (marker if marker.is_file() else directory).stat().st_mtime
    passed = trace.get("passed") if trace is not None else None
    return BundleSummary(
        key=directory.relative_to(root).as_posix(),
        target=directory.parent.name,
        notebook=directory.name,
        passed=passed if isinstance(passed, bool) else None,
        trace_ids=tuple(str(t) for t in (trace or {}).get("trace_ids", []) if isinstance(t, str)),
        reasons=tuple(str(r) for r in (trace or {}).get("reasons", []) if isinstance(r, str)),
        modified=modified,
    )


def discover(root: Path, *, max_depth: int = 4) -> list[BundleSummary]:
    root = root.resolve()
    found: list[BundleSummary] = []
    frontier = [(root, 0)]
    while frontier:
        directory, depth = frontier.pop()
        if any((directory / m).is_file() for m in _MARKERS) and directory != root:
            found.append(_summary(root, directory))
            continue
        if depth >= max_depth:
            continue
        for child in directory.iterdir():
            if child.is_dir() and not child.is_symlink():
                frontier.append((child, depth + 1))
    return sorted(found, key=lambda b: b.modified, reverse=True)


def _resolve(root: Path, key: str) -> Path:
    root = root.resolve()
    candidate = (root / key).resolve()
    if candidate == root or root not in candidate.parents or not candidate.is_dir():
        raise BundleNotFound(key)
    if not any((candidate / m).is_file() for m in _MARKERS):
        raise BundleNotFound(key)
    return candidate


def load(root: Path, key: str) -> BundleDetail:
    directory = _resolve(root, key)
    logs_dir = directory / "logs"
    logs = (
        {p.stem: p.read_text(errors="replace") for p in sorted(logs_dir.glob("*.txt"))}
        if logs_dir.is_dir()
        else {}
    )
    notebook = directory / "executed.ipynb"
    return BundleDetail(
        summary=_summary(root.resolve(), directory),
        trace=_read_trace(directory),
        logs=logs,
        notebook_path=notebook if notebook.is_file() else None,
    )
```

- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit `test(e2e): workbench UI reads bundles safely`.

---

### Task 3: `render.py` — executed notebook to sandboxed HTML

**Files:**
- Create: `packages/screamingface/tests/e2e/workbench/ui/render.py`
- Create: `packages/screamingface/tests/e2e/workbench/ui/test_render.py`

**Interfaces (Produces):**
- `notebook_html(path: Path) -> str`: the full HTML document for the notebook, built with nbconvert `HTMLExporter(template_name="classic")`, with `exclude_input_prompt=True`, `exclude_output_prompt=True`, and widget state dropped.
- `sandboxed_iframe(document: str) -> str`: returns `<iframe sandbox="" referrerpolicy="no-referrer" srcdoc="{html.escape(document, quote=True)}" …></iframe>`.

- [ ] **Step 1: Failing tests.**

```python
# tests/e2e/workbench/ui/test_render.py
from pathlib import Path

import nbformat

from workbench.ui.render import notebook_html, sandboxed_iframe


def _nb(tmp_path: Path, html_output: str) -> Path:
    cell = nbformat.v4.new_code_cell("x")
    cell.outputs = [nbformat.v4.new_output("display_data", data={"text/html": html_output})]
    path = tmp_path / "executed.ipynb"
    nbformat.write(nbformat.v4.new_notebook(cells=[cell]), path)
    return path


def test_notebook_renders_to_a_full_document(tmp_path: Path) -> None:
    doc = notebook_html(_nb(tmp_path, "<b>score 0.9</b>"))
    assert "<html" in doc.lower() and "score 0.9" in doc


def test_iframe_has_an_empty_sandbox_and_escaped_srcdoc() -> None:
    frame = sandboxed_iframe('<script>alert(1)</script><a href="javascript:x">y</a>')
    assert 'sandbox=""' in frame
    assert "<script>" not in frame  # escaped into the attribute
    assert "&lt;script&gt;" in frame
```

- [ ] **Step 2:** Run `uv run pytest tests/e2e/workbench/ui/test_render.py -q`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement.**

```python
# tests/e2e/workbench/ui/render.py
"""Executed notebook → HTML, shown only inside an empty-sandbox iframe (untrusted outputs)."""

from __future__ import annotations

import html
from pathlib import Path

import nbformat
from nbconvert import HTMLExporter


def notebook_html(path: Path) -> str:
    nb = nbformat.read(path, as_version=4)
    nb.metadata.pop("widgets", None)  # widget state cannot render outside a kernel
    exporter = HTMLExporter(template_name="classic")
    exporter.exclude_input_prompt = True
    exporter.exclude_output_prompt = True
    body, _ = exporter.from_notebook_node(nb)
    return body


def sandboxed_iframe(document: str) -> str:
    return (
        '<iframe class="nb" sandbox="" referrerpolicy="no-referrer" '
        f'srcdoc="{html.escape(document, quote=True)}"></iframe>'
    )
```

- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit `test(e2e): workbench UI renders notebooks in an empty sandbox`.

---

### Task 4: `runs.py` — one pytest run at a time, streamed, cancellable

**Files:**
- Create: `packages/screamingface/tests/e2e/workbench/ui/runs.py`
- Create: `packages/screamingface/tests/e2e/workbench/ui/test_runs.py`

**Interfaces (Produces):**

```python
KNOWN_UI_TARGETS = ("replay", "local")

@dataclass(frozen=True)
class RunRequest:
    target: str                    # in KNOWN_UI_TARGETS
    notebooks: tuple[str, ...]     # stems; empty = all
    confirm_paid: bool = False

@dataclass
class Run:
    id: str
    request: RunRequest
    out_dir: Path                  # <root>/runs/<id>
    lines: list[str]               # appended as they arrive, capped at 20_000 (oldest dropped, counted)
    dropped: int
    returncode: int | None         # None while running
    cancelled: bool

class RunRejected(ValueError): ...      # 400: invalid request / paid gate
class RunBusy(RuntimeError): ...        # 409: a run is active

class RunManager:
    def __init__(self, root: Path, *, workdir: Path, environ: Mapping[str, str],
                 spawn: Callable[[list[str], dict[str, str], Path], subprocess.Popen[str]] = _spawn) -> None
    def command(self, request: RunRequest, out_dir: Path) -> tuple[list[str], dict[str, str]]
    def start(self, request: RunRequest) -> Run
    def get(self, run_id: str) -> Run                       # KeyError if unknown
    def cancel(self, run_id: str) -> Run
    def follow(self, run_id: str, start: int) -> Iterator[str]  # yields lines from index `start`; returns when the run ends
```

**`command()`:**
- **argv:** `[sys.executable, "-m", "pytest", "tests/e2e/workbench/test_notebooks.py", "-v", "-rs"]`, plus `-k "<stem> or <stem>"` when `notebooks` is non-empty. Each stem must match `^[a-z0-9_-]+$`, otherwise `RunRejected`.
- **env:** a copy of `environ` with these set:
  - `SCREAMINGFACE_TEST_E2E=1`
  - `SCREAMINGFACE_WORKBENCH_TARGET=<target>`
  - `SCREAMINGFACE_WORKBENCH_OUT=<out_dir>`
  - `SCREAMINGFACE_WORKBENCH_REQUIRE_ALL=1`
  - `SCREAMINGFACE_TEST_PAID=1`, only for `local`
- **Gating:** `local` without `confirm_paid` or without `OPENROUTER_API_KEY` in `environ` raises `RunRejected` with the reason. An unknown target raises `RunRejected`.

**`_spawn`:** `subprocess.Popen(argv, env=env, cwd=workdir, stdout=PIPE, stderr=STDOUT, text=True, bufsize=1, start_new_session=True)`. The process starts in its own session so `cancel()` can `os.killpg(proc.pid, SIGTERM)`, then SIGKILL after 15 s. That kills the whole group, including the kernel and `screamingface up`. Note that `targets.local_stack`'s `finally` runs `down` on SIGTERM, because pytest turns SIGTERM into teardown via `KeyboardInterrupt`. Task 4 verifies this (Review Focus 2).

**Reader:** a daemon thread reads stdout lines into `Run.lines` under a lock and sets `returncode` on EOF. `follow()` waits on a `threading.Condition`.

**Run id:** `time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)`.

- [ ] **Step 1: Failing tests.** Use an injected `spawn` that runs a tiny Python script, so these tests don't need pytest-in-pytest or a stack:

```python
# tests/e2e/workbench/ui/test_runs.py
import subprocess
import sys
from pathlib import Path

import pytest

from workbench.ui.runs import RunBusy, RunManager, RunRejected, RunRequest


def _fake_spawn(script: str):
    def spawn(argv, env, cwd):
        return subprocess.Popen(
            [sys.executable, "-c", script], env=env, cwd=cwd, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
        )
    return spawn


def _manager(tmp_path: Path, script: str = "print('a'); print('b')", **env: str) -> RunManager:
    return RunManager(tmp_path, workdir=tmp_path, environ=env, spawn=_fake_spawn(script))


def test_command_sets_the_workbench_env_and_filters_notebooks(tmp_path: Path) -> None:
    argv, env = _manager(tmp_path).command(RunRequest("replay", ("quickstart",)), tmp_path / "o")
    assert argv[-2:] == ["-k", "quickstart"]
    assert env["SCREAMINGFACE_WORKBENCH_TARGET"] == "replay"
    assert env["SCREAMINGFACE_WORKBENCH_REQUIRE_ALL"] == "1"
    assert env["SCREAMINGFACE_WORKBENCH_OUT"] == str(tmp_path / "o")
    assert "SCREAMINGFACE_TEST_PAID" not in env


@pytest.mark.parametrize(
    ("request_", "env"),
    [
        (RunRequest("local", (), confirm_paid=False), {"OPENROUTER_API_KEY": "k"}),
        (RunRequest("local", (), confirm_paid=True), {}),
        (RunRequest("prod", ()), {}),
        (RunRequest("replay", ("x or y",)), {}),
    ],
)
def test_invalid_or_ungated_requests_are_rejected(tmp_path, request_, env) -> None:
    with pytest.raises(RunRejected):
        _manager(tmp_path, **env).start(request_)


def test_output_is_streamed_and_the_exit_code_recorded(tmp_path: Path) -> None:
    m = _manager(tmp_path)
    run = m.start(RunRequest("replay", ()))
    assert list(m.follow(run.id, 0)) == ["a", "b"]
    assert m.get(run.id).returncode == 0


def test_a_second_run_while_one_is_active_is_busy(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="import time; time.sleep(30)")
    first = m.start(RunRequest("replay", ()))
    with pytest.raises(RunBusy):
        m.start(RunRequest("replay", ()))
    m.cancel(first.id)


def test_cancel_kills_the_process_group(tmp_path: Path) -> None:
    script = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print('child', flush=True); time.sleep(60)"
    )
    m = _manager(tmp_path, script=script)
    run = m.start(RunRequest("replay", ()))
    next(m.follow(run.id, 0))
    done = m.cancel(run.id)
    assert done.cancelled and done.returncode is not None
    # The grandchild is in the same session, so it is gone too.
    out = subprocess.run(["pgrep", "-f", "time.sleep\\(60\\)"], capture_output=True, text=True)
    assert out.stdout.strip() == ""


def test_a_crashing_run_ends_with_its_exit_code(tmp_path: Path) -> None:
    m = _manager(tmp_path, script="print('x'); raise SystemExit(3)")
    run = m.start(RunRequest("replay", ()))
    assert list(m.follow(run.id, 0)) == ["x"]
    assert m.get(run.id).returncode == 3
```

- [ ] **Step 2:** Run `uv run pytest tests/e2e/workbench/ui/test_runs.py -q`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Implement** `runs.py` with the interfaces above. Use one `threading.Lock` for the active-run check and one `Condition` per run.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit `test(e2e): workbench UI run manager — one run, streamed, group-cancelled`.

---

### Task 5: `app.py` — routes, guards, pages

**Files:**
- Create: `packages/screamingface/tests/e2e/workbench/ui/app.py`
- Create: `packages/screamingface/tests/e2e/workbench/ui/__main__.py`
- Create: `packages/screamingface/tests/e2e/workbench/ui/test_app.py`

**Interfaces (Produces):**
- `create_app(*, root: Path, manager: RunManager, token: str, port: int, notebooks: Sequence[str]) -> FastAPI`
- `main(argv: Sequence[str] | None = None) -> None` in `__main__.py`:
  - **Arguments:** `--out` (default `./workbench-out`), `--port` (default `9112`), `--open/--no-open`.
  - **Startup:** generates the token, prints `http://127.0.0.1:<port>/?token=<token>`, and runs uvicorn on `127.0.0.1`.
  - **Notebook list:** the notebook stems come from `workbench.build_notebooks.NOTEBOOK_DIR`.

**Routes:**

| Method | Path | Does |
|---|---|---|
| GET | `/` | Run form (target radio, notebook checkboxes, paid checkbox shown only for `local`) and the bundle table from `discover(root)`: verdict pill, target, notebook, trace ids, reasons, time. Shows the `local` option as disabled with the reason when `OPENROUTER_API_KEY` is absent. |
| GET | `/bundles/{key:path}` | `load(root, key)`. Shows the verdict, the hop table from `trace.json` (`hops[].name/found/missing_ids`), the reasons, the cost and cache hits from `trace.result.candidates`, one collapsible `<pre>` per log hop, and `sandboxed_iframe(notebook_html(...))`. Returns 404 on `BundleNotFound`. |
| POST | `/runs` | Form or JSON `RunRequest`. Requires the token. Calls `manager.start`. Returns 303 to `/runs/{id}`. 400 on `RunRejected`, 409 on `RunBusy`. |
| GET | `/runs/{id}` | Live page: status, a `<pre id="log">` filled by EventSource, a Cancel button (POST with token), and links to the bundles under `runs/{id}/` once the run finishes. |
| GET | `/runs/{id}/events?from=N` | `text/event-stream`. One `data:` line per output line from `manager.follow`, then a final `event: end` with `{"returncode": …, "cancelled": …}`. |
| POST | `/runs/{id}/cancel` | Requires the token. Calls `manager.cancel`. Returns 303 back to the run page. |

**Middleware:**
- Reject a request whose `Host` header is not in `{f"127.0.0.1:{port}", f"localhost:{port}"}` with 400.
- Set these headers on every response: `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-src 'self'; form-action 'self'; base-uri 'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.

The token travels in the query string on first load and is then stored in a hidden form field. JS reads it from that field. Don't use cookies, so there is no ambient credential.

- [ ] **Step 1: Failing tests** (`fastapi.testclient.TestClient` with `base_url="http://127.0.0.1:9112"` and a `RunManager` using `_fake_spawn`):
  - `test_index_lists_bundles_and_the_run_form`
  - `test_wrong_host_is_rejected`: `Host: evil.example:9112` returns 400.
  - `test_post_without_token_is_forbidden`: returns 403, and no process is spawned (the fake spawn records calls).
  - `test_post_with_token_starts_and_redirects`: returns 303 to `/runs/<id>`. Then `/runs/<id>/events` streams `data: a`, `data: b` and an `end` event with `returncode 0`.
  - `test_busy_returns_409` and `test_local_without_key_returns_400_with_reason`
  - `test_bundle_page_shows_hops_logs_and_a_sandboxed_notebook`: asserts `sandbox=""`, the hop names, and the log text, HTML-escaped.
  - `test_bundle_key_traversal_is_404` (`/bundles/..%2F..%2Fetc`)
  - `test_responses_carry_csp_and_frame_deny`
  - `test_a_malformed_bundle_shows_as_unreadable` (Review Focus 3)
- [ ] **Step 2:** Run `uv run pytest tests/e2e/workbench/ui/test_app.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `app.py`.
  - HTML is built from small functions that return strings, with every dynamic value passed through `html.escape`.
  - One shared `<style>` block. Use the system font stack and a neutral palette with green/red/grey verdict pills, plus `prefers-color-scheme` dark tokens.
  - No external assets.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit `test(e2e): workbench UI app — viewer, launcher, loopback/token/CSP guards`.

---

### Task 6: Real end-to-end through the UI + entry points + docs

**Files:**
- Create: `packages/screamingface/tests/e2e/workbench/ui/test_ui_e2e.py`. It is gated like the replay lane (`require_e2e_stack()` and ifeval assets).
- Modify: `packages/screamingface/justfile`. Add:

```just
[doc("Open the e2e workbench UI (viewer + launcher) on 127.0.0.1:9112")]
workbench-ui out="./workbench-out":
    uv run --extra runtime python -m workbench.ui --out {{out}}
```

  `python -m workbench.ui` resolves because the recipe runs with `PYTHONPATH=tests/e2e`. Set that in the recipe, or have `__main__` insert the path itself; choose one and test it.
- Modify: `packages/screamingface/tests/e2e/workbench/README.md`. Add a "UI" section: how to start it, what each page shows, the security model (loopback, token, sandboxed notebooks), and the one-run-at-a-time rule.

- [ ] **Step 1: The e2e test.** Using `TestClient` and the **real** `RunManager` (no fake spawn):
  1. POST a `replay` run for `quickstart`.
  2. Follow its events to the end and assert `returncode == 0`.
  3. Load `/` and assert the new `runs/<id>/replay/quickstart` bundle is listed with a PASS pill.
  4. Load its bundle page and assert both hops are `found` and the iframe is present.
- [ ] **Step 2:** Run it for real:

```sh
SCREAMINGFACE_TEST_E2E=1 SCREAMINGFACE_E2E_ASSETS=~/.screamingface/benchmark-assets \
  uv run --extra runtime pytest tests/e2e/workbench/ui/test_ui_e2e.py -v -rs
```

  Expected: PASS.
- [ ] **Step 3: Manual smoke.**
  1. Run `uv run --extra runtime python -m workbench.ui --out ./workbench-out` and open the printed URL.
  2. Start a replay run from the page and watch the log stream.
  3. Open the bundle and check that the notebook renders inside the frame.
  4. Cancel a second run mid-way and confirm `lsof -iTCP:9105 -iTCP:9106 -iTCP:9108 -sTCP:LISTEN` is empty afterwards.

  Record what you observed in the ledger.
- [ ] **Step 4:** Commit `test(e2e): workbench UI end-to-end through a real replay run; just workbench-ui`.

## Out of scope (recorded, not dropped)

- **Hosted and preview targets and the Access login in the UI:** these come with unit 3. When they land, the UI will log in through the SDK and pass `SCREAMINGFACE_ACCESS_TOKEN` to the child process.
- **A trace-waterfall or span view:** the UI links trace ids and shows log excerpts. OTLP span collection is deferred in spec §3.4.1.
- **Persisting a run's history across UI restarts:** history is rebuilt from `workbench-out/runs/*` on disk. The live stream is kept in memory only.

## Done when

- Tasks 1–6 are committed on the unit 2 branch (or a branch stacked after PR 2 merges; no stacked PRs).
- All gates are green, and the UI e2e test passes on replay.
- The manual smoke in Task 6 Step 3 is recorded in the ledger.
- At PR-open: one `repo-dev-processes` leaf under OME-1636.
