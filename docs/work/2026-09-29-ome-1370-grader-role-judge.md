---
ticket: OME-1370
stack: screamingface-engine
status: done
started: 2026-09-29
finished: 2026-09-29
---

# ome-1370-grader-role-judge — let a judged board's judge fill inspect's grader role

## Intent

Judged imports (OME-1240) only work when the eval names its judge model in a scorer kwarg
(FrontierScience). Most inspect judges instead ask for "the grader":
`get_model(role="grader")`. Outside inspect's own eval loop nothing fills that role, so today
such a scorer either raises "No model specified" on every case or, when `INSPECT_EVAL_MODEL`
is set, falls through to a vendor model we don't meter. This unit lets a board row declare
`JudgeSpec(model=..., role="grader")`. During the grading pass the role is then bound to our
metered `screamingface/<model>` provider, next to the judge transport the aggregate already
binds.

Verified in inspect 0.3.263 (`inspect_ai/model/_model.py`): `get_model(role=...)` reads
`model_roles()`, a ContextVar (default `{}`) set by `init_model_roles`. Unbound role, no
`default` → active model → `INSPECT_EVAL_MODEL` → `ValueError`.

SimpleQA's board itself is NOT in this unit (ticket comment, 2026-09-29): its CSV data waits on
OME-1273, its paper scorer returns a dict score the shim cannot map, and its default scorer
calls the judge with tools, which the provider refuses.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py`: `JudgeSpec.role`
  (default `None`); revision pin `judge_role=<role>` only when set, so no published revision
  moves; `_judged_aggregate` binds the role when declared.
- `apps/screamingface-engine/src/screamingface_engine_inspect/judge_provider.py`:
  `bound_judge_role(role, model)`, which scopes the role binding to one grading pass.
- `apps/screamingface-engine/src/screamingface_engine_inspect/boards.py`:
  `_check_judge_declaration` accepts a role-bound judge. The role must be `grader`, and the
  scorer kwargs must dial no gateway judge (one judge, one path). The `model_graded_*`
  refusal message now points at `JudgeSpec(role="grader")`.
- Tests under `apps/screamingface-engine/tests/unit/inspect/`.

## Test plan

- Provider: a role-based scorer (`model_graded_qa` with no model) grades through the provider
  when the role is bound; the binding does not leak past its block; unbound role + no env model
  → the case fails, and no fetch happens.
- Assembly: role-bound board assembles; revision moves with the role pin; unsupported role
  refused by name; role-bound judge plus a gateway kwarg refused; `model_graded_*` without a
  judge still refused.
- End to end: a role-bound board's aggregate dials `/judge-4` with pinned params; the judge's
  tokens land in the case evidence accounting (the usage-sink acceptance).
- Regression: `test_published_revisions` and the FrontierScience board suite stay green.

## Acceptance

- Ticket acceptance 1 (role-based judge call through our provider, tokens in the usage sink)
  and 3 (refusal kept for role-based boards with no `JudgeSpec`).
- The whole `tests/unit/inspect` lane stays green; no published revision moves.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. `judge_provider.py` gains `bound_judge_role`; `single_shot.py`
  gains `JudgeSpec.role`, the conditional `judge_role=` pin and the aggregate's role binding;
  `boards.py` gains `_check_role_bound_judge`, plus `_check_declared_judge` (split out so
  `_check_judge_declaration` stays under ruff's complexity cap). All new tests are in one new
  file, `tests/unit/inspect/test_judge_grader_role.py` (13 tests); no prior test was touched.
  Also the `docs/tasks` mirror (none existed).
- **Commits:** `feat(screamingface-engine): let a judged board's judge fill inspect's grader role`
  (PR branch `OME-1370-grader-role-judge`).
- **Gates:** `uv run --extra inspect pytest -q tests/unit/inspect` 432 passed (was 419);
  `ruff check`, `ruff format --check`, `pyright` (with and without the inspect extra),
  `check_layering.py` green. Mutation check: dropping the aggregate's role binding turns the
  end-to-end test red. The full-suite coverage gate was not run locally (CI runs it); paid
  lanes were not run.
- **Deviations:** ticket acceptance 2 (the SimpleQA board) is not in this unit; see Intent.
  Added one cross-check the ticket didn't name: a `model_role` scorer kwarg must match the
  declared role, or the pinned judge would never be called. Known gap left for a follow-up:
  the importer can't tell that a custom scorer like `simpleqa_scorer` asks for the grader role
  (it has no judge kwarg), so it would emit such a row as unjudged.
- **Review (sf-code-review on `84708cef`, 2026-09-29):** two nonblocking findings, both fixed.
  (1) Nothing pinned that roles are per task: a two-task test now does, verified to fail when
  roles are made process-wide. (2) `model_role=None` got past the cross-check and would grade
  with inspect's default model, unmetered; the check now keys on the kwarg being present. One
  minor finding also fixed: the end-to-end test's "nothing leaks" assertion could never fail,
  because grading runs in a copied context, so it was dropped (the scope test pins the restore).
