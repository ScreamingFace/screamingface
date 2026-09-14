---
title: "Child 02: what the two sources actually disagree about"
ticket: OME-898 (child 2, not yet filed)
status: draft
date: 2026-09-02
---

# Findings

Before specifying anything, here is what the two existing sources say. The ticket asks for a
single source of truth and says `docs/positioning.md` must stop being one. These are the
grounds.

## The two sources

| | `docs/positioning.md` | the mirrored context sources |
|---|---|---|
| where | in the monorepo, 194 lines | a marketplace plugin, five mirrored files |
| currency | "aligned to delivery 2026-07-31" | "canon as of 2026-08-28" and "2026-08-29" |
| authority it claims | "the canonical product-narrative / messaging doc" | "Notion is the source of truth, so this is the authority on what a term means, even when a mirrored deck or Doc is older" |
| who can see it | every engineer with a checkout | only people who have installed the plugin |

Both call themselves canonical. That is the problem in one line.

## Where they disagree

Not stylistic. Each row changes what an engineer would write.

| Subject | The repo doc | Canon |
|---|---|---|
| **personas** | two, named: Rahul the developer as primary, Helen the policy mover as secondary, sourced from a July 2026 newsletter deck | four, in priority order, with Applied ML Researchers and Public Result Builders at top priority. Register differs sharply per persona |
| **the one-liner** | "the engine that runs model ensembles locally, the place to find, prove, and share state-of-the-art model ensembles, with no middleman taking a cut of every call" | "combines the best AI models into fusion models that are more intelligent, cost less, and proves it on a live leaderboard" |
| **the differentiator** | local execution and no middleman, plus "the hub for ensembles" | intelligence per dollar and public verification. Canon explicitly records that differentiating on composition is now contested ground because routing services ship composition features |
| **the word for the thing** | "ensembles" throughout | "fusions". The docs site also says fusions |
| **supported benchmarks** | DRACO, Healthbench, IFEval, MedX, GDPval, ContractEval, and more | draco, ifeval, healthbench, and the healthbench-worst30 variant. Nothing else, and canon warns against describing anything else as supported |
| **claims policy** | an honesty table of shipped against arriving, and "say no middleman on the local path, not free forever" | a claims boundary: no state-of-the-art claim on a benchmark the organisation authored, disclosure in the same sentence when a benchmark is ours, and held-out results described as auditable rather than reproducible |
| **launch state** | gates dated 7 and 14 August, with the public claim marked pending | the August dates have passed |

## What follows

**The repo doc is not merely stale, it is contradictory.** An engineer following it would use
the wrong word for the core object, aim at a persona canon does not list first, lead with a
differentiator canon has stepped back from, and name benchmarks the product does not
support. It is also the only one of the two that a fresh checkout can see.

**This is already leaking into shipped documentation.** The dogfood review of the Client docs
found a benchmark id that is not in canon's list and a headline claim that does not carry the
disclosure canon requires. Both are the predictable result of two sources disagreeing while
only one is visible to whoever is writing.

**Canon is not fully settled either.** The top terminology entry is marked "Needs Review",
and the personas file says the set is still being refined and warns against treating entries
as settled. So the answer is not "canon wins, copy it in". Whatever lands has to carry
status alongside content, or it recreates the same problem one month later.

## The fork this needs decided

Canon lives in Notion, is mirrored into a marketplace plugin, and the plugin installs per
user. Engineers only reliably see the repo. So: how does an engineer get the truth?

| Option | How | Cost |
|---|---|---|
| **A. Pointer only** | the repo carries no positioning content, just a note naming the plugin and telling you to install it | zero drift, but useless to anyone who has not installed it, and useless to a fresh agent session |
| **B. Declared dependency** | the repo declares the marketplace and plugin in its own settings, so every checkout resolves it | no copy, no drift, and it works for agents. Depends on the plugin staying available and on that declaration being honoured |
| **C. Synced mirror** | a script pulls the mirrored files into the repo, stamped with their sync date | visible to everyone with no install. Creates a third copy, and a third copy is what we are trying to stop |

Recommendation is **B**, with `docs/positioning.md` deleted and replaced by a short pointer
that names what replaced it and why. A is not enough for agents, which is the case the ticket
actually complains about. C reintroduces the failure mode.

Not decided here. This needs the owner, because it commits the repo to a dependency on a
plugin.
