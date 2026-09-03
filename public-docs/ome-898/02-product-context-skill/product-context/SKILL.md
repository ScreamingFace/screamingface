---
name: product-context
description: The single source of truth for what ScreamingFace is, what its parts are called, who we write for, and what we are allowed to claim. Use before writing any ticket, documentation page, release note, or copy, and whenever a term, a persona, a benchmark name, or a claim is in question. Supersedes docs/positioning.md.
user_invocable: true
owner: unassigned, see "Keeping this current"
stale_by: 2026-10-02
---

# ScreamingFace product context

Read this before writing anything that a reader outside the team will see, and before
writing a ticket that describes product behaviour.

## How to read the statuses

Every item below carries one. An item with no status is a defect in this file.

| Status | Means |
|---|---|
| **canonical** | settled. Use as written |
| **provisional** | current best definition, not final. Use it, and do not present the wording as settled |
| **open** | contested or unowned. Do not resolve it yourself. Ask the named owner |

Dates are the date of the source that supplied the item, not the date this file was edited.

## What this is

**canonical, 2026-08-29.** ScreamingFace is the open ecosystem for fusing many models into
measurably smarter AI systems, delivering more intelligence per dollar than any single
model. Other tools compose and other boards rank. What ScreamingFace adds is that it
verifies the result in public and hands you the recipe to re-run it yourself.

The name spans the products, the url4 protocol, and the community program.

**The product family, canonical, 2026-08-29.**

| Name | What it is |
|---|---|
| ScreamingFace Toolkit | the Client plus Studio plus a local Engine |
| ScreamingFace Client | the Python library. `pip install screamingface`. Composes models into a fusion, runs a benchmark, returns the score, the bill, and the url4 line that reruns it |
| ScreamingFace Studio | the desktop half of the Toolkit |
| ScreamingFace Engine | the execution engine for url4 recipes. Holds keys encrypted, holds benchmark answer keys, does the grading, and is the only component that talks to a model provider. Same software in three modes: local, community-hosted, institutional. Only the engine URL changes |
| Leaderboard | the verified board. A submission is validated, deduplicated by content hash, and independently re-run before it ranks |
| url4 | the grammar for expressing a composition, in one line |

**Casing matters.** The product names above are capitalised. `url4` is always lower case,
including at the start of a sentence.

## Terminology

**Lead term, canonical, 2026-08-29.** A **fusion** is the lead category noun. It is a
composed AI system built from many models used together for greater accuracy, speed, or
lower cost than any single member.

**A fusion is a system, never a "fusion model".** We train no models, and claim language
must not imply that we do.

**ensemble** is canonical too, as the technical synonym, for research, documentation, and
academic contexts. Fusion is the public, marketing-first term. Decided 2026-08-10. So a docs
page saying "ensemble" is correct; a launch post should say fusion.

| Term | Status | In brief |
|---|---|---|
| fusion | canonical | the lead noun. A composed system, not a model |
| ensemble | canonical | technical synonym, for research and docs registers |
| url4 | canonical | the one-line grammar for a composition. Always lower case |
| Benchmark | provisional | the exam: prompts plus grading criteria. Not the software that runs it |
| Evaluation harness | provisional | the proctor: the software that runs the exam. "eval harness" is fine in developer registers, "evaluation harness" in institutional ones |
| Leaderboard | provisional | the verified board. Re-run before ranking |
| SOTA | provisional | the best published result on a benchmark. A fusion is SOTA outright when it beats every single model including frontier models |
| Pareto-frontier SOTA | canonical | the best result at its cost. A fusion can hold this without being SOTA outright: worse than the top model, cheaper and better than anything at its price |
| Market blindness | canonical | nobody can see what intelligence costs or delivers for a task. This is the antagonist of the story |
| Neighbor | canonical | one of five kinds of adjacent tool. A kind, never a named company |
| Network-Sourced AI | provisional | vision-tier term. Intelligence composed live over a network. See the caution below |
| Reasoning routing | provisional | which models answer |
| Context routing | provisional | which knowledge is consulted |
| BYOK | provisional | bring your own key. The user supplies their own provider credentials |
| DRACO | provisional | the third-party public research benchmark we reproduce first. Not created by us |
| Fusion Monsters | provisional | the community program. The people, never the product. The external name is not final |
| STUB submissions | provisional | fake leaderboard entries used to test the board |

**Two cautions.**

Network-Sourced AI is the parent organisation's vocabulary. Make the ScreamingFace case on
fusions, verification, and intelligence per dollar. Leave the network-sourced framing to the
parent's own voice.

A neighbor is a kind of tool, never a company. Never attack an incumbent; adjacent tools
existing validates that composition matters.

## Who we write for

Four personas, in priority order. **provisional, 2026-08-28**: the set is still being
refined, and each entry is the current best definition rather than settled.

Identify which one the work is for, then match its register. The registers differ sharply,
and a community post, a researcher-facing result, and a consumer explainer are not the same
voice.

| Priority | Persona | Register | Surfaces they touch |
|---|---|---|---|
| 0, top | Applied ML researchers and public result builders | neutral and rigorous, academic or governmental | Client, Leaderboard, Studio, Fusion Monsters, Engine |
| 1, high | Technical developers and benchmark enthusiasts | direct and technical | Studio, Client, Leaderboard, Fusion Monsters, url4 |
| 1, high | Current or aspiring AI researchers | fully playful, community | Client, Leaderboard, Studio, Fusion Monsters |
| 1, high | Everyday AI users and general token payers | plain-language consumer | Leaderboard, Reports, the website |

**The top persona in one line.** Give me a credible baseline, an inspectable fusion, and a
fair way to submit and publish, so I earn public credit for work that survives scrutiny.

What they need to believe, and therefore what documentation for them must supply: the
benchmark and baseline are named and meaningful; the result is reproducible or its limits are
explicit; they can inspect and change enough of the recipe to make a defensible
contribution; the verification, submission, and attribution rules are clear before they
invest time; and the cost and key requirements are known up front.

If the work addresses someone outside these four, say so rather than forcing a fit.

## What we may claim

Rules, not argument. Each one is a gate on published copy.

| Rule | Status |
|---|---|
| No state-of-the-art claim on a benchmark we authored | canonical, 2026-08-28 |
| A result on a benchmark we authored or host names that fact in the same sentence as the result | canonical, 2026-08-28 |
| Results on held-out benchmarks are described as **auditable**, never reproducible. The url4 line is reproducible; a held-out score is auditable | canonical, 2026-08-28 |
| Results on privately held benchmarks publish as measurements, named with their owner and method | canonical, 2026-08-28 |
| We build a board only where no authoritative one exists | canonical, 2026-08-28 |
| The one thing we publish is the recipe | canonical, 2026-08-28 |
| A SOTA claim carries "no new models trained" in the same breath in safety-adjacent contexts | provisional |
| Never imply we train models. A fusion is a system | canonical |
| Disclosure about the parent organisation: do not lead with the connection; if asked, the answer is a plain factual yes | canonical, 2026-08-28 |
| No performance or accuracy claim without its methodology and conditions | canonical |

**Benchmark scores need provenance.** Two things a number does not reveal: who chose the
benchmark, and whether the system was tuned to it. A shared board where everyone is measured
on the same benchmarks answers the first. It does not answer the second. Do not collapse
selection, optimization, and contamination into "benchmarks are gamed"; they are three
failure modes with three remedies.

## What ships

**For benchmark ids the code is the authority, not this file and not canon.** Canon itself
says product facts belong to the product owners, and this was tested: canon's list omits
`draco-3pass`, while the engine defines it and carries a dedicated test for its definition.
Canon was behind. Verify an id against the engine before writing it into copy.

**Benchmark families, canonical as of 2026-08-28, verified against the engine 2026-09-02:**
`draco`, `ifeval`, `healthbench`.

| Id | Status | Note |
|---|---|---|
| `draco` | canonical | the deep-research benchmark. A third-party benchmark, not authored by us |
| `draco-3pass` | canonical, code-verified | defined in the engine with its own test. Absent from canon's list, which is behind |
| `ifeval` | canonical | instruction following |
| `healthbench` | canonical | the family |
| `healthbench-worst30` | canonical | the variant. Spelled with a hyphen, not `healthbench/worst30` |

Anything not listed here is not a supported benchmark. Entries visible on a hosted board that
are not in this table are leftovers and must never be described externally as supported.

**The lite variant is `draco-lite`** (owner, 2026-09-03). Use that name in copy.

**Open:** the code and the docs do not agree with it. The engine carries `draco-3pass` with
its own definition test, the Client docs advertise `benchmark="draco-3pass"` in four places,
and canon's list has neither. `draco-lite` appears only as `draco-lite@1` in a July task
mirror and in a notebook filename, `05_draco_lite_e2e.ipynb`, which a live docs page links to
and which is no longer in the examples directory.

So three sources give three answers, and this file is not the place that settles it. Owner:
whoever owns the supported-benchmark list. Until then, write `draco-lite` per the line above
and do not assume the engine id matches it.

**Open, 2026-09-02:** canon names DRACO twice with different provenance, once as a
third-party benchmark explicitly not created by us, and once as a board we would build and
own. The claims rules about self-authored benchmarks apply only to the second. Which one a
given result refers to has to be settled before a claim about it is published. Owner: brand.

## What is unsettled

Do not resolve these. They are recorded so nobody has to rediscover them.

| Item | Status | Owner |
|---|---|---|
| The ScreamingFace one-liner says we combine models into "fusion models", while the Fusion entry forbids exactly that phrase and the claim it implies. Canon contradicts itself on the core term | **open** | brand |
| Public claim language for benchmarks we authored has not been approved | **open** | claims |
| The external name of the community program is not final | **provisional** | brand and GTM |
| The persona set is still being refined | **provisional** | brand |
| The top terminology entry is marked as needing review | **provisional** | brand |
| Whether the token-buyer audience is covered by the researcher personas | **open** | brand |

## Not in this file

**Two sections of the source are marked "do not put in public copy"** by the people who own
it: a strategic question under reasoning routing, and one under context routing. They are
deliberately absent. This file is in a public repository.

Also absent, pending a named approval: claim language recorded as unapproved, quotes
attributed to named individuals from private discussion, and benchmark authorship and funder
material. None of it is needed to write documentation.

**Elsewhere by design:** colour, type, spacing, and component-level copy belong to the design
system. Page shape and prose craft belong to the documentation-writing skill. Launch
sequencing and shipped-state reporting belong to their own documents.

## Keeping this current

This file is a copy. It does not sync, so it goes stale when the sources change.

- **Owner: unassigned.** This needs one named person, not a team. Until it is filled in,
  treat every date above as the only signal of freshness.
- **Refresh trigger:** at each release, and whenever a positioning document or the
  terminology database changes materially, whichever comes first.
- **Stale-by** is in the frontmatter. An expired date is a prompt to refresh, not a reason to
  stop using the file.

## Sources

Read once as material, on 2026-09-02, and not depended on at runtime:

| Source | Stamped |
|---|---|
| terminology database, 26 entries | canon as of 2026-08-29 |
| target personas, four entries | canon as of 2026-08-28 |
| product-positioning document | source edited 2026-08-28, mirrored 2026-08-31 |
| brand-positioning document | via the terminology entries that cite it |

Where this file and those sources disagree, they are newer. Refresh rather than arguing with
this copy.
