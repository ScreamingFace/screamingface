---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open (under OME-500)
stack: repo
status: in_progress   # planned | in_progress | done | blocked
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
