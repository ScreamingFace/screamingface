---
title: "writing-docs: implementation plan"
ticket: OME-898 (child 1, not yet filed)
spec: ./spec.md
status: draft
date: 2026-08-20
---

# writing-docs: implementation plan

Builds the skill described in `spec.md`. Nothing in the deliverable names a product, an
organisation, or a repository. Everything specific arrives through the context contract.

## Where the work happens

The work item is a Linear `OME-N` issue, so its spec, plan, and ledger belong to this
monorepo's artifact trail. The skill itself does not: it is authored standalone and
installed as a plugin. Worth stating plainly, because the worktree-per-unit rule applies to
a repository this unit does not write to. The branch and PR happen where the skill lives.
The ledger and this plan stay here.

## Steps

**1. Survey candidate sources.**
Look at what documentation skills already exist: the divio skill, the humanizer repository,
and anything else worth pulling from. Output is a table in `reference/PROVENANCE.md` with
each candidate marked adopted or rejected, and a reason. This is what makes the survey
finish instead of running indefinitely.

**2. Check licences.**
For every source that gets distilled, record the licence and the attribution line in
`PROVENANCE.md` before any of its content is written down. Distilled rules with credit, not
copied text. Add a drift check per source, so a later divergence is detectable.

**3. `reference/divio.md`.**
The four modes, each with who the reader is and what breaks when the page mixes modes. The
one-page-one-mode rule, and the remedy: split, do not balance.

**4. `reference/prose-tells.md`.**
The `NEVER` / `INSTEAD` tables, craft rules only. Every prohibition gets a replacement,
because a rule with no replacement gets ignored under deadline. State at the top that the
file is authoritative on its own and defers to nothing, and that duplication with a house
writing skill is accepted rather than avoided.

**5. `reference/diagrams.md`.**
The table of concepts that need a picture, the four hard rules, how to specify a missing
diagram, and paste-ready starting points for each diagram type.

**6. `reference/review-angles.md`.**
Distil the owner's reviewer prompt into three passes, the nine-item scorecard with anchors,
the trust check, the output format, and the review rules. The de-specification is the work
here: the source prompt carries one product, one reader persona, and one metric triad, and
each of those becomes a contract slot rather than text in the file.

**7. `SKILL.md`.**
In this order: the two modes; load the context; pick the page type first; shape the page;
decide what to draw; write the prose; then the review flow and what the skill does not
cover. Frontmatter carries `description` and `user_invocable: true`.

**8. Checks.**
Grep the whole skill, `reference/` included, for product names, organisation names,
repository paths, and design-system names. Then grep for em-dashes and en-dashes. Then check
that no reference file depends on another skill being loaded. All three expect zero hits. These run before review rather than after, because they are the checks
that caught two coupling leaks and a punctuation breach in the drafts.

**9. Ship it.**
Land the skill, then confirm it installs through the host's plugin mechanism and is
invocable as `/writing-docs`.

## Verification

Run the checks in `spec.md` §9. The three that decide whether it is finished:

- **With nothing loaded**, the skill produces structure, prose, and diagram guidance and
  refuses to assert product claims, reporting the reader and metric slots as unknown. If it
  invents a claim here, it is not done.
- **With a context skill loaded**, that project's reader, metrics, and terminology are
  applied, and none of its specifics appear inside the skill.
- **Against a project in a different domain**, nothing in the output assumes the first
  project.

The rest is dogfooding: pick a real page that mixes modes and check the skill catches it,
then run the full review against a real documentation set to confirm it yields a friction
log with quoted locations and a paste-ready diagram rather than adjectives.

## Adoption here

Deliberately not part of this unit. Installing the plugin and adding the routing note is
`.claude/` work, and the epic already has a child that owns the `.claude/` flow. Folding it
there keeps this unit from reaching into a product repository, which is the whole point of
building the skill standalone.

## Sequence

```
1 survey -> 2 licences -+-> 3 divio ---------+
                        +-> 4 prose tells ---+
                        +-> 5 diagrams ------+-> 7 SKILL.md -> 8 checks -> 9 ship
                        +-> 6 review angles -+
```

Steps 3 through 6 are independent and can be written in any order. Step 7 wants all four.
