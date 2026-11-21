# url4 peer paid execution: at-most-once C6

Status: **DRAFT** (2026-11-21). Not approved. Nothing here is implemented or enabled. Split out of the
node-to-node auth spec (`docs/spec/2026-10-22-OME-1599-node-to-node-auth.md`, PR #1647, OME-1599) in
its seventh review round, by owner decision: the at-most-once design had grown into a
durable-execution problem that is separate from authentication. Until this spec is approved and
implemented, C6 (`url4://` remote-node calls) stays refused with `x.remote_node_unsupported` (#1450
F1b), even on a node with peer auth configured.

## 1. Requirement (R11 of the auth spec)

Within a retention horizon, a paid C6 call starts its paid work **at most once** per
`(caller, Idempotency-Key)`, however often it is retried or duplicated. An outcome that cannot be
proven is reported, never re-run.

Inputs the auth spec fixes and this spec relies on: the request is already authenticated and
authorized (auth spec §5.5 steps 1–7); it carries exactly one `Idempotency-Key` (22 base64url
characters, covered by the signature); step 8 hands it here before any child run, execution or spend
exists.

## 2. Design (carried over from #1647 round six, head 8877e38b8)

The text below is §5.9 of the auth spec as of round six, moved unchanged apart from cross-references.
HupBaHa verified its golden vectors. Section 4 lists what round seven found still open; those points
are **not yet addressed** in this text.


Replay protection (auth spec §5.5 step 6) stops a captured request from being resent. It does not stop a legitimate
retry, which is re-signed with a fresh nonce on purpose (auth spec §5.3). Paid execution is made safe by the
receiver's **idempotency store**, not by the nonce. The url4 server does not deduplicate
`Idempotency-Key` today; this section is new behaviour that C6 requires.

**The guarantee.** Within the retention horizon (below), a `(caller, Idempotency-Key)` starts its
paid work **at most once**. If the receiver cannot prove whether that work happened, the call ends as
`outcome_unknown` and is reconciled. It is never run again automatically. A local compare-and-set
cannot fence a provider call that is already in flight, so the store never re-runs work that may
have reached a provider.

- **Key.** The record key is `(caller authority, Idempotency-Key)`. A C6 request must carry exactly one
  `Idempotency-Key`; a missing or malformed key (not 22 base64url characters) is
  `x.peer_idempotency_required`.
- **Request fingerprint.** Lowercase hex sha256 over the UTF-8 bytes of the RFC 8785 (JCS)
  serialization of this JSON object. Every key is always present, with `null` when absent:

  ```
  {"v":1, "method":…, "path":…, "query":…,        // auth spec §5.3.1 raw forms
   "content_digest":…,                             // the sha-256 member value, or null
   "auth_token_sha256":…,                          // sha256 hex of the URL4-Auth-Token bytes, or null
   "sub":…, "run":…, "trace":…, "scope":…, "budget":…}   // from the verified grant
  ```

  Exact encodings, so every replica computes the same bytes:
  - `v`: the integer `1`.
  - `method`: the request method as an uppercase JSON string.
  - `path`, `query`: the auth spec §5.3.1 `@path` and `@query` values as JSON strings, exactly the raw ASCII
    bytes received (still percent-encoded; `query` keeps its leading `?`, and is `"?"` when empty).
    A raw path or query byte outside printable ASCII (0x21–0x7E) is refused with
    `x.peer_auth_failed` at step 1, so no decoding choice is left.
  - `content_digest`: the 32 bytes of the `Content-Digest` `sha-256` member (decoded from its sf-binary
    base64), as 64 lowercase hex characters; `null` when the request has no `Content-Digest`.
  - `auth_token_sha256`: sha256 of the `URL4-Auth-Token` field value bytes, after removing leading and
    trailing whitespace (RFC 9110 field value), as 64 lowercase hex; `null` when the field is absent.
  - `sub`, `run`, `trace`: the grant's JSON strings, unchanged. `scope`: the grant's JSON array of
    strings, in the grant's order. `budget`: the grant's decimal string, unchanged (never parsed as a
    number), or `null`.

  Golden vector (normative): `GET`, `@path` `/url4/peer/v1`, `@query` `?q=(ctx)!%27Describe%27`, no body,
  `URL4-Auth-Token: v1.example-encrypted-credential`, grant `sub` `tenant-a`, `run` `run-42`, `trace`
  `4bf92f3577b34da6a3ce929d0e0e4736`, `scope` `["eval"]`, `budget` `"0.50"`. The JCS string is

  ```
  {"auth_token_sha256":"f0959e74a1f77de3a6fefc1df4b165d6e900f48ae9430b6d97c5bf2ebbaddb07","budget":"0.50","content_digest":null,"method":"GET","path":"/url4/peer/v1","query":"?q=(ctx)!%27Describe%27","run":"run-42","scope":["eval"],"sub":"tenant-a","trace":"4bf92f3577b34da6a3ce929d0e0e4736","v":1}
  ```

  and the fingerprint is `71bbdec257f2da3844aedb9747c522c3d78aa5ec28c6f29ca62511e94cbf8a7c`.

  - `URL4-Auth-Token` is in the fingerprint because the receiver decrypts it and uses the credential.
    A key reused with a different credential is a conflict, never a replay of the first credential's
    result. The caller must send the same token bytes on every retry.
  - `trace` is stable for a logical call, so it is fingerprinted. A retry under a new trace is a
    conflict.
  - Left out, because they legitimately change between retries: the signature, its nonce and
    `created`, and the grant's `iat`, `exp` and `jti`.
- **Claim (auth spec §5.5 step 8).** Before the child run is created and before any spend, one atomic
  insert-if-absent, shared by every replica serving the authority, creates
  `{phase: "claimed", fingerprint, incarnation, op_id, child_run_id, epoch: 1, owner, lease_until,
  journal: []}`. `incarnation` is 128 fresh random bits (22 base64url characters) drawn at insert and
  persisted; `op_id` and `child_run_id` are derived from it (below) and stored in the same write.
  Then:
  - inserted → proceed;
  - exists, different fingerprint → `x.peer_idempotency_conflict`;
  - exists, same fingerprint, `completed` → **replay the saved response** (same status, body and
    `x.` code), with no new execution and no new spend;
  - exists, same fingerprint, `outcome_unknown` or `abandoned` → `x.peer_outcome_unknown`;
  - exists, same fingerprint, `claimed`, `dispatched` or `reconciling` with a live lease →
    `x.peer_request_in_progress`;
  - exists, same fingerprint, `claimed` with an expired lease → takeover (state table).

  A key is never re-run once anything was sent under it. A caller that wants a fresh attempt after
  `x.peer_outcome_unknown` uses a **new** `Idempotency-Key`; that is a new logical call, and the
  caller owns the decision that a double effect is acceptable.
- **Child run (auth spec §5.5 step 9).** The child run's id is the `child_run_id` fixed in the claim, and it is
  created with create-if-absent on that id. A takeover reuses the same id, so a crash right after
  the child was created never leads to a second child. A `claimed` record is deleted only after the
  owner has cancelled that child run by id (fenced on the record), so no child is left orphaned.
- **Fenced transitions.** Every change to a record is one compare-and-set on the full expected state
  `(phase, owner, epoch)`. A write whose expected state no longer matches is rejected, and its result
  is discarded. A transition that takes the record away from an owner **bumps `epoch` and clears or
  replaces `owner` in the same write**. So a stalled owner that resumes fails every later write,
  including the one that would complete the record.
- **Identities (byte level).** Each value below is the lowercase hex sha256 of the UTF-8 bytes of the
  JCS serialization of a JSON object:
  - `op_id` = H(`{"v":2,"caller":<caller canonical authority>,"idempotency_key":<key>,"incarnation":<incarnation>}`),
    where `<key>` is the `Idempotency-Key` sf-string's 22 characters, without the quotes, as received.
    A key reused after the record's retention gets a new record, a new incarnation and so new
    provider keys; it can never pick up an old provider result.
  - `child_run_id` = H(`{"v":1,"op_id":<op_id>,"kind":"child_run"}`).
  - Effect key = `"u4-"` + H(`{"v":3,"op_id":<op_id>,"spawns":<spawns>,"node":<node>,"call":<call>}`):
    - `spawns`: the chain of dynamic spawns that leads to the effect, outermost first, as a JSON array
      of `[site, instance]` pairs. `site` is the spawning node's path **within the body that contains
      it** (a string of 0-based child indexes joined by `.`, root `"0"`). `instance` is the logical
      instance at that site: the input row index for a `MapNode`, and for a `LazyExpr` site or an
      `execute_node` call, the 0-based ordinal of that spawn at that site in program order, assigned
      before scheduling. `[]` when there is no spawn. Because every pair names its site, two sibling
      Maps, or two `LazyExpr` sites with identical body text, never share a key: their sites differ
      even when their compiled bodies are the same.
    - `node`: the effect's node path within the innermost spawned body (or the root plan when
      `spawns` is `[]`).
    - `call`: the integer ordinal of the effect within that one invocation, in the body's program
      order, never in journal-arrival order.
    - **Retries keep the key.** A physical retry of an effect, by a `;retry=` guard or after a
      transport error, is the same logical effect: it looks up its journal entry by
      `(spawns, node, call)` and resends with the journaled key. The attempt number is never part of
      the key.
  - The key is always exactly 67 ASCII bytes (`u4-` plus 64 lowercase hex). A provider is
    key-capable (below) only if it accepts that string **untruncated and unaltered**; a provider
    whose key field cannot hold it is treated as having no idempotency key. The key is never
    truncated or re-hashed.
  - The final provider key string is stored in the journal verbatim and re-sent from there. It is never
    recomputed.

  Golden vectors: caller `n1.example`, key `AAECAwQFBgcICQoLDA0ODw`, incarnation
  `EBESExQVFhcYGRobHB0eHw`:
  `{"caller":"n1.example","idempotency_key":"AAECAwQFBgcICQoLDA0ODw","incarnation":"EBESExQVFhcYGRobHB0eHw","v":2}`
  → `op_id` `3887a1dcfe3a0852fe5c259649ade837e37b5d419c02d95c928fb8b45c5aadd2`.
  - `child_run_id`: `{"kind":"child_run","op_id":"3887a1dc…5aadd2","v":1}` (full `op_id`) →
    `3f56f4003a5ab4424a1c90f9acd1a5e2c719065e63b881e8e124d6438982d203`.
  - Effect `node` `"0"`, `call` 0, with `spawns`:
    - `[]` →
      `{"call":0,"node":"0","op_id":"3887a1dcfe3a0852fe5c259649ade837e37b5d419c02d95c928fb8b45c5aadd2","spawns":[],"v":3}`
      → `u4-fedadae4395e2b447af0aef71352cc0a971a32d5cb08629b8248005a7f6d28fa`;
    - `[["0.1",0]]` (Map at site `0.1`, row 0) → `u4-76db6ca5a982341c21e18e826246247c9a2bdd5ee827e9950b54f88dfdfd5735`;
    - `[["0.2",0]]` (a sibling Map with the same body, row 0) → `u4-e57f7b4bd188773e7bb08d2722202f8c837a36b0c34677d2f7e733fc278ec616`;
    - `[["0.1",1]]` (row 1) → `u4-e1530bdae67d2f3bdbee3724f73611e2abcb6f60bcba4d55e22e4912c676d4bc`;
    - `[["0.1",0],["0.0",1]]` (a nested Map at site `0.0` of that body, row 1) →
      `u4-998a2a76a84da33b70f07e301956b15955250f65a79c340a504aaf256cdd32ec`.
- **Effect journal: a replay envelope.** Before each external effect (a paid call, an outbound fetch
  that costs), the owner appends a journal entry to the record by fenced compare-and-set. The entry
  is immutable once written and holds:
  - the identity `(spawns, node, call)` and the final provider key;
  - the provider and its declared capabilities (below);
  - the **exact request envelope**: method, URL, body bytes, and every header except credentials.
    Credential headers are stored only as a reference to the credential, which is resolved again at
    resend. The envelope is the request as built from its dependency outputs, so resending never
    recomputes those outputs;
  - once a response arrives, in a second fenced write: its status, headers and body bytes (the
    **response record**), before that output is used by any later node.

  Only after the entry is written is the effect sent. An effect not in the journal was never sent; an
  entry without a response record is **unanswered**. The node outputs a run builds from response
  records are recomputed deterministically from those records, so the run's result can be rebuilt
  from the journal alone. An envelope too large for the store (the store's per-record limit) makes
  that effect ineligible for reconciliation; it is still sent, and if it ends unanswered the record
  stays `outcome_unknown`.
- **Provider capabilities.** Each provider adapter declares three, statically:
  - `dedup_key`: accepts the 67-byte key untruncated and deduplicates on it;
  - `dedup_horizon`: how long it remembers a key;
  - `replays_response`: a duplicate request with the same key returns the **original** response
    (status and body), not an error or a fresh one.

  A provider that does not declare all three is not key-capable.
- **Phases.**
  - `claimed`: the journal is empty; nothing external has happened. The child run exists or is being
    created under `child_run_id`.
  - `dispatched`: at least one journal entry exists.
  - `completed`: the result is saved. Purgeable after retention.
  - `outcome_unknown`: some entry is unanswered and the owner is gone. Never purged.
  - `reconciling`: a reconciler holds the record.
  - `abandoned`: an operator closed it without provider evidence. Terminal, never purged, never
    re-run; retries get `x.peer_outcome_unknown`.
- **Reconciliation.** Allowed only when every unanswered entry's provider is key-capable
  (`dedup_key` and `replays_response`), its envelope is stored, and the earliest unanswered entry's
  journal time is inside the shortest `dedup_horizon` among those providers. The reconciler resumes
  the run from the journal: answered entries use their response records and are never resent;
  unanswered entries are resent from their envelopes with their journaled keys, and the provider's
  replayed response becomes the response record; any later effect the run then needs is journaled
  and sent as usual. The rebuilt result is saved as `completed`.
- **Operator resolution.** An operator may move `outcome_unknown` to `completed` only with
  **authoritative provider evidence** for every unanswered entry: the provider's own record that the
  request with that key executed, and its response. That evidence becomes the response record, and
  the result is rebuilt as in reconciliation. Without that evidence the operator may only move the
  record to `abandoned`. Neither path re-runs anything, and "not executed" from a provider is never
  enough, because a delayed request may still arrive.
- **The complete state table.** Each row is one fenced compare-and-set from `(phase, owner, epoch)`;
  any change not in this table is rejected.

  | From | To | When |
  |---|---|---|
  | absent | `(claimed, O, 1)` | claim insert with `incarnation`, `op_id`, `child_run_id` |
  | `(claimed, O, e)` | `(claimed, O, e)` | O renews its lease |
  | `(claimed, O, e)` | `(claimed, O′, e+1)` | O's lease expired; the next request with the same fingerprint takes over and reuses `child_run_id` |
  | `(claimed, O, e)` | absent | retryable failure before any effect; only after O cancelled the child run by id |
  | `(claimed, O, e)` | `(dispatched, O, e)` | first journal entry written |
  | `(claimed, O, e)` | `(completed, O, e)` | run finished with no effects; result saved |
  | `(dispatched, O, e)` | `(dispatched, O, e)` | lease renewal, a new journal entry, or a response record |
  | `(dispatched, O, e)` | `(completed, O, e)` | result saved; no entry is unanswered |
  | `(dispatched, O, e)` | `(outcome_unknown, none, e+1)` | O fails, or O's lease expires (any replica may write this) |
  | `(outcome_unknown, none, e)` | `(reconciling, R, e+1)` | reconciler R starts; reconciliation conditions hold |
  | `(reconciling, R, e)` | `(reconciling, R, e)` | lease renewal, a new journal entry, or a response record |
  | `(reconciling, R, e)` | `(completed, R, e)` | rebuilt result saved; no entry is unanswered |
  | `(reconciling, R, e)` | `(outcome_unknown, none, e+1)` | R fails, or R's lease expires |
  | `(outcome_unknown, none, e)` | `(completed, operator, e+1)` | authoritative provider evidence for every unanswered entry |
  | `(outcome_unknown, none, e)` | `(abandoned, operator, e+1)` | operator closes it without evidence |
  | `(completed, ·, e)` | absent | retention expired |

  A crashed owner or reconciler leaves a lease that expires; the expiry row moves the record on, and
  the resumed process then fails the fence.
- The caller surfaces `x.peer_outcome_unknown` and does not retry automatically.
- **Retention.** At least 24 h after the record reaches `completed`. `outcome_unknown`, `reconciling`
  and `abandoned` are never purged. Within retention a reused key replays or conflicts; after it, the
  key starts a new record with a new incarnation, so its provider keys are new too. Callers must not
  reuse a key for a different logical call; the fingerprint conflict catches it within retention.
- **Store unavailable** → fail closed with `x.peer_key_unavailable` (retryable) before any execution.
- The caller treats a replayed response exactly like the original.

## 3. Tests

Each test counts provider calls and spend at the receiver, using a
fake provider that can charge and then drop its response:
- Lost response after completion: a re-signed retry with the same key returns the saved response.
  Exactly one provider call is made.
- Concurrent duplicates: N parallel requests with the same key and fingerprint (across two replicas
  sharing the store) make one provider call. The others get `x.peer_request_in_progress` or the
  replayed result.
- Conflicts, each with zero provider calls → `x.peer_idempotency_conflict`. A conflict arises when the
  same key comes with a different:
  - body;
  - `sub` or `budget`;
  - `trace`;
  - `URL4-Auth-Token` (and the first token's saved response is not returned).
- Fingerprint vectors: the §2 golden vector gives exactly its JCS string and
  `71bbdec2…cbf8a7c`. Variants: no `URL4-Auth-Token` → `null`; a body → its `content_digest` hex; an
  empty query → `"?"`; a token with surrounding whitespace hashes the same as without. Two replicas
  compute the same fingerprint for the same request.
- Retryable failure while `claimed`: the record is deleted, and the retry makes one provider call.
- Provider charges, then its response is lost (the failure is in `dispatched`): the record becomes
  `outcome_unknown`, and a retry gets `x.peer_outcome_unknown` with zero further provider calls.
- Lease expiry in `dispatched` (the owner is paused mid-call, then resumes): no takeover. The record
  moves to `outcome_unknown` with `epoch + 1` and no owner. The resumed owner's completion is
  rejected by the fence (phase and epoch both differ), and there is one provider call in total.
- Identity vectors: the §2 `op_id`, `child_run_id` and effect-key golden vectors. Two concurrent
  branches whose effects journal in either arrival order get the same keys. Each of these runs twice,
  with the spawns completing in opposite orders, and gives the same distinct keys both times:
  - a `MapNode` over two rows;
  - two sibling Maps with identical bodies;
  - a Map nested in a Map;
  - two `LazyExpr` sites with identical body text;
  - two `execute_node` calls of the same node.

  A `;retry=` guard that retries an effect three times sends the same journaled key each time.
  Reconciliation re-sends the journaled key string byte for byte. A provider fake whose key field is
  shorter than 67 bytes is treated as not key-capable.
- Child run: a crash injected right after the child run is created and before the first journal
  entry; the takeover reuses the same `child_run_id`, and exactly one child run exists. A retryable
  failure in `claimed` cancels that child before the record is deleted, leaving no orphan.
- Replay envelope: reconciliation resends the stored envelope byte for byte (credentials resolved
  again), uses stored response records for answered entries without resending them, and rebuilds the
  same result as an uninterrupted run. A provider without `replays_response` makes the record
  ineligible. An over-limit envelope keeps the record `outcome_unknown`.
- Operator: `completed` is refused without provider evidence for each unanswered entry; `abandoned`
  is accepted, survives retention, and a retry gets `x.peer_outcome_unknown` with zero provider calls.
- Key reuse after retention: the record is purged, the same key is sent again, and the new record has
  a new incarnation, a new `op_id` and new provider keys; a provider fake that still remembers the old
  keys returns no old result.
- No re-run: there is no transition out of `outcome_unknown` except the two in the table; a retry with
  the same key keeps getting `x.peer_outcome_unknown` with zero provider calls, and a new key runs as
  a new call.
- State machine: every row of the §2 table, and every transition not in it (for example
  `outcome_unknown → claimed`, `abandoned → completed`, `dispatched → absent`) rejected by the fence.
  A reconciler killed
  mid-run leaves `reconciling`; after lease expiry the record is `outcome_unknown` and the old
  reconciler's completion is rejected.
- Journal before send: a failure injected between the journal write and the send leaves a journaled
  effect with no provider call; a send without a journal entry is impossible (asserted on the fake).
- Automatic reconciliation past the provider's dedup horizon is not attempted; the record stays
  `outcome_unknown`.
- Lease expiry in `claimed`: a takeover bumps `epoch`, and the stale owner's writes are rejected. One
  provider call is made in total.
- Reconciliation: with an idempotency-key provider fake, re-issuing with the same `op_id` keys
  completes the record, and the provider sees duplicates it deduplicates (one charge). With a
  provider that has no idempotency key, the record stays `outcome_unknown` until an operator saves a
  result.
- The claim exists before the child run: a failure injected between them leaves no orphan child run.
- A missing `Idempotency-Key`, and the store being down, refuse before any execution.

## 4. Open: HupBaHa's round-seven findings (2026-11-20, on #1647 at 8877e38b8)

Blockers:
1. **Retries: answered versus unanswered.** One key is reused and resent for every transport and
   `;retry=` attempt, but the capability gate applies only to reconciliation. Keep url4's
   "reuse until answered" rule. A retry proven to be pre-send may go ahead. An ambiguous no-response
   may be resent only with a stable dedup namespace and horizon; without dedup it becomes
   `outcome_unknown`. Any recorded response ends that logical effect, and a guard retry gets a fresh
   journal entry and key.
2. **Fence strength.** `(phase, owner, epoch)` can ABA-match after a `claimed` record is deleted and
   reinserted (epoch resets to 1). Include `incarnation`, a fresh lease token and a monotonic record
   revision in every mutation predicate. Enter a fenced `cancelling` phase before touching the child
   run, and require durable quiescence before deletion. Make journal identities unique.
3. **Credential namespace.** Re-resolving a credential reference at resend can move the same key into
   another provider idempotency namespace (rotation to another account, project, OAuth principal or
   endpoint). Journal an immutable, non-secret provider principal, namespace and version; resend only
   when the refreshed credential proves the same namespace, otherwise stay `outcome_unknown`.
4. **Payload retention and security.** Full request and response bodies can stay forever in
   `outcome_unknown` or `abandoned`. Require tenant-scoped encryption and audited access, and
   crypto-shred payloads once reconciliation is impossible or the record is abandoned, keeping only
   the minimal permanent tombstone that rejects key reuse.

Also:
5. `replays_response` must cover every semantic response header url4 consumes, not only status and
   body.
6. Define lookup-driven lease-expiry handling for `dispatched` and `reconciling`.

## 5. Review history

Six rounds on #1647 shaped section 2: receiver-side deduplication (round 1); `outcome_unknown` and a
full fingerprint (2); fenced transitions, effect journal and golden fingerprint (3); quoted C6
vector, effect identity and state machine (4); manual release removed, invocation coordinate and
record incarnation (5); child run id, spawn-site keys, replay envelope and `abandoned` (6).
