---
ticket: OME-1117
stack: screamingface
status: done
started: 2026-09-16
finished: 2026-09-16
---

# OME-1117 — Export a report in inspect's log format

## Intent

Give researchers in the inspect ecosystem a way to open our run results in the tooling
they already use: `report.export(format="inspect")` writes a one-way `.eval` log from a
completed report — provenance-labeled as produced by the ScreamingFace engine, carrying
the run's real metered cost — that `inspect view` opens with nothing new to install.
One-way only: the log is never re-imported and never feeds the leaderboard.

Note: `OME-1117` carries a blocked-by relation on `OME-1115` (imported-board e2e).
The export lands in `packages/screamingface` against report.v1 and must work for
home-grown-board reports too, so the code proceeds now; only the final
imported-board proof waits on `OME-1115`. Owner directed start 2026-09-16.

## Planned changes

- `packages/screamingface/pyproject.toml` + `uv.lock` — new `inspect` extra pinned
  `inspect-ai==0.3.263` (engine's pin)
- `packages/screamingface/src/screamingface/_inspect_log/{__init__,payload,write}.py` —
  pure payload mapping + quarantined writer (lazy import, find_spec gate)
- `packages/screamingface/src/screamingface/report.py` — `export(path=None, *,
  format="json"|"inspect", candidate=None)` seam
- `packages/screamingface/tests/test_inspect_log_{payload,write,live}.py` + append-only
  additions to `tests/test_report.py`; `public_surface_snapshot.json` regen (owner ask)
- Spec `docs/spec/2026-09-16-OME-1117-inspect-log-export.md`; plan
  `docs/plan/2026-09-16-OME-1117-inspect-log-export.md`
- No schema/model change → no migration (S1 n/a)

## Test plan

- Pure payload tests (no inspect installed): provenance block, sample mapping
  (turns/output/scores/failures/refusal), target "", cost → `total_cost`, status
  success/error, multi-candidate selector + refusal messages, suffix guards
- Writer tests via sys.modules stubs: missing-dep error names `screamingface[inspect]`;
  happy path calls `model_validate` + `write_eval_log` with our payload
- Export seam tests: format dispatch, per-format default paths, json branch untouched
- Live opt-in round-trip (`importorskip`): export → `read_eval_log` → status/samples/
  metadata/total_cost — run locally with the extra, skipped in CI

## Acceptance

- A completed report exports to a `.eval` file that `inspect view` (inspect_ai's reader)
  opens; the log carries the provenance label and the run's real metered cost.
- No re-import surface; leaderboard untouched.
- Works for a home-grown-board report, not only imported boards.

## Wisdom review (pre-commit)

- Design: one pure mapping module + a quarantined writer behind the extra — no reader,
  no multi-log export surface (YAGNI held; "export all" is a caller loop).
- Tests name the invariants: one-way provenance stamp, metered cost passed through
  (never fabricated), SELECTED dataset size, scored-case output/refusal exclusivity.
- Blast radius: `Report.export` signature (additive; old calls byte-identical) →
  surface snapshot regen (owner sign-off); new `inspect` extra + declared uv conflict
  with `runtime` (upstream pins genuinely incompatible, verified).
- Security: no secrets touched; export is a local, user-initiated file write of the
  user's own run data.
- S1 n/a (no schema/model change). No bare except. One file-level
  `reportMissingImports=false` (engine shim precedent, WHY comment attached).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `[tool.uv] conflicts` in
  `packages/screamingface/pyproject.toml` (see Deviations); `tests/test_report.py`
  gained 4 appended seam tests (pure insertions, verified).
- **Commits:** 4b476287 — feat(py-screamingface): export a report in inspect's
  .eval log format (docs commit follows).
- **Gates:** `run_gates.py screamingface --skip-append-only` ALL GREEN (ruff check,
  format, pyright 0 errors, pytest 1525 passed / 23 skipped, cov ≥95%, notebooks,
  uv build, distribution check). Append-only flag: only the regenerated
  `public_surface_snapshot.json` (two additive `export` signature rows) —
  owner-approved 2026-09-16. Live acceptance:
  `uv run --extra inspect pytest tests/test_inspect_log_live.py` — 1 passed
  (inspect's own reader opens the export; provenance + total_cost verified).
- **Deviations:** (1) `inspect-ai==0.3.263` and the runtime extra's
  `litellm==1.98.0` cannot co-install on any platform — declared as a genuine
  `[tool.uv] conflicts` pair instead of loosening a pin; local-runtime users export
  from a separate env. (2) A graded refusal exports with the refusal text as the
  scored answer (OME-1037 exclusivity), discovered at RED. Ticket's blocked-by on
  `OME-1115` covers only the imported-board proof; export verified on home-grown
  report fixtures per the ticket's own Don't-regress clause.
