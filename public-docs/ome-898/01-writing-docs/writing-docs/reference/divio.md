# The four page types

A documentation set serves four different needs, and a page that tries to serve two serves
neither. Pick one before writing.

| type | serves | reader is | reader's question | what it must not do |
|---|---|---|---|---|
| **tutorial** | learning | a beginner following along | "teach me how this works" | stop to enumerate options or list parameters |
| **how-to** | a goal | someone with a task in hand | "help me do this specific thing" | teach concepts they did not ask about |
| **reference** | lookup | someone who already knows what they want | "what exactly does this do?" | narrate, persuade, or teach |
| **explanation** | understanding | someone asking why | "why is it built this way?" | give steps to follow |

## Which one am I writing?

Two questions settle it almost every time.

**Does the reader arrive knowing what they want?** No means tutorial or explanation. Yes
means how-to or reference.

**Do they want to act, or to understand?** Act means tutorial or how-to. Understand means
reference or explanation.

|  | wants to act | wants to understand |
|---|---|---|
| **does not know what they want** | tutorial | explanation |
| **knows what they want** | how-to | reference |

## What breaks when types mix

Mixing is the most common documentation failure, and each pairing fails in its own way.

| mixture | how it fails |
|---|---|
| tutorial + reference | the beginner hits a parameter table and stops following |
| tutorial + explanation | design rationale interrupts the thing they were doing |
| how-to + tutorial | a reader with a task is taught material they did not ask for |
| how-to + explanation | steps stall while the page argues for the approach |
| reference + explanation | the fact the reader came for is buried in an argument |
| reference + tutorial | a lookup page assumes a starting state |

## The remedy is a split, not a balance

A mixed page cannot be fixed by trimming the intruding material until it feels
proportionate. That material is usually worth keeping. It is in the wrong place.

1. Name the two types the page currently serves.
2. Decide which one the page's title and location promise.
3. Move the other material to its own page of that type.
4. Link between them once, in the direction the reader travels.

A tutorial links forward to reference. Reference links back to explanation. How-to links to
both. Explanation links to nothing operational, because a reader who wants to act has left
already.

## Signals that a page is mixed

- a parameter or options table inside a numbered walkthrough
- the word "why" appearing in a page of steps
- a step that says "for the full list of options, see below", and then supplies it
- a reference entry whose worked example is longer than its description
- an explanation page whose last section is called "getting started"

## Attribution

The four-type model is Diátaxis, by Daniele Procida (`diataxis.fr`). It is described here in
our own words. Nothing is reproduced from it. See `PROVENANCE.md`.
