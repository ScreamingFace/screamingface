---
name: sdlc-electron
description: >-
  Use for EVERY development iteration on Electron desktop code — any change (feature, bug
  fix, refactor, follow-up) across main / preload / renderer in a project whose
  `.claude/sdlc.local.md` maps a stack to this skill. Rigid SDLC loop: work-ledger first →
  frame → a11y-first design → TDD (RED first, Testing-Library; IPC contracts tested on both
  sides) → append-only wise coverage → quality gates via run_gates.py (incl. a11y) → wisdom +
  95%-confidence review → commit. Invoke BEFORE writing or modifying any Electron code;
  re-enter per unit of work. Toolchain commands and project conventions come from the card;
  Python uses `sdlc-python`.
---

# SDLC Iteration — Electron

**Announce at start:** "Using the sdlc-electron skill — the rigid TDD loop for the Electron stack."

This is a **RIGID** process skill. Every Electron change in a card-carrying project goes through
this loop. No shortcuts, no "this one is too small." One iteration = one focused, tested,
reviewed, committed unit of work — then re-enter the loop. The loop, ledger, and gates are
shared verbatim with the sibling skill (Python uses `sdlc-python`) under LOOP PARITY — the
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

## Stack idiom — Electron (TS: main / preload / renderer)

- **Architecture doctrine is a separate skill:** design-time invariants (process topology,
  extension platform, process supervision, diagnostics) live in `arch-electron` — invoke it
  when a unit designs new architecture, changes the extension API, or integrates an
  external process. This skill owns the build-time loop and the security checklist below.
- **Anchor syntax:** `//` (TS/TSX; e.g. `// WHY:`, `// INVARIANT:`).
- **Process model:** every unit names which process(es) it touches — **main** (Node
  services, IPC handlers, external I/O), **preload** (the `contextBridge` API surface),
  **renderer** (React UI). Cross-process work is still ONE unit when it implements one
  IPC contract end-to-end.
- **Testing idiom:** renderer — React Testing Library: assert **behavior and accessible
  roles**, never implementation details; cover the render states (loading / empty / error /
  success), user interactions, and boundary inputs. Main — unit-test services with Electron
  APIs mocked at the boundary. **IPC contracts are tested on BOTH sides** (main handler +
  typed preload bridge) with typed payloads.
- **Strict TypeScript:** no `any` at boundaries — especially IPC payloads and the preload
  API surface.
- **Security posture is non-negotiable** — the official Electron security checklist
  (electronjs.org/docs/latest/tutorial/security) is encoded here:
  - `contextIsolation: true` · `nodeIntegration: false` · `sandbox: true` · never disable
    `webSecurity` · never enable `allowRunningInsecureContent` or experimental features ·
    no `<webview>` without `will-attach-webview` verification.
  - **Validate the sender of every IPC message** in main-process handlers
    (`event.senderFrame` against a URL allowlist) — an unvalidated handler is a
    privileged-action hole.
  - `session.setPermissionRequestHandler` set, deny-by-default; a **CSP** is defined
    (headers via `onHeadersReceived` or meta tag).
  - Navigation restricted (`will-navigate`) and window creation controlled
    (`setWindowOpenHandler`); never pass untrusted input to `shell.openExternal`.
  - Remote content only over `https:`/`wss:`; Electron stays on a current version.
  - **All external HTTP runs in the main process** — the renderer reaches the network only
    via typed IPC (CORS + credential hygiene).
- **Gate categories the card's `gates:` must cover:** typecheck (tsc) · lint · format · test
  (full suite) · **a11y** (jest-axe / Testing-Library a11y assertions) · coverage. a11y is a
  GATE, not a nicety.
- **Stack rule S1 — a11y-first DESIGN.** Accessibility (roles, labels, focus, keyboard nav,
  contrast) is designed in at the DESIGN step, and a11y assertions land WITH the component in
  the SAME iteration. Declare it in the ledger's Planned changes; confirm it in the Outcome.
- **Stack rule S2 — IPC contracts ship whole.** Any new or changed IPC channel lands WITH
  its typed contract and both-side tests (main handler + preload surface) in the SAME
  iteration. Declare it in the ledger's Planned changes; confirm it in the Outcome.

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

## Stack wisdom prompts — Electron

- Do tests assert behavior + accessible roles, or brittle implementation details?
- All render states (loading/empty/error/success) covered? a11y assertions present (S1)?
- Any `any` at a boundary — IPC payload, preload surface, external API response?
- New/changed IPC channel → typed contract + both-side tests in this same iteration (S2)?
- New IPC handler → is the sender validated (`senderFrame` allowlist)?
- New window / navigation / external-link path → restricted per the checklist?
- Any external HTTP or Node API creeping into the renderer?

## Stack red flags — Electron

| Thought | Action |
|---|---|
| `any` at a boundary / `eslint-disable` to move on. | STOP. Fix the types/code, or ask. |
| Asserting on implementation details. | STOP. Test behavior and roles. |
| Disabling or skipping an a11y check. | STOP (S1). a11y is a gate. |
| `nodeIntegration: true` / `contextIsolation: false` / `sandbox: false` / `webSecurity: false` "to make it work". | HARD STOP. Security posture is non-negotiable — ask. |
| External HTTP (or Node APIs) in the renderer. | STOP. Route via the main process over typed IPC. |
| New IPC channel without its contract + both-side tests. | STOP (S2). Land them in the same iteration. |
| `ipcMain` handler without sender validation (`senderFrame`). | STOP. Validate against the allowlist first. |
| Untrusted input to `shell.openExternal` / unrestricted `will-navigate` / `setWindowOpenHandler`. | STOP. Restrict per the security checklist. |
