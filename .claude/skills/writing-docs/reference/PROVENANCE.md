# Provenance

What this skill is built from, under what terms, and what was considered and left out.

## Distilled sources

| Source | Author | Licence | Retrieved | Used in | How |
|---|---|---|---|---|---|
| Diátaxis, the four-document framework | Daniele Procida, `diataxis.fr` | not stated on the site or its colophon (checked on retrieval) | 2026-09-02 | `divio.md` | described in our own words; no text reproduced |
| humanizer | `github.com/blader/humanizer` | MIT | 2026-09-02 | `prose-tells.md` | pattern list reorganised into rule-and-replacement form, then extended |
| documentation reviewer prompt | supplied by the owner of this skill | internal | 2026-09-02 | `review-angles.md`, `diagrams.md` | de-specified: one product, one reader, and one metric set removed and replaced by context slots |

Because the Diátaxis licence is unstated, `divio.md` paraphrases the framework and cites it
rather than copying any of its wording. If the licence is later published and permits
reproduction, that file can be tightened against the original.

## Drift check

Each distilled source can move. To check whether this skill has fallen behind:

| Source | Check | Expected |
|---|---|---|
| Diátaxis | re-read `diataxis.fr` and compare the four types and their definitions against `divio.md` | four types, same distinctions |
| humanizer | re-read its pattern list and diff against the four tables in `prose-tells.md` | every upstream pattern has a row, or a recorded reason it does not |
| reviewer prompt | compare against `review-angles.md`: three passes, nine rubric items, the trust check, the output order | all present, none carrying a product name |

Run the drift check when a source publishes a new version, and record the date here.

## Survey: what else was considered

The brief asked for a look at other documentation skills worth pulling from. Candidates are
recorded by role rather than by name, so that this file stays free of any one organisation's
vocabulary. The named detail lives in the work item that commissioned the skill.

| Candidate | Verdict | Reason |
|---|---|---|
| a house content-writing skill (voice, AI-tell scrubbing, terminology, personas, revision passes) | **not referenced; duplication accepted** | this skill stays independent by decision. Where its prose rules restate rules such a skill also carries, the duplication stands, because a skill that only works properly alongside another one is not independent. Its audience-first principle is adopted on the merits: the reader is fixed before any prose. |
| a product-context skill (product facts, personas, positioning, freshness ranking) | **pattern adopted** | the idea that product facts and personas are loaded rather than assumed became the context contract in `SKILL.md` §1. |
| a design-system skill (tokens, brand assets, component copy) | **boundary drawn** | component-level copy belongs to whatever design system a project runs. This skill governs body prose. |
| publishing and distribution skills | **out of scope** | they move a finished document; they say nothing about how it is written or shaped. |
| a single-purpose content skill (event material, cheat sheets) | **rejected** | one document type, not documentation architecture. |
| a skill-authoring template and contribution skill | **used as process, not content** | governs how a skill is added to a marketplace, not what belongs in this one. |

**The finding that shaped this skill:** nothing surveyed covers documentation architecture.
No page-type model, and nothing on when a concept needs a diagram. That gap is what this
skill fills, and it carries page types, page shaping, diagrams, and the review procedure in
full.

It runs standalone by design, not as a fallback. It references no other skill, and every
reference file is complete on its own. With nothing loaded, the prose rules apply in full and
the review still runs, with the unavailable slots reported as unknown.

The accepted cost of that independence: where a rule here also exists in some other skill,
the two copies can drift apart, and the drift check above is the only thing watching.

## Changes from use

Findings from running the skill, recorded so the reason for each rule survives.

| Date | Change | Why |
|---|---|---|
| 2026-09-02 | `review-angles.md`: added the rule for when the examples cannot be run | The first real review ran in an environment with no runtime, and the file said only "run the code". A reviewer following it literally either stalls or quietly implies they ran something. The rule now names what to check instead. |
| 2026-09-02 | `prose-tells.md`: added the rule on parallel implementations in tabs | A second review, on a set documenting one SDK in two languages, found three divergences that a tabbed layout hid: a unit difference, an availability difference, and a call-signature difference. Only the first was stated. The page-type model does not reach this, because the defect is the layout asserting parity rather than the page being the wrong type. |

## Agnosticism

No product name, organisation name, repository path, or design-system name appears in this
skill, including this file. Every project-specific input arrives through the context slots
listed in `SKILL.md` §1. Adding a name here, however convenient, turns a reusable skill into
one project's skill wearing a general label.
