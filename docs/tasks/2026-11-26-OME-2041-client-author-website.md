---
id: OME-2041
linear_url: https://linear.app/openmined/issue/OME-2041/let-submit-accept-a-personal-website-and-display-name-per-author
status: Done
type: task
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1915
created: 2026-11-26
closed: 2026-11-26
---

# Let submit() accept a personal website and display name per author

`submit(..., authors_metadata=...)` already let a caller put any key into one author's metadata
dict, sent through unvalidated. Within one author's entry, `display_name` is now accepted as an
alias for the existing `full_name` field (sending both is refused, not silently resolved), and
`website` is validated as an absolute http(s) link — same shape rules as the SDK's existing
`paper_url` validator (http/https only, a host, no user info, no control characters or
whitespace, length capped at 2048), which itself mirrors the Scoreboard's `validate_paper_url`.

This is the client-sf half of a cross-cutting pair split per the repo's cross-cutting rule.
`OME-2015` is the independent scoreboard-side sibling (storage, API, portal rendering of the same
`website`/`display_name` fields) — neither blocks the other.

Not covered (deferred, per ticket scope): account-level default profile — no server-side
account/profile/user concept exists today.

Ledger: `docs/work/2026-11-26-OME-2041-client-author-website.md`.
Branch: `OME-2041-client-author-website`.
