---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress
started: 2026-10-27
finished:
---

# e2e-workbench-u8-trace-view — one Trace view that tells the run's story (unit 8)

## Intent

The bundle page's "Trace chain" is a pass/fail table: two hops and their line counts. The run's
story is already in the bundle but scattered: 39 spans, 59 SDK events, gateway logs and the
accounting. Unit 8 joins these into one Trace view, with a header, a hop path, a cross-service
span tree rooted at a client span derived from SDK events, model calls with their logs, the
checks in plain words, and an OTLP/JSON export.
- Plan: `docs/plan/2026-10-27-e2e-workbench-u8-trace-view.md`.
- Spec: §3.8.

## Planned changes

See the plan, Tasks 1–5.

## Test plan

See the plan. The Review Focus items each get a test in the owning task.

## Acceptance

- The replay bundle shows five hops and one tree from `sdk.evaluate` down to the gateway calls.
- The expected-failure bundle has its failing path open and red.
- The OTLP/JSON download parses as `TracesData`.
- Gates green.

## Findings (before work)

- **2026-10-27 real replay** (trace `e7117aab…`), on the UI branch with 6a:
  - gateway chat spans nest under the engine span `/benchmarks/candidate`;
  - `url4.run` is the only orphan, and its parent is the client's `traceparent` span id;
  - gateway server spans have `attributes: {}`, which becomes follow-up B8 (`aigateway`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files** (all under `packages/screamingface/tests/e2e/workbench/`, nothing under
  `apps/`):
  - T1: `telemetry_recorder.py`, `test_telemetry_recorder.py`.
  - T2: `ui/trace_story.py`, `ui/test_trace_story.py`; `ui/telemetry.py` (`Telemetry.found`).
  - T3: `ui/trace_html.py`, `ui/test_trace_html.py`, `ui/pages.py`, `ui/render.py`,
    `ui/telemetry_html.py` (shared helpers moved to `render.py`).
  - T4: `ui/otlp_json.py`, `ui/test_otlp_json.py`, `ui/app.py`.
  - T5: `ui/test_ui_e2e.py`, `README.md` ("Reading the Trace view"), this ledger.
- **Commits:**
  - `deeb3e078` — feat(e2e): recorder stamps first/last event time for the client span
  - `5270a84b6` — feat(e2e): TraceStory — one model of a run across every hop
  - `edd636e53` — fix(e2e): address review of T1+T2
  - `ce4342e8f` — feat(e2e): Trace view replaces the trace-chain table
  - `0a0304ad7` — fix(e2e): address review of T3
  - `216d17219` — feat(e2e): download a bundle's spans as OTLP/JSON
  - this commit — docs(e2e): Trace view guide and u8 real proof
- **Gates** (2026-10-27, from `packages/screamingface`, committed tree, 6a not applied):
  - `uv run ruff check .`: all checks passed. `uv run ruff format --check .`: 649 files
    formatted. `uv run pyright`: 0 errors, 0 warnings.
  - `uv run pytest -q`: 5405 passed, 40 skipped, 75 deselected (9 min 25 s).
  - CI shape `pytest -n auto --dist worksteal --cov=screamingface --cov-fail-under=95`:
    5405 passed, 40 skipped; coverage **97.03%** (TOTAL 18328 stmts, 545 missed).
  - `scripts/check_notebooks.py`: rc 0. `uv build` + `scripts/check_distribution.py`: rc 0
    (`dist/` removed after).
- **Real proof** (keyless replay, $0; 6a = OME-1747 engine span export applied to the
  working tree for these runs only, then removed; `git status` clean under `apps/`):
  - **Replay lane**, `SCREAMINGFACE_TEST_E2E=1 SCREAMINGFACE_WORKBENCH_REQUIRE_ALL=1`, both
    notebooks: `test_notebook[replay-debug_failing_run]` and `[replay-quickstart]` PASSED,
    2 passed in 12.4 s.
    - `quickstart`, trace `ef2d82fe72b3aceb350e959f0274a010`: 39 spans (+ derived
      `sdk.evaluate` = 40 tree rows), 59 SDK events, log lines engine 4 / aigateway 4. Hops:
      notebook ✓, engine ✓ (35 spans), aigateway ✓ (4 spans), provider grey "none on replay:
      served from cache", scoreboard grey "not instrumented". 2 model calls, 2 cache hits,
      spend `unknown`. `url4.run` under `sdk.evaluate`; both `POST /v1/chat/completions`
      under `/benchmarks/candidate`.
    - `debug_failing_run`, trace `58575c7182ee58acf19395eed7753eff`: 31 spans, 43 events.
      **Review Focus 5:** hop path aigateway ✗ "2 of 2 calls failed: upstream_error" ✓; the
      tree's error path (16 `details open class="err-path"`, `sdk.evaluate` → `url4.run` →
      … → `/benchmarks/candidate` → `/benchmarks/case-execution`) is open and red ✓; both
      call rows are red (`hl-err`, pill `error upstream_error`) ✓, but there is no log
      `<details>` to open on them: no gateway line matched a call (see Findings).
  - **`ui/test_ui_e2e.py`** (real replay run through the routes): RED by mutation (forced
    `_client_span` to return None → `assert [] == ['sdk.evaluate']`), reverted, then 1 passed
    (12.0 s; again 13.5 s after the final refactor). **Its tree assertions need 6a merged**:
    on a branch without OME-1747 the engine exports no `url4.run` and the test fails at the
    tree.
  - **UI smoke** on port 9141 (`scripts/workbench-ui --port 9141 --no-open`, stopped after):
    POST `/runs` replay quickstart → 303; run ended `{"returncode": 0, "cancelled": false}`
    in 11.4 s; bundle page's Export link → `GET …/trace.otlp.json` 200 `application/json`,
    `attachment; filename="d2a2759a6c04c56956878eb0c1fc434f.otlp.json"`. Parsed with
    `json_format.ParseDict` into `TracesData` (hex ids re-encoded to base64 first): 2
    `resourceSpans` (`screamingface-engine` 35, `aigateway` 4) = 39 spans, one trace id,
    16-byte trace / 8-byte span ids; `sdk.evaluate` not exported; `url4.run` present.
- **Deviations:**
  - Task 5 `ui/test_ui_e2e.py`: the old hop-table assertions (`<tr><td>engine|aigateway`,
    `>found<` ×2) were already stale after Task 3 (real run: `assert 0 >= 2`). Replaced by
    `_assert_trace_view` (five hops with states, `sdk.evaluate` the only synthetic row,
    parent edges via `HTMLParser`), called from `_assert_bundle_page` to stay inside ruff's
    statement limit.
  - Task 3 `trace_html.section(story, key, token, page: int = 1, *, appendix="")`: `page` is
    1-based (matches `tm.page_of` and the `trace_page` query), not the plan's `page: int = 0`;
    `appendix` carries the raw trace.json into the section.
  - Task 3 `trace_html` has its own `_pager`/`_link` instead of reusing `telemetry_html._pager`:
    a different query key (`trace_page`) and anchor (`#trace-tree`).
  - Task 3 hop path is a CSS-styled `<table>` (boxes + arrows, column under 480px), not an SVG
    row: tabular data stays readable as rows to screen readers and text search; each state
    carries a small inline SVG glyph only.
  - Review of T3: `Telemetry.found` names the JSONL files that exist, so the Trace header can
    tell a missing `events.jsonl` (unknown) from an empty one (0).
  - Spec §3.8 names the synthetic span's service `screamingface-sdk`; Task 2 rendered
    `notebook`. Resolved in the final review fix: the span's service is now
    `screamingface-sdk`, per the spec. The notebook hop reads "1 derived span", so it no longer
    disagrees with the header's span count, which leaves the derived span out.
  - Final review fix: the header's spend is `accounting.json`'s total over every model (still
    `unknown` when any part is unknown or there are no model rows), not the sum of per-call
    spend; past the call cap the count reads "N shown of M".

## Findings (real run, 2026-10-27)

- **Call status and model are inherited from the engine parent.** In `debug_failing_run` both
  chat spans sit under one failed `/benchmarks/candidate` (model `ministral-3b-2512`), so the
  view says "2 of 2 calls failed" and shows that model on both rows, though only the
  `gpt-5.5` member failed (404). Root cause: gateway spans carry no attributes or HTTP status
  (follow-up B8).
- **No gateway line joins a call on replay.** Note on both bundles: "N gateway log lines …
  matched no model call" (quickstart 4, failing 3); every call row reads "no log lines
  matched". Corrected cause (final review): replay gateway lines carry **no timestamp at all**.
  aigateway's `_FORMAT` (`apps/aigateway/src/aigateway/logs.py`) is
  `%(levelname)s: %(name)s %(call_context)s%(message)s`, and the replay harness writes raw
  stdout to `aigateway.log` (`harness/_local_proc.py`), so `line_ns` returns None. Time
  matching (and Review Focus 4's ambiguous label) can fire only on the `local` target, whose
  `runtime.log` lines are timestamped; on replay it is exercised only by synthetic
  ISO-prefixed fixtures. The view now notes unstamped lines apart from stamped lines outside
  every window. A join on replay needs B8 (`gateway_call_id` on the span).
- **Merge order (for the PR body).** `_assert_trace_view` in `ui/test_ui_e2e.py` needs OME-1747
  (6a). This branch is stacked on the unmerged UI PR (base `adb90276b` is not on
  `origin/main`), and the replay CI lane runs `pytest tests/e2e`, so it fails until 6a lands.
  Order: land 6a and the UI PR, then retarget this PR to `main` and merge it. State this in the
  PR body.
- OTLP/JSON ids are hex per the OTLP spec; protobuf `ParseDict` alone reads them as base64
  (24-byte ids, silently). Consumers must re-encode, as `test_otlp_json.py` does.
