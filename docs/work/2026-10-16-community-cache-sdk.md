---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-16
finished: 2026-10-16
---

# community-cache-sdk — `sf.cache.pull_from_remote` and `use_cache=` (epic OME-1311, PR 3/4)

## Intent

A signed-in user of a local engine can pull the community request cache into their local
gateway with one call — `sf.cache.pull_from_remote()` in a notebook or `screamingface cache
pull` in a shell — and every later local run hits those rows for free. The local gateway now
caches by default, and `evaluate(..., use_cache=False)` opts one run out. Stacked on PR 2
(#1439, OME-1635) and PR 1 (#1433, OME-1631). Spec decision 14 and plan "PR 3"
(`docs/spec/2026-10-15-community-cache.md`, `docs/plan/2026-10-15-community-cache.md`), as
settled item by item with the owner on 2026-10-16.

## Planned changes

- `packages/screamingface/src/screamingface/cache.py` (new, public) — `pull_from_remote`,
  `PullResult`, `CachePullError`.
- `packages/screamingface/src/screamingface/_cache/` (new, private):
  - `pages.py` — the hosted page client (own httpx session against `url`, Access auth, streamed
    `GET /v1/cache/entries`, gzip, replay-safe, problem+json → SDK errors) and the NDJSON page
    reader (header / rows / trailer; a page without its trailer is discarded);
  - `pull.py` — the pull loop (count on the first request, revisions on every header, page N
    loaded while N+1 downloads, transient retries with backoff, the in-memory cursor per
    `(url, models)`);
  - `local.py` — the local side: `require_runtime_extra()`, plugin loading for the revisions,
    the lazy `sqlite_loader` import, the data-dir database path, loader refusals → messages;
  - `progress.py` — notebook card (IPython display handle) and terminal line, `evaluate`'s
    tri-state.
- `client.py`, `_default_client.py`, the evaluation runner and transport — `use_cache: bool =
  True` carried like `capture` to `Cache-Control: no-cache` on the run request.
- `_runtime/bootstrap.py` — `AIGW_REQUEST_CACHE_ENABLED=true` in `LOCAL_GATEWAY_DEFAULTS`.
- `_runtime/cli.py` — `screamingface cache pull [--model]… [--url] [--data-dir]`.
- `__init__.py`, `tests/public_surface_snapshot.json`, `README.md`, `CHANGELOG.md`.
- Spec decisions 9 and 14, out of scope, and the plan (PR 3, new PR 4) updated to the settled
  design.

## Test plan

- Page reader: header, rows and trailer parsed line by line; a gzip body; a missing trailer is
  a cut page; a malformed line is refused; `remaining` read when present.
- Page client (`httpx.MockTransport`): path and params (`count=true` only on the first request,
  repeated `model`, `after`), `Accept-Encoding: gzip`, the replay-safe extension, 401 →
  `AuthenticationError`, 422 → the problem detail, transport failure → `EngineUnavailableError`.
- Pull loop (fake page source + fake loader): pages walk to `next: null` and every page is
  loaded once; revisions are checked on every header and a mismatch stops the pull with nothing
  more loaded; a transient failure is retried and a persistent one raises with the counts so
  far; a repeat call with the same `url` and filter continues from the last committed page, a
  different filter starts over; a finished pull's next call starts over; `PullResult` counts.
- Local side: missing runtime extra → install message before any request; the database path
  follows the data dir; `not_a_gateway_database` / `outdated_gateway_database` → "run
  `screamingface up`" messages.
- Progress: off when piped and not forced; the terminal line carries rows, remaining, added and
  bytes; the final line for finished and interrupted; the notebook path updates one display.
- `use_cache`: `False` puts `Cache-Control: no-cache` on the run request for Recipes and raw
  URL4, sync and async; `True` sends no such header; a non-bool is a `TypeError`.
- Local default: `LOCAL_GATEWAY_DEFAULTS` turns the cache on, and an exported `false` wins.
- CLI: `cache pull` parses `--model` (repeatable), `--url`, `--data-dir`, calls the same function
  with progress on, and maps finished / refused / interrupted to exit 0 / 1 / 130.
- Public surface: `sf.cache` pinned in the snapshot; `import screamingface` still loads no
  `aigateway`.

## Acceptance

- `sf.cache.pull_from_remote()` and `screamingface cache pull` load the hosted community cache
  into the local gateway database, with progress, and a repeat call in the same process
  continues an interrupted pull.
- A local run then hits pulled rows; `evaluate(..., use_cache=False)` opts a run out.
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `screamingface/cache.py` (`pull_from_remote`, `PullResult`, `CachePullError`);
  `screamingface/_cache/{pages,remote,local,pull,progress}.py`; `use_cache` through
  `_evaluation/model.py` (Candidate field + `_without_cache`), `_evaluation/runner.py`,
  `_evaluation/url4.py`, `_engine/transport.py` (`_cache_headers`), `client.py`,
  `_default_client.py`; `_runtime/bootstrap.py` (cache on by default); `_runtime/cli.py`
  (`cache pull`); `__init__.py`; `README.md`; `CHANGELOG.md`. Tests: `test_use_cache.py`,
  `test_cache_{pages,remote,local,pull,progress,public,cli}.py`. Spec decisions 9 and 14, out
  of scope, and the plan (PR 3, new PR 4) updated to the design settled with the owner.
- **Commits:** `docs: settle the SDK surface for the community-cache pull …`;
  `feat(screamingface): sf.cache.pull_from_remote, use_cache=, and the local cache on by default`.
- **Gates:** `run_gates.py screamingface` green except append-only (run with
  `--skip-append-only` until the approval manifest exists): ruff, format, pyright, pytest with
  coverage ≥ 95%, notebooks, build, distribution. New tests: 123 passed. The local side was also
  checked against the real gateway (runtime extra installed temporarily): the plugins loaded
  give `openrouter_adapter` beside the core revisions, and a reloaded row adds nothing.
- **Deviations:**
  - Prior tests changed, owner-approved (2026-10-16): the two local-defaults tests in
    `test_runtime_cli.py` gain `AIGW_REQUEST_CACHE_ENABLED`; `test_public_surface.py` pins
    `screamingface.cache`; `public_surface_snapshot.json` regenerated (+`sf.cache`,
    +`use_cache` on three `evaluate` signatures). `test_parser_exposes_public_commands` is NOT
    changed (it parses bare commands; `cache` needs a subcommand) — `cache pull` is covered in
    `test_cache_cli.py`.
  - Rows load in 500-row batches as a page streams in, one transaction per batch, rather than
    one transaction per page (spec decision 11): it bounds client memory on a ~235 MB page and
    overlaps download with load without threads. The cursor still advances only past a page
    that ended with its trailer, and loading is idempotent, so the guarantees are unchanged.
  - The runtime-extra check reuses the runtime's module probe but not `require_runtime_extra()`,
    which also writes the gateway's env defaults into `os.environ` — wrong for a notebook process.
  - `main` in `_runtime/cli.py` gains `PLR0915` beside its existing `C901, PLR0912` noqa (it was
    at the statement limit).
