---
ticket: OME-1996
stack: url4
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-19
finished:
---

# url4-expand-at-most-one — named at-most-one expansion for url4 sources (C19)

## Intent

Implement contract C19 of the Router Recipe extension spec
(`docs/spec/2026-11-16-router-recipe-extension/contracts-placement.md`): the package extension
`expand.at_most_one=true` on a named `;expand` source with one guard. Zero elements contribute
nothing and no failure; one element contributes exactly what a plain source holding it contributes,
under the source's own name; two or more fail the source. This lets a later Unit place a Router as a
Fusion member whose abstention is absent rather than read as an answer. The spec and the plan
(`docs/plan/2026-11-16-router-recipe-extension.md` §7) are normative; this unit first pins the two
items the spec left to it by amending C19, then implements. Landing: `pkg/url4-sdk`, under epic
OME-1306. No Router code and no live call.

## Planned changes

- Spec amendment (before code): C19 builder surface and two-plus failure code in
  `contracts-placement.md`; the matching rows in `test-plan.md`, the §9 item in `00-overview.md` and
  step 7.1 of the plan; one stale "Unit 6 spec" wording in `contracts.md`.
- `packages/url4/src/url4/core/errors.py`: `ErrorCode.EXPANSION_TOO_MANY`.
- `packages/url4/src/url4/core/builders.py`: the `at_most_one` keyword of `src` and the form check.
- Parser and annotations (`core/grammar.py`, `core/_annotations.py`): parse-time form rules.
- Lowering and execution (`dag/_descriptor.py`, `dag/nodes/iteration.py`, `dag/nodes/_shared.py`,
  `dag/nodes/broadcast_result.py`, `dag/semantics/code_binding.py`, `dag/_wiring.py` if the quorum
  gate needs it): the zero, one and two-plus behavior in both panels and the code binding.
- `packages/url4/src/url4/core/render.py`: writes the mark after the guard.
- New tests under `packages/url4/tests/`; `packages/url4/CHANGELOG.md`.

## Test plan

- First failing tests, from `test-plan.md` (url4 leaf rows): text panel, broadcast panel and code
  binding for zero, one, empty-string and two-plus elements under `;required` and `;optional` and
  quorum; non-collection value keeps `expansion_not_iterable`; refusals at parse and in `url4.src`
  (no `;expand`, no name, no guard, both guards, another value, duplicate, mark before every
  source-level key); parse then render keeps the bytes.
- Cross-version run of the final rendered bytes on an isolated url4 install from `455166b0d`.
- Wheel built and installed with base dependencies only (no Pydantic): parse, render and the three
  consumers run.
- Prior url4 tests run unchanged; unmarked and `;expand` sources keep behavior and bytes.
- Expected prior-test transitions: the inventory at base `c403ebd33` found none. No test or snapshot
  enumerates the exact `ErrorCode` set (`tests/regressions/test_status_mapping.py` iterates every
  member generically and stays valid), pins the `url4.src` signature, or names an `expand.*` key. The
  `__all__` sizes in `tests/unit/test_hygiene_ratchets.py` do not change with a keyword and an enum
  member, and this leaf adds none of the patterns that test counts.

## Acceptance

- The C19 amendment is approved by the owner before any code.
- The plan §7 exit holds: the C19 matrix and the old-reader fallback are green, and no Router code is
  part of this landing.
- The url4 gate runner (`run_gates.py url4`) green, including the coverage floor.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - Spec and plan amendment (approved by the owner before code): `contracts-placement.md`,
    `test-plan.md`, `00-overview.md` and `contracts.md` under
    `docs/spec/2026-11-16-router-recipe-extension/`; `docs/plan/2026-11-16-router-recipe-extension.md`
    step 7.1.
  - New `packages/url4/src/url4/core/at_most_one.py`: the one owner of the mark's form. The parser
    (which the DAG text path parses through), the tree path, `url4.src` and the renderer all call
    it.
  - `core/errors.py` (`EXPANSION_TOO_MANY`), `core/_annotations.py` (the mark's key, and the param
    validator refuses the mark as an expression param in text, in a render and in a node's HTTP
    query), `core/grammar.py` (form check on every whole parsed source, and a marked text too
    deep to read refused at `parse` and `parse_value`, in an `except RecursionError` of each
    one's own frame; its intent fallbacks never read a C19 error as prose or a code pointer; it
    imports `core/at_most_one.py` as a module, and its module docstring and four comments by
    `intent_atom` are rewrapped to 100 columns, word for word, to stay within its cap),
    `core/intent.py` (the intent classifier raises a C19 error instead of reclassifying it, and
    refuses a marked text too deep to read the same way, as `is_named_job` does since the twelfth
    review's second report),
    `core/_iteration_envelope.py` (a reduce over iteration's inner tail refuses the mark),
    `core/builders.py` (`src(..., at_most_one=True)`, the mark placed right after the guard through
    `with_mark` in `core/at_most_one.py`, and the form check; a marked intent or reducer too deep
    to read is refused the same way, since the twelfth review's second report), new
    `core/_builder_exec.py` (the execution axis of `src`, moved out of `builders.py`),
    `core/render.py` (render refuses a broken form through the guard module's reparse wrapper, and
    a marked structured intent too deep to read back the same way, since the twelfth review's
    second report), `core/parser.py` (`build` refuses a marked text too deep to read the same
    way, since the eleventh review; it carried an explicit refusal until the third).
    `core/descriptor_head.py` carried one until the third review and is back to its base bytes.
  - `dag/node.py` (`NoElement`), `dag/nodes/iteration.py` (`ExpandNode.at_most_one`), new
    `dag/nodes/_at_most_one.py` (the zero, one and two-plus rule), `dag/nodes/_shared.py` (gather
    and frame skip `NoElement`), `dag/_descriptor.py` (lowering), new
    `dag/_at_most_one_texts.py` (the entry check over the url4 a run parses later, and the one
    reader of a relative call's context), `dag/_lowering.py` (`compile_expression` runs the entry
    check before lowering; a call's context goes through the shared reader), `dag/_run_files.py`
    (`run` runs it before the run-start file phase), `dag/semantics/code_binding.py`
    (`CodeSlot.at_most_one`), `dag/_code_wiring.py` (slot flag), `dag/source_scan.py` (the
    holdings-ref predicate reads a context with no C19 refusal, through `c19_blind` in
    `core/_annotations.py`).
  - New tests: `tests/unit/test_at_most_one_form.py`, `tests/unit/test_at_most_one_runtime.py`
    (48 tests at PR-open), then 55 more in the review round, including the new
    `tests/unit/test_at_most_one_bytes.py`, then 37 in the third review, 9 in the fourth and 9 in
    the fifth, in the new `tests/unit/test_at_most_one_paths.py`, 42 in the sixth, in the new
    `tests/unit/test_at_most_one_texts.py`, 37 in the seventh, 7 of them in the new
    `tests/unit/test_at_most_one_receivers.py`, 26 in the ninth, 10 of them in the new
    `tests/unit/test_at_most_one_contexts.py`, 16 in the tenth, 14 of them in the new
    `tests/unit/test_at_most_one_intents.py`, 12 in the eleventh, in the new
    `tests/unit/test_at_most_one_readers.py`, and 5 in the twelfth and 23 in its second report, in
    the same module: 319 C19 tests in all.
  - One prior test changed in its module docstring only, after the eighth review:
    `tests/spec/test_abnf_call_context.py`, with the owner-approved transition pinned in the new
    `.claude/test-change-approvals/OME-1996.json`. No test code changed.
- **Commits:** one commit, `feat(url4): let a named expand source take at most one element`,
  authorized by the owner on 2026-11-20, made on base `c403ebd33` and rebased onto the then-current
  `origin/main` before PR-open. Linear OME-1996 (under OME-1306), filed at PR-open on 2026-11-20 with
  the owner's confirmation; the owner confirmed the exact mirror path
  `docs/tasks/2026-11-20-OME-1996-url4-expand-at-most-one.md` after the number existed. Branch
  renamed to `OME-1996-url4-expand-at-most-one`. A second commit,
  `fix(url4): refuse valued guards and envelope marks on at-most-one sources`, authorized by the
  owner on 2026-11-21 after the second review, carries the review-round code, tests and docs. A
  third commit, `fix(url4): check every url4 a run parses for the at-most-one form`, authorized
  by the owner on 2026-11-23 after the twelfth review's second report, carries the third to
  twelfth reviews' code, tests and docs.
- **Gates:** the url4 gate runner (`run_gates.py url4`) green: append-only check, ruff check, ruff
  format, pyright, pytest 3363 passed and 17 xfailed, coverage 98.81% (floor 95%). The suite also
  passes on Python 3.12.9, 3.13.11 and 3.14.2 with the same counts. The touched execution modules and
  the new form module are at 100% line coverage.
  After the rebase onto `c3a9bd7cd` (no `packages/url4` change on main since `c403ebd33`;
  `uv lock --check` passes), rerun on 2026-11-20: `run_gates.py url4 --base c3a9bd7cd` green
  (append-only check, ruff check, ruff format, pyright, pytest with the coverage floor; the project
  environment is Python 3.14.2). In separate frozen environments: Python 3.12.9 and 3.14.2, 3363
  passed and 17 xfailed each; Python 3.13.11 with the floor, 3363 passed and 17 xfailed, coverage
  98.79%.
  CI then failed `tests (base install)` on all three versions at `scripts/check_module_size.py`
  (see Deviations). After the fix, rerun on 2026-11-20 against `c3a9bd7cd`: `run_gates.py url4
  --base c3a9bd7cd` green (project environment, Python 3.14.2); `scripts/check_module_size.py` and
  `scripts/check_suppressions.py` (3, baseline 3) pass. In separate frozen environments with the
  floor, each 3363 passed and 17 xfailed: Python 3.12.9 98.80%, 3.13.11 98.81%, 3.14.2 98.79%. The
  two new modules, `core/at_most_one.py` and the touched execution modules are at 100% line
  coverage.
  After the review round, rerun on 2026-11-21 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green (append-only check, ruff check, ruff format, pyright, pytest with the coverage
  floor); `scripts/check_module_size.py` within every cap and `scripts/check_suppressions.py` (3,
  baseline 3) pass. In separate frozen environments with the floor, each 3418 passed and 17
  xfailed: Python 3.12.9 98.82%, 3.13.11 98.81%, 3.14.2 98.79%. `core/at_most_one.py`,
  `core/_builder_exec.py`, `core/render.py` and the touched execution modules are at 100% line
  coverage; the lines left uncovered in `core/builders.py` and `core/parser.py` are outside this
  change.
  After the third review, rerun on 2026-11-21 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap and
  `scripts/check_suppressions.py` (3, baseline 3) pass. In separate frozen environments with the
  floor, each 3455 passed and 17 xfailed, coverage 98.81%: Python 3.12.9, 3.13.11 and 3.14.2.
  `core/_annotations.py`, `core/at_most_one.py`, `core/render.py` and `dag/_descriptor.py` are at
  100% line coverage; the lines left uncovered in `core/_iteration_envelope.py`, `core/grammar.py`
  and `dag/_lowering.py` are outside this change.
  After the fourth review, rerun on 2026-11-21 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap and
  `scripts/check_suppressions.py` (3, baseline 3) pass. In separate frozen environments with the
  floor, each 3464 passed and 17 xfailed: Python 3.12.9 98.81%, 3.13.11 98.83%, 3.14.2 98.80%.
  `core/_annotations.py`, `core/at_most_one.py`, `core/render.py` and `dag/_descriptor.py` are at
  100% line coverage; the lines left uncovered in `dag/_lowering.py` and `dag/_run_files.py` are
  outside this change.
  After the fifth review, rerun on 2026-11-21 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap and
  `scripts/check_suppressions.py` (3, baseline 3) pass. In separate frozen environments with the
  floor, each 3473 passed and 17 xfailed, coverage 98.83%: Python 3.12.9, 3.13.11 and 3.14.2. Every
  line this change adds or changes in `packages/url4/src` is covered.
  After the sixth review, rerun on 2026-11-22 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap and
  `scripts/check_suppressions.py` (3, baseline 3) pass. In separate frozen environments with the
  floor, each 3515 passed and 17 xfailed: Python 3.12.9 98.82%, 3.13.11 98.82%, 3.14.2 98.80%.
  Every line this change adds or changes in `packages/url4/src` is covered, the new
  `dag/_at_most_one_texts.py` included.
  After the seventh review, rerun on 2026-11-22 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap and
  `scripts/check_suppressions.py` (3, baseline 3) pass. In separate frozen environments with the
  floor, each 3552 passed and 17 xfailed: Python 3.12.9 98.83%, 3.13.11 98.80%, 3.14.2 98.84%.
  Every line this change adds or changes in `packages/url4/src` is covered; the lines left
  uncovered in `core/grammar.py`, `dag/_lowering.py` and `dag/_run_files.py` are outside it.
  After the eighth review (the docstring-only transition), rerun on 2026-11-22 against
  `c3a9bd7cd`: `run_gates.py url4 --base c3a9bd7cd` green, the append-only check included;
  `scripts/check_module_size.py` and `scripts/check_suppressions.py` (3, baseline 3) pass; the
  mirror gate passes. The approval matcher returns OME-1996 for the transition. Python 3.12.9
  with the floor: 3552 passed and 17 xfailed, coverage 98.84%. No source changed in this round.
  After the ninth review, rerun on 2026-11-22 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap and
  `scripts/check_suppressions.py` (3, baseline 3) pass; the mirror gate passes. In separate frozen
  environments with the floor, each 3578 passed and 17 xfailed: Python 3.12.9 98.84%, 3.13.11
  98.81%, 3.14.2 98.83%. Every line this change adds or changes in `packages/url4/src` is covered;
  the lines left uncovered in `core/grammar.py`, `dag/_lowering.py` and `dag/_run_files.py` are
  outside it.
  After the tenth review, rerun on 2026-11-22 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap (`core/grammar.py` 705/705)
  and `scripts/check_suppressions.py` (3, baseline 3) pass; the mirror gate passes. In separate
  frozen environments with the floor, each 3594 passed and 17 xfailed, coverage 98.87%: Python
  3.12.9, 3.13.11 and 3.14.2. Every line this change adds or changes in `packages/url4/src` is
  covered, and so is the reference fallback in `core/intent.py`, uncovered at base.
  After the eleventh review, rerun on 2026-11-22 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap (`core/grammar.py` 705/705)
  and `scripts/check_suppressions.py` (3, baseline 3) pass; the mirror gate passes. In separate
  frozen environments with the floor, run one at a time, each 3606 passed and 17 xfailed: Python
  3.12.9 98.87%, 3.13.11 98.86%, 3.14.2 98.87%. The 3.13 difference is one base line in
  `core/_call_head.py` (a remote expression with no host) that only the property tests reach,
  by chance. Every line this change adds or changes in `packages/url4/src` is covered.
  After the twelfth review, rerun on 2026-11-23 against `c3a9bd7cd`: `run_gates.py url4 --base
  c3a9bd7cd` green; `scripts/check_module_size.py` within every cap (`core/grammar.py` 705/705,
  `core/parser.py` 264/267) and `scripts/check_suppressions.py` (3, baseline 3) pass; the mirror
  gate passes. In separate frozen environments with the floor, run one at a time, each 3611
  passed and 17 xfailed: Python 3.12.9 98.87%, 3.13.11 98.86%, 3.14.2 98.85%. The differences
  are base lines that only the property tests reach, by chance: the `core/_call_head.py` line
  above, and on 3.14 one more in `core/render.py` (a descriptored collection in a value
  position). Every line this change adds or changes in `packages/url4/src` is covered.
  After the twelfth review's second report, rerun on 2026-11-23 against `c3a9bd7cd`:
  `run_gates.py url4 --base c3a9bd7cd` green; `scripts/check_module_size.py` within every cap
  (`core/builders.py` 477/478, `core/grammar.py` 705/705, `core/parser.py` 264/267,
  `core/render.py` 616/676) and `scripts/check_suppressions.py` (3, baseline 3) pass; the mirror
  gate passes. In separate frozen environments with the floor, run one at a time, each 3634
  passed and 17 xfailed: Python 3.12.9 98.87%, 3.13.11 98.86%, 3.14.2 98.84%. The differences
  are base lines that only the property tests reach, by chance: the `core/_call_head.py` line
  above, and on 3.14 two in `core/_render_guards.py` (`_decode`'s parse-error branch), which the
  suite without the property tests leaves uncovered on 3.14 too; the `core/render.py` line was
  reached this time. Every line this change adds or changes in `packages/url4/src` is covered.
- **Cross-version (test-plan row 178):** the new builder rendered a text and a broadcast panel with
  two plain members and one marked member, under quorum 3 and quorum 2, `;required` and `;optional`,
  for zero, one and two elements (24 byte strings). An isolated url4 install from `455166b0d` accepted
  every string. Zero: no source from the marked member; quorum 3 ends in `quorum_not_met` with zero
  process calls; quorum 2 makes one text call over `a: A` and `b: B` only, and two broadcast parts.
  One: a bare `x` in the text panel and `m[0]` in the broadcast. Two: two sources (`x`, `y`;
  `m[0]`, `m[1]`). The new reader on the same bytes: zero is the same; one gives `m: x` and
  `source_name: m`; two fails a `;required` member with `x.expansion_too_many`, like any other
  source failure, and omits an `;optional` one. The review round pins these 24 strings as golden
  bytes in `tests/unit/test_at_most_one_bytes.py`; the old reader itself does not run in CI.
- **Base wheel:** the built wheel, installed with `--no-deps` over the exact exported base lock
  (httpx and its dependencies only) on Python 3.12 and 3.14, with Pydantic and Tortoise absent, ran
  parse and render round trip, the text panel (zero, one, two), the broadcast panel and the code
  binding. Rebuilt and rerun on 2026-11-21 after the review round, on Python 3.12 and 3.14: the same
  smoke plus a valued guard and an envelope mark, both refused, and a guard given through
  `annotations=` with the mark right after it. Rebuilt and rerun after the third review, on
  Python 3.12 and 3.14: the same smoke, and the canonical call form with the mark is refused.
  Rebuilt and rerun after the fourth review, on Python 3.12 and 3.14: the same smoke, and a broken
  tree beside an image opt-in is refused with no fetch, and an inline collection's mark is
  refused. The same smoke fails on the third-review wheel, which fetched the image first.
  Rebuilt and rerun after the fifth review, on Python 3.12 and 3.14: the same smoke, and a marked
  tree source named `""`, `src` or `bad-name` is refused with no fetch and no call. The same smoke
  fails on the fourth-review wheel, which accepted the empty name.
  Rebuilt and rerun after the sixth review, on Python 3.12 and 3.14: the same smoke, and a
  broken mark in an iteration's body, a deferred group and a call's context, and the mark in a
  tree's reducer or intent, are refused with no fetch and no call. The same smoke fails on the
  fifth-review wheel, which skipped the broken row.
  Rebuilt and rerun after the seventh review, on Python 3.12 and 3.14: the same smoke, and a
  Form-3 processor with a broken mark in a row, rows where another error comes first (in a
  member, a nested group, an intent call or an intent param) and a well-formed mark too deep to
  check are refused with no fetch and no call; a deep unmarked text compiles; a remote call's
  broken mark is forwarded and the receiving node refuses it with no fetch. The same smoke fails
  on the sixth-review wheel, which ran the processor's calls first.
  Rebuilt and rerun after the ninth review, on Python 3.12 and 3.14: the same smoke, and a broken
  mark beside an `@` in quoted text, in a URL's user or in a nested sibling, a context group the
  text path defers that fails on another rule beside or around a broken mark, a valued `;expand`
  on a marked source, the mark in a tree reducer's `;` chain and a deep Form-3 processor with the
  mark are refused with no fetch and no call; a real holdings ref still ships verbatim, and an
  unmarked `;expand=false` still expands. The same smoke fails on the seventh-review wheel, which
  fetched `/a` and shipped a broken mark beside a quoted email to its route.
  Rebuilt and rerun after the tenth review, on Python 3.12 and 3.14: the same smoke, and a broken
  mark in a group's, a row's, a tree row's, a relative and a Form-3 processor's intent is refused
  with no fetch and no call, the intent classifier raises it, a context too deep to read that
  names the mark is refused, and a node answers both with HTTP 400 to a raw query; a well-formed
  mark in a structured intent still runs. The same smoke fails on the ninth-review wheel, which
  sent the broken intent to the model as its prompt.
  Rebuilt and rerun after the eleventh review, on Python 3.12 and 3.14: the same smoke, and a
  marked text too deep to read is refused by `parse`, `parse_value`, `build`, `Parser.build`,
  `classify_intent` and the client front door with a node target or protocol params, with no
  fetch, while an unmarked one keeps its `RecursionError`. The same smoke fails on the
  tenth-review wheel, where `parse` let the marked text escape as a `RecursionError`.
  Rebuilt and rerun after the twelfth review, on Python 3.12 and 3.14: the eleventh review's
  smoke, and each public eager reader reads a 20-group text, unmarked or marked, from as deep a
  caller as its base entry, to the frame, refusing the marked one a frame deeper; `parse_value`,
  `build` and `Parser.build` read the 141-group text from the top level. The same smoke fails
  on the eleventh-review wheel, where `parse` fell two frames short.
  Rebuilt and rerun after the twelfth review's second report, on Python 3.12 and 3.14: the
  eleventh and twelfth reviews' smokes, and a marked intent or reducer too deep to read is
  refused by `expr`, `broadcast`, `reduce`, `iterate`, an iteration's reducer in a source,
  `is_named_job`, `Url4Node.code`, `render` (a named job, and a structured intent checked and
  unchecked) and the client helpers (`query`, `broadcast`, `reduce`, `iterate`, an iteration
  with a reducer locally and with a node target, a named job and a structured intent), with no
  fetch, while an unmarked one keeps its `RecursionError`; a marked source given to the same
  builders is still refused. The same smoke fails on the twelfth-review wheel, where all 20
  escaped as a `RecursionError`.
- **Deviations:**
  - The form owner is a new public module `core/at_most_one.py`. A private module would add two
    cross-layer private imports from `dag`, which the private-import ratchet forbids.
  - `dag/_wiring.py` and `dag/nodes/broadcast_result.py` needed no change: the one element is
    returned as a plain value, so the quorum gate and the broadcast record already give it the
    source's name. `dag/node.py`, `dag/nodes/_shared.py` and `dag/_code_wiring.py` changed instead.
    `core/_annotations.py` changed only in the third review, to hold the mark's key next to the
    param validator that refuses it.
  - `packages/url4/CHANGELOG.md` is not edited: the release tool writes it from the commit message.
  - Module size ratchet. The first push failed CI's `scripts/check_module_size.py`, which
    `run_gates.py url4` does not run: five capped modules went over their caps
    (`core/_render_guards.py` 231/225, `core/builders.py` 501/478, `core/grammar.py` 712/705,
    `dag/nodes/_shared.py` 270/267, `dag/nodes/iteration.py` 215/197). No cap was raised. The fix
    splits by reason to change: the zero, one and two-plus rule moved from `iteration.py` to
    `dag/nodes/_at_most_one.py`; the execution axis of `src` (`_exec_annotations` with its timeout
    and retry text) moved to `core/_builder_exec.py` as `exec_annotations`, which returns the typed
    keys and the guard; mark placement moved to `with_mark()` in `core/at_most_one.py`, which
    `src` calls after appending `annotations=` (the review round below);
    `grammar.py` dropped its `_parse_source` wrapper and checks the form at the two call sites
    through `checked_form` in `core/at_most_one.py`; `render.py` calls the guard module's reparse
    wrapper itself, so `core/_render_guards.py` is back to its base bytes. Comments in `_shared.py`
    were shortened. After the fix: `_render_guards.py` 225/225, `builders.py` 467/478,
    `grammar.py` 703/705, `render.py` 612/676, `_shared.py` 267/267, `iteration.py` 196/197.
    `_shared.py` and `_render_guards.py` now sit exactly at their caps.
  - `core/builders.py`, `core/grammar.py` and `core/render.py` are above 450 lines. `builders.py`
    shrank below its base size; `grammar.py` and `render.py` got only the calls into the form owner.
  - No prior test changed.
  - Review round (2026-11-21), seven findings on PR head `709d25e69`, verified by probes against
    the worktree and decided by the owner:
    - Two elements and sibling calls. A delayed marked source fails with `x.expansion_too_many`
      after a sibling call already started. The owner classified this as a wrong promise in our
      texts, not a runtime defect: `expansion_not_iterable` and a missing `;required` source show
      the same call order, C19 says the guards apply to this failure as to any other, a barrier
      would add an execution phase for marked sources only and change the concurrency of the whole
      DAG, and the Engine member read gives zero or one element, so two-plus is a defensive path.
      "Before any call" became "like any other source failure" in the mirror, the PR body and the
      Linear issue (the last two after approval). New parity tests hold the failing fetch until the
      sibling calls run and assert the same call trace for the marked two-element failure,
      `expansion_not_iterable` and a missing source, in the text and broadcast panels. No scheduler
      barrier.
    - A guard with a value (`;optional=false`) passed the form check, and the runtime read it as
      `;optional`. The form now takes `;required` or `;optional` only as a flag, at parse, in
      `url4.src` and at render; an unmarked source keeps its valued guard.
    - A complete group or iteration envelope accepted the mark as a no-op expression param. The
      envelope decoder (`core/parser.py`, shared by `build` and the DAG text path) and the renderer
      (even with `check=False`) now refuse it. A runtime test runs an expression-valued marked
      member, the SDK member slot shape, through the DAG: its chain is a source annotation, and
      the new refusal does not reach it.
    - `url4.src` wrote the mark before a guard given through `annotations=`, and refused that
      combination on an expression-valued source. The builder now places the mark right after the
      guard whichever argument gave it (`with_mark` in `core/at_most_one.py`);
      `exec_annotations` no longer writes the mark.
    - The mirror named the code `expansion_too_many`; it is `x.expansion_too_many`.
    - The broadcast one-element test checked only the third part; a new test asserts the whole
      envelope and the exact process calls.
    - The cross-version evidence lived only in this ledger; the 24 strings are now golden bytes in
      a committed test. Running the `455166b0d` reader in CI would need a workflow change and is
      left for a separate decision.
    - The C19 spec text matches the code: a valued guard is refused (approved by the owner on
      2026-11-21 as a clarification of the approved C19, not a new contract), the builder locator
      names `with_mark`, and test-plan row 203 lists the new refusals.
    - Second review (2026-11-21): the spec's source anchors into files this change touched were
      stale after the split. All were moved to the current lines: in `contracts-placement.md` the
      `*` prefix (`render.py:285`), the guard and mark order (`_builder_exec.py:31-34`,
      `builders.py:178-180`, `at_most_one.py:52-62`), `_guard_annotation_boundary`
      (`render.py:307-323`), the two-plus failure (`dag/nodes/_at_most_one.py:22-26`, with
      `expansion_not_iterable` at `iteration.py:49-56`), `errors.py:117`, `_descriptor.py:54-64`,
      `builders.py:142-196`, and the one-line shifts in `_shared.py` and `code_binding.py`
      (C18 included); in `contracts.md` the `_error_payload` anchor (`_shared.py:163-183`). The
      old-reader anchors (`grammar.py:230-260`, `_descriptor.py:33-60` at `455166b0d`) point into
      that commit and stay as written. This ledger no longer says the execution-axis module took
      the mark.
    - Module sizes after the round: `builders.py` 469/478, `parser.py` 260/267, `render.py`
      616/676; the others are unchanged.
    - Third review (2026-11-21), on PR head `8f353bb84`: all three code findings reproduced by
      probes against the worktree; the fixes were decided by the owner.
      - A reduce over iteration dropped the mark from its inner tail
        (`(src*(body)!'p';expand.at_most_one=true)!'r'`) without a word, before and after an
        `iteration.*` directive. The iteration decoder now refuses it, only on that branch, so a
        marked expression-valued group source keeps building. The inner tail still drops any other
        non-directive param, as an iteration has no params field; that is base behavior and is
        unchanged.
      - The tree path (`run(tree)`, `compile_expression(tree)`) never checked the form:
        `expand.at_most_one=false` ran as `true`, `;optional=false` swallowed the two-plus
        failure, a mark without `;expand` was ignored, and an `Expression` param carried the mark.
        Lowering a source now runs the parser's form check first, and lowering an expression, a
        relative call or a remote call refuses the mark among its params. A code group builds its
        slots through the same lowering, so it refuses them too, before any fetch or call.
      - The canonical call form (`/p?expand.at_most_one=true&q=(a)!'i'`) parsed and rendered,
        while the `;` chain form was refused. As the owner chose, the one param validator
        (`validate_param`) now refuses the mark. The `;` chain, an envelope, the canonical call
        form, both render paths and a node's HTTP query all share it, so a node refuses over HTTP
        what it refuses in text (`OME-507`), with HTTP 400 like any other invalid param. The key
        moved to `core/_annotations.py`, because `core/at_most_one.py` imports that module;
        `at_most_one.py` re-exports it. The explicit refusals the validator now covers were removed
        from `grammar.py`, `parser.py`, `descriptor_head.py` and `render.py`.
      - The spec states the rule in one Form bullet: the mark is never an expression parameter,
        where the validator refuses it, and which two readers refuse it themselves. The tree path
        is named in the form bullet, test-plan row 203 lists the new refusals, and the source
        anchors into the files this round moved point to the new lines. The second-review entry
        above keeps the lines of its own time.
      - 37 new tests in `tests/unit/test_at_most_one_paths.py`; no prior test changed. Module
        sizes: `grammar.py` 702/705, `parser.py` 258/267, `render.py` 612/676, `_lowering.py`
        627/640, `builders.py` 469/478.
      - The PR body and the Linear description are updated after the commit, as the owner
        approved.
    - Fourth review (2026-11-21), on the uncommitted third-review tree: both findings reproduced
      by probes against the worktree.
      - `run(tree)` fetched files before it refused. The run-start file phase (blob refs and
        `https://` attachment opt-ins) runs before the compile, and the third-review form check
        sat in the lowering, so a broken tree beside an image fetched the image and then failed.
        The third-review claim "before any fetch or call" did not hold for such a tree.
        `run(text)` fetched nothing: a text that does not parse skips that phase.
      - An inline collection (an `Expression` with no intent as an iteration's collection) is
        lowered as a list, not through the expression lowering, so a mark among its params passed
        the checks per lowering.
      - One walk over the tree, `check_tree` in `core/at_most_one.py`, replaces the four checks
        per lowering: it checks every source's form and the params of every expression, relative
        call and remote call. `compile_expression` calls it on a tree before lowering; `run`
        calls it on a tree before the run-start file phase and reads a refused tree as a text that
        does not parse, so nothing is fetched and the compile raises the error. `dag/_descriptor.py`
        is back to its bytes at `8f353bb84`; `dag/_lowering.py` keeps one call.
      - 9 new tests in `tests/unit/test_at_most_one_paths.py`, with a control that a well-formed
        marked tree beside the same files does fetch them; the file's IO double now records bytes
        fetches too. No prior test changed. Module sizes: `_lowering.py` 625/640; the others are
        unchanged.
    - Fifth review (2026-11-21), on the uncommitted fourth-review tree.
      - The form check accepted any name that was not `None`. A tree whose marked source was
        named `""`, `src` or `bad-name` passed `check_tree`, compiled, fetched and called the
        model with that name, while the text form and `url4.src` refuse each of them. The one
        element keeps the source's name, so the C19 form now requires a source name the text form
        accepts: a string, an identifier (the lexical `_IDENT_RE` the parser and `url4.src` use),
        never the reserved `src`. The rule sits in `core/at_most_one.py`, which imports no
        builder. The builder still checks the name first, so its messages are unchanged.
      - The words "run(tree) refuses what run(text) refuses" claimed more than the walk does. It
        enforces the C19 marked-source and reserved-param constraints only; a tree built in code
        is not otherwise validated (an unknown annotation such as `("bad key", "x")` beside a
        well-formed mark still compiles and runs, as before C19). The docstring, the spec bullet
        and a test comment now say so.
      - A cycle guard in `check_tree` was considered and left out: frozen nodes cannot form a
        cycle without bypassing the dataclass, the wire cannot carry one, and the compiler and
        `nodes.walk` already assume an acyclic tree.
      - 9 more parametrized cases in `tests/unit/test_at_most_one_paths.py` (empty, reserved and
        non-identifier names, on the panel, code and compile paths), each refused with no fetch
        and no call; no prior test changed.
    - Sixth review (2026-11-22), on the uncommitted fifth-review tree: all three findings, and
      two more shapes of the first, reproduced by probes against the worktree.
      - The walk checked tree nodes only, but some url4 stays raw text that a run parses later.
        An iteration's body with a broken mark compiled, fetched the collection and failed each
        row, so `iteration.on_error=skip` returned `[]`, and a code reducer over those rows ran
        on an empty input. A tree's reducer carrying the mark as a param failed after the
        collection fetch and a call per row; a tree's intent carrying it became a collected row
        error.
      - On the text path a deferred group keeps its sources lazy: `parse` and `build` refused a
        broken member inside it, but `compile_expression` accepted it and `run` fetched its
        sibling first.
      - A relative call's context with a broken mark failed to read as a source list and fell
        back to prose, so it shipped outbound.
      - Fix: a C19 refusal now raises `AtMostOneFormError`, a `ParseError` subclass with the same
        code, which no lenient reader swallows. The new entry check `check_target`
        (`dag/_at_most_one_texts.py`) parses every such text as the run will (a row as the text
        it spawns, a reducer as `ReduceNode` reads it, a context segment by segment, a text
        eagerly) and adds its trees to the `check_tree` walk through a new `later` hook, so the
        form module still parses no text. `compile_expression` and `run` call it where they
        called `check_tree`, and `run` now for text too. Any other parse error keeps its base
        behavior: a row that fails on another rule is still skipped.
      - A call's context has one reader for the entry check and the lowering
        (`read_source_list`): a C19 error is never prose; a context with a segment that is not a
        source for another reason stays prose and ships verbatim, the mark in it included,
        whatever the segments' order; a quoted mark is data.
      - Not read, by design: a remote call's context, which the remote node parses (C6), and a
        relative reducer's context, which `ReduceNode` ships verbatim to its route with the rows.
        A C19 node refuses either at its own entry.
      - Engine fragments (`bare_root_ok=True`, the spawn hook) skip the entry check: they come
        from a target already checked.
      - 42 new tests in `tests/unit/test_at_most_one_texts.py`, 7 of them controls of the base
        behavior; no prior test changed. Module sizes: `_lowering.py` 613/640; the new module
        has 103 lines.
    - Seventh review (2026-11-22), on the uncommitted sixth-review tree: four findings, all
      reproduced or confirmed against the worktree, and two more shapes found while fixing them.
      - A Form-3 `processor=` expression is url4 its user wrote, but the run start read it through
        `_ast_of`, which swallowed every `ParseError`, the C19 subclass included; its spawn then
        skipped the entry check (`bare_root_ok=True`). With a broken mark in the processor's row,
        the run fetched `/a`, `/b` and the collection and called the reduce before failing as
        `unknown_processor`. Fix: `_ast_of` calls `check_target` outside the lenient block, so a
        C19 error is raised at run start, before any I/O, for the run text and the processor
        alike (`_processor_scan` already read the processor through `_ast_of`).
      - The parser stops at a group's first error, so a member that broke another rule hid a
        later member's broken mark: the row failed on that error alone and was skipped or
        collected. The same held one level down (`n=(other, broken)!'inner'`), for an intent call
        after a broken body (a row reads its intent's params before its body and its call after),
        and for an intent param that breaks another rule before a broken body. Fix: the grammar
        reads a group's members through `checked_members` (`core/at_most_one.py`), where a C19
        error outranks any other at every depth and, without one, the first error is raised as
        before; the entry check reads a row's body and intent apart (the intent after an empty
        text, which the grammar reads the same way). A member that breaks another rule in its own
        chain or intent is not read further: C19 is not a full validator.
      - Reading the members after a failure reached a 300-deep member that the eager parser
        cannot read (it reaches about 140 nested groups): two prior tests in
        `tests/unit/test_remote_node_call_context_preflight.py` failed with a `RecursionError`.
        Checking it against the base wheel also showed a sixth-review regression no test caught:
        `compile_expression` of a deep text that names no mark failed with a `RecursionError` in
        the entry check, where the base compiles it lazily. Fix: as the remote-call precheck does
        (`_remote_walk.py`), a text too deep for the eager parser is read as characters only
        then: one that names the mark is refused, FAIL CLOSED, a well-formed mark included
        (`refuse_too_deep`); any other keeps its base behavior. Compile and run now match the
        base on deep run texts, deep rows and deep call contexts; the base's own `RecursionError`
        on a deep call context at compile and on any deep text at run is unchanged.
      - Receiver-owned contexts: the reviewer agreed that a remote call's context, a relative
        reducer's context and a holdings context stay unread by the caller. The new
        `tests/unit/test_at_most_one_receivers.py` pins that each is forwarded byte for byte and
        that a receiving node of this version refuses the mark at its entry with no fetch, beside
        a relative call's own context, which the caller refuses. The spec now states the rule. The
        header of `tests/spec/test_abnf_call_context.py` still names the remote twin as resolved
        caller-side; it is a prior test and stays unchanged unless the owner approves the edit.
      - Trust boundary, recorded in the spec: the C19 entry guarantee covers public text and core
        parse-tree inputs; a custom lowering registry and a pre-built `Graph` or `DagNode` are
        trusted and not scanned.
      - 37 new tests: 30 in `tests/unit/test_at_most_one_texts.py` (both orders, skip and collect,
        text and tree, the processor, depth, and two controls: a group without a C19 error still
        reports its first error, and a tree row that fails on another rule alone is still
        skipped), and 7 in the new receivers module. `_refused` now asserts the C19 error itself.
        No prior test changed. Module sizes: `core/grammar.py` 702 (unchanged), `_lowering.py`
        613/640, `core/at_most_one.py` 196, `dag/_at_most_one_texts.py` 121.
    - Eighth review (2026-11-22), on the uncommitted seventh-review tree: no new source or runtime
      defect; one documentation inconsistency, and three owner decisions.
      - Prior-test transition, docstring only: the module docstring of
        `tests/spec/test_abnf_call_context.py` said the remote twin resolves its context
        caller-side, which is wrong. It now says the relative sugar and its canonical relative twin
        resolve it caller-side (a probe gave the same result for both) and that a remote call's
        context is receiver-owned and checked separately. Imports, test functions and assertions
        are unchanged: the module's syntax tree after the docstring equals the base. The owner
        approved the exact transition, pinned in `.claude/test-change-approvals/OME-1996.json`:
        base blob `f491ea080d71a5ea22d33d8911f0fb76b608d060`, approved blob
        `ee8311c5d587c584e57ee1fffc349bd9529f4cee`. The append-only check passes. A module
        docstring is outside its protected ranges, so the check does not need the manifest here;
        the approval matcher still matches the file against it.
      - Receiver-owned boundary, approved: a remote call's context, a relative reducer's context
        and a holdings context stay unread by the caller and are forwarded byte for byte. A
        receiving node of this version refuses a malformed mark at its entry; an older one ignores
        the key, and readers-first rollout keeps a writer from sending the mark to one.
      - Trust boundary, approved: a custom lowering registry and a pre-built `Graph` or `DagNode`
        are trusted and not scanned for C19; this leaf adds no generic DAG scanner.
      - The spec line on the prior test's header now names the file as the relative-call record.
    - Ninth review (2026-11-22), on the uncommitted eighth-review tree: five defects, each
      reproduced before the fix (two High, three Medium).
      - High: the holdings-ref predicate (`holds_holdings_ref`, `dag/source_scan.py`) read each
        segment with the full grammar and counted one that failed to read and held an `@` as a
        holdings ref. The C19 error is a `ParseError`, so a broken mark beside an `@` in quoted
        text (`'user@example.com'`), in a URL's user (`https://user@host/a`) or in a nested
        sibling made the context the receiver's: compile and run accepted it, and the run fetched
        `/a` and shipped the broken mark to the route verbatim. Fix: the predicate reads with no
        C19 refusal (`c19_blind`, a context variable every C19 refusal asks first); whether a
        context holds a holdings ref is a question about its structure, which the mark must not
        change. A real holdings ref still counts, beside a broken mark or not, and its context
        still ships verbatim.
      - High: the entry check read a relative call's context segments with the eager grammar,
        while lowering (`_slot_from_text`) defers a group through `deferrable_group` without
        reading its sources. A deferred group that failed on another rule made the context prose
        for the check and a source list for lowering: the run fetched an image opt-in before
        lowering refused a later broken mark, and a mark inside a later group compiled and failed
        at run time with an ordinary `ParseError`, after fetching `/a`. Fix: the entry check reads
        each segment as lowering does (`_context_member`): `deferrable_group` first, and a
        deferred group's text read for a C19 error only. With no C19 error such a call still
        compiles, as at base.
      - Medium: the grammar reads `;expand` by its key alone and dropped its value, so
        `m:/a;expand=false;required;<mark>` parsed as a marked expansion and rendered without
        `=false`, while `url4.src` refused the same form. Fix: on a marked source the grammar keeps
        a valued `;expand` (`keeps_valued_expand`) and the form check refuses it ("write ;expand
        as a flag, without a value"); an unmarked `;expand=false` still expands, as at base.
      - Medium: the entry check parsed only a tree reducer's source side
        (`split_intent(reducer)[0]`), which drops its `;` chain with the mark, and that group
        without its intent failed on another rule and was read leniently, so `run(tree)` fetched
        the collection and ran the rows before the reduce failed. Fix: `_reducer_tree` refuses the
        mark in the reducer's `;` chain first, as the text path's envelope decode does.
      - Medium: the processor scan (`_processor_scan`, `dag/_run_files.py`) ran the resolve-time
        grammar (`build`) before the entry check, so a Form-3 processor with the mark nested too
        deeply for the eager parser raised a `RecursionError` before `refuse_too_deep`. Fix: the
        entry check first. A deep unmarked processor keeps the base `RecursionError`. The node's
        HTTP route reads the processor from its query: `handle_http` calls `node.fetch`
        (`peer/_http.py:108`), and the eval path passes the `processor` param to `_run_text`
        (`_eval_parts`, `peer/_dispatch.py:158-160`). A raw `GET /v1?processor=<deep marked
        text>&q=('hi')!'i'` answered HTTP 500 `internal_error` at base and answers HTTP 400
        `malformed_source` here (`status_for`), so the fix closes that HTTP 500. A percent-encoded
        processor answers 200 at base and here: the query reader does not decode it, so its text
        starts with `%`, reads as a Form-1 id and, with no reduce, is never evaluated.
      - Private-import ratchet: the first fix imported `c19_blind` from `core._annotations` and
        `split_directive_fields` from `core._splitters` into `dag`, two new cross-layer private
        crossings (23 against the baseline 21). Fix: `c19_blind` is re-exported from the public
        `core/at_most_one.py` with a redundant alias, as `core/grammar.py` re-exports a lexical
        name, and `split_directive_fields` comes from `core/parser.py`, as `split_intent` does.
      - Compared with the base: an unmarked `;expand=false`, a deep unmarked processor, and the
        calls `/ep((bad;1=2)!'i', b:/b)!'out'`, `/ep(run: 1, (bad;1=2)!'i')!'out'` and
        `/ep(a@b, x)!'o'` behave as at base.
      - 26 new tests: 10 in the new `tests/unit/test_at_most_one_contexts.py` (an `@` in data,
        text and tree; a real holdings ref still shipped; a well-formed mark beside a URL's user
        resolved on the caller; deferred groups; one control), 12 in
        `tests/unit/test_at_most_one_form.py` (a valued `;expand` at parse, in `url4.src`, at
        render and on the tree path; two controls) and 4 in `tests/unit/test_at_most_one_texts.py`
        (a tree reducer's `;` chain; a deep processor, with its HTTP status). No prior test
        changed in this round. Module sizes: `core/grammar.py` 703/705, `_lowering.py` 614/640,
        `core/at_most_one.py` 216, `dag/_at_most_one_texts.py` 147, `dag/source_scan.py` 425.
    - Tenth review (2026-11-22), on the uncommitted ninth-review tree: two defects, each
      reproduced before the fix (one High, one Medium), and gate figures to refresh.
      - High: two intent fallbacks in the grammar (`_relative_intent`, `_intent_value_or_text`)
        and the classifier's remote form (`_remote_form`, `core/intent.py`) turn a `ParseError`
        into a code pointer, prose or a reference, and the C19 error is a `ParseError`. So
        `(a:'A')!(*m:https://two;required;<mark>=false)!'inner'` built its intent as prose,
        compiled, and ran it as the model's prompt; a row's intent did the same after the
        collection fetch; a Form-3 processor's was not refused at run start;
        `(a:'A')!/p?<mark>=true&q=(b)!'i'` became a code pointer refused on another rule; and
        the classifier called the first prose and a remote call with the mark as a param a
        reference. At base the key was unknown, so the first intent was read as an expression
        and evaluated. Fix: each fallback re-raises a C19 error first (`raise_if_c19`,
        `core/at_most_one.py`), one line each, so `core/grammar.py` stays within its cap. An
        audit of every other `except ParseError` in `packages/url4/src` found none that loses a
        C19 error: each re-raises it, converts it to a `ValueError` or `RenderError`, answers a
        yes-or-no question (`is_named_job`), or reads C19-blind on purpose; the
        iteration-envelope descriptor check (`_is_descriptored`) can swallow one, but each text
        that reaches it with the mark fails at parse on another rule, as at base.
      - Medium: the entry check asks whether a relative call's context holds a holdings ref
        before it reads the context, and that reading parses each segment in order. A context
        too deep for the eager parser escaped as a `RecursionError`, an HTTP 500, before
        `refuse_too_deep`, a well-formed mark included. Fix: `_receiver_owned`
        (`dag/_at_most_one_texts.py`) refuses such a context when it names the mark, FAIL
        CLOSED, and keeps the base `RecursionError` otherwise; a holdings ref ahead of the deep
        segment still makes the context the receiver's.
      - Low: the gate figures in the ledger and the drafts are rerun after the two fixes.
      - Compared with the base: an intent that only looks like url4 (`(two words, here)`,
        `{not a struct`), a failing code pointer (`/p((`), a failing reference
        (`url4://n/p((`), a remote call whose context holds a broken mark (the receiver's) and
        a deep unmarked context behave as at base.
      - 16 new tests: 14 in the new `tests/unit/test_at_most_one_intents.py` (a group's and a
        relative intent at parse; those two, a row's and a tree row's intent at compile and run;
        a Form-3 processor's; the classifier; two controls; a node's HTTP 400 for a structured
        intent, a deep context and a deep processor, by a raw query) and 2 in
        `tests/unit/test_at_most_one_contexts.py` (a deep marked context; an unmarked control).
        No prior test changed in this round. Module sizes: `core/grammar.py` 705/705,
        `_lowering.py` 614/640, `core/at_most_one.py` 228, `core/intent.py` 208,
        `dag/_at_most_one_texts.py` 162.
    - Eleventh review (2026-11-22), on the uncommitted tenth-review tree: one defect, reproduced
      before the fix (Medium), and stale source anchors (Low).
      - Medium: `compile_expression` and `run` refused a marked text too deep for the eager
        parser, but the public eager readers did not: `parse`, `parse_value`, `build`,
        `Parser.build` and `classify_intent` let it escape as a `RecursionError`, and so did the
        client front door, which builds the text itself for a node target or protocol params
        before it runs. At base the key was unknown and each raised the same `RecursionError`.
        Fix: each of those readers reads through `read_refusing_too_deep`
        (`core/at_most_one.py`), which refuses such a text when it names the mark, FAIL CLOSED,
        and keeps the `RecursionError` otherwise. The grammar's two entries go through
        `checked_read`, which also does the form check `parse` did, so `core/grammar.py` stays
        at 705/705. The parser re-enters none of these readers while it reads (checked on six
        nesting shapes), so the guard acts only at the outer call, once the stack has unwound,
        and the recursion below keeps its base behavior. An internal reader that calls `parse`
        and catches a parse error now meets such a text as it meets a shallow C19 error;
        `compile_expression` and `run` refuse it before them. `intent_atom` and
        `parse_group_root` stay unguarded: they are internal readers, every public path to them
        is guarded, and `intent_atom` re-enters itself on an intent chain, where a guard would
        act at the recursion limit. The twelfth review's second report found public paths that
        were not guarded; see there.
      - Low: three anchors into `core/_annotations.py` in the C19 placement spec had drifted
        after its earlier additions (`validate_exec_annotations`, `classify_boundary`, the C19
        branch of `validate_param`), and the fix moved `classify_intent`'s end by one line. All
        four are updated, and every other anchor in the C19 fragment was checked against the
        function it names.
      - Compared with the tree before the fix: for a deep marked and a deep unmarked text at the
        top, in a collection, a row's body or intent, a relative call's context, an intent and a
        named member, only `build` changes (a marked text is refused instead of a
        `RecursionError`); `compile_expression`, `run`, the fetches and a node's HTTP status are
        the same, and so is a Form-3 processor's refusal. The helper adds up to two stack frames
        above the recursion, so the eager parser's reach moved by one level at its very edge on
        Python 3.14: `build` reads 140 nested groups where it read 141, and `parse_value` an
        intent chain of 81 where it read 82; `parse` and `classify_intent` are unchanged. The
        edge is not a contract: it already moves with the caller's own stack depth, by more than
        that through `Client.evaluate` or a node's handler. The twelfth review rejected this
        shift as a change to unmarked texts; see there.
      - 12 new tests in the new `tests/unit/test_at_most_one_readers.py`: the five readers with
        a deep marked text and with a deep unmarked control, and the client front door with a
        node target and with protocol params, with no fetch. No prior test changed in this
        round. Module sizes: `core/grammar.py` 705/705, `core/at_most_one.py` 254,
        `core/parser.py` 264, `core/intent.py` 209.
    - Twelfth review (2026-11-23), on the uncommitted eleventh-review tree: one defect, reproduced
      before the fix (Medium).
      - Medium: the eleventh review's shared helper (`read_refusing_too_deep`, and `checked_read`
        over it) stood between each public eager reader and its parser, two frames for `parse`,
        `parse_value` and `build` and one for `classify_intent`. An unmarked text near the limit
        that base read then failed: on the same caller stack, an unmarked 141-group text that
        base `parse_value`, `build` and `Parser.build` read raised a `RecursionError` on Python
        3.12, 3.13 and 3.14, and so did `Client.evaluate()` where it builds the text. C19 keeps
        unmarked sources as they were, so the eleventh review's disclosure did not make the shift
        compatible. Fix: `parse`, `parse_value`, `build` and `classify_intent` each call
        `refuse_too_deep` in an `except RecursionError` of their own frame and re-raise, and the
        two helpers are gone; `build`'s body is back in `build`. An exception handler costs a
        frame nothing, so each reader calls its parser from its own frame, as at base. A fifth
        name imported from `core/at_most_one.py` would wrap `core/grammar.py`'s import onto seven
        lines, so it imports the module, as `core/render.py` imports its guard module, and its
        module docstring and four comments by `intent_atom` are rewrapped to 100 columns with the
        same words in the same order (eight lines), to stay at 705/705.
      - Compared with base on Python 3.12.9, 3.13.11 and 3.14.2: the reviewer's top-level case
        (`_parse_value`, `parse_value`, `build` and `Parser.build` on the 141-group text) reads
        on both. From a helper's frame each public reader reaches as far as at base (`parse`,
        `parse_value`, `Parser.build` and `classify_intent` 140 nested groups, `build` 141) and
        fails one group deeper the same way. The eleventh review's shift is gone.
      - 5 new tests in `tests/unit/test_at_most_one_readers.py`: for each public reader, a
        20-group text is read from as deep a caller as its base entry (its parser, called from
        one frame) reads it, to the frame; one frame deeper an unmarked text raises a
        `RecursionError` and a marked one is refused. Each failed before the fix, by the frames
        the helper added. No committed test changed; in the module, `_deep` takes a depth and the
        well-formed mark is a constant. Module sizes: `core/grammar.py` 705/705, `core/parser.py`
        264/267, `core/at_most_one.py` 234, `core/intent.py` 213.
    - Twelfth review, second report (2026-11-23), on the uncommitted eleventh-review tree: one
      defect, reproduced before the fix (Medium), which disproves a claim of the eleventh review.
      - Medium: the builders read a string intent or reducer through `intent_atom` with no guard:
        `url4.expr`, `url4.broadcast`, `url4.reduce` and `url4.iterate` (its `intent=` and
        `reduce=`) in `_intent_node`, and an iteration's reducer given as a source in
        `_rewrite_reducer_iteration` (`core/builders.py`); `Client.query`, `.broadcast`,
        `.reduce` and `.iterate` build through them. A marked intent or reducer too deep for the
        eager parser escaped as a `RecursionError`, while a marked source given to the same
        builders was refused. The eleventh review wrote that every public path to `intent_atom`
        and `parse_group_root` was guarded; it was not.
      - An audit of every call to `intent_atom` and `parse_group_root` outside the parser found
        three more paths of the same kind, reproduced the same way: a client call with a node
        target rewrites an iteration's reducer through `_rewrite_reducer_iteration`;
        `is_named_job` (`core/intent.py`), which `render` and `Client.evaluate` call on a named
        job and `Url4Node.code` on a code name; and `render`, which reads a structured intent
        back (`check_structured_intent`), under `Client.evaluate` too.
      - Fix: `_intent_node`, `_rewrite_reducer_iteration`, `is_named_job` and the renderer's
        `_render_intent`, around its call to `check_structured_intent`, each call
        `refuse_too_deep` in an `except RecursionError` of their own frame and re-raise, as the
        public eager readers do. Not through `read_refusing_too_deep`, as the report proposed:
        the twelfth review removed it, since a wrapper frame cost every read its depth. The
        parser re-enters none of the four, and no frame is added. The guard sits in
        `_render_intent`, not in `core/_render_guards.py`, which this change does not otherwise
        touch and which is at its cap. Outside the parser, every other call to `intent_atom` or
        `parse_group_root` is under `build` (`assemble_expression` is `build`'s body, and only
        `build` calls it), in the DAG layer behind the entry check of `compile_expression` and
        `run`, which refuses such a text first, or in `dag/_code_wiring.py`, which reads only a
        reducer with no `(`. `intent_atom` and `parse_group_root` stay unguarded for the reason
        the eleventh review gave.
      - Compared with base on Python 3.12.9, 3.13.11 and 3.14.2: from a helper's frame, `expr`,
        `broadcast`, `iterate` (intent and reducer), an iteration's reducer in a source,
        `is_named_job` and `render` (checked and unchecked) read a 20-group unmarked intent, or a
        20-level tree, from as deep a caller as at base, to the frame. A deep unmarked intent
        keeps its `RecursionError` at every one of these entries.
      - 23 new tests in `tests/unit/test_at_most_one_readers.py`: 11 for the builders,
        `is_named_job`, `render` and `Url4Node.code` with a deep marked intent and a deep
        unmarked control; 9 for the client helpers, with no fetch; and 3 reach tests (`expr`, an
        iteration's reducer, `is_named_job`) against their parser called from as many frames as
        at base. Each failed before the fix. No committed test changed. Module sizes:
        `core/builders.py` 477/478, `core/render.py` 616/676, `core/intent.py` 216,
        `core/at_most_one.py` 236.
