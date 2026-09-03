---
title: "writing-docs: different-domain verification run"
ticket: OME-898 (child 1, not yet filed)
results: ./RESULTS.md
status: draft
date: 2026-09-02
---

# Different-domain run: the SyftHub SDK documentation

Purpose is verification, not a commissioned review: does the skill produce useful findings
on a documentation set it was not written for, without leaning on anything from the first
project?

Target: the SDK section of the Syft Space Hub docs site. Reader path is the section's own
Getting Started order, plus its navigation tree.

**Caveat on how different this is.** The first target was ported from this codebase, so the
two share chrome, layout components, and navigation shape. This tests a different product,
a different reader, and a different domain. It does not test a different framework or a
different organisation. Findings marked *inherited* appear in both sites and may come from
the shared lineage rather than from independent decisions.

## Context slots

None available. There is no context skill for this product, and this reviewer knows nothing
about it beyond what the pages say.

| Slot | Available |
|---|---|
| the reader | **no**. Inferred from the section itself: a developer integrating an SDK. Stated as an inference, not a fact |
| the time budget | **no** |
| operational metrics | **no** |
| product facts, terminology casing, positioning | **no** |
| house voice, target voice, house writing skill | **no** |

So nothing below asserts what the product is or does. Every product statement is what the
page claims.

## Findings

**1. Installation is filed as onboarding and is almost pure reference.** The navigation puts
it under "Getting Started", between Overview and Quick Start. The page contains an
environment-variable table, a constructor with every optional parameter enumerated in
comments, a requirements block, and a resource-cleanup section. It contains no numbered
steps, no narrative, and no single path a newcomer can follow start to finish.

This is the sharpest page-type violation in either run. The remedy is the split, not a trim:
a short tutorial that installs the package, sets one URL, and makes one successful call,
with the table and the full option list moving to a reference page.

**2. The page opens with no prose.** The first element after the title is `<h2>Installing the
SDK</h2>` followed immediately by a code block. No sentence says what the SDK is for, what
the reader needs first, or what will be true when they finish. First contact has nothing to
work with.

**3. Two languages in tabs, with real divergences and no map.** Every block offers Python and
TypeScript. Three differences are load-bearing:

| Difference | Where it is stated |
|---|---|
| `timeout` is seconds in Python, milliseconds in TypeScript | a callout box, correctly |
| accounting email and password are Python only | one column of the env-var table |
| `login` takes keywords in Python and positional arguments in TypeScript | nowhere |

Tabs imply parity. Where parity does not hold, a reader who switches languages carries
assumptions that are quietly wrong. The timeout callout shows the team knows this and does
it well once. It needs to be done for every divergence, in one place a reader can check.

**4. The documented pattern puts a password in source.** The client constructor example
passes `accounting_password="your-password"` inline, and the cleanup example hard-codes
`login(username="alice", password="secret123")`. The env-var route exists on the same page
and should lead, with the inline form either removed or shown as the thing not to do. A
reader copying the first example they see is copying the wrong one.

**5. The section has three of the four page types and no explanation at all.** Getting
Started, User Guides, and Reference are all present. Nothing in the section answers why the
thing exists or why it is built this way. For a product in this domain that is the question a
new reader most needs answered, and there is no page for it.

**6. Decorative glyphs on every navigation entry.** Nine entries, nine symbols, several of
them obscure. They carry no information the label does not, and the prose rules treat
decoration as noise. Minor, and *inherited*: the same pattern shape appears on the other
site.

**7. The verify step prints a version and shows no expected output.** *Inherited*, in a
different shape. Better than the other site's magic count, because a version cannot drift
into a wrong assertion, but a reader still cannot tell whether what they saw was right.

## Out of scope, and correctly so

The pages carry hard-coded colour utilities, for example `text-yellow-400` and `bg-zinc-900`,
rather than theme tokens. That is a design-system concern about component-level presentation,
which the skill explicitly cedes. Noting it here only to record that the boundary rule fired
rather than being ignored.

## Verification result

**Pass.** The skill produced seven findings on a documentation set it was not built for. Five
are specific to this set and could not have come from the first run: the near-total absence
of tutorial content in a page filed as onboarding, the missing opening prose, the
two-language asymmetry, credentials in source, and a whole page type missing from the
section. Two are marked inherited and discounted accordingly.

Nothing in the output assumed anything about the first project. No concept, name, or metric
from it appears. With no context skill available the run reported every slot as unavailable
and made no claim about what this product is.

## What this run changed in the skill

One gap found. The skill has nothing to say about documentation that covers two
implementations in parallel, which is common for an SDK shipped in more than one language.
The page-type model does not reach it, because the problem is not which type the page is; it
is that a tabbed interface asserts parity that the APIs do not have.

Rule added to `reference/prose-tells.md`, in the structure table:

> **NEVER** present two implementations in parallel tabs without stating where they diverge.
> **INSTEAD** keep one list of the differences, and repeat any divergence that changes a
> call signature, a unit, or an availability at the point of use.
