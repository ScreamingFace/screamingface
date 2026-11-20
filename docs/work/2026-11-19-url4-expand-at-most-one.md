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
  - `core/errors.py` (`EXPANSION_TOO_MANY`), `core/grammar.py` (form check after a full source parse;
    the mark is refused as an expression param), `core/descriptor_head.py` (the same refusal on a
    deferred group's chain), `core/builders.py` (`src(..., at_most_one=True)`, written right after the
    guard), `core/_render_guards.py` and `core/render.py` (render refuses a broken form).
  - `dag/node.py` (`NoElement`), `dag/nodes/iteration.py` (`ExpandNode.at_most_one`),
    `dag/nodes/_shared.py` (gather and frame skip `NoElement`), `dag/_descriptor.py` (lowering),
    `dag/semantics/code_binding.py` (`CodeSlot.at_most_one`), `dag/_code_wiring.py` (slot flag).
  - New tests: `tests/unit/test_at_most_one_form.py`, `tests/unit/test_at_most_one_runtime.py`
    (48 tests).
- **Commits:** one commit, `feat(url4): let a named expand source take at most one element`,
  authorized by the owner on 2026-11-20, made on base `c403ebd33` and rebased onto the then-current
  `origin/main` before PR-open. Linear OME-1996 (under OME-1306), filed at PR-open on 2026-11-20 with
  the owner's confirmation; the owner confirmed the exact mirror path
  `docs/tasks/2026-11-20-OME-1996-url4-expand-at-most-one.md` after the number existed. Branch
  renamed to `OME-1996-url4-expand-at-most-one`.
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
- **Cross-version (test-plan row 178):** the new builder rendered a text and a broadcast panel with
  two plain members and one marked member, under quorum 3 and quorum 2, `;required` and `;optional`,
  for zero, one and two elements (24 byte strings). An isolated url4 install from `455166b0d` accepted
  every string. Zero: no source from the marked member; quorum 3 ends in `quorum_not_met` with zero
  process calls; quorum 2 makes one text call over `a: A` and `b: B` only, and two broadcast parts.
  One: a bare `x` in the text panel and `m[0]` in the broadcast. Two: two sources (`x`, `y`;
  `m[0]`, `m[1]`). The new reader on the same bytes: zero is the same; one gives `m: x` and
  `source_name: m`; two fails a `;required` member with `x.expansion_too_many` before any call and
  omits an `;optional` one.
- **Base wheel:** the built wheel, installed with `--no-deps` over the exact exported base lock
  (httpx and its dependencies only) on Python 3.12 and 3.14, with Pydantic and Tortoise absent, ran
  parse and render round trip, the text panel (zero, one, two), the broadcast panel and the code
  binding.
- **Deviations:**
  - The form owner is a new public module `core/at_most_one.py`. A private module would add two
    cross-layer private imports from `dag`, which the private-import ratchet forbids.
  - `core/_annotations.py`, `dag/_wiring.py` and `dag/nodes/broadcast_result.py` needed no change:
    the one element is returned as a plain value, so the quorum gate and the broadcast record already
    give it the source's name. `dag/node.py`, `dag/nodes/_shared.py`, `dag/_code_wiring.py`,
    `core/descriptor_head.py` and `core/_render_guards.py` changed instead.
  - `packages/url4/CHANGELOG.md` is not edited: the release tool writes it from the commit message.
  - `core/builders.py`, `core/grammar.py` and `core/render.py` were already above 450 lines; each got
    only the call into the form owner (plus the builder keyword), no new responsibility.
  - No prior test changed.
