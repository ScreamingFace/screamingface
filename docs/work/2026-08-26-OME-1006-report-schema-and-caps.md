---
ticket: OME-1006
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1006 — Report schema and hard caps on every input

## Intent

`apps/report-intake` boots and answers its probes (`OME-1005`) but accepts nothing. This unit
gives it its only write — `POST /v1/reports` — and, more importantly, gives that write a
boundary: every byte a client can send is bounded before it is believed. Spec §2.1 fixes the
shape, §2.4 fixes the numbers, and `OME-969` is why the numbers are concrete rather than
"bounded".

The security posture of this unit is that **nothing downstream has to re-check size**. The
classifier (`OME-1007`), the store (`OME-1008`), and the ticket renderer (`OME-1009`) all
receive a `BoundedReport` whose every leaf already fits a stated cap.

## Planned changes

Source (all under `apps/report-intake/src/report_intake/`):

- `core/problem_catalogue.py` — **new.** The constructors for every status this service can
  return. `PROBLEM_CATALOGUE` maps status → title; no route raises `ProblemException` with an
  ad-hoc status (plan §2.6).
- `core/body_limit.py` — **new.** Pure-ASGI pre-routing middleware enforcing the 64 KiB total
  body cap *before* anything parses the body.
- `core/headers.py` — **new.** `read_allowed()`, the general request-header allowlist.
  `x-user-email` is deliberately not in it (plan §4, conflict 13).
- `reports/caps.py` — **new.** Spec §2.4 as data, plus the truncator.
- `reports/schema.py` — **new.** Pydantic models for spec §2.1 exactly, plus `BoundedReport`.
- `reports/binding.py` — **new.** `bind()`: parse → structural caps → control-strip →
  truncate → validate.
- `reports/pipeline.py` — **new.** The `ReportPipeline` protocol and `BindOnlyPipeline`,
  which `OME-1008` replaces with `StorePipeline` (plan §6).
- `routes/reports.py` — **new.** `POST /v1/reports`.
- `core/problem.py` — **edit** (adds `render_problem`, which the ASGI middleware needs
  because it sits outside `ExceptionMiddleware` and cannot raise).
- `main.py` — **edit, as a diff** (plan §2.1): add the body-limit middleware, the pipeline
  assignment, and `include_router(reports.router)`. Nothing existing moves.

Tests (`apps/report-intake/tests/unit/`): `test_problem_catalogue.py`, `test_body_limit.py`,
`test_headers.py`, `test_caps.py`, `test_report_schema.py`, `test_reports_route.py`,
`test_mesh_header_containment.py`.

## Test plan

Boundaries first, since the boundaries are the deliverable.

- A report over the body cap is rejected with the cap named in the detail (413).
- A body whose declared length is under the cap is never buffered by the middleware.
- A chunked body that grows past the cap mid-stream is still rejected.
- Malformed JSON is 400; a JSON array at the top level is 422.
- A schema string from a future major is 400, not 422 — the client must not retry it.
- A payload nested past depth 6 is rejected; so is one with more than 64 keys on a node.
- A payload nested thousands deep does not crash the parser (`RecursionError` → 422).
- An unknown key at the top level is rejected; an unknown key inside `client` or `context`
  survives verbatim into the payload.
- Every truncating row of §2.4: `note`, `error.message`, `error.details`, `client`/`context`
  strings, `user_agent`, `notes[]` — each truncated, each marked, each still under its cap.
- An oversized traceback keeps its head **and** its tail.
- Control characters other than tab and newline are stripped; tab and newline survive.
- An ordinary report is returned byte-identical — the truncator is a no-op under the caps.
- `scanned` retains text that truncation removed from `payload` (the `OME-1007` seam).
- Structural: `x-user-email` is named in at most one module, and never in the report route or
  the report store; `read_allowed()` does not return it.

## Acceptance

- `POST /v1/reports` answers `202` with the spec §2.2 shape for an accepted report.
- Every row of the §2.4 caps table is enforced, with the reject/truncate split the spec
  states: only the total body cap and structural violations reject.
- Every error is `application/problem+json` from a catalogue constructor.
- `caller_email` is unconditionally `None` until `OME-1011` lands.
- `uv run pytest` / `ruff check` / `ruff format --check` / `pyright` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus two documentation refreshes the change invalidated —
  `apps/report-intake/README.md` (which said in so many words that `POST /v1/reports` arrives
  with `OME-1006`) and `apps/report-intake/docs/complexity-baseline.md` (whose `file:line`
  entries had all shifted).
- **Commits:** one on `OME-1002-report-intake-service`; sha recorded at squash-merge.
- **Gates:** `uv run .claude/scripts/run_gates.py report-intake` → ALL GATES GREEN.
  `pytest` 130 passed (87 new), coverage 99.48% against an 80% floor; `ruff check` clean;
  `ruff format --check` 38 files formatted; `pyright` 0 errors.
- **The complexity tier held without a single exemption.** The tree roughly tripled and none
  of the four headline numbers moved: C901 7, PLR0915 18, PLR0912 6, PLR0911 3, all still set
  by `OME-1005`'s `_classify_forwarded_allow_ips`. The baseline file is refreshed rather than
  loosened, which was the point of recording it.
- **Verified against a real server, not only `TestClient`:** `uv run report-intake` answers
  `/healthz` 200, `/readyz` 503 (so the CI image job's assertions still hold with a write
  endpoint present), `202` with the §2.2 body for a valid report, and `413` naming the cap for
  a 70 KB one.

### Three decisions worth re-reading before `OME-1007`–`OME-1011`

- **`json.loads` gives up before this service can measure anything.** Within the 64 KiB body
  cap a client can nest ~20,000 levels, which raises `RecursionError` inside CPython's own
  scanner — an unhandled 500 on input a client fully controls. It is caught in `_parse` and
  answered with the 422 the depth cap would have given. The depth and key-count walk is
  iterative for the same reason.
- **Validation runs *after* truncation, on the mapping that gets persisted.** "Validated,
  truncated report" then means one object rather than two hopefully-equal ones, and
  `BoundedReport.document` is a typed view of `BoundedReport.payload` rather than of something
  that no longer exists.
- **A 422 never echoes the value it rejected.** Pydantic's error objects carry the offending
  input alongside the reason; `_describe` reads `loc` and `msg` by name. Serializing one whole
  would quote free text back over an unauthenticated response, which is the leak the whole
  classification rule exists to prevent.

- **Deviations:**
  - **`403` is not in `PROBLEM_CATALOGUE` yet.** Plan §2.6 states the final set as
    `{400, 403, 413, 422, 429, 503}`; §12 assigns the `403` row to the same change that adds
    `bot_gate_required()` and `bot_gate_unverifiable()` — `OME-1011` — and says that change
    updates this item's catalogue-exactness test rather than leaving it to redden. Followed §12,
    since shipping the two constructors here with no gate to raise them would take `OME-1011`'s
    work and leave dead code. The test names `OME-1011` and the expected final set.
  - **`ref` is longer than the spec's illustrative `r_8f21c0`.** `secrets.token_hex(6)`, not 3:
    three bytes collide at a few thousand rows by the birthday bound, and this value is the
    primary key `OME-1008` declares unique. The spec's example is in a JSONC block, not in a
    normative table.
  - **`Content-Type` must be `application/json`, answered `400` when it is not.** Spec §2.1 says
    JSON only and §2.3's table has no `415`, so the catalogue's `400` carries it. This is what
    actually enforces "no form encoding, from any client": `enctype="text/plain"` is how a
    cross-site form is coaxed into producing a JSON-shaped body with no preflight, and a
    browser holding a live mesh session is the caller that matters there.
  - **A dropped `notes[]` entry is marked out of band only**, in `BoundedReport.truncations`.
    Every string cap marks in band so the mark survives into the payload and onto the ticket;
    for an item-count cap the in-band equivalent is a seventeenth entry in a list whose cap is
    sixteen.
  - **`Idempotency-Key` is passed through unbounded.** §2.4 gives it no row, and inventing a cap
    here would be spec drift — but it lands in a unique column. `OME-1008` owns bounding it.
