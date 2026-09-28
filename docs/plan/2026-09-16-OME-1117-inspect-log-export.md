# OME-1117 — Plan: export a report in inspect's log format

Spec: `docs/spec/2026-09-16-OME-1117-inspect-log-export.md` · Stack: `screamingface`

## Steps (each `[step] → verify: [check]`)

1. **`pyproject.toml` + lockfile** — add `[project.optional-dependencies] inspect =
   ["inspect-ai==0.3.263"]`; `uv lock`.
   → verify: `uv lock --check` green; `uv sync --extra notebook` still installs no
   inspect distribution.
2. **RED — payload mapping tests** (`tests/test_inspect_log_payload.py`, pure):
   provenance block; sample mapping (input turns, output, scores, failed-case
   metadata, refusal); target `""`; selected-case dataset size; cost passthrough
   as `total_cost`; status success/error; multi-candidate selector + refusals;
   `.eval` suffix guard; `candidate=` with json refused.
   → verify: fails with `ModuleNotFoundError`/`AttributeError` (module absent).
3. **GREEN — `_inspect_log/payload.py`** — small pure builders (ruff caps:
   complexity 8 / statements 26): `_spec_payload`, `_sample_payload`,
   `_results_payload`, `_stats_payload`, `eval_log_payload(report, candidate)`.
   → verify: step-2 tests pass; whole prior suite green.
4. **RED — writer tests** (`tests/test_inspect_log_write.py`): missing-dep error
   names `screamingface[inspect]` (sys.modules stub removal); happy path via
   stubbed `inspect_ai.log` module (asserts `model_validate` + `write_eval_log`
   called with our payload and the selected path).
   → verify: fail for the right reason.
5. **GREEN — `_inspect_log/write.py` + `__init__.py`** — find_spec gate, lazy
   import, file-level `# pyright: reportMissingImports=false` with WHY.
   → verify: step-4 green.
6. **RED — export seam tests** (extend `tests/test_report.py` — append-only):
   `export(format="inspect")` writes `report.eval` for a single-candidate report;
   path default per format; json branch byte-identical (existing tests untouched).
   → verify: fail on unknown kwarg.
7. **GREEN — `report.py` export seam** — new signature, lazy `_inspect_log` import,
   format dispatch; Feynman docstring.
   → verify: step-6 green; full suite green except public-surface snapshot.
8. **Surface snapshot** — regenerate (`UPDATE_SURFACE_SNAPSHOT=1`), diff shows only
   the `export` signature rows. **Owner sign-off required (append-only gate).**
   → verify: `pytest tests/test_public_surface.py` green.
9. **Live round-trip test** (`tests/test_inspect_log_live.py`,
   `pytest.importorskip("inspect_ai")`): export → `read_eval_log` → status,
   samples, provenance metadata, total_cost. Skipped in CI; run locally with the
   extra.
   → verify: green under `uv run --extra inspect pytest tests/test_inspect_log_live.py`.
10. **Gates** — `uv run ../../.claude/scripts/run_gates.py screamingface` (or repo
    runner path) all green.
11. **Ledger outcome + commit(s) + PR** — conventional commits, `Refs: OME-1117`;
    PR ≤500 LoC (single PR expected: ~2 modules + tests).

## Files

- `packages/screamingface/pyproject.toml`, `uv.lock`
- `packages/screamingface/src/screamingface/_inspect_log/{__init__,payload,write}.py`
- `packages/screamingface/src/screamingface/report.py` (export seam only)
- `packages/screamingface/tests/test_inspect_log_payload.py`
- `packages/screamingface/tests/test_inspect_log_write.py`
- `packages/screamingface/tests/test_inspect_log_live.py`
- `packages/screamingface/tests/test_report.py` (append-only additions)
- `packages/screamingface/tests/public_surface_snapshot.json` (regen — owner ask)

## Edge cases

- Failed candidate (score None): status `"error"`, no results scores metrics beyond
  coverage? → keep `results.scores` with `coverage` only when score is None.
- Case with no output (failed before answer): sample without `output`, failures in
  metadata.
- `cost_usd` None (unpriced): `total_cost` omitted, `cost_usd: null` in metadata —
  never fabricated.
- Multi-turn envelope input: decoded turns; opaque/undecodable input: raw string.
- Duplicate default filename: overwrite (same convention as json export).

## Risks

- Public-surface snapshot regen trips the append-only gate → planned owner ask.
- Coverage 95%: payload+write fully covered via stubs; live test skipped in CI
  (its lines are test code, not source).
