---
ticket: OME-1639
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

## Review follow-up 1 — errors outside the SDK's own types (2026-10-17, PR #1446 review)

- **Intent:** a failure the pull loop did not anticipate must still stop the progress display
  and, where it is a known local or download failure, reach the caller as a `CachePullError`
  carrying the counts so far — not a raw traceback with the card stuck on "pulling…".
- **Planned:** `_cache/local.py` — `load()` turns `sqlite3.Error` into `CachePullError`
  (`local_load_failed`, "call again" hint); `_cache/remote.py` — `httpx.DecodingError` is
  transient like a transport failure; `_cache/pull.py` — `run_pull` stops the display on any
  other exception and re-raises it unchanged.
- **Tests (append-only):** `test_cache_local.py` locked database → `local_load_failed` with the
  halfway result; `test_cache_remote.py` corrupt gzip body → `TransientPageError`;
  `test_cache_pull.py` an unexpected error stops the display and reaches the caller as itself.
- **Outcome:** done as planned. Three new tests (no prior test touched); all `screamingface`
  gates green. `prepare()` was left alone: it touches no SQLite (only a file-exists check and the
  plugin revisions), so there is nothing there to convert.

## Review follow-up 2 — which data dir a pull writes to (2026-10-17, PR #1446 review)

- **Decision (owner, 2026-10-17):** document, don't add `data_dir=`. `pull_from_remote` writes to
  `default_data_dir()`, the same stack `sf.connect()` routing discovers (`_runtime/detect.py`);
  a stack under `up --data-dir` is already invisible to the SDK, and the CLI's
  `cache pull --data-dir` covers it.
- **Outcome:** docstring of `sf.cache.pull_from_remote` names the database and both ways to
  target another stack. No code or test change; public surface unchanged.

## Review follow-ups 3 + 4 — what a repeat call resumes (2026-10-17, PR #1446 review)

- **Intent:** a repeat call resumes only a cursor that loaded into the same database (3), and
  only one that completed at least a page (4) — so `resumed=True` is never reported for a pull
  that did nothing, and a pull into another database never skips the pages it never received.
- **Done:** `Destination` gains `name` (`LocalGateway`: its database path); the cursor records
  its destination and is continued only into it, otherwise a fresh one replaces it. The cursor is
  stored in `_CURSORS` when a page completes, not when the call starts. The key stays
  `(origin, models)`, so `test_an_interrupted_pull_keeps_its_cursor_for_the_next_call` is
  unchanged; consequence: a call into database B replaces A's cursor (A starts over later —
  costs only time, loading is idempotent).
- **Tests (append-only):** another database starts from the first page with `resumed=False`; a
  refused destination and a failed first page each leave `_CURSORS` empty and the next call
  unresumed. The two test stand-in gateways gain a `name` attribute (insert-only).
- **Gates:** all `screamingface` gates green.

## Review follow-up 5 — a resumed pull's ETA (2026-10-17, PR #1446 review)

- **Done:** `Snapshot` gains `rows_at_start` (default 0); `eta_s` divides only the rows this call
  read by this call's elapsed time. `_Loop` records the cursor's `rows_read` when the call starts.
- **Tests (append-only):** `test_cache_progress.py` ETA of a resumed snapshot; `test_cache_pull.py`
  a resumed call's snapshots carry where the call started. Gates green.

## Review follow-up 6 — rate limits are transient (2026-10-17, PR #1446 review)

- **Why it mattered:** the Engine's own cache route answers `429` + `Retry-After`
  (`CommunityCacheRateLimited`), which the pull treated as a permanent refusal.
- **Done:** `remote.py` uses the SDK's shared `_core.retry._RETRYABLE_STATUS` (408, 429, 502–504,
  520–524) instead of its own {502, 503, 504}, and `TransientPageError` carries
  `_retry_after_seconds(response)`. The retry waits `max(backoff, min(Retry-After, 60 s))`.
  500 stays permanent, as in the shared set.
- **Tests (append-only):** the shared statuses are transient; a 429's `Retry-After` is carried;
  the wait honours, ignores (shorter than backoff) and caps the hint. Gates green.

## Review follow-ups 7–10 (2026-10-17, PR #1446 review)

- **7 — the database is checked before any request.** `LocalGateway.prepare()` calls the loader's
  new public `check_database()` (added to PR #1433 in `baf7f1d3f`, merged up the stack) in place
  of the file-exists check: a missing, foreign or unmigrated database is refused before the
  sign-in, the counted first page and the download, and even when the filter matches no rows. A
  `sqlite3.Error` there is `local_load_failed`, shared with `load()` via `_unwritable`.
- **8 — `--model ""` is a usage error.** The parser validates `--model` (argparse exit 2) instead
  of `_models` raising `TypeError` past `main`. The review's second half did not hold: a bad
  `--url` raises `ValueError`, which `main` already reports, and every `ScreamingFaceError` is
  raised inside `run_pull`, which already wraps it.
- **9 — not changed here.** Measured, then left per-batch; the loader docstring in #1433 now says
  what one transaction covers and why (see that ledger). Possible follow-up: time-bounded commits.
- **10 — one name for the gateway database.** `_runtime/config.GATEWAY_DATABASE_NAME` is used by
  both `RuntimeConfig.gateway_database_url` and `_cache.local.gateway_database`; `DATABASE_NAME`
  is gone from `_cache.local`.
- **Stack:** PR #1433 → #1439 → #1446 updated by merge commits (no force-push), owner's choice.
- **Tests (append-only):** prepare refuses outdated / not-a-gateway / locked before any request;
  empty `--model` exits 2 without pulling; the pull's database equals the runtime's. The loader
  stand-in fixture in `test_cache_local.py` gains `check_database` (a module-level helper) —
  owner-approved 2026-10-17 and recorded in `.claude/test-change-approvals/OME-1639.json`.
- **Gates:** all `screamingface` gates green after every finding; the review fixes land as one
  commit (owner's choice).

## Follow-up from the gateway and Engine reviews (#1433, #1439 round 2, 2026-10-20)

The fixed #1439 branch (which carries #1433's) is merged in first; then one commit.

- **Byte-bounded load batches:** `walk_page` ends a batch at `BATCH_ROWS` (500) rows or
  `BATCH_BYTES` (8 MB) of line text, whichever comes first — the same memory issue #1433's review
  found on the gateway side, here on the client.
- **Skipped rows:** the loader now skips and counts a row a local lookup could not serve (owner's
  choice in the #1433 round) instead of refusing its batch. `LocalGateway.load` returns
  `(inserted, skipped)`; the loop counts skips at the page's end like `rows_read`, so a retried
  page counts them once; `PullResult.rows_skipped` (default 0, last field) carries the total and
  the final progress line shows it when non-zero. The `malformed_row` refusal mapping is gone (the
  loader no longer raises it).
- **Tests:** new tests for the byte bound, the skip count across a retried page, and the final
  line; the loader stand-in returns `skipped`, and `test_cache_local.py` drops its `malformed_row`
  refusal row and asserts the `(inserted, skipped)` pair — the pinning-test update for the removal,
  recorded in `OME-1639.json`. The public-surface snapshot is regenerated (+`rows_skipped`).

## Review round 2 (PR #1446 review by HupBaHa at the 8 MB-batch head, 2026-10-20)

Four findings; the owner chose the approach for 1 and 3. One commit.

1. **One sign-in per process:** `pull_into` no longer opens and closes a `Client` per call.
   `_session` reuses the default client when it is already open on the same Engine origin (never
   creating it, so the source still never follows `SCREAMINGFACE_ENGINE_URL`), and otherwise
   keeps one pull client per origin for the process.
2. **Resume identity:** the cursor is bound to `LocalGateway.identity` — the resolved path plus
   the file's device and inode — so a database deleted and recreated, moved into place, or reached
   through a retargeted symlink starts over. A file overwritten in place (same inode) still counts
   as the same database.
3. **Interruption:** the original `KeyboardInterrupt` is re-raised with the counts as `.result`
   (a `CachePullError` would let `except Exception` swallow Ctrl-C). The CLI's "the next pull
   starts over" stays: the CLI is its own process, so its next pull does start over.
4. **Blank URL:** only `None` selects production; `url=""` is refused by the client, and the CLI
   gives a blank or malformed `--url` a usage error (exit 2).
- **Tests (new, in files this PR added):** shared session across calls, default-client reuse on
  the same origin and not on another, blank URL refused, CLI usage error, interrupt counts, file
  identity across replace and symlink retarget. `test_cache_local.py` (pinned in `OME-1639.json`)
  only gains tests; its approved blob is refreshed.

## Review comments by khoaguin (PR #1446, 2026-10-21)

- **What a hit needs (README):** a few lines after the pull example: a row answers only the exact
  request (model, prompt, parameters, Benchmark revision, `answer_seed`); the rows cannot say
  which configurations they cover; two ways to land on one that does (a standard Benchmark with a
  bare `sf.Model`, or a leaderboard entry's `url4`, with its caveats: only hosted runs are in the
  hosted cache, and an entry does not carry its `answer_seed`). The longer-term ideas (configs
  suggested from the leaderboard after a pull, an `evaluate(..., cache_only=True)` dry run) are
  not in this PR.
- **A filter that matches nothing:** a filtered pull that finishes with zero rows read raises a
  `UserWarning` naming the filter. The page reports one total, not one per model, so the warning
  names the whole filter rather than the one model that matched nothing.
- **Tests (files this PR added):** the warning with a filter and zero rows; none without a filter
  or with rows; the existing session-sharing test now expects the warning for its empty filtered
  page.

## Review round 3 (PR #1446 review by HupBaHa at `41b67342a`, 2026-10-21)

Status: DONE. Weighed against latency (owner's call): every fix here is free on the hot
path — once per call, error path only, or the same per-row work — and no per-page check is added.

1. **Line and body bounds:** `HostedPages` splits the decompressed bytes into lines itself and
   refuses a line over 32 MiB as malformed before it is decoded; lines are handed on as bytes, so
   the batch's byte bound counts UTF-8 bytes. A retryable status (429/5xx) is classified before
   any of its body is read, and other refusals read at most 64 KiB of problem detail.
2. **Rows before the trailer:** a line after the trailer is caught before the page's last batch is
   handed on. A failed call's `rows_read` includes the rows read of the page it stopped in, so it
   is never below `rows_added`.
3. **Database identity:** after each page, before the cursor advances, the destination's identity
   is compared with the one the pull started with; a database replaced during the pull stops it
   with `destination_changed`, on its last page too. Measured: ~16 µs a check, ~2 ms over a full
   pull (120 pages), against ~4 ms to load one 500-row batch, so the owner chose to add it (the
   latency rule is about real costs, not microseconds). A file overwritten in place still counts
   as the same database (round 2).
4. **Session preference:** this module's own signed-in client is used before the default
   client; the default is used only when the module has none for that origin.
5. **Concurrent pulls:** one pull at a time per `(url, models)`; a second concurrent call is
   refused with `pull_in_progress` instead of sharing the cursor.
6. **Pull clients never closed:** not changed; one per origin for the process, by design.
- **Spec:** decision 12 now says what the code does: a cut page does not advance the cursor (its
  loaded rows stay), a line is at most 32 MiB, and a line after the trailer refuses the page
  before its last batch loads.
- **Tests (files this PR added):** a row after the trailer hands on nothing; the batch bound in
  UTF-8 bytes; a character split across chunks; a line over the cap and a non-UTF-8 line are
  malformed; a retryable status's body is never read; a refusal reads one 64 KiB chunk of ten; a
  failed call counts the rows of the page it stopped in; a concurrent pull of the same filter is
  refused while another filter runs; a later default client does not replace the pull's own.
  Each failed against `655b3ea06`. Gates green.
- **Follow-up (same day):** the identity check above, with a test that a database replaced
  mid-pull or on the last page stops the pull before the cursor moves; spec decision 14's resume
  paragraph names `destination_changed` and `pull_in_progress`.
