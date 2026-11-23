---
ticket: OME-1977
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-11-19
finished: 2026-11-19
---

# futurex-judge-temperature — stop the FutureX-Past Judge sending temperature 0

## Intent

On the hosted Engine, FutureX-Past fails every level-3 and level-4 Case as `scorer_error`.
The Judge row pins `temperature: 0` on `openrouter/openai/gpt-5.4`. The gateway always sends
`provider.require_parameters = true`, and no OpenRouter endpoint for gpt-5.4 accepts
`temperature`. So every Judge call fails, and a full run grades levels 1-2 only. This unit
removes the pin, as on every other gpt-5.4 Judge row (OME-1602), and adds a catalogue guard so
that no gpt-5 Judge row can pin `temperature` again.

Spec: `docs/spec/2026-11-19-futurex-judge-temperature.md` · Plan: `docs/plan/2026-11-19-futurex-judge-temperature.md`

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — the futurex_past
  JudgeSpec params and comment; a new NAMED DEVIATION comment.
- `apps/screamingface-engine/tests/unit/inspect/test_judge_param_support.py` — new guard test.
- `apps/screamingface-engine/tests/unit/inspect/test_benchmark_fingerprints.py` — futurex_past
  fingerprint literal.
- Revision: per Q1 in the spec. Hold → no other pin changes. Bump → `published_revision`,
  `test_published_revisions.py`, `CHANGELOG.md`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/local_tasks/futurex_past/README.md`
  — Judge and router sentences; a new named deviation.
- `apps/screamingface-engine/docs/benchmarks-fidelity/futurex_past.md` — judge row and the
  row quote.

## Test plan

- RED: `test_no_openai_reasoning_judge_pins_temperature` fails on main (futurex_past is the
  only offender).
- RED: `test_futurex_past_judge_sends_no_temperature` — the futurex_past JudgeSpec has no
  `temperature` and keeps `max_tokens=4096` and `web_search=false`.
- GREEN: drop the pin; both pass. The futurex_past fingerprint literal turns red → update it.
- All prior tests stay unchanged and green.

## Acceptance

- The futurex_past Judge call carries no `temperature`.
- The guard test fails if any `openrouter/openai/gpt-5*` Judge row pins `temperature`.
- `run_gates.py screamingface-engine` is green.
- README and Fidelity Record say what the Judge sends now.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, minus the bump files (Q1 = hold): `benchmarks.py` (futurex_past
  JudgeSpec), new `tests/unit/inspect/test_judge_param_support.py`,
  `tests/unit/inspect/test_benchmark_fingerprints.py` (futurex_past moved to the held group,
  `200cf4f72481ffb0` → `cbf11bdc4466620e`), `tests/unit/inspect/test_local_task_futurex_past.py`
  (`_JUDGE_PARAMS` only), `local_tasks/futurex_past/README.md`,
  `docs/benchmarks-fidelity/futurex_past.md` (new "Since the audit (2026-11-19)" section,
  frontmatter fingerprint).
- **Commits:** `fix(screamingface-engine): stop the FutureX-Past Judge sending temperature 0`.
- **Gates:** ruff check OK; ruff format --check OK (1438 files); pyright 0 errors (venv without
  the inspect extra, as CI); check_layering OK; pytest (inspect extra) 13700 passed, 240 skipped,
  8 failed. The same 8 fail on clean `origin/main` c403ebd33 (enigmaeval catalogue rows,
  import-isolation tests), so they predate this unit. After filing OME-1977 and writing
  `.claude/test-change-approvals/OME-1977.json`, `run_gates.py screamingface-engine` → ALL GATES
  GREEN (append-only, ruff, format, pyright, layering, pytest with coverage; venv without the
  inspect extra, as CI's typecheck).
- **Deviations:** two prior tests changed with owner approval (2026-11-19):
  `test_benchmark_fingerprints.py` (futurex_past literal, held-id rule) and
  `test_local_task_futurex_past.py` (`_JUDGE_PARAMS` constant only, no assertion changed).
  Published revision held at `200cf4f72481ffb0` (owner Q1).
