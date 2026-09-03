---
ticket: OME-904
stack: python
status: in_progress
started: 2026-08-20
finished:
---

# OME-904 — Show benchmark descriptions on the leaderboard (engine text as the only copy)

## Intent

The leaderboard prints "No description published." for every benchmark because the
deployed seed list carries ids + revisions only, and Helm replaces lists wholesale —
so the descriptions hand-copied into `apps/scoreboard/charts/scoreboard/values.yaml`
never reach the database. Good text already exists in the Engine benchmark definitions.
This unit makes the Engine's benchmark catalogue the ONLY copy: the scoreboard seed job
fetches `GET {engine}/v1/benchmarks` at deploy and writes description / focus /
dataset_url / revision from it, so a deploy override physically cannot blank the text.

Owner decisions (2026-08-20):
- Mechanism: seed job fetches the Engine catalogue at deploy (not build-time codegen,
  not request-time merge).
- The Engine `Benchmark` gains `focus` + `dataset_url` so all four fields have one copy.
- Tracked as one ticket / one PR spanning both apps (owner override of the
  cross-cutting split rule).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py` — optional
  `focus` / `dataset_url` on `Benchmark`, surfaced in `_metadata()`.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/{draco,ifeval,healthbench}/definition.py`
  — carry the focus / dataset link text.
- `apps/scoreboard/src/scoreboard/seed.py` — fetch + map the Engine catalogue, merge with
  the configured legacy rows.
- `apps/scoreboard/charts/scoreboard/values.yaml` + `templates/job-seed-benchmarks.yaml`
  — `seedBenchmarks.engineUrl`, legacy demo rows only.
- Tests on both sides.

## Test plan

Engine (`tests/unit/test_benchmark_display_metadata.py`): a declared focus line and dataset link
reach both the catalogue entry and the detail resource; a benchmark declaring neither publishes
neither key (absent, never null); blank focus and non-http(s) dataset links are refused; the
three installed benchmarks publish the focus lines and dataset links the board displays, IFEval
deliberately without one; the published revision is the computed revision and display metadata
does not move it.

Scoreboard (`tests/unit/test_seed_engine_catalog.py`): a catalogue entry becomes a seed row with
`title` mapped to `display_name`; an entry without display extras seeds them absent; catalogue
fields the board does not display are ignored; the catalogue path is appended to the configured
origin; transport failure, error status, non-JSON body, and a missing displayed field each
surface as `EngineCatalogUnavailable` rather than an httpx/json exception; an Engine row wins
over a configured row sharing its id and the shadowed id is reported; a configured row the
Engine does not publish is kept; the seeded revision is the catalogue revision, never a
configured literal; an unreachable Engine leaves an already-seeded board untouched and does not
fail; an unreachable Engine does fail when no row carries a revision; no configured Engine URL
seeds only the configured rows.

## Acceptance

- No file outside an Engine benchmark definition states a benchmark's description, focus, or
  dataset link.
- `helm template` renders `SCOREBOARD_SEED_ENGINE_URL` when `seedBenchmarks.engineUrl` is set
  and omits it when empty.
- Both stacks' gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `apps/scoreboard/src/scoreboard/scores/store.py`
  (`has_registered_revision`, so the bootstrap check reads the database through the store rather
  than reaching for the ORM from the seed module) and
  `apps/scoreboard/charts/scoreboard/README.md`. The before/after diagram is NOT committed
  (owner decision 2026-08-20): it lives on the Linear issue as an attachment, keeping binaries
  out of the repository. Source is in the session scratchpad. No migration: `benchmarks` already carries
  `description`, `focus`, `dataset_url`, and `revision` columns, so S1 does not apply.
- **Commits:** see the OME-904 branch.
- **Gates:** `run_gates.py screamingface-engine` ALL GATES GREEN; `run_gates.py scoreboard` ALL
  GATES GREEN. The review round ran with `--skip-append-only` under owner approval (below).

## Review round (PR #657, 2026-08-20)

Eight findings, all verified before any fix — two of them by executing the behaviour rather
than reading it (`follow_redirects` defaults to False; `.json()` raises `UnicodeDecodeError`,
not `JSONDecodeError`, on a non-UTF-8 body).

- **Release-breaking:** `httpx` was declared under `[dependency-groups].dev` while the image is
  built with `uv sync --frozen --no-dev`, so `import httpx` in `scoreboard.seed` would have
  been a `ModuleNotFoundError` on every deploy. No test could see it, because tests install the
  dev group. Moved to `[project.dependencies]`, relocked, and pinned by a test that reads
  `pyproject.toml` — the only kind of test that can defend this.
- **"Engine is the only copy" held on the happy path only.** With the catalogue unreadable
  there is nothing to shadow with, so the deploy's own stale entries would have overwritten
  good rows with null descriptions — OME-904 reproduced by its own fix. Configuration may now
  never write an entry asserting a `revision` the Engine did not publish this pass, nor one
  naming an existing Engine-owned row.
- **The bootstrap guard read the database after writing to it**, so a configured entry carrying
  a revision satisfied the guard with the row it had just written. The prior state is now read
  before anything is seeded.
- **The likeliest misconfiguration was silent** (chart upgraded without `engineUrl`). Those
  entries are now refused and named loudly.
- One unreadable catalogue entry rejected the whole batch; entries are now validated
  independently, and the Engine enforces the board's column widths so over-long text fails
  where it is written instead of at deploy.
- Redirects are followed; `UnicodeDecodeError` is caught; the fetch retries transport failures
  and 5xx (never a 4xx or a mangled body); and `parser.error` no longer wraps the whole run, so
  an unrelated `ValueError` can no longer surface as a command-line usage error.

## CI round (PR #657, 2026-08-20)

CI caught a caller I never looked for: `packages/screamingface/_runtime/server.py:141` imports
`scoreboard.seed._run`, whose signature this work changed. Pyright reported the missing
argument, but the signature was the smaller half — that local runtime seeds its board from
`scoreboard_seed_json(BUILTIN_BENCHMARKS)`, whose rows carry revisions, so under the new
refusal rule every one of them would have been refused and a local leaderboard would have come
up EMPTY. A green type-check would still have shipped a broken local stack.

The root cause was the API, not the call site. That path is doing exactly what this ticket
does — derive the board's catalogue from the Engine registry — in process rather than over
HTTP, because a local stack runs both in one virtualenv. It had no door. `seed_from_sources`
and `_run` now take `engine_rows`, the in-process adapter beside the HTTP one, and the local
projection also carries `focus`/`dataset_url` so a local board matches the deployed one.

Process lesson: three stacks in this repo import `scoreboard.seed`, and I ran gates for two.
Changing a signature means grepping for callers across the whole monorepo, not across the app
that owns the file.

## Second review round (PR #657, 2026-08-20) — approved with four notes

All four verified before acting; the first by executing a request against the live host.

- **The obvious `engineUrl` value silently disables the feature.**
  `https://fusion.dev.screamingface.ai/v1/benchmarks` answers **HTTP 200 with `content-type:
  text/html`** — a Cloudflare Access sign-in page, not a 401. Every layer then behaves as
  designed: status check passes, parse fails, failure is survivable, stale configured entries
  are refused, job exits zero. Deploy looks clean, text never refreshes. Fixed three ways: the
  parse error now names the content type and says the address must be in-cluster; the fallback
  logs at WARNING and states that text was not refreshed; the chart comment records why the
  public hostname is the wrong value.
- **Nothing exercised a real Engine response.** Every test fed the parser a payload written in
  this repo, so they proved the parser agrees with itself — the same shape as the bug being
  fixed. Added `tests/fixtures/engine_catalog.json`, captured from the actual producer
  (`catalog_entry()` over the real registry), and a test that parses it. It passed first run,
  which is the confirmation that was missing rather than a fix.
- **Blocking I/O inside an async caller** — sync `httpx.Client` + `time.sleep`, ~49s worst
  case. Correct for a one-shot Job; documented as an AIDEV-NOTE because `seed_from_sources` is
  `async` and would tempt a caller into running it from a live server.
- **An empty description drops the whole benchmark**, not just its text — no row, no board,
  submissions refused. Owner reversed the original intent (2026-08-20): a missing board is a
  far worse failure than a plain-looking row, so the consumer now tolerates absent prose and
  stores it as NULL. Not a placeholder sentence — `leaderboard_view.py` already renders "No
  description published." for an absent one, and prose written into the database could never
  be told apart later from prose an author actually wrote. Leniency stops at id/title/revision,
  without which there is nothing to register or rank. The Engine still REFUSES to define a
  benchmark without a description: require it where it is written, tolerate it where it is
  read.

### Testing the contract for real

Filip's "nothing exercises a real Engine response" was the sharpest note, and the obvious fix —
one test running both halves in process — turned out to be impossible: the two apps have
separate virtualenvs by design, and the Client SDK's venv carries their source on its path but
none of their dependencies (not even pydantic), because its local runtime installs those at use
time. Verified, not assumed.

What was done instead: the producer pins the contract on its own side
(`test_the_catalog_keeps_the_field_names_the_leaderboard_seeds_from` asserts the catalogue keeps
the exact field names the board seeds from, and says so), the consumer keeps the recorded real
response as a fixture, and each half's docstring names the other so a rename finds both. The
producer is the side that can break the contract, so the producer is the side that pins it.

Still open, and an owner call because it is CI configuration: the SDK lane is path-filtered to
`packages/**`, so an Engine-only pull request never runs the seam tests. Adding
`apps/screamingface-engine/**` to that filter would close it.

### Second rebase (2026-08-21)

`main` moved 24 commits ahead and DRACO went the way HealthBench had: refactored into a
`draco_benchmark()` factory producing two boards (canonical five-pass, plus `draco-3pass` for
cache-seeded replays). Resolved identically — `focus`/`dataset_url` threaded through the
factory, both call sites passing them, one shared `DRACO_DATASET_URL` constant. The two boards
share a dataset and a subject, so the Focus line carries the only difference a reader can see:
"Research reports with citations" against "Research reports, three judge passes".

Third new benchmark to land mid-branch, which made a testing mistake visible: the recorded-
response test asserted a hardcoded roster of benchmark ids, so every added board failed it for
no reason. Replaced (owner-approved, sdlc rule 5) with the invariant it was reaching for —
every benchmark in the response survives the trip, whatever they are. A test that goes red for
ordinary work teaches people to edit the test, which is the last reflex you want when it
eventually goes red for a real one.

Known limit of that trade: a benchmark silently DISAPPEARING from the Engine no longer fails
this test, because both sides shrink together. It shows up as a deletion in the regenerated
fixture instead, which is visible in review.

Owner-approved prior-test edits (sdlc rule 5, 2026-08-20): 18 lines across two committed test
files — five mechanical (the fetch returns a `CatalogRead` so it can report unreadable
entries), eight adding `retry_delay=0` so failure tests do not sleep through the real backoff
(28s -> 0.07s), three widening a fixture helper, and one changed expectation, because finding 5
proved batch-rejection wrong. A new test covers the case that must still raise.
- **Deviations:**
  - The plan's step 1 included pinning each installed benchmark's revision as a literal. That
    test was written, went red, and was replaced rather than satisfied: the three revisions the
    chart pins (`draco 1c58b3085912e304`, `ifeval 0b88a52b5f10a6d9`,
    `healthbench-worst30 6cd57aee171fbdc4`) do NOT match what this checkout computes
    (`66a463248586b277`, `1cba769ece27f7ef`, `39cfd96b068f7230`). Pinning literals in a test
    would have recreated exactly the hand-copied second copy this ticket removes, so the test
    now asserts the published revision is the benchmark's own computed value, and the board's
    protection lives where it belongs — the seeded revision comes from the catalogue response.
  - That mismatch is a PRE-EXISTING drift, surfaced by this work and not caused by it: the
    deployed board's revisions are stale relative to this checkout's Engine. It also means the
    ticket's "quick unblock" (re-seed from `values.yaml`) would seed stale revisions. Reported
    to the owner.
