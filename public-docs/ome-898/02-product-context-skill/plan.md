---
title: "product-context: implementation plan"
ticket: OME-898 (child 2, not yet filed)
spec: ./spec.md
findings: ./findings.md
status: draft
date: 2026-09-02
---

# product-context: implementation plan

Builds the skill in `spec.md`. Unlike child 01, this lands in this monorepo, because the
content is product-specific and the ticket's complaint is that engineers see only repository
skills.

## Where the work happens

The repo is public and protected, so this needs a work item, a worktree, a branch, and a PR.
None of that exists yet. So the skill is built here in the staging directory first, reviewed,
and moved into a worktree when the child issue is filed. Nothing is written into the shared
checkout on the way.

## Steps

**1. Read every canonical source in full.**
Five mirrored files: terminology, personas, positioning, the strategy document, and the
deck. Two have been read in part; the rest have not. Record the sync date stamped on each,
because those dates become the per-item dates in the skill.

**2. Reconcile against what actually ships.**
Canon is a marketing artifact and can lead or lag the code. For each product fact, check the
repo: the package name, the module surface, the benchmark identifiers the engine publishes,
the app names. Where canon and the code disagree, record both and mark the item open rather
than picking a winner. The benchmark list is the one to be most careful with, because the
docs site already advertises an id canon does not list.

**3. Write the six sections.**
What this is, terminology, who we write for, what we may claim, what ships, what is
unsettled. Each item gets a status, a date, and an owner. Shape the personas so they read as
"the reader", and the claims material as rules rather than argument, because that is what the
documentation skill pulls.

**4. Add the stale-by date and the refresh trigger.**
At the top, with the named owner. An expired date is a prompt, not a failure.

**5. Quarantine the three items that need a yes.**
Write them, keep them out of the skill until the yes lands, and record who owes it. Do not
merge them by default.

**6. Retire `docs/positioning.md`.**
Delete it and leave a pointer naming the skill that superseded it, the date, and the reason.

Six files reference its path, and they split two ways:

| Reference | Action |
|---|---|
| `docs/scream-lisbon-digest.md` | live guidance, update the reference |
| `docs/screamingface-v1-launch-plan.md` | live guidance, update the reference |
| `docs/tasks/2026-07-31-OME-717-*` | historical, leave alone |
| `docs/work/2026-07-31-OME-717-*` | historical, leave alone |
| `docs/work/2026-08-22-OME-936-*` | historical, leave alone |
| `docs/work/2026-07-28-OME-655-*` | historical, leave alone |

Task mirrors and work ledgers are records of what was true when they were written. Rewriting
them to point at a document that did not exist yet falsifies the record. The pointer left in
place of the deleted file is what keeps those links meaningful.

**7. Handle the other five stale files.**
Two get dated headers. Three need a decision from whoever owns them, so open those as
questions with named people rather than editing them. Do not quietly rewrite someone else's
document.

**8. Checks.**
No dashes. Every item has status, date, and owner. The skill loads with the marketplace
plugin absent. No reference to that plugin as a dependency.

**9. Re-run child 01 against it.**
The context-loaded review currently runs against the mirrored files read by hand. Redo it
against this skill. If 01's slots do not fill without hand-assembly, that is a finding about
one of the two, and the point of doing them in this order.

## Verification

The nine checks in `spec.md` §9. The three that decide it:

- **Ask it the name of the core object with nothing else installed.** It answers with
  canon's word. If it says the retired doc's word, the whole unit failed.
- **Ask it which benchmarks are supported.** Canon's four, no others.
- **Ask it something canon marks provisional.** It answers and says the status is
  provisional. A skill that presents provisional material as settled has inherited the
  problem it was built to remove.

## Sequence

```
1 read sources -> 2 reconcile with code -+-> 3 write sections -> 4 stale-by -> 8 checks -> 9 re-run 01
                                         +-> 5 quarantine (blocked on named yes)
                                         +-> 6 retire positioning.md
                                         +-> 7 the other five files (three blocked on owners)
```

Steps 5 and 7 have external blockers and must not hold up 3, 4, 6, 8, and 9. The skill ships
without the quarantined items.
