---
ticket: OME-1404
stack: screamingface-engine
status: done
started: 2026-09-29
finished: 2026-09-29
---

# glossary-renames — rename the engine's benchmark code to the `CONTEXT.md` glossary

## Intent

A newcomer to the engine's benchmark code has to learn a private dialect first ("board", "exam",
"bake", "spine", "row", "verdict", …). Several of those words mean something else in the
project glossary (`CONTEXT.md`): "board" is its avoid word for Leaderboard, "row" for Case.
This unit renames the internal Python names to glossary words and adds glossary entries for the
words that stay. It's a pure rename: no behaviour, revision or wire string changes.

The spec is the Linear issue itself (three rename tables, eight glossary drafts, two owner
decisions: one PR, and "bake" goes). This ledger does not copy the tables.

## Planned changes

One PR, one commit per rename group, each passing the gates on its own:

1. `CONTEXT.md`: the Recipe fix and the eight new entries.
2. The inspect plugin's own names (first table, minus board / exam / bake).
3. "board" → benchmark across core and plugin.
4. "exam" → variant, and "row" → case grade.
5. `spine/` → `shared_grading/`, `ScoredPath`, stage → phase, `bind_*`, DRACO tasks, smaller names.
6. The wire-contract Python names (draft feedback, case grade, loop outcome, graded answer,
   judge evidence), keeping every wire string.
7. "bake" → "prepare" in code, living engine docs, Dockerfiles and CI comments.

Tooling: a token-aware renamer (NAME tokens renamed exactly; comments and docstrings get the
prose pass; wire strings masked), so string literals a client reads can't change by accident.

## Test plan

- A rename adds no behaviour, so no new tests. The proof is that nothing observable moved:
  - a fingerprint of all 35 registered boards (revision, rendered URL4 protocol, catalogue
    fields, asset bundle id), taken on `main` before the first commit and diffed after each
    group: it must stay byte-identical;
  - ruff, ruff format, pyright, the layering check, the full engine suite and the inspect lane
    after each group.

## Acceptance

- Each "Today" name in the ticket's three tables greps to 0 in the engine, apart from the wire
  strings each row keeps.
- The fingerprint of all 35 boards stays byte-identical to `main`.
- Full engine suite + inspect lane pass; `test_published_revisions.py` passes with its literals untouched.
- `CONTEXT.md` has the Recipe fix and the eight entries.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** 233 files under `apps/screamingface-engine` (src, tests, engine docs, Dockerfiles,
  `pyproject.toml` comment), three engine CI workflow comments, `CONTEXT.md`, this ledger and the task
  mirror. 43 file renames (modules and test files).
- **Commits:** one per rename group, each gated on its own:
  `docs: add the benchmark-preparation words to the glossary` · the inspect plugin's own names ·
  board → benchmark · exam → variant and row → case grade · spine / ScoredPath / stage / bind / judge
  requests / pins · the wire-contract Python names · bake → prepare · the last `bind_*` record builders.
- **Gates:** ruff, ruff format, pyright 0 errors, layering OK, `uv lock --check`; full suite 4623 passed
  (94% coverage); inspect lane 496 passed. Fingerprint of all 35 boards (revision, rendered URL4
  protocol, catalogue fields, asset bundle id) and the served OpenAPI/AsyncAPI documents byte-identical
  to `main`, checked after every group.
- **Deviations:**
  - `ScoredPath` became `BenchmarkAggregation`, not the ticket's `RubricAggregation`: it also drives
    IFEval (deterministic) and the imported inspect benchmarks.
  - `spine/exam.py` became `shared_grading/mean_scorer.py`, not `variant.py`: it holds the mean scorer,
    no variant.
  - `records.bind_case` / `bind_check` became `case_record` / `check_record` (not `build_case_record`,
    which those modules already import).
  - stage → phase covers the ticket's three names plus their helpers and the one implementer
    (`ActivityPhase`); the activity tests' own "stage" wording is left alone.
  - Kept on purpose: public benchmark descriptions and client-facing failure messages that say "board"
    or "baked"; route-handler parameters the URL4 protocol binds by name (`case_evaluations`); the
    authoring guide's exam analogy and the "exam hall" analogies in `candidate_scope.py`.
  - Not touched: dated SDLC records (`docs/spec|plan|work|tasks`), the engine CHANGELOG, and the SDK
    package (its README, notebook and justfile still say "bake"; SDK owners' call).
  - Spec was the Linear issue itself; no separate `docs/spec` / `docs/plan` files.
- **Rebase onto #1113 (2026-09-30):** the grader-role judge merged first, so its new code went
  through the same rename groups (its `boards.py` / `single_shot.py` conflicts resolved by
  re-running each group's renamer, and `test_judge_grader_role.py`'s imports and names renamed
  inside each group's commit). Review cleanups folded into their groups: leftover test names
  (`test_build_tasks_*`, `test_recovered_array_*`, `test_case_evaluation_endpoint_*`, the inspect
  `*snapshot*` tests), three "shim" comments, one half-renamed importer template, and the
  loop-outcome ContextVar's name. `CONTEXT.md` also gained an **Inspect** entry: a name that starts
  with `inspect` means the inspect_ai framework.
- **Owner-verify:** merge; rebase #1096 onto it (it touches renamed files). Follow-up outside this
  PR: `.claude/agents/sf-code-review.md` still names `spine/rubric.py` and
  `CheckSurface.expected_check_cost` (owner-territory file, separate small PR).
