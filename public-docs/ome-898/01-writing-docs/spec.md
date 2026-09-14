---
title: "writing-docs: a documentation-writing skill"
ticket: OME-898 (child 1, not yet filed)
plan: ./plan.md
status: draft
date: 2026-08-20
---

# writing-docs

A skill that tells whoever works on documentation, person or agent, what shape a page should
take, how the prose should read, when a concept needs a picture, and how to review a page
someone else wrote.

It exists because documentation gets written to whatever shape the writer had in mind that
day. Reference detail lands in a tutorial, a how-to stops to teach, structure that wants a
diagram arrives as three paragraphs of prose, and the writing carries the usual generated
tells. There is no shared answer to "what kind of page is this?", so every writer invents
one.

**The skill is completely agnostic.** It names no product, no organisation, no repository,
and no file path. Everything specific to whoever installs it, house voice included, arrives
through the contract in §5 and is resolved at runtime. A skill that hard-codes one project's
conventions is that project's skill with a general label on it.

Parent: `OME-898`.

## 1. Two entry points

The skill does two jobs, and they share the same reference material.

| Mode | Question | Uses |
|---|---|---|
| **write** | I am about to write or change a page | §4.1 page shape · §4.2 prose · §4.3 diagrams |
| **review** | I am reading a page someone else wrote | §4.4 review angles, which lean on all three |

Keeping them in one skill is deliberate: a review that judges a page against different
rules than the writer was given is a review nobody can act on.

## 2. Non-goals

- **No CI gate and no lint script.** Advisory only (owner, 2026-09-02).
- **No product facts, no house voice rules, no positioning language.** All of it belongs to
  a context skill (§5). A rule naming a product or an organisation cannot ship here,
  however small it is.
- **Not a docs generator.** This governs documentation a person or agent writes, not docs
  derived from a diff.
- **Not for internal engineering artifacts.** See §3.
- **No repository, path, or toolchain assumptions.** The skill must work in a project it has
  never seen.

## 3. Scope

Scope is a class of document, not a location.

**In scope, anything written for a reader outside the authoring team:** documentation pages,
READMEs, narrative or tutorial notebooks, release notes and changelog prose.

**Out of scope:**

| Excluded | Why |
|---|---|
| specs, plans, ledgers, design docs | written for the team, and the four modes in §4.1 do not describe them |
| generated API reference | derived from source, so a toolchain concern rather than a prose one |
| issue bodies, pull-request text, commit messages | governed by a project's own process conventions |

The boundary is the reader. If someone outside the team reads it, this skill applies.

## 4. What the skill composes

Three distilled inputs, and nothing else. The skill calls no other skill. Everything that is
project specific is a §5 slot.

| Input | Answers | Origin |
|---|---|---|
| divio | what shape is this page? | the divio documentation system |
| prose tells | does this read like a person wrote it? | `github.com/blader/humanizer` |
| review angles | what is wrong with the page in front of me? | the owner's reviewer prompt |

### 4.1 divio: page shape

Four modes, and the rule that **one page serves exactly one mode**:

| mode | serves | reader is | what breaks when mixed |
|---|---|---|---|
| tutorial | learning | a beginner following along | reference detail stalls the beginner |
| how-to | a goal | someone with a task in hand | teaching interrupts the task |
| reference | lookup | someone who knows what they want | narrative buries the fact |
| explanation | understanding | someone asking why | how-to steps derail the argument |

Mixing modes on one page is the most common documentation failure, so mode selection comes
first, and a mixed page is a defect to split rather than a style preference to discuss.

### 4.2 Prose tells: how it reads

Throat-clearing openers, the "it's not just X, it's Y" construction, reflexive triads,
stacked hedging, over-signposting, and closing paragraphs that summarise what the reader
just read. Written as a `NEVER` / `INSTEAD` table so every prohibition carries a
replacement. A rule with no replacement gets ignored under deadline.

These are craft rules, true in any project. Register conventions that vary by house, such as
whether contractions are allowed, are not here. They are the house-voice slot in §5.

Two rules from the review angles live here rather than being stated twice: **numbers over
adjectives** (a performance claim without methodology is not a fact) and **prefer
deletion** (clarity is usually fewer words, so a fix that adds text has to justify itself).

### 4.3 Diagrams: when prose is the wrong medium

The test: *is the reader being asked to assemble a picture in their head that the page
should have drawn?* Structure, flow, sequence, state, and decisions are all cheaper to see
than to read.

Concepts that need a diagram unless they are trivial:

| Concept | Diagram | The question it answers |
|---|---|---|
| components and boundaries | component | what are the pieces, and what talks to what? |
| request or data flow | flow or sequence | what happens on one call, and where does cost accumulate? |
| composition topology | topology | how do parts chain, fan out, or fall back, and where do errors travel? |
| lifecycle | state | what states exist, and what moves between them? |
| "use X when, use Y when" | decision tree or matrix | which one do I pick? |
| tradeoff space | annotated chart or table | where does each configuration land? |

Four hard rules:

- **One idea per diagram.** A figure needing a paragraph to explain it has failed. Split
  overloaded figures, cut decorative ones.
- **Diagrams as code.** A text format that lives in the repo and is reviewed in the PR.
- **Text and picture agree.** Every label uses the exact name the prose and the API use. If
  the diagram forces better names, rename the prose too.
- **A stale diagram is worse than none.** It teaches a wrong model, confidently.

### 4.4 Review angles: reading a page as its reader

A review procedure, in three passes. Its value is that it is done as a specific reader with
a specific goal and a real time budget, not as a copyeditor.

**Pass 1, the naive read.** Read in the order the docs present. Do not skip ahead, and do
not use knowledge the docs have not given you. Log every point of friction with its
location and the exact sentence: a re-read to parse, a term used before it is defined, a
scroll back to check something, a guess at what a parameter does, an unanswered "why this
way?", a sample that would not run as written, and any sudden jump in difficulty. Small
frictions count, because they compound into abandonment.

**Pass 2, the structural read.** Map what each section assumes and where that was
introduced: forward references, orphaned concepts, redundant re-explanations, terminology
drift. Then check the arc (what it is → why it exists → smallest working thing → core
abstractions → how they compose → operational reality → limits) and note where the page
jumps, backtracks, or stalls. Check whether examples grow minimal → realistic →
production-shaped, one new idea at a time.

**Pass 3, the visual pass.** For every concept, mark it: has a diagram that works; has one
that fails (decorative, overloaded, stale, or labelled differently from the text); or needs
one and lacks it. For each gap, say what the reader needs to see: the boxes, the arrows, the
labels, and the one question it answers.

**Scorecard**, each scored 1 to 5 with quoted evidence: first contact · time to first
success · concept ordering · learning-curve shape · example quality · reference
navigability · terminology discipline · honest operations · visual clarity.

**Trust check.** Limitations and "when not to use this" stated plainly rather than buried;
claims carrying methodology; operational tradeoffs surfaced where the design decisions are
made rather than in an appendix; no unverifiable superlatives; and the signs of a project
expecting to be depended on, meaning versioning, changelog, migration notes, a contribution
path. Every sentence that erodes trust gets quoted **and rewritten**.

**Output**: verdict · friction log · flow map · scorecard · diagram plan with paste-ready
diagram source · top fixes as before and after · what already works, so nobody fixes it
away.

**Rules that make the review usable:** be specific and quote the location; rewrite rather
than critique; run the code if you can and report real output; do not grade on a curve,
because "fine for docs" is not the bar.

### 4.5 The survey

The epic asks for a look at what other documentation skills exist. It terminates by
construction: every candidate is recorded in `reference/PROVENANCE.md` as adopted, or
rejected with a reason. An unsurveyed candidate is not a defect. An undocumented decision
is.

### 4.6 Independence, and accepted duplication

The skill calls no other skill. `reference/prose-tells.md` is authoritative on its own and
does not defer to a house writing skill, even where a house skill carries the same rule.

That duplication is deliberate (owner, 2026-09-02). A skill that only works properly
alongside another one is not independent, whatever its own files say. The cost is real and
named: two copies of a rule can drift apart, and the drift check in `PROVENANCE.md` is the
only thing watching for it.

## 5. The context contract

The skill holds no project or organisation knowledge. It declares what a context skill must
supply and consumes whatever the host has.

The review procedure is what makes this contract load-bearing rather than decorative. Pass 1
cannot be run without knowing who the reader is and what they came to do.

| Slot | Supplies | Used by |
|---|---|---|
| house voice | register conventions the house holds to, beyond the craft rules | write, trust check |
| product facts | what the thing is, what its parts are called | write and review |
| terminology casing | exact casing of names | write and review |
| positioning language | how the project describes itself | write |
| the reader | who the newcomer is, and what they came to do | review pass 1 |
| the time budget | how long they will spend before giving up | review pass 1 |
| operational metrics | the numbers this project's readers judge it by | scorecard, trust check |
| target voice | the voice a rewrite should land in | trust check |

More than one skill may fill the contract: one supplying house voice, another product facts.
The skill consumes whatever is loaded and does not care how many there are.

**Resolution.** Before writing or reviewing, look for loaded context skills and apply them.
Loading happens through the host's own plugin mechanism. This skill does not name, install,
or import one.

**Degradation is the load-bearing part.** With nothing loaded, the skill produces page
structure, prose craft, and diagram guidance, and **flags every product claim and voice
choice as unverified rather than inventing one**. The review still runs, with the reader and
metric slots reported as unknown rather than assumed. A skill that guesses at positioning is
worse than one that says it does not know.

## 6. Layout

```
writing-docs/
  SKILL.md                      the two modes, mode selection, the anti-rules table,
                                the context contract, the degradation path
  reference/divio.md            the four modes, distilled
  reference/prose-tells.md      the NEVER / INSTEAD tables
  reference/diagrams.md         which concepts need a picture, and the four hard rules
  reference/review-angles.md    the three passes, scorecard, trust check, output, rules
  reference/PROVENANCE.md       source, licence, retrieval date, and drift check per
                                source, plus what the survey rejected and why
```

`diagrams.md` is its own file rather than part of the review angles because it is needed
when writing a page, not only when reviewing one.

**Before distilling:** check the licence on each source and record attribution in
`PROVENANCE.md`. Distilled rules with credit, not wholesale copies of someone's text.

## 7. Decisions

Owner, 2026-09-02:

- **Advisory only.** No lint, no CI gate in this unit.
- **Completely agnostic.** No product and no organisation specifics in the skill. All of it
  arrives through §5.
- **The skill is independent, and duplication is accepted.** This reverses an earlier
  instruction on the same day. An intermediate version ran a house writing skill's passes and
  let it win on conflict; that is removed. Where this skill's prose rules restate rules a
  house skill also carries, the duplication stands. It also means the epic's "should use that
  skill because it will evolve" is knowingly not satisfied: the owner chose independence over
  inheritance. See §4.6.

Recorded so they are not re-opened:

- **Scope is a document class, not a path** (§3), read from the epic's two constraints:
  product reviews docs manually at release, and docs must match product voice. Both point at
  prose a reader outside the team sees.
- **The review angles are de-specified into a procedure plus context slots** (§5). The source
  prompt was written for one product, one reader, and one metric triad. The passes, scorecard,
  and rules all survive removing those, and the specifics become contract slots.
- **Name: `writing-docs`.** Reads as an action at the invocation site, and carries no product
  noun.
- **No design-system precedence section.** An earlier draft carried a rule about which
  system wins on component copy. It was generic in wording but existed only because of one
  specific design system, which is the coupling this decision forbids. Cut.

Mine rather than the epic's, and flagged as such:

- **The skill is authored and published standalone rather than inside a product
  repository.** It follows from agnosticism but the epic does not say it. Authoring it inside
  a product repo is what made the first draft of this spec fail: repository paths, a named
  design system, and a hard dependency on one context skill all crept in. Where it is
  published is a distribution question and does not appear anywhere in the skill's content.

## 8. Acceptance

- The skill exists with a `description` and `user_invocable: true`, and installs through the
  host's plugin mechanism.
- **Agnosticism check:** no product name, organisation name, repository path, or
  design-system name appears anywhere in the skill, `reference/` included. The only
  context-shaped thing is the §5 contract, which names nothing.
- **Punctuation check:** no em-dashes or en-dashes anywhere in the skill.
- The four modes are stated with the one-mode rule and the remedy for a mixed page.
- A `NEVER` / `INSTEAD` table for the prose tells, holding craft rules only, with no house
  register conventions.
- The diagram table and the four diagram rules, including diagrams-as-code.
- The three review passes, the nine-item scorecard, the trust check, and the output format.
- **Independence check:** the skill references no other skill by name or by role, and every
  reference file is complete on its own.
- `PROVENANCE.md` records source, licence, retrieval date, and a drift check for each
  distilled source, plus the survey's verdicts.
- The degradation path is written down and says to flag unverified claims rather than invent
  them.

## 9. Verification

- Take a page that mixes modes. The skill names the conflict and proposes the split.
- Run the review against a real documentation set. It produces a friction log with quoted
  locations and at least one paste-ready diagram, not a list of adjectives.
- Run it with no context skill loaded: it produces structure, prose, and diagram guidance,
  and reports the reader and metric slots as unknown rather than assuming them.
- Run it with a context skill loaded: the reader, the metrics, and the terminology are
  applied, and none of that project's specifics appear inside `writing-docs` itself.
- Hand `reference/review-angles.md` to someone who did not write it. They find a real gap
  using only that checklist.
- Run it against a project it was not written for, in a different domain. Nothing in the
  output assumes the first project.
