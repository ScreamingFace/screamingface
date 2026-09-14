---
title: "product-context: a single source of truth for product and brand"
ticket: OME-898 (child 2, not yet filed)
findings: ./findings.md
status: draft
date: 2026-09-02
---

# product-context

A repo skill that answers, for anyone writing a ticket, a docs page, or any copy: what is
this product, what do we call its parts, who are we writing for, and what are we allowed to
claim.

It exists because there are two answers to those questions today and they disagree.
`docs/positioning.md` sits in the repo, is three weeks stale, and contradicts the marketing
canon on seven counts, including the word for the core object. The canon is correct and
almost nobody has it, because it installs per person. Engineers and agent sessions see only
the repo, so the repo's wrong answer is the one that gets used. `findings.md` has the
evidence.

**Name.** `product-context`, not `screamingface-context`. The marketplace already has a skill
by that name, and two skills with one name is the confusion this unit is meant to end.

## 1. Non-goals

- **Not a dependency on the marketplace skill.** No install, no import, no deferral. Its
  mirrored files were read once as source material, the way a spec reads any source. Where
  content overlaps, the duplication is accepted (owner, 2026-09-02).
- **Not an arbiter.** Where canon says a fact is owned by a named person, this skill records
  the fact, the owner, and the date. It does not decide.
- **Not a sync target.** No script pulls from Notion. See §6 for what replaces that.
- **Not brand visual law.** Colour, type, and component copy stay with the design skill.
- **Not a launch plan or a status report.** Those are separate documents with separate
  lifetimes.

## 2. Everything in it is public

Decided by the owner, 2026-09-02: the content is publishable, and the skill lands in the
public monorepo.

That is a change of posture, not just a move, so it is worth stating what becomes public:
the terminology and its status, the personas and their registers, the positioning line and
what it replaced, the claims boundary, the supported benchmark list, and the relationship
disclosure policy.

**Three items need a named yes before merge, not before writing.** They are not ours to
publish and publishing them cannot be undone:

| Item | Why it needs a yes | Who |
|---|---|---|
| claim language canon records as not yet approved | publishing unapproved claim wording makes it look approved | whoever owns claims |
| quotes attributed to named people, with dates, from private Slack | attribution of private discussion to individuals | the people quoted |
| benchmark authorship and funder material | commercial and partner sensitivity | brand and product owners |

The rest can be written and reviewed without waiting. If a yes does not come, those three
are dropped and the skill still stands, because none of them is needed to write a docs page.

## 3. What it contains

Organised by what a reader needs, and shaped so the documentation skill can pull from it.
That skill declares slots; this content has to be findable as those slots rather than as a
narrative.

| Section | Contents | Fills |
|---|---|---|
| **What this is** | the one-line positioning, and the product family with each part named | product facts |
| **Terminology** | every canonical term, its definition, its exact casing, and terms we avoid | terminology casing |
| **Who we write for** | the personas in priority order, each with its register, goals, and pain points | the reader |
| **What we may claim** | the claims boundary, the disclosure rules, and the words reserved for narrower meanings | positioning language, target voice |
| **What ships** | the supported benchmark list, and what must not be described as supported | product facts |
| **What is unsettled** | every item whose status is provisional or whose owner has not signed off | all of the above |

**Every item carries a status.** Canonical, provisional, or open. Canon's own top terminology
entry is marked as needing review and its persona set is described as still being refined,
so a skill that presents all of it as settled would be wrong on its first day. An item with
no status is a defect.

**Every item carries a date and an owner.** Not a general provenance note at the bottom. Per
item, because they go stale at different rates and are owned by different people.

## 4. What gets retired

The ticket says skills plural and gives one example. This is the enumeration, with evidence.

| File | Last touched | Verdict | Why |
|---|---|---|---|
| `docs/positioning.md` | 2026-08-10 | **delete**, replace with a pointer | claims to be canonical, contradicts canon on seven counts, and references `narrative-funnel-chapter-guide.md`, which does not exist |
| `docs/screamingface-v1-launch-plan.md` | 2026-08-10 | **needs an owner's call** | its gates are dated 7 and 14 August and have passed. Either archive it or restate it |
| `docs/scream-lisbon-digest.md` | 2026-08-10 | **keep, mark dated** | a point-in-time event digest. Correct as a record, wrong as guidance. Say which it is at the top |
| `docs/PROJECT-OVERVIEW.md` | 2026-08-10 | **needs an owner's call** | `positioning.md` names it the "companion of record for what's shipped", and it is three weeks old. Whatever replaces that role must be current or must stop claiming the role |
| `docs/ISSUES.md` | 2026-08-10 | **needs an owner's call** | same, cited for verified shipped state |
| `.claude/README.md`, product-context section | 2026-07-08 | **replace with a pointer** | says "Team: TBD, to be settled in the next couple of days (2026-07-08)", and uses "Ensemble" where canon says fusion |

`positioning.md` is the only outright deletion. The rest either get a dated header or a
decision from whoever owns them, and this spec does not pretend to make those calls.

**The pointer that replaces `positioning.md`** names the skill that supersedes it, the date,
and the reason, so anyone arriving via an old link learns where truth moved rather than
finding a blank.

## 5. What this fixes downstream

Two defects already shipped because the wrong source was the visible one. Both were found by
the documentation review in child 01, and both are symptoms rather than causes:

- a benchmark id advertised on the docs site that is not in canon's supported list
- a headline result carrying no disclosure, against a rule requiring it in the same sentence

Neither is fixed by this unit. They are fixed by whoever owns the docs, using this skill.
Listed here so the connection is on the record.

## 6. Staying current without a sync

There is no script, so the copy goes stale when Notion changes. Two things instead:

- **A named owner** for the skill, whose job is the refresh. Not "the team".
- **A stated trigger**: refresh at each release, and whenever a positioning document or the
  terminology database changes materially. Whichever comes first.

**A stale-by** date at the top of the skill, so a reader can see the content has aged rather
than having to guess. An expired date is not a failure, it is a prompt.

This is the accepted cost of independence. Stated plainly here so nobody is surprised by it
later.

## 7. Decisions

Owner, 2026-09-02:

- **Everything is publishable**, and the skill lands in the public monorepo. §2 lists the
  three items that still need a named yes before merge.
- **Independent of the marketplace skill.** Content copied, not referenced. Duplication
  accepted.

Recorded so they are not re-opened:

- **It lives in this monorepo**, because the ticket's complaint is that engineers see only
  repository skills. Unlike child 01, this content is product-specific, so the repo is its
  natural home.
- **Named `product-context`** to avoid colliding with the marketplace skill's name.
- **Status per item, not per document.** Canon is partly provisional, and a skill that hides
  that inherits the problem it was built to fix.
- **`positioning.md` is deleted rather than edited.** Editing it keeps a second canonical
  document alive, which is the thing being removed.

## 8. Acceptance

- The skill exists in the repo, with a description and a stale-by date, and it loads without
  the marketplace plugin installed.
- Every item carries a status, a date, and an owner. An item missing any of the three is a
  defect.
- Terminology gives exact casing for every product name, including the core object, and lists
  the terms we avoid.
- Personas appear in priority order, each with its register, and each readable as "the
  reader" by the documentation skill.
- The claims boundary and the disclosure rules are stated as rules, not as argument.
- The supported benchmark list is present, with the note about what must not be described as
  supported.
- `docs/positioning.md` is gone and a pointer stands in its place naming what superseded it.
- Every file in §4 is either changed, dated, or listed with a named person who owes a
  decision.
- The three items in §2 are either published with a recorded yes, or absent.

## 9. Verification

- Ask the skill, with the marketplace plugin not installed, what the core object is called.
  It answers with canon's word, not the old one.
- Ask it which benchmarks are supported. It gives canon's four and no others.
- Ask it who the primary reader is. It gives canon's top-priority persona, not the one from
  the retired doc.
- Ask it whether a state-of-the-art claim can be made on a benchmark we authored. It says no
  and names the rule.
- Ask it something canon marks provisional. It answers and says the status is provisional.
- Re-run child 01's context-loaded review against this skill instead of the mirrored files.
  Its slots fill from this content with no hand-assembly. If they do not, that is a finding
  about one of the two.
- Grep the repo for the retired doc's path. Every reference either goes to the pointer or is
  updated.
