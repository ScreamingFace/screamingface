# Spec — reconcile ledger-first with PR-time filing (Option A)

**Refs:** OME-1262 (folded into scope) · epic OME-1259 (adopt epic-first)
**Date:** 2026-09-24
**Status:** proposed

## Problem

OME-1262 moved Linear issue creation to **PR-open** (epic-first, confirm-first): no `OME-N`
exists while you code. But `sdlc-python` / `sdlc-electron` — deliberately untouched by
OME-1262 — still bake the ticket id into the coding phase in three places, all inside the
**`SHARED-LOOP`** regions that `check_loop_parity.py` requires to be **byte-identical** across
both skills:

1. **Ledger filename** (rule 1): `YYYY-MM-DD-<ticket-id>-<desc>.md` — un-nameable without `OME-N`.
2. **Checklist step 1 "Ticket first"**: *"the unit's issue exists … moves to In Progress; the ledger names the issue."*
3. **Commit step 11**: *"Body carries the card's `commit_refs` with the ticket number."*

Plus two non-shared spots: card **D8 ledger-naming** (`sdlc.local.md`) and the **ledger
TEMPLATE** frontmatter (`ticket: OME-<N>`).

Even OME-1262's own ledger (`2026-09-22-OME-1262-…md`, `ticket: OME-1262`, "Parent epic:
OME-1259") was filed-first — the authors couldn't follow the new rule because the naming
forced an early id.

## Decision — Option A: slug-keyed ledger, backfill the id

The **ledger leads the coding unit and is keyed by a date+slug name for its whole life.** The
Linear `OME-N` is a *record* that appears at PR-open and is backfilled into the ledger
frontmatter (and the PR body). **Ledger identity ≠ Linear identity.** This keeps ledger-first
intact while honoring PR-time / epic-first filing.

Constraint: rule 1, step 1, and step 11 are SHARED-LOOP — every edit below is applied
**verbatim in both `sdlc-python` and `sdlc-electron`**, and `check_loop_parity.py` must pass.

## Exact edits

### 1. `sdlc-python` + `sdlc-electron` — rule 1 (SHARED-LOOP, identical in both)

**Before**
```
1. **Work-ledger first.** Before any code or test, create the ledger in `ledger_dir` from the
   card (this repo: `docs/work/`, named `YYYY-MM-DD-<ticket-id>-<desc>.md` per D8; copy
   `docs/work/TEMPLATE.md`) with Intent + Planned changes + Test plan + Acceptance. Fill the
   Outcome at the end. **No code before its ledger.**
```
**After**
```
1. **Work-ledger first.** Before any code or test, create the ledger in `ledger_dir` from the
   card (this repo: `docs/work/`, named `YYYY-MM-DD-<slug>.md` per D8 — the branch slug, not a
   ticket id; copy `docs/work/TEMPLATE.md`) with Intent + Planned changes + Test plan +
   Acceptance, and `ticket: unfiled`. The Linear issue is filed at PR-open (per
   `task-management`); backfill `ticket: OME-N` then. Fill the Outcome at the end. **No code
   before its ledger.**
```

### 2. `sdlc-python` + `sdlc-electron` — checklist step 1 (SHARED-LOOP, identical in both)

**Before**
```
1. **LEDGER (PLANNED)** — Intent + Planned files + Test plan + Acceptance. Flip to
   IN_PROGRESS when coding. **Ticket first:** the unit's issue exists (file it per
   `task-management` if missing) and moves to **In Progress**; the ledger names the issue.
```
**After**
```
1. **LEDGER (PLANNED)** — Intent + Planned files + Test plan + Acceptance. Flip to
   IN_PROGRESS when coding. **Ledger first, ticket at PR-open:** no Linear issue is required
   to start; the ledger carries `ticket: unfiled`. The issue is filed per `task-management`
   when the PR is opened — under an epic, after the user confirms — and its `OME-N` is then
   backfilled into the ledger.
```

### 3. `sdlc-python` + `sdlc-electron` — commit step 11 (SHARED-LOOP, identical in both)

**Before**
```
11. **COMMIT** — only when gates green and confidence ≥95% (or confirmed). Conventional
    message; never append `Co-Authored-By`. Body carries the card's `commit_refs` with the
    ticket number.
```
**After**
```
11. **COMMIT** — only when gates green and confidence ≥95% (or confirmed). Conventional
    message; never append `Co-Authored-By`. Commits need no ticket; the `OME-N` reference
    (card `commit_refs`) goes in the PR body at PR-open, and may be added to later commits
    once the issue is filed.
```

> Steps 4–10 and 12 are unchanged. Step 12 ("Close the ticket per `task-management`") stays
> correct — by close the issue exists.

### 4. Card D8 — `sdlc.local.md`, `## ledger naming (D8)` (single file, not shared)

**Before**
```
`docs/work/YYYY-MM-DD-<ticket-id>-<short-description>.md` — created at work START
(date = start), frontmatter `status: planned|in_progress|done|blocked` + `finished:` filled
at close. Template: copy `docs/work/TEMPLATE.md`.
```
**After**
```
`docs/work/YYYY-MM-DD-<slug>.md` — created at work START (date = start; `<slug>` = the branch
description, NOT a ticket id, since no `OME-N` exists until PR-open). Frontmatter
`ticket: unfiled` (backfilled to `OME-N` when the issue is filed at PR-open),
`status: planned|in_progress|done|blocked`, `finished:` filled at close. Template: copy
`docs/work/TEMPLATE.md`.
```
`commit_refs: "Refs: OME-N"` is unchanged — only its *timing* moves to the PR body (see edit 3).

### 5. `docs/work/TEMPLATE.md` frontmatter (single file)

**Before**: `ticket: OME-<N>`
**After**: `ticket: unfiled   # set to OME-N when the issue is filed at PR-open`
Title line `# OME-<N> — <one-line unit title>` → `# <slug> — <one-line unit title>` (backfill
the id in-body if desired at PR-open).

### 6. `CLAUDE.md` rule 2 (single file) — missed by OME-1262

OME-1262 updated rule 1 (epic-first) but left rule 2 with the old ledger name.

**Before**
```
2. **Work ledger.** Every unit has `docs/work/YYYY-MM-DD-<ticket-id>-<desc>.md` — created
   at work START from `docs/work/TEMPLATE.md`, outcome filled at finish.
```
**After**
```
2. **Work ledger.** Every unit has `docs/work/YYYY-MM-DD-<slug>.md` (slug, not a ticket id —
   no `OME-N` exists until PR-open) — created at work START from `docs/work/TEMPLATE.md`,
   `ticket: unfiled` backfilled to `OME-N` at PR-open, outcome filled at finish.
```

## Non-goals

- No change to epic-first, confirm-first, self-assign, or the bug exception (OME-1262 owns those).
- No new workflow states or labels.
- Existing `OME-N`-named ledgers are left as-is (non-breaking; only new ledgers use the slug).

## Contradiction scan — further findings

Beyond edits 1–6, a full sweep of the process surface found:

- **Applied (mechanical, same decision):** `task-management/SKILL.md` — "(in-progress at
  ledger creation)" → "(in-progress when the issue is filed at PR-open)".

Three more trace to the same root ("no `OME-N` exists until PR-open"). Owner decisions taken:

**Fork A — branch naming + GitHub automation. → RESOLVED: rename at PR-open (applied).**
`CLAUDE.md` rules 5 & 6 and `working-in-this-repo/SKILL.md` §6 mandated `OME-N-<description>`
branches; `task-management` keys GitHub status automation off `…/<issue-id>-…`. Resolution:
branches use `<slug>` at work start and are **renamed to `OME-N-<desc>` at PR-open**
(`git branch -m`) once the issue is filed, so the branch-name automation still links; `Refs:
OME-N` lives in the PR body, not commits. Edited: `CLAUDE.md` rules 5 & 6,
`working-in-this-repo/SKILL.md` §6 branch + commit bullets.

**Fork B — `sdlc-unit-executor` is issue-first. → RESOLVED: universal, dispatch = confirmation
(applied).** PR-time filing applies to ALL work. The executor was reworked: its input is a
**unit of work + parent epic** (not a pre-existing `OME-N`); dispatching it on those IS the
user's confirmation to file (it is headless, never asks mid-run). It works on a `<slug>`
branch, and **at PR-open** files the leaf under the pre-approved epic (self-assigned), renames
the branch, backfills the ledger, creates the mirror, and opens the PR with `Refs: OME-N`.
Pre-filing STOPs return `blocked` with the question in the return value (no issue to annotate
yet). Edited: `.claude/agents/sdlc-unit-executor.md` (full rewrite).

**Fork C — `ticket-filer` obsolete under universal PR-time filing. → RESOLVED: repurpose
(applied).** It no longer batch-files leaves up front. Rewritten as the mechanical **single-leaf
PR-open filer**: given one implemented leaf + its parent epic, it validates against the card,
files under the epic (self-assigned, In Progress), and returns the identifier for the PR body;
the caller backfills the ledger + creates the `docs/tasks/` mirror. Bug path preserved (no
parent/assignee, Triage, reviewers tagged). Still never creates an epic. Edited:
`.claude/agents/ticket-filer.md` (full rewrite).

## Verification

```sh
cd .claude/worktrees/OME-1262-epic-first-filing
uv run python .claude/scripts/check_loop_parity.py        # must print "LOOP PARITY OK"
grep -n "ticket-id" .claude/skills/sdlc-python/SKILL.md .claude/skills/sdlc-electron/SKILL.md .claude/sdlc.local.md   # expect no coding-phase hits
```
Then a fresh session rooted in this worktree: run a small change end-to-end and confirm the
ledger is created as `YYYY-MM-DD-<slug>.md` with `ticket: unfiled`, code/commits proceed with
no issue, and the issue is filed (backfilled) only at PR-open.
