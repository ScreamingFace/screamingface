---
ticket: OME-1478
stack: screamingface-engine
status: done
started: 2026-11-02
finished: 2026-11-02
---

# hle-importer-and-judge-settings — let the importer and the judge take HLE's maintained grading

## Intent

HLE (Humanity's Last Exam) is graded by an LLM judge with HLE's own `regex_judge` scorer, the
maintained set-up in inspect_evals' `run_configs/default.yaml` (owner's pick on 2026-11-02, after
the paper-faithful o3-mini judge turned out to be gone from OpenRouter except as `:batch`). Run
against main, the importer and the grader refuse it. This unit removes those refusals without
loosening any rule for other rows, so PR 2 of 2 can import the HLE row. Onboarding only: no paid
call.

1. The importer finds a scorer only in the Task's own module or in `inspect_ai.scorer`;
   `regex_judge` lives in `inspect_evals.hle.scorers`.
2. The judge-shape reader sees `get_model(role=role)` in the helper `_resolve_grader(role)` and
   cannot say which role it is; the role is the scorer's own `grader_role` argument.
3. The reader sees `model_graded_qa(model=grader)` with `grader` a local, and calls it a judge in
   a variable; the local only ever holds `_resolve_grader(grader_role)`, a model lookup.
4. At grading, the gateway judge refuses `temperature=0` and `max_tokens=32768`, which the judge
   asks with (default.yaml's judge stanza), although the row pins the same two.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`: `_resolve_scorer`
  also resolves a scorer defined in another module of the eval's own package; `_unseen_judge_role`
  resolves a role held in a scorer argument from the kwargs.
- `.../judge_shape.py`: follow a helper's parameter back to the scorer argument its caller passes
  (`JudgeShape.role_parameters`, resolved by `roles_given(kwargs)`); a local that only ever holds
  a model lookup is that lookup.
- `.../benchmarks.py`: assembly's bound-role check reads the resolved roles.
- `.../judge_provider.py`: the setting guard also admits a setting the pins carry with the same
  value.

## Test plan

RED first, new test files only (no prior test edited): importer resolution on HLE's real scorer
built from the installed default.yaml; judge-shape role parameters and lookup locals on a
stand-in package (positive and the cases that must stay closed); the guard's equal-to-pin rule
and HLE's real `regex_judge` grading one Case through the gateway judge.

## Acceptance

- The importer, run on `inspect_evals.hle.hle:hle` with default.yaml's primary judge and
  `--whole-run-metric mean`, gets past the scorer checks.
- HLE's `regex_judge` grades one Case through the gateway judge with exactly the two pins on the
  wire.
- No existing row's revision or judge wire changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. A first cut (the o3-mini plan) also added a strict-JSON carrier
  on the request scope, `JudgeSpec.unsent_settings` and a role-config binding; removed in a
  follow-up commit once the owner switched to default.yaml's judge, since nothing used them.
- **Role from the kwargs only:** a role parameter resolves from the row's kwargs, never the
  argument's default (inspect logs only passed arguments, so the role is always in the hashed
  kwargs); this keeps the prior refusal test for a bare `asks_a_role_it_was_given()` intact.
- **Real importer run (2026-11-02, scratch `--engine-src`):** `inspect_evals.hle.hle:hle` with
  default.yaml's scorer spec narrowed to `graders: [grader]` and `--whole-run-metric mean` →
  exit 0, 2,500 Cases, Case Digest `7fb3221865f1…`, licence mit, `cais/hle` at `5a81a4c7`.
- **Commits:** see the PR.
- **Gates:** 585 passed across the touched suites (judge provider, grader role, judge shape,
  redraw, seed per pass, judged assembly, judged imports, observability, importer lanes,
  published revisions and fingerprints) plus the 3 new files; ruff, ruff format, pyright clean;
  layering OK. Full suite: pre-push hook and CI.
- **Deviations:** the removed first cut above; no prior test edited.
