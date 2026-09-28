# OME-1053 — Client authorship contract

Status: approved for implementation on 2026-09-03.
Parent contract: `docs/spec/2026-09-01-OME-1051-multiple-authors.md` on the Scoreboard feature
branch.

## User contract

All submission surfaces accept the same keyword-only parameter:

```python
authors: Sequence[str] | None = None
```

The supported calls are the lazy `sf.leaderboards.submit`, bound synchronous
`Client.leaderboards.submit`, and bound asynchronous `AsyncClient.leaderboards.submit` APIs.

- `None` preserves today's request shape by omitting `authors`.
- A supplied sequence is the exact credit list. The submitter is never added implicitly.
- A supplied sequence contains 1–10 syntactically valid email addresses of at most 255
  characters each.
- Order and duplicates are preserved; the client performs no normalization or ownership check.

## Wire contract

The shared submission builder adds the top-level field only when specified:

```json
{"authors": ["alice@example.com", "bob@example.com"]}
```

The Scoreboard remains the authoritative validator and persistence owner. Local validation exists
to reject invalid Python API arguments before network I/O and mirrors the approved Scoreboard
syntax contract exactly.

## Read contract

`LeaderboardScore` and `LeaderboardEntry` expose:

```python
authors: tuple[str, ...] | None
```

This is deliberately not named `author_emails`. Public Scoreboard JSON privacy-trims email domains,
so a write containing `alice@example.com` can read back as `("alice",)`. The client
preserves that public response exactly as an immutable tuple.

`None` is allowed because the Scoreboard contract permits a submission without a resolved
submitter. A non-null response must be a non-empty JSON array of non-blank strings. This client is
released only after the Scoreboard feature deploys; compatibility with a pre-feature Scoreboard is
not a release requirement. Existing decoder fixtures that omit the new optional value continue to
decode as `None` without a special legacy fallback.

## Deployment constraint

The current Scoreboard rejects unknown submission fields. The Scoreboard implementation must be
merged and deployed before a client containing `authors=` is released. The client PR may be opened
as a draft and developed independently against the approved wire contract.

## Out of scope

- Co-author identity, allowlist, ownership, or deliverability verification.
- Granting authors access to private submissions.
- Automatically including the submitter.
- Scoreboard storage, migration, deduplication, and portal display.
