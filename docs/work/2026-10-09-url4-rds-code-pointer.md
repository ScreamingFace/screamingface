---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open (under OME-500)
stack: repo
status: in_progress   # planned | in_progress | done | blocked — built; waits for PR-open (user) and K1–K9 (Kevin)
started: 2026-10-09
finished:
---

# url4-rds-code-pointer — URI intents run as RDS code-pointer calls (url4 2.0.0)

## Intent

Spec, plan and build a url4 package change: a relative-URI or `url4://` intent becomes an RDS
code-pointer call that receives the group's sources as structured data (URL4 Spec B §6).
2026-10-09: the user approved the spec in plain words and chose "plan + code on the K1–K9
defaults; stop before the PR". Kevin McDonough confirms K1–K9 in parallel. Version: join the
pending 2.0.0 (release PR #852 merges after this PR).

## Planned changes

- `docs/spec/2026-10-09-url4-rds-code-pointer/00-overview.md`
- `docs/spec/2026-10-09-url4-rds-code-pointer/prd/rds-code-pointer.md`
- `docs/spec/2026-10-09-url4-rds-code-pointer/contracts.md`
- `docs/spec/2026-10-09-url4-rds-code-pointer/test-plan.md`
- this ledger
- `docs/plan/2026-10-09-url4-rds-code-pointer.md` (Tasks 0–6)
- code, `packages/url4/src/url4/`: `core/errors.py`, `core/_annotations.py`, `core/intent.py`
  (new), `wire/rds.py` (new), `wire/subrequest.py`, `peer/_dispatch.py`, `peer/direct.py`,
  `peer/_http.py`, `dag/nodes/_shared.py`, `dag/nodes/group.py`, `dag/nodes/fetch.py`,
  `dag/nodes/code_pointer.py` (new), `dag/nodes/iteration.py`, `dag/_wiring.py`,
  `dag/_lowering.py`, `io/http.py`, package exports
- tests, `packages/url4/tests/`: `spec/test_rds_code_pointer.py`, `unit/test_intent_classifier.py`,
  `unit/test_rds_document.py`, `unit/test_rds_dispatch.py`, `unit/test_http_remote_errors.py`
  (new); appends to `spec/test_param_conformance.py`; approved flips CH8–CH10 in
  `unit/test_dag.py` and `unit/test_characterization.py`
- `packages/url4/README.md` ("Migrating to 2.0"), `docs/spec/2026-07-11-url4-package-v1-spec.md`

## Test plan

PRD §7 rows CH1–CH11 and 1–29, in the plan's task order (CHAR first). Gates:
`run_gates.py url4`. Regression: the Engine unit suite and the SDK suite with no test edits.

## Acceptance

- Every PRD §7 row (CH1–CH11, 1–29) has a test; CH8–CH10 are the only changed prior tests.
- `run_gates.py url4` green (append-only against the merge base names only the two CH8–CH10
  files until the PR-open manifest exists).
- Engine unit suite and SDK suite green against this url4 with no test edits.

## Notes

- The user's decisions U1, U2, U3a/U3b, U4 and the release rule are recorded as ans:Q1–Q5 in the
  overview §4.
- Probes ran on 2026-10-09 with `uv run` in `packages/url4` (url4 1.5.1, `origin/main` at
  `93fef7ae5`). They confirmed the three facts in the task: the combine intent fails with
  `endpoint_not_found`; `extract=last_number@1` fails `param-value`; `\'` and `\\` escapes
  round-trip and `''` does not.
- Extra findings from the probes, recorded as open items, not fixed here:
  - `intent_atom` classifies relative and remote *expressions* in intent position as
    `RelUrl`/`Url`, so they run as data reads with unresolved `$1` and a still-quoted intent
    (overview O2). This affects the E4a "Next stage" form.
  - The iteration reducer `(…)!/reduce` (no parens) passes the string `/reduce` to the `process`
    hook as a prompt (PRD D8 fixes it as part of 2.0).
  - A call's own URI intent is resolved on the caller node (overview O1).
- Monorepo search: no live production code uses a URI intent (overview §8). The first real user
  is the local E4a nested-url4 plan.
- Part G §26 is unpublished, so every wire detail is `[proposed]`.
- Linear: none now. At PR time, after the user confirms, file one issue under OME-500.

## Build log (2026-10-09)

- Orchestration: the main loop planned and reviewed; Haiku `implementer` agents built Tasks
  0–4b from the plan; a `design-reviewer` reviewed Tasks 0–2.
- Design review, Tasks 0–2: two STRUCTURAL findings. (1) The classifier re-derived the
  grammar's production rules and disagreed with them (`/p?a=(b)`, `url4://:80/p`,
  `/rows*()!'R'`). The plan's A4 caused it. The main loop rewrote the classifier on
  `parse_value` (plan L7, `642664416`). (2) CH11 rows 3 and 5 also flip (E2); spec and plan
  fixed (`597146a2a`). Fixes 3–7 in `cbc4023b1`.
- Deviation, TDD order: in `cbc4023b1` the `ValueError` catch and the input-type check were
  written before their tests. The RED evidence is the reviewer's probes on the old code.
- Deviation, gate: `cbc4023b1` was committed while `run_gates.py url4` (base `HEAD`) was red on
  the append-only check (two comment-anchor edits in helpers of a test file new on this branch).
  Against the merge base (the pre-push standard) all gates are green. Since then every commit
  checks the gate's exit code.
- Append-only: from Task 4a, `run_gates.py url4 --base <merge-base>` names only
  `tests/unit/test_dag.py` and `tests/unit/test_characterization.py` (CH8–CH10). The other gates
  run with `--skip-append-only`. The manifest `.claude/test-change-approvals/OME-N.json` is
  written at PR-open.
- Task 4b (`8a1f907e5`): broadcast parts have no barrier (same as the LLM broadcast); the
  required-failure test was made deterministic (one source). A malformed URI reducer now fails
  with `malformed_source` at run time (L7 rule).
- New owner item O6 (out of scope, 1.5.1 bug): an LLM-mode broadcast calls `process("")` for a
  failed `;optional` source and keeps a row with an empty result; the collector's skip never
  fires. The RDS path does not have this bug (no call, no row, PRD D7).
- Owner decisions still open: L7 (`url4://n` with no path → `malformed_source`), and Kevin's
  K1–K9.

## Outcome (2026-10-09; the PR is not open)

- **Actual files:** as planned, plus `tests/spec/test_rds_code_pointer_sites.py` and
  `tests/spec/test_rds_code_pointer_http.py` (split for the file-size limit). `wire/__init__.py`
  has no re-exports (callers import submodules). `dag/_lowering.py` grew to 805 lines (it was
  over the 450 limit before this branch): follow-up to split it.
- **Commits:** `bb62875bf` plan · `a111734a4` CHAR · `c5be3be1a`, `1c23ee93f`, `642664416`
  classifier · `95c36b0cb`, `cbc4023b1` codec · `6e89be938` dispatch · `5b742cff2`
  `feat(url4)!` group path · `8a1f907e5`, `10b4d8d90` broadcast + reducer · `0d192610f` remote
  error code · `bf3f64148` HTTP + E4a rows · `6c9584779`, `c910b3807` review-fix round ·
  `597146a2a`, `65ab7f69a`, `f270b4ea6` + this commit docs.
- **Gates:** `run_gates.py url4 --skip-append-only` ALL GREEN (1543 tests, coverage ≥ 95%).
  `--base <merge-base>` append-only names only `tests/unit/test_dag.py` and
  `tests/unit/test_characterization.py` (CH8–CH10; manifest at PR-open).
- **Regression:** Engine `tests/unit` 4638 passed, no test edits (run twice, the second after
  the fix round). SDK 2221 passed + 159 notebook-widget tests with `--extra notebook` (the 14
  first-run failures were the missing extra, not url4).
- **Reviews:** `design-reviewer` ×2 and `sf-code-review`: no open STRUCTURAL finding; every
  FIX applied (plan "Review round" R1–R6). Kept by decision: a reducer head the grammar cannot
  parse still fails at `validate()`/run time (1.5.1 behavior, `test_validate_parses_reducer_instruction`).
- **Deviations:** see the build log above; new owner items O6, O7; new input for Kevin on K2
  and K5.
- **Before the PR:** rebase on `origin/main`; the user confirms the issue text; file one issue
  under OME-500; rename the branch `OME-N-url4-rds-code-pointer`; write
  `.claude/test-change-approvals/OME-N.json` for CH8–CH10; mirror in `docs/tasks/`; the PR body
  says #852 merges after this PR; squash title `feat(url4)!: run URI intents as RDS
  code-pointer calls` with the `BREAKING CHANGE:` footer.
