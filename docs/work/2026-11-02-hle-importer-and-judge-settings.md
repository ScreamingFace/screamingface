---
ticket: OME-1478
stack: screamingface-engine
status: done
started: 2026-11-02
finished: 2026-11-02
---

# hle-importer-and-judge-settings — let the importer and the judge take HLE's official grading

## Intent

HLE (Humanity's Last Exam) is graded by one LLM judge, OpenAI o3-mini, with HLE's own
`json_judge` scorer: the paper-faithful set-up in inspect_evals' `run_configs/original.yaml`
(owner decision, 2026-10-28). Run against main on 2026-11-02, the importer and the grader refuse
it in four places. This unit removes those refusals without loosening any rule for other rows,
so PR 2 of 2 can import the HLE row. Onboarding only: no paid call.

1. The importer finds a scorer only in the Task's own module or in `inspect_ai.scorer`;
   `json_judge` lives in `inspect_evals.hle.scorers`.
2. The judge-shape reader sees `get_model(role=role)` in the helper `_resolve_grader(role)` and
   cannot say which role it is, so the scorer is refused as "a role held in a variable". The role
   is the scorer's own `grader_role` argument, which the row's kwargs pin (`"grader"`).
3. At grading, the gateway judge refuses three settings HLE's code passes: `max_tokens` (inspect's
   role config in `original.yaml`, 4096), `response_schema` (strict JSON output) and `temperature`
   (0, gap-filled from `default.yaml`, which inspect's OpenAI provider drops for o-series models).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`: `_resolve_scorer`
  also resolves a scorer defined in another module of the eval's own package, by the factory's
  own module; `_unseen_judge_role` resolves a role held in a scorer argument from the kwargs.
- `.../judge_shape.py`: follow a helper's parameter back to the scorer argument its caller
  passes; report it as a role parameter (`JudgeShape.role_parameters`) and resolve it against a
  row's kwargs in one place (`JudgeShape.roles_given`), read by the importer and by assembly.
- `.../benchmarks.py`: assembly's bound-role check reads the resolved roles.
- `.../single_shot.py`: `JudgeSpec.unsent_settings`, settings an eval passes that the judge's own
  provider never sends (benchmark identity when set); passed to the transport.
- `.../judge_provider.py`: the role binding carries the row's pinned params as the role's config
  (inspect's `model_roles` config); the setting guard also admits a setting equal to a pinned
  param, a `response_schema` equal to the pinned `response_format`, and the row's unsent settings.

## Test plan

RED first, new test files only (no prior test edited):
- importer: a scorer from a sibling module of the eval's package resolves to that module; one
  from outside the package is refused.
- judge shape: a role passed through a helper's parameter from a scorer argument is a role
  parameter; resolved by kwargs, by the argument's default, and refused when neither is a string.
- provider: `max_tokens` equal to the pinned value passes and the wire is unchanged; a different
  value is refused; `response_schema` equal to the pinned `response_format` passes, a different
  one or one with nothing pinned is refused; an unsent setting passes and never reaches the wire;
  HLE's real `json_judge` grades through the provider with the role bound.
- Relevant existing suites re-run: judge provider, grader role, judge shape, importer lanes.

## Acceptance

- The importer, run on `inspect_evals.hle.hle:hle` with `original.yaml`'s scorer spec and
  `--whole-run-metric mean`, gets past the scorer checks.
- HLE's `json_judge` grades one Case through the gateway judge with `max_tokens=4096` and the
  pinned `response_format` on the call and no temperature.
- No existing row's revision or judge wire changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the strict-JSON carrier: `url4` param values cannot hold
  JSON (`param-value` takes ALPHA / DIGIT / `.-_,:/`), so `response_format` is not a param. It is
  `JudgeSpec.response_format` (JSON text, identity), carried on `RequestScope.response_format`
  around the one judge call whose `response_schema` matches, and written into the chat body by
  the connector (`world/request_parameters.py: response_format_body_field`,
  `world/connector.py`, `request_scope.py`). Owner's pick, 2026-11-02, over base64 in a url4
  param: nothing outside the engine depends on it, so a url4-native typed option can replace it.
- **Role from the kwargs only:** a role parameter resolves from the row's kwargs, never the
  argument's default (inspect logs only passed arguments, so the role is always in the hashed
  kwargs); this keeps the prior refusal test for a bare `asks_a_role_it_was_given()` intact.
- **Real importer run (2026-11-02, scratch `--engine-src`):** `inspect_evals.hle.hle:hle` with
  `original.yaml`'s scorer spec and `--whole-run-metric mean` → exit 0, 2,500 Cases, Case
  Digest `7fb3221865f1…`, licence mit, `cais/hle` pinned at `5a81a4c7`.
- **Commits:** see the PR.
- **Gates:** 718 passed across the touched suites (judge provider, grader role, judge shape,
  redraw, seed per pass, judged assembly, judged imports, observability, importer lanes,
  published revisions and fingerprints, connector, answer seed, request scope) plus the 4 new
  files; ruff, ruff format, pyright clean on the 12 touched files; layering OK. Full suite:
  pre-push hook and CI.
- **Deviations:** the carrier above; no prior test edited.
