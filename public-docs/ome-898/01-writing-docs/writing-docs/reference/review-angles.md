# Reviewing a documentation set

A review procedure, run as a specific reader with a specific goal and a real time budget.
Its value comes from that constraint. A copyeditor's pass finds typos. This finds the places
a reader gives up.

## Before you start

From the context slots, fix three things and write them at the top of the report:

- **the reader**: who they are and what they already know
- **their goal**: the concrete thing they came to accomplish, stated as a task
- **their time budget**: how long they will spend before abandoning it

If those slots are unavailable, say so and report them as unknown. Do not invent a persona.
A review run as an imaginary reader produces findings nobody can act on.

Also fix **the operational metrics** this project's readers judge it by, since two of the
nine rubric items depend on them.

## Pass 1: the naive read

Read in the exact order the docs present. Do not skip ahead. Do not use knowledge the docs
have not given you, including anything you know about the project from elsewhere. If the
docs do not say it, you do not know it.

Keep a friction log. Record the location and the exact sentence every time you:

- pause and re-read something to parse it
- meet a term, acronym, or abstraction before it has been defined
- scroll back to check something you were expected to remember
- have to guess what a parameter, return value, or option does
- ask "why would I do it this way?" and get no answer
- hit a code sample that would not run as written: missing imports, undefined variables, a
  stale API
- feel the difficulty jump rather than step

Every entry is data. Do not filter out the small ones. Small frictions compound into
abandonment, and the reader who leaves does not file a complaint.

## Pass 2: the structural read

Now read as an architect of the reader's understanding.

**Concept dependency map.** For each section, list what it assumes the reader knows and
where that was introduced. Flag:

| Problem | What it looks like |
|---|---|
| forward reference | a term used before its definition |
| orphan | a concept introduced and never used again |
| redundant re-explanation | the same idea taught twice, differently |
| terminology drift | one thing under two names, or two things under one name |

**Narrative arc.** A documentation set that clicks builds the model in layers: what this is,
why it exists, the smallest working thing, the core abstractions, how they compose, the
operational reality, then the edge cases and limits. Note every place the actual docs jump a
layer, backtrack to an earlier one, or stall.

**Example progression.** Do examples grow minimal, then realistic, then production-shaped,
each adding exactly one new idea? Or does one leap several ideas at once?

## Pass 3: the visual pass

For every concept, mark one of three verdicts:

- **has a diagram, and it works**: matches the prose, same terminology, one idea, current
- **has a diagram, and it fails**: decorative, overloaded, stale, or labelled differently
  from the text
- **needs a diagram and lacks one**: the prose describes structure, flow, sequence, state,
  or a decision, and the reader must assemble it mentally

For each failure and each gap, specify what the reader needs to see: the boxes, the arrows,
the labels, and the one question it answers. Then supply paste-ready source. See
`diagrams.md` for the concept-to-diagram table and the starting points.

## Scorecard

Nine items, each scored 1 to 5, each with a quoted line of evidence. A score without a quote
is an opinion.

| # | Item | 1 | 5 |
|---|---|---|---|
| 1 | **first contact** | after a minute on the landing page you cannot say what this is or who it is for | you can state what it does, who it is for, and what it improves on |
| 2 | **time to first success** | no runnable example, or one that fails | a minimal copy-pasteable example early, with its expected output shown |
| 3 | **concept ordering** | terms are routinely used before they are defined | nothing is used before it is introduced |
| 4 | **learning-curve shape** | cliffs: whole layers skipped between pages | difficulty rises in steps you can climb |
| 5 | **example quality** | toy examples that no real use resembles | minimal, realistic, runnable, progressive |
| 6 | **reference navigability** | you know what you want and still cannot find it | one or two hops from question to answer |
| 7 | **terminology discipline** | the same thing has three names | one name per concept, everywhere |
| 8 | **honest operations** | the operational metrics appear as adjectives, or not at all | numbers with methodology, versions, and conditions |
| 9 | **visual clarity** | structure and flow are prose-only, or diagrams contradict the text | every structural concept is drawn well or is simple enough not to need it |

Do not grade on a curve. "Fine for docs" is not the bar. The bar is that it clicks.

## Trust check

Documentation should read as though written by an engineer talking to an engineer, and it
should be honest about what the thing costs.

| Check | Failing looks like |
|---|---|
| plain honesty about limits | no "when not to use this", or it is buried in an appendix |
| numbers over adjectives | "fast", "efficient", "scalable" with no measurement |
| operational reality where decisions are made | the costs of the design surfaced far away from the page where you choose it |
| no marketing residue | unverifiable superlatives, landing-page sentences |
| a project expecting to be depended on | no versioning or stability statement, no changelog, no migration notes, no contribution path |

For every sentence that erodes trust, quote it **and rewrite it** in the target voice from
the context slots. A quoted complaint is half a finding.

## Output

One report, these sections, this order.

1. **Verdict.** Three to five sentences. Would this reader adopt it on the strength of the
   docs alone? Where did understanding flow, and where did it break?
2. **Friction log.** Chronological, with locations and quotes.
3. **Flow map.** Concept-ordering and arc problems, as a dependency list.
4. **Scorecard.** Nine items, each with its score and one line of quoted evidence.
5. **Diagram plan.** Every missing or failing diagram, prioritised. Each entry: exact
   location, the concept, the diagram type, the one question it answers, and paste-ready
   source using the project's exact terminology.
6. **Top fixes.** Prioritised by impact on time-to-understanding, drawn from both the prose
   and the diagram plan. Each one: exact location, why it blocks flow, and a concrete before
   and after.
7. **What already works.** The sections, examples, and diagrams that click, so nobody
   improves them away.

## Rules

- **Be specific.** Every finding quotes the exact text and names its location. "The
  quickstart is confusing" is not a finding.
- **Rewrite, do not critique.** Show the fix, in the target voice.
- **Prefer deletion.** Clarity is usually fewer words. A fix that adds text has to justify
  itself.
- **Run the code.** Report actual errors and actual output, not assumptions.
- **When you cannot run it, say so and check it another way.** Some review environments
  cannot execute the examples: no credentials, no network, no runtime. Mark every example
  unverified rather than implying you ran it, then check what is checkable without running
  anything. Do the imports match what is used? Do the names match the reference pages? Does
  the same example appear elsewhere with different arguments? Does the page show what
  success looks like? An example with no expected output is a finding whether or not you
  could run it.
- **One reader, one goal.** Judge everything against the reader and the goal you fixed at
  the start. Anything that does not serve them is a candidate for restructuring.
- **One idea per diagram.** A diagram needing a paragraph to explain it has failed.
- **Text and picture must agree.** Every proposed label uses the exact names the prose and
  the API use. If the diagram forces better names, propose renaming the prose too.
