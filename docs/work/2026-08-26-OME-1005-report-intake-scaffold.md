---
ticket: OME-1005
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1005 — Scaffold `apps/report-intake` with its CI lane

## Intent

Stand up the eighth stack in the monorepo as an empty-but-real service: a uv project, a
FastAPI composition root, the RFC 9457 plumbing every later item raises through, the two probe
endpoints, and a path-filtered CI lane that builds and smokes the image. Nothing here accepts a
report — `POST /v1/reports` arrives with `OME-1006`. What this unit owes the other six items is
the set of seams §2 of the plan freezes, built once so six parallel units cannot each invent
their own.

Plan: `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md` §3.
Spec: `docs/spec/2026-08-26-OME-1004-report-intake-service.md`.
Epic: `OME-1002`.

## Planned changes

App (`apps/report-intake/`):

- `pyproject.toml` — distribution `report-intake`, console script `report-intake`, the strict
  complexity tier (`max-complexity = 8`, `max-statements = 26`, `max-branches = 7`,
  `max-returns = 3`), matching scoreboard and the engine rather than aigateway's grandfathered
  numbers.
- `pyrightconfig.json` — copied byte-for-byte from `apps/scoreboard`.
- `docs/complexity-baseline.md` — the file the ruff comments point at.
- `src/report_intake/config.py` — `Settings`, `env_prefix="REPORT_INTAKE_"`, the sole authority
  on this service's environment (plan §2.4). Copies scoreboard's single-prefix shape, not
  aigateway's dual-prefix `validation_alias` drift. `NoDecode` on every list/tuple field.
- `src/report_intake/logs.py` — the engine's `logs.py`, not scoreboard's (which has the
  `logging.lastResort` bug). Called from `create_app`, so a pod gets configured logging.
- `src/report_intake/core/problem.py` — RFC 9457 plumbing, mirrored (not imported) from the
  engine's `auth/problem.py`. This unit owns the module; `OME-1006` adds
  `core/problem_catalogue.py` beside it.
- `src/report_intake/routes/health.py` — `/healthz`, static, never grows a storage import.
- `src/report_intake/routes/ready.py` — `/readyz` behind the `app.state.readiness_check` seam,
  failing closed until `OME-1008` installs a real probe. Nobody edits this file again.
- `src/report_intake/main.py` — `create_app`, the startup guards, no `lifespan=` yet.
- `src/report_intake/cli.py` — uvicorn entrypoint.
- `Dockerfile`, `README.md`.

Repo registration (the six-step new-component checklist):

- `.github/workflows/report-intake-tests.yml` — path-filtered lane; unlike aigateway and
  scoreboard it **builds and smokes the image**, which is the defect those two admit to in
  their own Dockerfile comments.
- `.github/CODEOWNERS`, `.github/dependabot.yml` (uv + docker ecosystems).
- `release-please-config.json` + `.release-please-manifest.json`.
- `CONTRIBUTING.md` stacks table and run-from-source block.
- `.claude/sdlc.local.md` — the stack's gate list, so local gates and CI cannot disagree.
- `.claude/skills/working-in-this-repo/SKILL.md` — the routing table row.

## Test plan

Behaviour-named, in house style:

- `/healthz` answers 200 without touching storage, and answers from a non-loopback client.
- `/readyz` fails closed before a storage probe is installed; a probe that answers true makes it
  ready; a probe that answers false keeps it 503. The seam is `app.state.readiness_check` and
  installing one is a single assignment.
- A `REPORT_INTAKE_*` variable matching no `Settings` field refuses to boot and names the
  variable — the check that stops a pod booting with authentication silently disabled.
- `REPORT_INTAKE_ALLOWED_NETWORKS=10.0.0.0/8` parses as a comma-separated CIDR list rather than
  failing as malformed JSON (the `NoDecode` case), and a host-bits-set entry is refused rather
  than widened.
- `FORWARDED_ALLOW_IPS="*"` and any entry overlapping `allowed_networks` refuse to boot, with a
  message naming the variable and the fix.
- A `ProblemException` renders as `application/problem+json` with `None` members dropped, and a
  non-problem exception propagates untouched.
- `logs.configure` gives the app logger its own handler, is idempotent, and does not propagate.

## Acceptance

- `uv sync`, `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`
  all green from `apps/report-intake`.
- The six registration points exist and name the new stack.
- The seams `OME-1006`–`OME-1012` are promised in plan §2 exist and are exercised by a test:
  `core/problem.py`, `app.state.readiness_check`, `Settings` as environment authority.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `uv.lock` and `tests/unit/test_cli.py`. 26 files under
  `apps/report-intake/`, one new workflow, seven edited repo-level registration files, and this
  ledger. The one planned file that is **not** here is a `cors_origins` setting — see
  Deviations.

- **Commits:** the orchestrator owns git for this unit; no commit was made from inside it.

- **Gates** (run from `apps/report-intake`, all green):

  | Gate | Result |
  |---|---|
  | `uv sync` | 36 packages resolved, 35 audited |
  | `uv lock --check` | current |
  | `uv run pytest -q` | **43 passed** |
  | `uv run ruff check` | All checks passed |
  | `uv run ruff format --check` | 22 files already formatted |
  | `uv run pyright` | 0 errors, 0 warnings, 0 informations |
  | coverage | **99%** (`--cov=report_intake`), against the stack's 80 floor |
  | `run_gates.py report-intake` | ALL GATES GREEN, including the append-only check |

  The CI image job was executed locally as written: `docker build` succeeded, the container
  started, `/healthz` answered `200 {"status":"ok"}` and `/readyz` answered `503
  {"status":"not ready"}` — the fail-closed value the workflow asserts.

- **The `verify_chart_wiring` half of §2.4 is deliberately not here.** `Settings` is the
  authority and the startup guard is its first enforcement mechanism; the second is a chart
  assertion, and the chart is `OME-1012`. Nothing in this unit renders an environment.

- **Deviations:**

  1. **`cors_origins` is not a field yet.** Plan §2.4 lists `REPORT_INTAKE_CORS_ORIGINS` in the
     frozen environment surface, but §9 gives the CORS decision — which origins, which headers,
     no credentials — to `OME-1011`. Shipping the field here would have meant either a setting
     nothing reads (the trap §3 names for `lifespan=`) or guessing `OME-1011`'s allowed-header
     list in advance. It arrives with its reader. Consequence while that is true: the startup
     guard refuses `REPORT_INTAKE_CORS_ORIGINS`, which is correct — no chart renders it yet.
  2. **`auth_mode` is not a field yet either**, for the same reason: it is `OME-1011`'s, and it
     has no reader here. The `FORWARDED_ALLOW_IPS` guard §3 assigns to this unit is therefore
     keyed on `allowed_networks` being declared rather than on the mode. That is strictly more
     general — declaring the networks is what makes `request.client.host` load-bearing, whether
     the reader is mesh identity or the rate-limit key — and it keeps working unchanged when
     `OME-1011` adds `auth_mode=mesh_or_turnstile` on top, since that mode requires the networks.
  3. **`.claude/skills/working-in-this-repo/SKILL.md` was edited**, though the unit brief's
     enumerated list of repo-level files did not name it. Plan §3 names the skill's routing
     table as step six of the six-step new-component checklist, so it is registration the plan
     explicitly names; the edit is one table row plus one "where does my change belong" bullet.
  4. **The `503` on `/readyz` is plain JSON, not `application/problem+json`.** The problem
     catalogue exists so a client can decide what to do next; a kubelet reads a status code and
     nothing else. Recorded here because `OME-1008` installs the probe on this seam and should
     not "fix" the body on the way past.

- **Two things a later item should not undo:**
  - `main.py` has **no `lifespan=`**. `OME-1008` adds it with `db.py`. Anything appended to
    `app.router.on_startup` alongside a `lifespan=` is a silent no-op on the pinned starlette,
    which is how a retention sweeper never runs while its unit tests all pass.
  - The lock resolved **starlette 1.6.0**, not the 1.3.1 the plan's §6 note was written
    against. The `on_startup` hazard is unchanged (1.6 still runs `Router.lifespan_context`
    directly), but anyone re-verifying that note should test against what is actually locked.

- **`app.routes` is not the list of paths an app serves, on this starlette.** An
  `include_router` is wrapped behind a delegating entry with no `path` and no `routes`, reaching
  the real ones only through `original_router`. The obvious spelling of
  `test_installing_a_probe_replaces_the_seam_rather_than_adding_a_second_route` found **zero**
  `/readyz` routes and failed outright — which was luck: written as `<= 1` or `is not None` the
  same mistake is a permanently green test that could never see a duplicate. The helper
  flattens both shapes; anything later that counts routes should use it rather than re-derive it.

## 2026-08-27 — the app's `CLAUDE.md`, and the `reply_to` decision

Two gaps closed on the finished service. Neither is new behaviour beyond one rendered label.

### 1. `apps/report-intake/CLAUDE.md`

Every other app in the monorepo carries one and the eighth stack did not, so an editor arriving
at this service had the 350-line `README.md` — which describes what the service *does* — and no
short statement of what an edit must not *break*.

Written to the house shape: `apps/aigateway/CLAUDE.md`'s dense one-bullet-per-invariant list and
`apps/aigateway-ui/CLAUDE.md`'s bold-led form and length. Two sections, **Contracts** and **Traps
already paid for**, and a first line that points at `README.md` for everything that is not a
guardrail — the point of the file is that it is short enough to be read before an edit, so
duplicating the README into it would defeat it.

The contracts are the ones plan §2 froze plus the four the build discovered: `Settings` as the
sole environment authority with the chart rendering exactly its fields (and the boot guard and
the two-sided chart assertion that enforce it); `X-User-Email` named in one module with the peer
checked first; core never importing an adapter and a sink receiving `TicketContent` rather than a
report; persist-before-deliver and the fact that `StorePipeline` must never classify; `/healthz`
never growing a dependency; the classifier being fail-closed and reading `scanned` rather than
`payload`; `scan_text`-not-`classify_report` at the dispatcher; no ad-hoc status and no `422` that
echoes what it rejected; no client-controlled value reaching a rendered artifact as free-form
Markdown; and `reply_to` (below). The traps are the ones that cost something once — `lifespan=`
versus `on_startup`, `app.routes` not being the route list, `DELIVERY_TIMEOUT_S` coupled to
`CLAIM_GRACE`, one migration for every column, `queued` being terminal success, `mark_filed` not
touching `attempts`, the triage reads being console-only, `LinearSink` shipping inert under repo
rule 9, `disabled` meaning loopback-only, the `403`/`503` split, the rate limit's key, and the
containment tests being an enforcement mechanism rather than coverage.

**Repo `CLAUDE.md` was not edited.** Rule 9 governs selecting `LinearSink` and is the owner's;
this file states that it governs and moves on, exactly as `delivery/linear_sink.py` does.

### 2. `reply_to` validation — DECIDED: accept, and mark it in the ticket

The state before this pass: `reply_to: "not-an-email"` was accepted, stored and answered `202`,
and nothing anywhere said that was a choice. A reader could equally conclude it was an oversight
and "fix" it with an `EmailStr`.

**Decision: keep accepting, and never add a syntax check.** Rejecting loses the error, the
traceback, the client versions and the trace id — everything that makes the report diagnosable —
over the one field this service authorizes nothing on and never treats as identity. A report with
a typo'd address is still a report somebody can act on; a refused one is not, and spec §8's rule
for the client is that a report is never lost. Spec §9's caller table had already settled the
posture in two words — *accepted, unverified*, for both caller classes — so this pass is the code
catching up to the spec rather than a new fork.

**The cost is paid where it can be seen.** Accepting is only the better trade if the artifact a
human acts on admits what it is holding, so `delivery/render.py` now renders a value that does not
look like an address under a second label:

```
- reply-to (self-asserted, does not look like an address): not-an-email
```

Without it the failure is silent in the worst direction: `bob@openmindorg` reads as an address at
a glance, a triager answers it, the bounce lands days later in somebody's sent folder, and by then
the report is closed and the reporter is still waiting.

Four properties of that label, each of which is a decision:

- **It is a label, not a repair.** The value is carried verbatim in the body and in
  `TicketContent.reply_to`, which a sink routes on. Nothing branches on the answer.
- **`_looks_like_an_address` is a shape check and the wording says so.** It is deliberately
  calibrated to over-flag: an exotic-but-legal address (a quoted local part, a domain literal) is
  marked, which costs a triager one second, where an unmarked typo costs the reporter their answer.
  A real RFC 5322 validator would trade that calibration for somebody else's.
- **It stays rare.** An ordinary address is unmarked, because a warning printed on every report is
  a warning nobody reads. Asserted in the test.
- **`queue show` inherits it and `queue list` does not.** `show` prints `render_ticket(...).body`
  verbatim — it is what an agent pastes into Linear, and with `QueueSink` still the default it is
  the artifact a human actually reads today. `list` is a scan view whose `REPLY TO` column is 40
  characters; a marker there would crowd the row it is meant to help read.

**The existing `max_length` is a LENGTH refusal and is not a precedent for a syntax one**, which
the new route test states in as many words. That bound exists because the column is `varchar(320)`
and an over-long value reached tortoise's validator, where every ORM failure becomes
`StorageUnavailable` → `503` — the one status spec §8 defines as *retry unchanged*, for a
permanent failure. Length has a wrong answer; shape does not.

Said in three places, so the decision is reachable from wherever a reader arrives: the
`ReportDocument.reply_to` docstring (the schema statement, with the reasoning), the comment at the
persistence seam in `store_pipeline.py` (the spec-facing one — it cites §9 and points at both
other places), and `README.md`'s identity section.

### Files

- **New:** `apps/report-intake/CLAUDE.md`.
- **Edited:** `src/report_intake/delivery/render.py` (`_reporter_bullets` + `_reply_to_label` +
  `_looks_like_an_address`, and one clause in the module docstring),
  `src/report_intake/reports/schema.py` (the `reply_to` docstring),
  `src/report_intake/reports/store_pipeline.py` (the persistence-seam comment), `README.md`.
- **Tests (+3):** `tests/unit/test_ticket_render.py` —
  `test_a_reply_to_that_does_not_look_like_an_address_says_so_in_the_ticket` and
  `test_marking_a_reply_to_labels_it_and_never_rewrites_it`;
  `tests/unit/test_persistence_route.py` —
  `test_a_reply_to_that_is_not_an_address_is_accepted_rather_than_losing_the_report`.

### Gates (from `apps/report-intake`)

| Gate | Result |
|---|---|
| `uv run pytest -q` | **534 passed** |
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 87 files already formatted |
| `uv run pyright` | 0 errors, 0 warnings, 0 informations |

No existing test was weakened or rewritten. The two new render tests were inserted at a test
boundary, and both edited test files pass the append-only check.

**Observation, not a blocker:** `uv run .claude/scripts/run_gates.py report-intake` currently
fails its append-only check on four files this pass did not touch —
`tests/unit/test_{chart_environment,cli,config,ticket_sinks}.py`, all modified in place by the
earlier `OME-1009` follow-up passes on this branch. Whoever owns the commit should decide whether
those in-place edits are the Confidence-Gate decision the check asks for, or whether the check
should be run with `--base` against the branch point.

### No environment change

No `Settings` field was added, so plan §2.4's frozen environment surface is still 23 names and the
Helm chart is untouched. `tests/unit/test_chart_environment.py` passes unchanged.
