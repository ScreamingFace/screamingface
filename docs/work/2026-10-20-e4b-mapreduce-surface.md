---
ticket: OME-1653
stack: screamingface
status: planned
started: 2026-10-20
finished:
---

# e4b-mapreduce-surface — replace the recipe surface with map → select → reduce

## Intent

The Product Owner proposed a map → select → reduce grammar for recipes (notebook
`e4b-combine-mapreduce.ipynb`, 2026-10-20). The owner took it with no backward compatibility, put
it on top of PR #1461 so the E4b stack merges with the final surface, and added an Engine narrow
step so a narrow step can come before a reducer.

## Planned changes

- See the plan: `docs/plan/2026-10-20-e4b-mapreduce-surface.md` §2 (units 0–8).

## Test plan

- See `docs/spec/2026-10-20-e4b-mapreduce-surface/test-plan.md`.

## Acceptance

- The 13 notebook cases and the part 2–7 recipes run in the new form; the parity set compiles to
  today's bytes except the planned changes (overview §4); `Filter >> Mean` and `Rank >> Vote` run
  in one combine call; the old names are gone; all gates green.

## Log

- 2026-10-20: owner answers A0–A5 (overview §5). Five scouts mapped the compile path, the url4
  rebuild and UI, the Engine combine spec, the public surface, and the test, docs and template
  scope. Spec and plan written (unit 0).
- 2026-10-20: Opus spec review → ESCALATE (4 blocker, 11 major, 7 minor). All 22 findings applied:
  private `_surface` staging + one swap unit (12); `ReduceNode` kept internal as the `over=`
  extractor target (1); pinned `name@v` ids in `over=`/`normalize=` (10); Engine judged set for
  `scores@1` after narrow (2); the one-step places listed (3); member-row rules (4); `NR-C1` refuses
  narrow before Merge/JudgePick/model-fallback Gate (5); one judge per block incl. JudgePick (6); no
  associativity claim (7); corrective loops stay root (8); `First` keeps today's equals rule (9);
  `Node` names for every internal class (11); 4 Engine `test_sdk_*` files in the migration (13);
  O13 message rewording + MSG-1 (14); rg check scope (15); minors 16–22.
- 2026-10-20: second Opus review → PASS WITH FIXES. Applied: `judged` = `present` before any
  narrow step; LO-0 (`lower()` is the identity on old values until the swap) and LO-5 only for a
  closed block; private `_narrow` carrier; one lowering point for every recipe entry; unit 6
  rebuild through `_surface.rebuild` with an exec namespace, judge round trips + RB-2 in unit 7;
  one snapshot statement; fixture list; CH rows moved to the units that add the steps; narrow
  record `signal` + `scores`; EX-2 sentinel; MSG-1 by an `ast` scan with an allow list; CH-14;
  O14/GA-6 (gated vote with an extractor `over=` refused; owner choice open).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
