---
title: "writing-docs: dogfood results"
ticket: OME-898 (child 1, not yet filed)
spec: ../spec.md
plan: ../plan.md
review output: ./public-docs-review.md
status: draft
date: 2026-09-02
---

# Dogfood results

The record of the exercise. What was run, what it proved, what it changed. The findings
about the documentation set itself are a separate document, `public-docs-review.md`.

## Setup

| | |
|---|---|
| Skill under test | `writing-docs`, as built in `../writing-docs/` |
| Installed at | `~/.claude/skills/writing-docs/` |
| Target | the Client documentation site, at the commit its own sidebar names, `90a104e3` |
| Reader path | landing page, Overview, Installation, Your first fusion, plus the navigation tree and router |
| Reader, goal, time budget | senior researcher composing multiple models, install to a working composition, 30 minutes |
| Runtime available | none. No Python, no credentials, no network to a provider |
| Runs | two: one with no context skill loaded, one with the project's canonical terminology loaded |

Two runs rather than one, because the difference between them is the thing the spec's
verification section actually asks about.

## Verification results

Against `spec.md` §9.

| Check | Result | Evidence |
|---|---|---|
| names a mode conflict on a page that mixes types and proposes the split | **pass** | Installation is filed under Tutorials and is roughly forty percent reference and troubleshooting. The skill proposed moving the seven-item FAQ to a how-to rather than trimming it |
| produces a friction log with quoted locations and at least one paste-ready diagram | **pass** | sixteen friction entries, each with a file and line, and three Mermaid diagrams using the site's own terms |
| with nothing loaded, produces guidance and reports unknown slots rather than inventing | **pass** | six of nine slots reported unavailable at the top of the report, and every product statement marked as a claim the docs make rather than a verified fact |
| with a context skill loaded, applies it and keeps its specifics out of the skill | **pass** | the second run produced three findings the first could not reach. Nothing from the project entered the skill: the name and dash checks still return zero |
| review angles usable by someone who did not write them | **not run** | needs a second person |
| runs against a project in a different domain | **not run** | see gaps below |

## What the two runs proved about the context contract

The no-context run found structure, ordering, terminology drift internal to the docs,
missing example outputs, and missing diagrams.

The context-loaded run found a possible claims-policy breach, a benchmark id absent from the
canonical supported list, and a word the project has explicitly reserved for a narrower
meaning.

Neither run found the other's findings. That is the strongest evidence from this exercise
that the contract belongs in the skill rather than being an optional extra, and that a docs
review run with nothing loaded should not be called finished.

It is also evidence the degradation path works as specified. The first run had every
opportunity to guess at the product's claims policy and did not.

## What the exercise changed in the skill

| Change | Reason |
|---|---|
| `review-angles.md`: a rule for when the examples cannot be run | The rule said only "run the code". This run had no runtime, so a reviewer following it literally would either stall or quietly imply they ran something. It now says to mark examples unverified and names four things checkable without running anything |
| `PROVENANCE.md`: a "changes from use" table | So the reason behind a rule survives the person who added it |

One change from one run is a low yield, which is itself informative: the skill's content
held up under first contact better than expected. The next two runs are the ones that will
say whether that holds.

## Highest-value findings handed back

Full list in the review. These three are the ones that need a person rather than an edit:

1. **The claims-policy question.** Canon requires a result on a self-authored benchmark to
   name that fact in the sentence naming the result, and bars a state-of-the-art claim on
   such a benchmark. The Overview's headline result carries no such disclosure, and a
   navigation entry reads "Reproduce DRACO state-of-the-art". Flagged, deliberately not
   rewritten.
2. **An advertised benchmark id that canon does not list.** Either canon is behind a shipped
   variant or the docs advertise something unsupported. Someone who knows which needs to say.
3. **"Reproducible" against "auditable".** Canon reserves the second word for held-out
   results. Two adjacent Overview bullets claim the first.

Everything else is a docs edit: the Quickstart naming, the missing tutorial outputs, the
invitation gate placement, the provider-keys contradiction, the Installation split, the three
diagrams, one benchmark on the reader path, the install check, a stability statement, and 43
em-dashes across 18 of 37 pages.

## Gaps in this exercise

- **No execution.** No example was run. Every code finding is a consistency finding, and the
  review says so rather than implying otherwise.
- **Four pages, not the whole set.** The reader path only. The API reference tab, the learn
  section, and the guides were not read, so the review says nothing about them. A full sweep
  would likely raise more terminology drift, since that is what drift does.
- **One reader.** The scorecard is scored for a researcher evaluating adoption. A different
  reader, for instance someone maintaining an existing integration, would score reference
  navigability and stability differently.
- **Single reviewer.** The review angles were run by the same party that wrote them, which is
  the weakest possible test of whether they are usable by anyone else.
- **Different-domain run outstanding.** Until the skill is run against a documentation set
  from another domain, the claim that it is product-agnostic rests on the name and dash checks
  rather than on evidence.
