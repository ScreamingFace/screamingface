---
ticket: OME-950
stack: url4
status: done
started: 2026-08-23
finished: 2026-08-23
---

# OME-950 — report relative URL4 routes in span names

## Intent

Make the existing URL4 span stream identify relative operations by their static route template.
This supplies the one missing fact needed for exact terminal Case counting from ordinary spans,
without adding a second progress-event path or coupling URL4 to ScreamingFace Benchmarks.

## Planned changes

- `docs/tasks/2026-08-23-OME-950-relative-route-span-name.md`
- `docs/spec/2026-08-23-OME-950-relative-route-span-name.md`
- `docs/plan/2026-08-23-OME-950-relative-route-span-name.md`
- `docs/work/2026-08-23-OME-950-relative-route-span-name.md`
- `packages/url4/tests/unit/test_observe.py`
- `packages/url4/src/url4/dag/executor.py`

## Test plan

- RED: execute a successful relative fetch and require its start observation to name the route.
- RED: execute a failing relative fetch and require the same route detail plus a matching error
  finish.
- Preserve all existing detail sources and the start/finish span bijection.
- Pin remote URL4 operations to an unqualified static path; their existing node kind distinguishes
  them from local relative operations.
- Run the complete URL4 quality gate, including lint, format, typecheck, tests, and coverage.

## Acceptance

- Relative URL4 spans expose only the authored static path template.
- Remote URL4 spans expose the same static path and retain their distinct operation name.
- Successful and failed terminal relative operations are distinguishable by route and existing
  status without any new event type.
- Rendered URL4, execution results, scheduling, and existing observation fields are unchanged.
- The full URL4 quality gate passes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** all six planned files — four SDLC artifacts, the URL4 DAG observer detail
  selector, and its observation tests. Review follow-up coverage pins the remote node's
  unqualified path and distinct node kind.
- **Commits:** `34cea424` — `fix(url4): report relative routes in span names`; this final ledger
  evidence update follows in the documentation commit.
- **Gates:** RED: 2 failed for empty relative-node detail; focused GREEN: 2 passed; full URL4
  suite: 1161 passed; `uv run .claude/scripts/run_gates.py url4`: ALL GATES GREEN (append-only,
  ruff check, ruff format, pyright, pytest with 95% coverage floor).
- **Review follow-up:** the owner approved revising the prior remote test after confirming that
  `SpanData.operation` already preserves `RemoteFetchNode` versus `RelUrlNode`. The final
  production diff is the single `path` tuple entry; remote detail stays unqualified and consumers
  match `(operation, name)`. The append-only gate is intentionally skipped for that one approved
  expectation correction. Focused local-success, local-error, and remote-boundary tests: 3 passed;
  `uv run .claude/scripts/run_gates.py url4 --skip-append-only`: ALL EXECUTABLE GATES GREEN (ruff
  check, ruff format, pyright, full pytest with the 95% coverage floor).
- **Deviations:** none.
