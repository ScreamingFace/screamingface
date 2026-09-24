---
name: sdlc-python
description: >-
  Use for EVERY development iteration on Python code — any change (feature, bug fix,
  refactor, follow-up) in a project whose `.claude/sdlc.local.md` maps a stack to this skill.
  Rigid SDLC loop: work-ledger first → frame → design → TDD (RED first) → append-only wise
  coverage → quality gates via run_gates.py → wisdom + 95%-confidence review → commit. Invoke
  BEFORE writing or modifying any Python code; re-enter per unit of work. Toolchain commands
  and project conventions come from the card; Electron desktop code uses `sdlc-electron`.
---

# SDLC Iteration — Python

**Announce at start:** "Using the sdlc-python skill — the rigid TDD loop for the Python stack."

This is a **RIGID** process skill. Every Python change in a card-carrying project goes through
this loop. No shortcuts, no "this one is too small." One iteration = one focused, tested,
reviewed, committed unit of work — then re-enter the loop. The loop, ledger, and gates are
shared verbatim with the sibling skill (Electron uses `sdlc-electron`) under LOOP PARITY — the
`SHARED-LOOP` regions below are changed in both skills together, never in one
(`.claude/scripts/check_loop_parity.py` enforces it).

<!-- SHARED-LOOP:BEGIN -->
## Card resolution — before anything

Read `.claude/sdlc.local.md` in the project root. **Missing → HARD STOP:** tell the user the
card is missing (it is committed repo config — restore it from git) and stop; never guess
gates, paths, or conventions. Resolve the active stack entry: match the planned/changed paths
against `stacks[].root` for entries whose `skill:` names this skill; ambiguous or cross-stack
→ ask. Then read the card BODY section for the active stack — those project conventions bind
every cycle.

## Non-negotiable rules

1. **Work-ledger first.** Before any code or test, create the ledger in `ledger_dir` from the
   card (this repo: `docs/work/`, named `YYYY-MM-DD-<slug>.md` per D8 — the branch slug, not a
   ticket id; copy `docs/work/TEMPLATE.md`) with Intent + Planned changes + Test plan +
   Acceptance, and `ticket: unfiled`. The Linear issue is filed at PR-open (per
   `task-management`); backfill `ticket: OME-N` then. Fill the Outcome at the end. **No code
   before its ledger.**
2. **One iteration = one focused unit.** Never batch unrelated changes.
3. **Companion skills are binding.** Invoke every card `companion_skills` entry whose `when`
   condition matches this unit of work; skipping one marked `mandatory: true` is a process
   violation — STOP and run it.
4. **TDD always.** Write the failing test FIRST, then minimal code to pass. No production
   code without a test that demanded it. Test idioms: see the Stack idiom section.
5. **Tests are append-only across cycles.** NEVER delete/rewrite/weaken/skip a prior test to
   make new code pass. A prior test that genuinely must change is a Confidence-Gate decision
   → STOP and ask. Adding tests is always fine.
6. **Wise & thorough coverage — not just lines.** Happy path, boundaries, error paths, and
   the invariant the code protects (the card body names the project's invariants).
   Assertions verify *behavior*, never "it ran".
7. **Quality gates are absolute.** Run the repo's gate runner —
   `uv run .claude/scripts/run_gates.py <stack>` (from the repo root) — all card gates
   green before commit; never weaken a gate — fix the code. Also verify the card's `gates:`
   cover this skill's gate categories (Stack idiom section); a missing category is a card
   defect — surface it.
8. **The 95% Confidence Gate.** For ANY decision < 95% confident it is both correct AND
   wanted, STOP and ask first: ambiguous requirements, a design fork, changing a prior test
   or a public contract, a new dependency, or anything security-sensitive. The gate is
   call-and-return: pause → ask → resume the step you were on.
9. **"Is this wise?" is a required step**, not optional.
10. **Project conventions hold every cycle** — the card body's rules for the active stack.
11. **Bounded retries — HARD STOP at 10.** A unit gets at most 10 fix-and-rerun attempts
    against the same failing signal. On the 10th still-failing, HARD STOP and escalate with
    a **loop diagnosis** (the recurring failure, what changed each round, the suspected
    root cause). Never loop past 10.
12. **Semantic comment layer — write for the NEXT AI iteration.** Comment generously with
    ONLY this fixed, greppable anchor vocabulary (syntax per the Stack idiom section) plus
    the card's `extra_anchors` — an open set defeats greppability, so invent no others:
    - `WHY:` — the rationale/decision the type or test cannot encode.
    - `INVARIANT:` — a property that must always hold (the contract this code protects).
    - `AIDEV-NOTE:` — guidance/warning for the next agent touching this code.
    - `FEATURE:` — the product feature this code serves (name it).
    - `STORY:` — the user story / scenario it satisfies ("as a <persona>, I …").
    Anchor WHY/INVARIANT next to the code (and in tests for contracts). Do NOT add a
    comment that merely restates the code.
<!-- SHARED-LOOP:END -->

## Stack idiom — Python

- **Anchor syntax:** `#` (e.g. `# WHY:`, `# INVARIANT:`).
- **Tortoise ORM work — STRONGLY RECOMMENDED companion:** this repo's Python services
  (`apps/aigateway`, `apps/scoreboard`) use Tortoise ORM. For ANY Tortoise-touching unit
  (models, querysets, migrations, transactions, signals, FastAPI lifespan wiring), invoke
  the **`tortoise-dev`** skill — it carries the house patterns (model-per-file, abstract
  Base interfaces, strict member ordering, built-in Tortoise migrations — never Aerich,
  Pydantic v2). It is `mandatory: true` in the card's `companion_skills` (rule 3). If the
  plugin is not installed, STOP and propose installing it:
  https://github.com/sergio-bershadsky/ai/tree/main/plugins/tortoise-dev
- **Testing idiom:** unit-test service/business logic against abstract interfaces — no DB, no
  network. Integration-test persistence on an ephemeral database (in-memory engine or
  testcontainers). Parametrize table-style where it clarifies.
- **Exceptions:** catch specific exceptions; never bare `except`.
- **Gate categories the card's `gates:` must cover:** format · lint · typecheck · test (full
  suite) · coverage.
- **Stack rule S1 — migrations ship with the schema.** Any schema/model change is authored
  AND its migration is created + committed in the SAME iteration (ORM-specific mechanics come
  from the card's `companion_skills`). Declare it in the ledger's Planned changes; confirm it
  in the Outcome. A schema change without its migration is an incomplete iteration — treat it
  like a red gate.

<!-- SHARED-LOOP:BEGIN -->
## The loop

```
WRITE LEDGER (PLANNED) → FRAME ──intent<95%?──▶ ASK (pause→resume) → DESIGN (is this wise?)
  ──companion `when` matches?──▶ INVOKE companion skill(s) ──approach<95%?──▶ ASK
  → RED (failing test; never touch prior tests) → GREEN (minimal code; run NEW + ALL prior tests)
  → REFACTOR (stay green, ≤450-line files) → COVERAGE PASS
  → QUALITY GATE (run_gates.py <stack>) ──red & attempt<10?──▶ fix & rerun
                                        ──red on 10th──▶ HARD STOP + loop diagnosis
  ──green──▶ WISDOM + CONFIDENCE REVIEW ──any change<95% or altered a prior test?──▶ ASK
  ──ok──▶ UPDATE LEDGER OUTCOME (actual files, commits, gates, deviations) → COMMIT → NEXT
```

The **95% gate is call-and-return**: pause → ask → resume the step you were on. The
QUALITY-GATE red path loops to GREEN only while `attempt < 10`.

## Checklist (one todo item per step, in order)

1. **LEDGER (PLANNED)** — Intent + Planned files + Test plan + Acceptance. Flip to
   IN_PROGRESS when coding. **Ledger first, ticket at PR-open:** no Linear issue is required
   to start; the ledger carries `ticket: unfiled`. The issue is filed per `task-management`
   when the PR is opened — under an epic, after the user confirms — and its `OME-N` is then
   backfilled into the ledger.
2. **FRAME** — restate task + acceptance; list exact files. *Intent <95%? ask.*
3. **DESIGN** — interfaces, file placement, test approach; simplest wise design (DRY, SOLID,
   YAGNI); apply the card body's conventions. **Invoke every companion skill whose `when`
   matches — now.** *Approach <95%? ask.*
4. **RED** — write failing test(s) (happy + boundaries + errors); run; confirm they fail for
   the right reason. Do not touch prior tests.
5. **GREEN** — minimal code; run the full test suite (new + all prior).
6. **REFACTOR** — clean while green; keep files focused (≤450 lines).
7. **COVERAGE PASS** — assert the meaningful branches/edges/errors per rule 6.
8. **QUALITY GATE** — `run_gates.py <stack>` all green. Bounded to 10 attempts (rule 11).
9. **WISDOM + CONFIDENCE REVIEW** — answer the wisdom prompts; altered a prior test? any
   decision <95%? → ask.
10. **LEDGER OUTCOME** — actual vs planned files, commit sha/message, gate results,
    **Deviations**. Status DONE | BLOCKED.
11. **COMMIT** — only when gates green and confidence ≥95% (or confirmed). Conventional
    message; never append `Co-Authored-By`. Commits need no ticket; the `OME-N` reference
    (card `commit_refs`) goes in the PR body at PR-open, and may be added to later commits
    once the issue is filed.
12. **NEXT** — re-enter the loop. All prior tests remain and keep passing. Close the ticket
    per `task-management` (commits + gates + ledger comment; state → Done).

## Test-preservation — the hard rule

Prior cycles' tests are the contract you must not break. New code earns its place by passing
**new** tests while **all old tests stay green and unmodified**. A wrong/obsolete old test is
a finding to surface, not a thing to quietly edit.

## Wisdom prompts (answer before commit — plus the Stack prompts below and any in the card body)

- Simpler design? Speculative generality (YAGNI)? Duplicated logic?
- Do tests assert real behavior and the invariants the card body names, or just "it ran"?
- Blast radius — did I touch a public contract, a shared interface, or a schema?
- Security — any secret logged/exposed? any fail-open path introduced?
- Card conventions honored for the active stack?

## Red flags — STOP immediately (plus the Stack red flags below and any in the card body)

| Thought | Action |
|---|---|
| "I'll update this old test to match the new code." | STOP. Confidence Gate — ask. |
| "Tests pass, ship it." (skipping wisdom review) | STOP. Run the review. |
| "~85% sure this is what they want." | STOP. Ask. |
| Weakening a gate / lowering coverage to move on. | STOP. Fix the code, or ask. |
| Production code with no failing test driving it. | STOP. Test first. |
| Code/tests before the ledger exists. | STOP. Create the ledger first. |
| Skipping a `mandatory: true` companion skill. | STOP (rule 3). Invoke it now. |
| Same gate/test red on the 10th retry. | HARD STOP (rule 11). Escalate with a loop diagnosis. |
| Non-obvious code with no `WHY:`/`INVARIANT:` and no `FEATURE:`/`STORY:` link — or a comment that just restates the code. | STOP (rule 12). Add a real semantic anchor; delete noise. |
<!-- SHARED-LOOP:END -->

## Stack wisdom prompts — Python

- Schema/model touched → is the migration present in this same iteration (S1)?
- Any bare `except`, or a swallowed exception that should surface?
- Typecheck clean without `# type: ignore` escapes?

## Stack red flags — Python

| Thought | Action |
|---|---|
| `# type: ignore` to move on. | STOP. Fix the types, or ask. |
| A bare `except:` / silently swallowed exception. | STOP. Catch the specific exception; surface failures. |
| Schema/model change with no migration this cycle. | STOP (S1). Create + commit the migration now. |
