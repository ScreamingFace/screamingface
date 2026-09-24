---
description: How to write and review documentation that reads well and is shaped right. Pick the page type (tutorial, how-to, reference, explanation), keep prose free of generated tells, decide when a concept needs a diagram, and review a page as the reader it was written for. Use when writing or changing any documentation page, README, tutorial notebook, or release notes; when reviewing docs someone else wrote; or when deciding how a documentation set should be organised.
user_invocable: true
---

# writing-docs

Two jobs, one set of rules.

| Mode | You are | Go to |
|---|---|---|
| **write** | about to write or change a page | §2 |
| **review** | reading a page someone else wrote | §3 |

A review that judges a page against different rules than the writer was given is a review
nobody can act on, so both modes read from the same four reference files.

| File | Holds |
|---|---|
| `reference/divio.md` | the four page types and how to pick one |
| `reference/prose-tells.md` | the `NEVER` / `INSTEAD` table |
| `reference/diagrams.md` | which concepts need a picture |
| `reference/review-angles.md` | the three review passes, scorecard, trust check |

## 1. Step zero: load the context

This skill holds no knowledge about any particular product, project, or house style. Before
writing or reviewing, look for a loaded context skill and read these slots from it.

| Slot | Supplies | Needed for |
|---|---|---|
| house voice | register conventions this house holds to, beyond the craft rules | write, rewrite |
| product facts | what the thing is, what its parts are called | write, review |
| terminology casing | the exact casing of every name | write, review |
| positioning language | how the project describes itself | write |
| the reader | who the newcomer is and what they came to do | review pass 1 |
| the time budget | how long they will spend before giving up | review pass 1 |
| operational metrics | the numbers this project's readers judge it by | scorecard, trust check |
| target voice | the voice a rewrite should land in | trust check |

More than one skill may fill these. Read whatever is loaded. Do not install or import
anything.

**If nothing is loaded, do not invent it.** Produce page structure, prose craft, and diagram
guidance as normal, then:

- state which slots were unavailable
- mark every product claim you cannot verify as unverified, rather than writing a plausible one
- in review, report the reader and the metrics as unknown rather than assuming a persona

Guessing at what a product is, or at how it describes itself, produces confident and wrong
documentation. Saying you do not know produces a question someone can answer in a minute.

## 2. Write mode

### 2.1 Pick the page type first

One page serves exactly one type. Read `reference/divio.md` and choose before writing a
sentence.

| type | serves | reader is |
|---|---|---|
| tutorial | learning | a beginner following along |
| how-to | a goal | someone with a task in hand |
| reference | lookup | someone who knows what they want |
| explanation | understanding | someone asking why |

If the page you are changing already serves two types, that is a defect. **Split it.** Do not
balance the two.

### 2.2 Shape the page

Within a type, build the reader's model in layers: what this is, why it exists, the smallest
thing that works, the core abstractions, how they compose, the operational reality, then the
limits. Examples grow from minimal to realistic to production-shaped, one new idea at a
time.

Two rules catch most structural damage.

- **Nothing is used before it is introduced.** If a term appears before its definition, move
  one of them.
- **One name per concept, everywhere.** Two names for one thing cost the reader more than
  any prose flaw.

### 2.3 Decide what to draw

Ask at every concept: *am I asking the reader to assemble a picture in their head that this
page should have drawn?* Structure, flow, sequence, state, and decisions are all cheaper to
see than to read. `reference/diagrams.md` has the table and the four hard rules.

### 2.4 Then write the prose

`reference/prose-tells.md` in full. The rules that matter most often:

| NEVER | INSTEAD |
|---|---|
| Announce what the section will do. "Let's dive in", "In this section we will…" | Start with the content. The heading already announced it. |
| Close with a summary of what the reader just read, or a generic outlook. | End on the last real point. |
| Adjectives for performance. "fast", "lightweight", "scalable". | The number, the method, and the conditions. |
| Stacked hedging. "may potentially, in some cases". | One hedge, or none. |
| A forced triad because three sounds complete. | As many items as are true. |
| Sales register. "seamlessly", "powerful", "nestled within". | Say what it does. |
| Em-dashes. | A comma, a colon, parentheses, or a full stop. |

**Prefer deletion.** Clarity is usually fewer words. A fix that adds text has to justify
itself.

## 3. Review mode

Run `reference/review-angles.md` end to end. In outline:

**Pass 1, the naive read.** Read in the order the docs present, as the reader from §1, with
their time budget. Do not skip ahead, and do not use knowledge the docs have not given you.
Log every friction with its location and the exact sentence.

**Pass 2, the structural read.** Map what each section assumes and where that was
introduced. Find forward references, orphaned concepts, terminology drift, and the places
where the arc jumps, backtracks, or stalls.

**Pass 3, the visual pass.** For every concept: has a diagram that works, has one that
fails, or needs one and lacks it. For each gap, specify the boxes, the arrows, the labels,
and the one question it answers.

Then score the nine rubric items, run the trust check, and produce the output in the order
`reference/review-angles.md` specifies. Four rules separate a review someone acts on from
one they ignore.

- **Quote the location.** "The quickstart is confusing" is not a finding.
- **Rewrite, do not critique.** Show the replacement text or the diagram source.
- **Run the code.** Report real errors and real output, not assumptions.
- **Do not grade on a curve.** "Fine for docs" is not the bar.

## 4. What this skill does not cover

- **Internal engineering artifacts:** specs, plans, design docs, ledgers. They are written
  for the team, and the four page types do not describe them.
- **Generated API reference.** That is a toolchain question.
- **Issue, pull-request, and commit text.** Each project has its own conventions.
- **Component-level copy** where a design system governs it: labels, buttons, chart legends,
  badges. That system wins inside a component. This skill governs the prose around it.
