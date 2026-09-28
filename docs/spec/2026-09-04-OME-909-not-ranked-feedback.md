# OME-909 — Not-ranked submission feedback

Status: in progress · Stack: scoreboard + screamingface

## Problem

The Scoreboard correctly excludes a score whose benchmark revision differs from the revision the
board is registered at. The write still succeeds, but the POST response and Client card currently
look identical to a rankable submission. A submitter can therefore pay for a full run, receive a
success receipt, and only discover later that the score never appears in the ranking.

## Decisions

### D1 — Persist successfully; explain ranking separately

A revision mismatch remains a successful `200` idempotent replay or `201` creation. The result is
valid evidence and stays stored. This feature must not turn comparability into request validity.

### D2 — The score contract carries one optional typed notice

The shared `ScoreSchema` gains an optional `ranking_notice` object so the established POST and GET
OpenAPI references remain intact. On a revision mismatch the POST contains the stable code
`benchmark_revision_mismatch`, the revision stored on the submitted score, and the benchmark
revision registered by the board. GET never populates the field: this is submit-time feedback, not
mutable ranking state promised by later reads.

### D3 — Matching responses remain unchanged on the wire

When no mismatch exists, `ranking_notice` is omitted—not serialized as `null`. The field's model
serializer excludes only an absent notice, including in GET and private JSONL export paths; it does
not drop any existing nullable score field. Existing score output remains byte-for-key compatible.

### D4 — The predicate mirrors the existing ranking rule

A mismatch exists only when the board has a non-null registered revision and the persisted score's
`benchmark_revision` is unequal to it. That includes a missing submitted revision. A board with no
registered revision does not filter by revision today and therefore emits no mismatch notice.
The ranking query and its revision filter are not changed.

### D5 — Report the persisted revision and a pre-write board snapshot

The submitted value comes from the persisted `ScoreSchema`, after the store's existing revision
resolution. The registered value is read immediately before the store call, inside the existing
database-error boundary. This avoids a new read after a successful write that could fail and hide a
persisted score id. Like all ranking state, a later seed can supersede the snapshot.

### D6 — The Client preserves the machine-readable fact

`LeaderboardScore` gains an optional immutable `LeaderboardRankingNotice`. The HTTP decoder
validates the exact reason code and both revision fields rather than reducing the response to
presentation copy. Older Scoreboards omit the field and continue to decode normally.

### D7 — The score card distinguishes publication from ranking

The card keeps the factual `Score published` receipt and successful persistence marker, then adds
an SFDS warning block: `Not ranked · benchmark revision mismatch.` It names the submitted and
registered revisions. Matching submissions render exactly as before. Warning semantics use the
existing shared report-card tokens; no new palette or decorative system is introduced.

## Verification contract

- mismatched creation and replay both persist/return success and include the same typed notice;
- the notice names the stored submitted revision and registered revision;
- matching and revisionless-board POST responses omit the notice;
- OpenAPI preserves the shared `ScoreSchema` response reference and documents the stable reason;
- the Client decodes absence and mismatch, rejects malformed notices, and exposes the typed value;
- the mismatched score card has an alert warning with escaped revision text;
- matching cards and the existing ranking filter remain unchanged;
- full Scoreboard and `screamingface` gates pass.

## Non-goals

- changing which rows rank, updating a stored row, or adding a database migration;
- reporting partial-run, privacy, verification, or reproduction state through this notice;
- promising that a submit-time snapshot remains the board's revision forever;
- changing the portal or adding an operator-side seed warning.
