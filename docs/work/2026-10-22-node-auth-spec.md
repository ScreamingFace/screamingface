---
ticket: OME-1599
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-22
finished:
---

# node-auth-spec — draft the url4 node-to-node authentication spec

## Intent

Spec #1450 (`OME-1535`, F1/F1b) defers remote `url4://` blobs (C2) and remote-node calls (C6)
until a node-to-node authentication spec exists, and keeps the #1521 peer allowlist empty until
then. This unit drafts that spec for `OME-1599`: threat model, options, a recommended design,
identity and key discovery, inbound authorization, replay protection, rotation, typed `x.` failure
codes, and how C2/C6 are enabled alongside the #1521 destination guard. Design only; no code.

## Planned changes

- `docs/spec/2026-10-22-OME-1599-node-to-node-auth.md` (new, DRAFT)
- `docs/work/2026-10-22-node-auth-spec.md` (this ledger)

## Test plan

- Spec only. The spec itself names the tests both nodes need (§9). Gates: `git diff --check`,
  `python3 .claude/scripts/check_mirror_status.py`.

## Acceptance

- The spec covers every item of the F1b bar: outbound identity, credential transport and rotation,
  inbound authorization, replay behaviour, typed auth failures and tests at both nodes.
- It is marked DRAFT and lists the open questions for Kevin (url4 grammar owner).
- Branch pushed; no PR opened (the orchestrator decides).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see branch `node-auth-spec`.
- **Gates:** `git diff --check` clean; `check_mirror_status.py` run (see commit).
- **Deviations:** url4 Part B §3.5 (`URL4-Auth-Token`) text was not available locally, so the
  header's binding is proposed and raised as open question Q1 rather than quoted.
- **2026-10-28 revision (approved by Sergey):** code facts in §1 re-verified against `origin/main`
  (`6ea6a0011`). The branch was not rebased on the remote (a force-push was blocked); a rebased copy
  is kept locally as `node-auth-spec-rebased`. Added a "Decisions requested from Kevin" checklist at the top and, in §10, a
  working assumption per question (conservative, consistent with #1450), its consequence, and what
  changes if Kevin answers otherwise, so review does not need Kevin live. Six questions (Q1–Q6) go to
  Kevin; the draft's former Q7 (consent hooks) is outside `OME-1599`'s scope and is now a note left
  to Part C. Linear `OME-1599` had no comments listing the questions; the six are the draft's own.
  Still DRAFT; no PR.
- **2026-11-02 resume (owner-approved):** brought the branch up to date with a normal
  `git merge origin/main` (157 commits, no conflicts; no rebase, no force-push). §1 code facts
  re-checked on the merged tree: `peer/server.py` deferral text, `io/http.py` `url4://`→`https://`
  with only `Idempotency-Key`, and the `x.remote_*_unsupported` refusals all unchanged. Kevin has not
  answered Q1–Q6 (no Linear reply), so the spec stays DRAFT and implementation does not start:
  the six forks are open design decisions, below the 95% gate. Status remains `in_progress`.
- **2026-11-07 review round (Kevin, PR #1647, CHANGES_REQUESTED 2026-11-06):** Kevin pointed out that
  `URL4-Auth-Token` in the url4 spec is an encrypted credential carried from the originating requestor
  to the destination node (Part B §3.5, Part H §31), not an authorization grant. Owner decision
  (Sergey, 2026-11-07): adopt Kevin's split. The grant moves to a new `URL4-Authz-Token` header;
  `URL4-Auth-Token` keeps its url4 meaning and is signature-covered when present. Updated §5.3
  (covered components, headers sent), §5.4 (retitled, relation note), §5.5 step 1, §5.8 codes, the
  Q1 checkbox and §10 Q1 (resolved, citing B §5.4.2, §5.6.4, §5.6.9; C §11.6.2; H §29.2.1, §31, §33,
  §35). Open note, not changed: Part H §31 still calls the header `ABC-Auth-Token`. No other design
  decision changed; Q2–Q6 stay open. Branch not synced with `main` (squash-merge absorbs the gap).
- **2026-11-19 review round (HupBaHa, PR #1647, CHANGES_REQUESTED 2026-11-17):** six protocol
  blockers. Owner chose to fix all of them now (2026-11-19). The direction (RFC 9421 plus signed
  grants) and the #1450 refusals are unchanged.
  1. Auth is now a route property: peer routes under `/url4/peer/` are always verified, and peer
     headers elsewhere are refused (§5.5, R10).
  2. Share grants use `aud` = the resource node and `grantee` = the reader (§5.4, §5.5 steps 2 and 7).
  3. Exactly-once C6 execution goes through an atomic receiver idempotency store keyed by caller and
     key, with a fingerprint and saved-result replay. Three new codes (§5.9, R11).
  4. Nested remote calls inside a delegated run are refused with `x.peer_nested_call_refused`, and
     attenuation is deferred to a follow-up (§5.10, R12).
  5. Separate `typ` and an exact RFC 8725 profile per grant kind, with no `kind` claim (§5.4).
  6. RFC 9421 request-context profile: the verifier uses its configured authority, the raw path and
     query, duplicate fields refused, `url4` label selection (§5.3.1).

  §9 gains a test vector for each blocker. Q2–Q6 are unchanged and still open for Kevin.
- **2026-11-19 second round (HupBaHa, CHANGES_REQUESTED 15:42Z):** HupBaHa confirmed three fixes
  (share `aud`/`grantee`, nested-call refusal, separate JWT profiles). Four blockers remained, all
  fixed in this round:
  1. §5.9 is at-most-once: `claimed` → `dispatched` (before any external effect) → `completed`, with
     epoch fencing. A failure or expired lease after dispatch becomes `outcome_unknown` (new code),
     which is reconciled through provider idempotency keys (`op_id`) or by an operator, never re-run.
     The claim precedes the child run.
  2. The fingerprint is RFC 8785 JCS and now includes the `URL4-Auth-Token` digest and `trace`.
  3. §5.5 maps C6 `/v1` and C2 `/blob` onto the `/url4/peer` wire prefix: the caller rewrites, the
     signature covers it, and the receiver strips it after verification.
  4. §5.3.1 parses `Signature-Input`, `Signature` and `Content-Digest` as RFC 8941 dictionaries, with
     exactly one `url4` member and all other members refused.

  §9 vectors are added for each.
- **2026-11-19 third round (HupBaHa, CHANGES_REQUESTED 16:59Z):** four details made normative:
  1. §5.9: every transition is a fenced compare-and-set on `(phase, owner, epoch)`; taking a record
     from its owner bumps `epoch` and clears `owner`. An effect journal with deterministic provider
     keys is written before each send. Auto-reconciliation is bounded by the provider's dedup
     horizon; a manual re-run needs a proven stop and a proven negative outcome.
  2. The fingerprint fields have exact encodings and a golden JCS vector with its sha256.
  3. C6 is pinned to `@path=/url4/peer/v1` plus the `encode_subrequest` `q=` query. C2: no grant is
     `x.peer_auth_required`; an uncovered or missing digest is `source_not_found` (T9).
  4. Duplicate RFC 8941 dictionary keys are refused before the parser collapses them, with fixed
     vectors.
