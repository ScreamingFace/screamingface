# Plan — link each paid-smoke dataset source to its pinned commit (OME-1524)

Spec: `docs/spec/2026-10-08-OME-1524-provenance-links.md` · ledger:
`docs/work/2026-10-08-provenance-links.md` · landing: the Engine's core provenance module and
inspect plugin, plus the paid smoke lane in the SDK tests. Nothing paid runs.

## Owner calls (2026-10-08)

- One PR across both landings, as OME-1492 PR 3 did.
- `web_url()` stays as it is; the link is a new `url` field.
- The two prior-test edits and the two paid-lane files are pinned in
  `.claude/test-change-approvals/OME-1524.json`.

## Steps (each `[step] → verify`)

1. Core link builders + `hugging_face_source` adds `url` → verify:
   `tests/unit/test_bundle_provenance_links.py` (commit-only, repo-id-only, tree vs blob,
   GitHub blob, config dropped, no key when unlinked).
2. IFEval's vendored-file source gets its GitHub link → verify: the IFEval prepare test, the
   expected link derived from the vendored banner's upstream path.
3. `CaseSource.url` (outside equality), filled by every describer; the replay label drops a
   None link → verify: `tests/unit/inspect/test_case_source_links.py`.
4. Run page renders the link, escapes the cell, links http(s) only → verify: new tests in
   `packages/screamingface/tests/paid/test_case_provenance.py`.
5. `copy_labels` + the smoke's overview step calls it → verify: one file per picked
   Benchmark, shared bundles resolved, missing labels skipped, never `cases.json`.
6. Gates: `run_gates.py screamingface-engine`, `run_gates.py screamingface`, extra-less
   Engine pyright, and the paid lane's free tests with `SCREAMINGFACE_TEST_PAID=1`.
