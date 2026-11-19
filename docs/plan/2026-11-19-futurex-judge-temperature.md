# FutureX-Past Judge temperature — Implementation Plan

**Goal:** the futurex_past Judge sends no `temperature`, and a guard keeps it that way.
**Spec:** `docs/spec/2026-11-19-futurex-judge-temperature.md`
**Ledger:** `docs/work/2026-11-19-futurex-judge-temperature.md`
**Stack:** python (`apps/screamingface-engine`), uv, pytest (inspect extra), ruff, pyright.
**Worktree:** `.claude/worktrees/futurex-judge-temperature` (branch `futurex-judge-temperature`, from `origin/main` c403ebd33).

## Global constraints

- Prior tests are append-only. The only literal edit is the futurex_past fingerprint (and, on a
  bump, the published-revision pin), per the revision rule.
- No network in tests. No real Judge call.
- The other four `temperature: 0` rows do not change.

## Review focus

1. Only the futurex_past fingerprint moves; every other fingerprint and published revision holds.
2. The guard matches by prefix `openrouter/openai/gpt-5` and reads `JudgeSpec.params` only.
3. The NAMED DEVIATION and the README say the same thing.

### Task 1 — RED

**File:** new `apps/screamingface-engine/tests/unit/inspect/test_judge_param_support.py`
(header: `# pyright: reportMissingImports=false` + WHY, `pytest.importorskip("inspect_ai")`,
`pytest.importorskip("inspect_evals")`, as in `test_benchmark_fingerprints.py`).

- [ ] `test_no_openai_reasoning_judge_pins_temperature`: over `BENCHMARKS`, collect each row
  whose `judge` is set and whose `judge.model` starts with `openrouter/openai/gpt-5` and whose
  `judge.params` has a `temperature` name. Assert the list is empty; the message names the keys
  and the WHY (`require_parameters`).
- [ ] `test_futurex_past_judge_sends_no_temperature`: the futurex_past row's `judge.params` equals
  `(("web_search", "false"), ("max_tokens", "4096"))`.
- [ ] Run `cd apps/screamingface-engine && uv run pytest tests/unit/inspect/test_judge_param_support.py -q`
  → both fail, naming futurex_past.

### Task 2 — GREEN

- [ ] `benchmarks.py`, futurex_past `JudgeSpec`: params → `(("web_search", "false"), ("max_tokens", "4096"))`.
  Replace the comment with: NAMED DEVIATION — Futurex-Eval asks at temperature 0; OpenRouter
  serves gpt-5.4 with no temperature control and the gateway forces `require_parameters`, so a
  pin fails every Judge call; no temperature, as on the other gpt-5.4 rows (OME-1602).
- [ ] Run the new tests → green. Run `test_benchmark_fingerprints.py` → futurex_past red.
- [ ] `just engine benchmark-bump futurex_past` → read the new fingerprint.
- [ ] Q1 = hold: update only the futurex_past literal in `test_benchmark_fingerprints.py` with a
  comment naming the old value and why.
  Q1 = bump: also `published_revision` on the row, `test_published_revisions.py` (comment with
  the old id and why), and a `CHANGELOG.md` line.

### Task 3 — docs

- [ ] `local_tasks/futurex_past/README.md`: the Judge paragraph (no temperature, why); the router
  sentence ("routes again at temperature 0" → at the Judge's default); add a named deviation.
- [ ] `docs/benchmarks-fidelity/futurex_past.md`: the judge row "Ours" text and the quoted
  `JudgeSpec` at the end; mark the change with the date and this unit's ticket.

### Task 4 — gates and commit

- [ ] `uv run .claude/scripts/run_gates.py screamingface-engine` (from the repo root) → green.
- [ ] Ledger Outcome filled.
- [ ] Commit: `fix(screamingface-engine): stop the FutureX-Past Judge sending temperature 0`.
- [ ] Push the branch. At PR-open, after the user confirms: file a `bug` in Triage (unassigned,
  landing `screamingface-engine`, `actor: agentic`, Irina + Kevin tagged), mirror in `docs/tasks/`,
  rename the branch `OME-N-futurex-judge-temperature`, `Refs: OME-N` in the PR body.
