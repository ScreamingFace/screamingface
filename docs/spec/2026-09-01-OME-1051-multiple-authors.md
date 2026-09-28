# OME-1051 — Multiple authors on a leaderboard submission

Status: approved for implementation on 2026-09-01.
Epic. Sub-issues: `OME-1052` (display · scoreboard), `OME-1053` (client · py-screamingface),
`OME-1054` (resubmission updates the stored list).

## 1. The problem, stated precisely

`submitted_by` currently does two unrelated jobs:

| Job | Consumer |
| --- | --- |
| **Authorization subject** — who owns the row on a private board, who owns an idempotency key | `list_owned_entries(owner=…)`, `_resolve_owned`, the scoped key |
| **Submitter display** — who sent the result | the existing portal column, renamed **"Submitter"** |
| **Credit line** — who gets named for the result | the new portal **"Authors"** column |

A Fusion built by two people can only carry one credit line. Splitting the two jobs is the whole
change: `authors` becomes the credit, while `submitted_by` keeps authorization and remains visible
as the submitter. The portal therefore shows two distinct columns: **Submitter** and **Authors**.

## 2. Owner decisions (2026-08-31)

**D1 — the submitter is responsible for their own omission.** `submit(result, authors=[...])`
uses *only* the listed addresses. A submitter who leaves themselves off is left off. No
auto-inclusion, no co-author verification; submitters are allowlisted, so the trust model is
"an allowlisted person does not lie about their collaborators".

**D2 — a private board scopes to the submitter, never to an author.** Naming someone as a
co-author grants them no read access. `list_owned_entries` keeps filtering on `submitted_by`.

**Consequence of D2 worth stating before anyone builds the display half:** on a private board
`entries` is empty for everyone and only `my_submissions` carries rows, to the submitter alone. So
on the entry challenge — the first and currently only private board — an author list is visible to
exactly two audiences: the submitter, and staff via `export_private_submissions`. `OME-1052`'s
display work has **no visible effect there** until that board goes public. It is not wasted, but
it cannot be demonstrated on healthbench-worst30.

## 3. Storage

New nullable column on `Score`:

```python
authors = fields.JSONField(null=True)
```

**`NULL` means "the client did not say", never "nobody".** A read derives `[submitted_by]` when
the column is null. Two reasons not to materialise the default at write time:

- It is the house pattern. `run_cost_usd` and `Benchmark.visibility` both use null-as-not-stated,
  and both have a comment explaining that writing the apparent default is what lets a later pass
  silently overwrite a real value.
- `OME-1054` makes a resubmission update the list. A materialised default would be indistinguishable
  from a deliberate single-author list, so the update path could not tell "never specified" from
  "specified as just me".

Migration is additive and **not backfilled** — every existing row reads as `[submitted_by]`, which
is what the board already shows.

## 4. Wire contract

```python
authors: list[str] | None = None
```

on `ScoreSubmission`. Bounded, because this is a public write path and `OME-969` is an open finding
that submission `metadata` is unbounded — do not add a second unbounded field next to it:

- at most **10** entries
- each at most 255 characters, matching the `submitted_by` column
- every entry must have syntactically valid email form; no deliverability or ownership check
- empty list rejected as a field error, not silently treated as null: `authors=[]` is a client bug,
  and "no authors" is not a state this feature has.

## 5. Publishing — the invariant that matters most

`submitted_by` is trimmed to its local part on every JSON read path by `_publish_submitter`
(`OME-834`), because the read API is public and unauthenticated and a harvester could otherwise
pull every submitter's address out of `GET /v1/leaderboard/{id}`.

**Author addresses must be trimmed identically.** Publishing a raw list beside a trimmed
`submitted_by` reopens exactly the hole `OME-834` closed, and does it in a field designed to hold
*more* addresses than before.

Concretely: a new annotated type beside `SubmittedBy`, same `PlainSerializer`, same
`when_used="json"` — the python-mode value must stay untrimmed, because `_ranked_entry` splats
`entry.model_dump()` in python mode.

```python
Authors = Annotated[
    list[str] | None,
    PlainSerializer(_publish_authors, return_type=list[str] | None, when_used="json"),
]
```

The staff export keeps full addresses, as it already does for `submitted_by` — that is the path
that exists so staff can contact people.

## 6. Read DTOs

`authors` is added to `ScoreSchema` and `LeaderboardEntry`, **and** to `RankedLeaderboardEntry`.

> AIDEV-NOTE in `routes/leaderboard.py:51`: `RankedLeaderboardEntry` mirrors `LeaderboardEntry`
> field-for-field plus `rank`, and `_ranked_entry` splats one into the other. Both set
> `extra="forbid"`, so a field added to one and not the other is a **runtime 500 on the read
> path**, not a type error.

Adding it to one and forgetting the other is the single most likely way to break this change, and
it will not be caught by pyright.

## 7. Dedup — and the trap it sets

`_content_hash` deliberately excludes `submitted_by`: *"identity is the recipe (what was run and
its result), not who ran it or when"*. `authors` is the same kind of thing and is excluded too.

The consequence is not obvious and needs saying: **resubmitting the same recipe with a corrected
author list dedups to the stored row and the correction is discarded.** Someone who forgets a
co-author under D1 and tries to fix it by resubmitting will appear to succeed and change nothing.

That is `OME-1054`'s scope — "resubmitting the same URL4 candidate with new metadata updates the
existing metadata, including authors". This spec defines the field; `OME-1054` defines the update.
**They must ship together, or D1 becomes a trap rather than a rule** — the difference between "you
are responsible for getting it right" and "you are responsible and cannot fix it".

Same shape as `run_cost_usd`, which has the identical interaction recorded on `OME-1029`.

## 8. Owner decisions (2026-09-01)

1. **At most 10 authors.** Raising the cap later is cheap; the public write path stays bounded.
2. **Authors are email addresses, validated for syntax only.** There is no deliverability,
   ownership, allowlist or domain check. Display names need a separate publishing contract.
3. **The list survives publication.** A list stored while a benchmark is private remains attached
   when it becomes public; public JSON exposes local parts only, under the rule in §5.
4. **Submitter and authors are both displayed.** The former Author column is renamed Submitter and
   a separate Authors column is added; submission history shows the same two fields.

## 9. Out of scope

- The SDK's `authors=` parameter (`OME-1053`, py-screamingface).
- Any change to who may *read* a private board (D2 settles it: the submitter).
- Any change to idempotency-key ownership, which stays with `submitted_by`.
