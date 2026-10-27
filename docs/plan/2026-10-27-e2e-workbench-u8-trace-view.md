# E2E workbench · Unit 8 — one Trace view that tells the run's story

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bundle page's "Trace chain" table (two hop rows with line counts) with one
**Trace** view. It shows the run across notebook → engine → aigateway → provider or cache →
scoreboard: a header, a hop path, a cross-service span tree rooted at a client span derived
from SDK events, one row per model call with its gateway logs, the verdict checks in plain
words, and an OTLP/JSON export.

**Architecture:** A pure model, `ui/trace_story.py`, builds a `TraceStory` from the bundle files
the workbench already writes (`trace.json`, `spans.jsonl`, `events.jsonl`, `accounting.json`,
`logs/*.txt`). A pure renderer, `ui/trace_html.py`, turns it into escaped HTML and inline SVG,
in the style of `telemetry_html.py`. `pages.py` swaps the old section for the new one. The
verdict, the receiver and the notebooks don't change, with one exception: the recorder stamps
the start and end times of the evaluate call, so the client span has real bounds.

**Tech Stack:** Python 3.12, the existing FastAPI UI, inline SVG, no JS library.

**Spec:** `docs/spec/2026-10-16-e2e-notebook-workbench.md` §3.8 (added with this plan); §3.3,
§3.6 and §3.7 stay authoritative for the verdict and capture.
**Depends on:** OME-1747 (6a, engine span export) and the UI PR (units 4, 6b, 7) merged to `main`.

## Owner decisions (2026-10-27)
- **Scope:** the UI view (header, hops, tree, calls, checks, export) plus client spans derived
  from SDK events (B2). Scoreboard OTel (B3), the SigNoz adapter (B6) and gateway span
  attributes (B8) become follow-up leaves.
- **Landing:** a separate PR after the UI PR, as a `repo-dev-processes` leaf under OME-1636.

## Facts this plan relies on (real replay bundle, 2026-10-27)
- 39 spans under one trace. Exactly one span has a dangling parent: `url4.run`, whose parent
  is the client's `traceparent` span id.
- Both gateway `POST /v1/chat/completions` spans are children of the engine span
  `/benchmarks/candidate`. That span carries `gen_ai.request.model`, `gen_ai.provider.name`,
  `gen_ai.usage.input_tokens` / `output_tokens`, `gen_ai.response.finish_reasons` and
  `url4.cache_status`.
- Gateway spans have `attributes: {}`. `POST /v1/frozen-copies…` spans hang off `url4.run`.
- Replay `accounting.json` has `by_model: []`. Spend is "unknown", never `$0`.

## Global Constraints
- Dev-only: everything stays under `tests/e2e/workbench/ui/`; nothing ships in the SDK wheel.
- Every rendered string is HTML-escaped. Bundle content is untrusted. CSP stays as it is (no
  inline event handlers; the existing nonce-scripted pattern only).
- `None` renders as "unknown", never 0. A partial sum of spend is "unknown".
- A synthetic span is always visibly marked ("derived from SDK events", dashed) and never
  written back into `spans.jsonl`.
- Bounded: at most 20 000 spans are read (the bundle cap). The tree renders at most 500 rows
  per page, with sibling collapse; a model-call table holds at most 2 000 rows. Anything cut is
  counted and shown.
- Log-to-call joins use the exact `trace_id=<32hex>` token rule from `trace_evidence.py`,
  never a substring match.
- Gates: the package's full gates (pytest with coverage floor, ruff, format, pyright,
  `check_notebooks.py`, `check_distribution.py`), the real replay lane, and `ui/test_ui_e2e.py`.

## Review Focus
1. **Bundle with no spans** (export down, or an older bundle): the view still renders the header,
   hops (grey with the reason), checks and log counts. It never shows an empty tree as success.
2. **Several orphan parents, or an orphan that isn't `url4.run`** (a cancelled run, or two
   evaluates in one notebook): no client span is invented; the view says why.
3. **A cycle or self-parent in `parent_span_id`** (a corrupt or hostile file) can't recurse
   forever. Each span is visited once, and a cycle member is shown as a root with a note.
4. **Concurrent model calls whose time windows overlap:** a gateway log line in both windows
   is shown under both and labelled "matched by time (ambiguous)", never silently assigned to one.
5. **The expected-failure bundle** (`debug_failing_run`): the failing call's row and its path in
   the tree are open and red; the hop path shows the gateway ✗ with the failure code.

---

### Task 1: client span timing in the recorder
**Files:**
- Modify: `packages/screamingface/tests/e2e/workbench/telemetry_recorder.py`. `EventRecorder`
  records `first_event_ns` and `last_event_ns` (wall clock, `time.time_ns()`, when each event is
  handled) and writes them into `recorder.json` as `{"first_event_ns": int|null,
  "last_event_ns": int|null}`.
- Test: `packages/screamingface/tests/e2e/workbench/test_telemetry_recorder.py`.

**Interfaces:**
- Produces: in `recorder.json`, the keys `first_event_ns` and `last_event_ns` (int or null).

- [ ] Write the failing test: two events at pinned `time_ns` 100 and 250 (monkeypatched) give
  `first_event_ns == 100` and `last_event_ns == 250`. No events gives both `null`.
- [ ] Run it; it fails with a `KeyError`.
- [ ] Implement it: set the first value once, update the last value on each event, and write
  both in `finish()`.
- [ ] Run it; it passes. Commit with `feat(e2e): recorder stamps first/last event time for the client span`.

### Task 2: `TraceStory` model
**Files:**
- Create: `packages/screamingface/tests/e2e/workbench/ui/trace_story.py`
- Test: `packages/screamingface/tests/e2e/workbench/ui/test_trace_story.py`

**Interfaces:**
- Consumes: `ui/telemetry.py` `load(directory, *, cap=LINES_CAP) -> Telemetry` (events, spans,
  report, accounting, dropped), plus its helpers `gateway_calls(text, trace_ids)` (exact-token
  gateway lines by call id), `money` / `money_sum`, `usage_by_model` and `page_of`, all reused
  rather than duplicated. Also `trace.json` as a dict and `logs/aigateway.txt` as text.
- Produces:
  ```python
  @dataclass(frozen=True)
  class Node:            # one span in the tree
      span: Mapping[str, Any]; children: tuple["Node", ...]; synthetic: bool; collapsed: int
  @dataclass(frozen=True)
  class Hop:
      name: Literal["notebook", "engine", "aigateway", "provider", "scoreboard"]
      state: Literal["ok", "fail", "grey"]; reason: str | None
      spans: int; log_lines: int | None; latency_ns: int | None
  @dataclass(frozen=True)
  class Call:
      span_id: str; model: str | None; provider: str | None; cache: str | None
      tokens_in: int | None; tokens_out: int | None; spend: Decimal | None
      latency_ns: int | None; status: str; failure_code: str | None
      log_lines: tuple[str, ...]; match: Literal["call_id", "time", "time-ambiguous", "none"]
  @dataclass(frozen=True)
  class Check:
      rule: str; held: bool; evidence: str
  @dataclass(frozen=True)
  class TraceStory:
      trace_ids: tuple[str, ...]; verdict: str; wall_ns: int | None
      hops: tuple[Hop, ...]; roots: tuple[Node, ...]; calls: tuple[Call, ...]
      checks: tuple[Check, ...]; notes: tuple[str, ...]; cut: Mapping[str, int]
  def build(bundle_dir: Path) -> TraceStory
  ```

- [ ] Write the failing tests, one per rule, each built from small JSONL fixtures in `tmp_path`:
  - **Tree:** nesting by `parent_span_id` across services. A gateway span sits under
    `/benchmarks/candidate`.
  - **Client span:** exactly one orphan, which is `url4.run`, gives a synthetic
    `sdk.evaluate` root whose `span_id` is the orphan's parent and whose bounds come from
    `recorder.json`. With 0 orphans, 2 orphans, or an orphan that isn't `url4.run`, no synthetic
    span is made, and a note names the reason (Review Focus 2).
  - **Cycle:** A→B→A, and a self-parent. Both terminate; the cycle member becomes a root, with
    a note (Review Focus 3).
  - **Collapse:** 9 sibling `TextNode`s collapse to one `Node` with `collapsed=9`. The path to
    an error span is never collapsed.
  - **Calls:** each `POST /v1/chat/completions` span becomes a `Call`, with model, provider,
    cache and tokens taken from its parent engine span, and spend from `accounting.json` by
    model (`None` when absent).
  - **Log match:** a gateway line with the exact trace token whose timestamp falls inside
    exactly one call window gives `match="time"`. Inside two windows gives
    `"time-ambiguous"`, and the line appears under both calls (Review Focus 4). A
    `trace_id=<id>x` substring gives no match.
  - **Hops:**
    - engine is `ok` when it has spans and `trace.json`'s engine hop found the id;
    - provider is `grey` "none on replay: served from cache" when every call has cache `hit`;
    - scoreboard is always `grey` "not instrumented";
    - with no spans at all, engine and aigateway take their state from `trace.json`, and the
      tree shows the note "no spans received" (Review Focus 1).
  - **Checks:** each `trace.json` hop, the lifecycle, unattributed lines and (for an
    expected failure) the `expect`/`observed` pair each become one `Check`, in plain words.
  - **Caps:** 20 001 spans gives `cut["spans"] == 1`.
- [ ] Run them; they fail with `ModuleNotFoundError`.
- [ ] Implement `build` as pure functions: `_tree`, `_client_span`, `_calls`, `_match_logs`,
  `_hops`, `_checks`. Do an iterative DFS with a `seen` set, with no recursion over untrusted
  depth.
- [ ] Run them; they pass. Run pyright on the file. Commit with
  `feat(e2e): TraceStory — one model of a run across every hop`.

### Task 3: Trace view HTML
**Files:**
- Create: `packages/screamingface/tests/e2e/workbench/ui/trace_html.py`
- Modify: `packages/screamingface/tests/e2e/workbench/ui/pages.py`: replace the
  "Trace chain" section (`_hop_table`, `_chain_facts`) with `trace_html.section(story, key,
  token, page)`, and keep a "raw trace.json" `<details>`.
- Test: `packages/screamingface/tests/e2e/workbench/ui/test_trace_html.py`

**Interfaces:**
- Consumes: `TraceStory` from Task 2.
- Produces: `section(story: TraceStory, key: str, token: str | None, page: int = 0) -> str`.

- [ ] Write the failing tests:
  - the header shows the trace id, verdict, call count, cache hits and "unknown" spend on
    replay;
  - the hop path has 5 nodes, and grey nodes show their reason text;
  - the synthetic span row has the `synthetic` class and the "derived from SDK events" label;
  - a collapsed row reads "×9";
  - an error path is `open` and red;
  - a call row expands to its log lines, and the "matched by time" label is present;
  - every field that came from a hostile `<script>` span name is escaped;
  - 1 200 spans give 3 pages with a pager.
- [ ] Run them; they fail.
- [ ] Implement it, reusing `_e`, `_usd`, `_duration` and `_pager` from `telemetry_html.py`;
  move any shared helpers into `ui/render.py` if both modules need them. The SVG hop path is
  a fixed-width row of 5 boxes with arrows that wraps to a column under 480px via CSS.
- [ ] Run them; they pass. Commit with `feat(e2e): Trace view replaces the trace-chain table`.

### Task 4: OTLP/JSON export
**Files:**
- Modify: `packages/screamingface/tests/e2e/workbench/ui/app.py`: add
  `GET /bundles/{key}/trace.otlp.json`, behind the same loopback, token and path guards as the
  other bundle routes.
- Create: `packages/screamingface/tests/e2e/workbench/ui/otlp_json.py` with
  `to_otlp_json(spans) -> dict`, which groups by service into `resourceSpans` → `scopeSpans` →
  `spans`, with hex ids, string nanosecond times, and attributes as typed `AnyValue`s.
- Test: `packages/screamingface/tests/e2e/workbench/ui/test_otlp_json.py`

- [ ] Write the failing tests:
  - a round trip through `opentelemetry.proto` `json_format.ParseDict` into
    `TracesData` succeeds;
  - a synthetic span is not exported;
  - a path-traversal key returns 404;
  - with no token, the route returns 403.
- [ ] Implement it. The route returns `application/json` with
  `Content-Disposition: attachment; filename="<trace_id>.otlp.json"`.
- [ ] Run them; they pass. Commit with `feat(e2e): download a bundle's spans as OTLP/JSON`.

### Task 5: real proof and docs
- [ ] `ui/test_ui_e2e.py`: assert that the bundle page has the Trace view with five hops, the
  `sdk.evaluate` synthetic root, `url4.run` under it, and a gateway chat span under
  `/benchmarks/candidate`. Show RED by mutation (drop the synthetic root), then revert.
- [ ] Real replay lane with `REQUIRE_ALL=1` passes for both notebooks. Open the
  `debug_failing_run` bundle and check Review Focus 5 in the HTML.
- [ ] UI smoke on a separate port (the owner's UI holds 9112): start a replay quickstart, open
  the bundle, download the OTLP/JSON, and parse it with `TracesData`.
- [ ] README: replace "Trace chain" with a "Reading the Trace view" section. Update the ledger.
  Commit with `docs(e2e): Trace view guide and u8 real proof`.

## Follow-up leaves (filed when their PRs open, each under OME-1636)
- **B3 `scoreboard`:** OTel server spans and `trace_id` in the scoreboard's logs, so the submit
  hop turns from grey to real.
- **B6 `repo-dev-processes`:** a SigNoz query adapter (`SIGNOZ_TOKEN`) so unit 3's cloud
  bundles get `spans.jsonl` by trace id.
- **B8 `aigateway`:** set `gateway_call_id`, `gen_ai.request.model`, the cache status and
  `http.response.status_code` on the gateway server span, so log lines join by call id rather
  than by time.

## Done when
- On a replay bundle, the Trace view shows five hops, one tree from `sdk.evaluate` down to the
  gateway calls, the model calls with their log lines, the checks in plain words, and a working
  OTLP/JSON download.
- The expected-failure bundle shows the failing path open and red.
- All gates are green, the PR is merged, and the leaf is closed with the close template.
