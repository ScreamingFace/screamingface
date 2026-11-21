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
- `uv run .claude/scripts/run_gates.py url4` green, including the coverage floor.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - Spec and plan amendment (approved by the owner before code): `contracts-placement.md`,
    `test-plan.md`, `00-overview.md` and `contracts.md` under
    `docs/spec/2026-11-16-router-recipe-extension/`; `docs/plan/2026-11-16-router-recipe-extension.md`
    step 7.1.
  - New `packages/url4/src/url4/core/at_most_one.py`: the one owner of the mark's key and form. The
    parser, the DAG text path, `url4.src` and the renderer all call it.
  - `core/errors.py` (`EXPANSION_TOO_MANY`), `core/grammar.py` (form check on every whole parsed
    source through `checked_form`; the mark is refused as an expression param),
    `core/descriptor_head.py` (the same refusal on a deferred group's chain), `core/builders.py`
    (`src(..., at_most_one=True)`, the mark placed right after the guard through `with_mark` in
    `core/at_most_one.py`, and the form check), new `core/_builder_exec.py` (the execution axis of
    `src`, moved out of `builders.py`), `core/parser.py` (a group or iteration envelope refuses the
    mark as a param), `core/render.py` (render refuses a broken form through the guard module's
    reparse wrapper, and refuses the mark as an expression param).
  - `dag/node.py` (`NoElement`), `dag/nodes/iteration.py` (`ExpandNode.at_most_one`), new
    `dag/nodes/_at_most_one.py` (the zero, one and two-plus rule), `dag/nodes/_shared.py` (gather
    and frame skip `NoElement`), `dag/_descriptor.py` (lowering), `dag/semantics/code_binding.py`
    (`CodeSlot.at_most_one`), `dag/_code_wiring.py` (slot flag).
  - New tests: `tests/unit/test_at_most_one_form.py`, `tests/unit/test_at_most_one_runtime.py`
    (48 tests at PR-open), then 55 more in the review round, including the new
    `tests/unit/test_at_most_one_bytes.py`: 103 C19 tests in all.
- **Commits:** one commit, `feat(url4): let a named expand source take at most one element`,
  authorized by the owner on 2026-11-20, made on base `c403ebd33` and rebased onto the then-current
  `origin/main` before PR-open. Linear OME-1996 (under OME-1306), filed at PR-open on 2026-11-20 with
  the owner's confirmation; the owner confirmed the exact mirror path
  `docs/tasks/2026-11-20-OME-1996-url4-expand-at-most-one.md` after the number existed. Branch
  renamed to `OME-1996-url4-expand-at-most-one`. A second commit,
  `fix(url4): refuse valued guards and envelope marks on at-most-one sources`, authorized by the
  owner on 2026-11-21 after the second review, carries the review-round code, tests and docs.
- **Gates:** `uv run .claude/scripts/run_gates.py url4` green: append-only check, ruff check, ruff
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
  `annotations=` with the mark right after it.
- **Deviations:**
  - The form owner is a new public module `core/at_most_one.py`. A private module would add two
    cross-layer private imports from `dag`, which the private-import ratchet forbids.
  - `core/_annotations.py`, `dag/_wiring.py` and `dag/nodes/broadcast_result.py` needed no change:
    the one element is returned as a plain value, so the quorum gate and the broadcast record already
    give it the source's name. `dag/node.py`, `dag/nodes/_shared.py`, `dag/_code_wiring.py` and
    `core/descriptor_head.py` changed instead.
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
