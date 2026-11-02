---
ticket: OME-1601
stack: screamingface-engine + screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-13
finished: 2026-10-13
---

# e4b-pick-output — Pick outputs one JSON field (E4b unit 7)

## Intent

`sf.Pick(..., output="answer")` makes the Case answer one top-level field of the winning member's
JSON reply (S5 "choose response with maximum confidence", S8 "response from model chosen"), so a
scorer sees `42` and not the whole JSON reply. The engine select operators `by_field@1` and
`best_holder@1` take an optional `output` arg under the same id (ans:Q5, P5). A winner without a
usable field abstains with the new reason `output_missing` and never falls back to the next member
(ans:Q12). Spec: `docs/spec/2026-10-13-e4b-combine-extensions/prd/pick-output.md`, CS#4 of
`prd/catalog-and-schema.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/combine/ports.py` — `output_missing` in
  `AbstainReason`, `AnswerReason`, `ABSTAIN_REASONS`; `MAX_OUTPUT_READ_BYTES` moved here;
  `OUTPUT_FIELD`, `check_output_arg`, `output_field_text`, `with_output`.
- `.../combine/endpoint.py` — import `MAX_OUTPUT_READ_BYTES` from ports (re-export kept).
- `.../combine/operators/fields.py` — `by_field@1` arg check, `output`, args schema.
- `.../combine/operators/signals.py` — `best_holder@1` arg check, `output`, args schema.
- `packages/screamingface/src/screamingface/answer.py` — `output_missing` in both Literals.
- `.../screamingface/fields.py` — `Pick(output=...)`: compile, rebuild, repr, block options.
- `.../screamingface/blocks.py` — `output` option on the `argmax` and `pick_field` rows.
- Tests: new `ET/test_combine_pick_output.py`, `ET/test_pick_output_recipes.py`,
  `ST/test_pick_output.py`, `ST/test_pick_output_url4_fixtures.py`; golden cases for `by_field@1`
  and `best_holder@1`; two evidence scenarios; pinned edit of the `best_holder@1` args schema.
- Regenerated: `combine-evidence.v1` and `answer.v1` snapshots, `evidence_cases.json`, public
  surface, `recipe_s5_pick_output.url4`, `recipe_s8_pick_output.url4`.
- Docs: SDK README (Pick section, Combine recipes S5/S8 rows), CHANGELOG entry.

## Test plan

- CHAR PO#1: a Pick without `output` returns the full original text and compiles to today's bytes.
- RED PO#2–PO#17 and CS#4 (18 rows, unit spec §3): field and signal picks return the winner's
  field; missing, null, blank, non-JSON, non-object, oversized or non-canonical values abstain with
  `output_missing`; no fallback to the runner-up; tie and equals use the first holder; fenced JSON
  works; bad names are refused on both sides; args schemas, goldens, evidence, compile, url4
  round trip, engine runs of SDK-compiled recipes, and the v1 vocabulary all list the new parts.

## Acceptance

- `sf.Pick("confidence", order="max", output="answer")` and the `by_signal` form give the Case
  answer `42` for the S5/S8 replies in an offline engine run.
- A winner without the field abstains with `output_missing`; the runner-up is never used.
- No compiled-url4 byte change for a Pick without `output`; no new failure code; no schema id change.
- Engine, SDK and repo gates green, with the owner approval manifest for the pinned edits.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. One more test: `ST/test_pick_output.py::
  test_changelog_entry_names_the_pick_output_operator_ids` (see Deviations).
- **Commits:** 0282f83e7 — test(e4b): RED for E4b unit 7 pick-output; 06cabe358 — feat(e4b):
  Pick outputs one JSON field (pick-output); docs commit — README and CHANGELOG; review-fix
  commit — see "Review fixes" below.
- **Gates:** see "Review fixes" below (the final run is after the review fixes).
- **Deviations:**
  - The CS#9 check in `ST/test_mean.py` takes the first bullet that names `` `sf.Pick( ``. That
    is the older Pick bullet, so the check passes with or without the new bullet. A new test in
    `ST/test_pick_output.py` finds the bullet by `` `output_missing` `` and checks the two
    operator ids and the "Requires an SF Engine" text. It failed before the bullet was written
    (`assert 0 == 1`) and passes after.
  - The CHANGELOG bullet goes after the E4b `sf.Median` weights bullet (the last E4b bullet),
    as the unit spec says.

### RED record (commit A, draft)

- Engine focused run: 55 failed, 452 passed. SDK focused run: 21 failed, 142 passed.
- RED rows fail on the refused `output` arg (`SpecInvalid`), on the missing `output_missing`
  reason, on the full reply text (S5/S8 recipes), or on the schema and golden assertions.
- CHAR rows pass: PO#1 (engine and SDK, row 1b).
- Rows that pass in commit A by design (the stub already refuses or stores the value):
  the bad-name and extra-key `check_args` refusals (PO#11), the core `a.b` refusal (PO#11),
  the SDK bad-name and `output` length rows (PO#11b, the 64-character case), the drift guard
  `test_pick_output_url4_fixture_matches_the_sdk_compiler` (fixtures made by the stub), the
  rebuild refusal for `output=7` (PO#16 tamper), and the golden meta test (PO#13).

### Review fixes (fix commit)

- Q-C: `ports.output_field_text` has one return now. It reads the field with `walk_field_path`
  and catches `ValueError` with `contextlib.suppress`. The behavior is the same; the PO#4, #6,
  #7 and #10 rows pin it. Ruff PLR0911 is green. This change went into the feat commit
  (06cabe358), because the pre-commit ruff hook refused the commit without it.
- Q-A: `ST/test_pick_output.py::test_pick_repr_and_python_show_the_output` expected
  `sf.signal(...)` in `repr`. `Signal.__repr__` gives `signal(...)`, and
  `ST/test_pick_by_signal.py:106` pins that form. The oracle now says
  `Pick(by_signal=signal('field:confidence'), order='max', output='answer')`. The `_python()`
  assertion keeps `sf.signal(...)`.
- Q-B: `ST/test_frozen_record_fields.py:184` counts the engine evidence scenarios. The two new
  scenarios make 28 (was 26). Plan erratum: this file needs owner approval.
- Q-D: the two new scenario names are added AFTER the `SCENARIOS` dict and the `_EXPECTED_NAMES`
  set (unit spec §2.9 c-d default form), not inside them. The append-only gate no longer flags
  these two files.
- Optional MINOR findings (an `_output_arg` helper, one shared `OUTPUT_FIELD` regex and args
  schema, no second `_spec_steps` call): not done. They are optional and change no behavior.

### Final gates (after the review fixes, `--base e4b-filter-judge`)

- screamingface-engine: append-only red with 5 offenders (all on the approval list):
  `evidence_cases.json`, `screamingface.combine-evidence.v1.json`, `best_holder@1.json`,
  `by_field@1.json`, `test_rest_operators.py`. With `--skip-append-only`: ALL GATES GREEN
  (ruff check, ruff format, pyright, check_layering, pytest with coverage).
- screamingface: append-only red with 3 offenders (all on the approval list):
  `screamingface.answer.v1.json`, `public_surface_snapshot.json`,
  `test_frozen_record_fields.py`. With `--skip-append-only`: ALL GATES GREEN (ruff check,
  ruff format, pyright, pytest with coverage, check_notebooks, uv build, check_distribution).
- repo: ALL GATES GREEN.
