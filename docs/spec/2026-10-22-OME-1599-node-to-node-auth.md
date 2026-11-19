# OME-1599 — url4 node-to-node authentication

Status: **DRAFT** (2026-10-22). Not approved. Nothing here is implemented or enabled. Wire names, HTTP
statuses and `x.` codes are **proposed** until Kevin (url4 grammar and wire owner) signs them off; the
`url4/peer` parts need Ionésio's review. Until this spec is approved, spec #1450 (`OME-1535`) F1 and F1b
stand unchanged: every `url4://…/blob/…` ref fails with `x.remote_blob_unsupported` and every `url4://`
remote-node call with `x.remote_node_unsupported`, both before any I/O, and the #1521 peer allowlist
stays empty.

Revised 2026-10-28: every open question now carries a stated **working assumption** (§10), chosen as
the conservative option consistent with merged spec #1450, so the draft can be reviewed without
Kevin's live input. An assumption is not a decision; each one names what changes if Kevin answers
otherwise.

Revised 2026-11-19 for HupBaHa's review of PR #1647 (six protocol blockers):
1. Peer authentication is now a route property (§5.5); second round: the `url4://` → wire path
   mapping onto `/url4/peer`.
2. Share grants put the resource node in `aud` and the reader in `grantee` (§5.4).
3. Paid C6 calls are deduplicated at the receiver (§5.9); second round: at-most-once with
   `outcome_unknown` and reconciliation, and a full JCS fingerprint.
4. Nested remote calls under a delegated run are refused (§5.10).
5. The two grant kinds have separate, exact validation profiles (§5.4).
6. The RFC 9421 request context behind proxies is fixed (§5.3.1); second round: fields are parsed
   as RFC 8941 dictionaries holding exactly one `url4` member.

Third round (same day): every phase change in §5.9 is a fenced compare-and-set and the effect journal
is written before any send; the fingerprint has exact field encodings and a golden vector; C6 is
pinned to `@path=/url4/peer/v1` plus the `q=` query; C2 refusals follow the T9 rule; duplicate
dictionary keys are refused before parsing collapses them.

The direction (RFC 9421 plus signed grants) is unchanged, and #1450's fail-closed refusals still stand.

## Decisions requested from Kevin

Tick or overrule; details, consequences and the alternative for each are in §10.

- [x] **Q1** Resolved (owner decision, 2026-11-07, on Kevin's review): the grant travels in a new
  `URL4-Authz-Token` header; `URL4-Auth-Token` keeps its url4 meaning (encrypted credential). Node
  authentication is the RFC 9421 `Signature` that covers both.
- [ ] **Q2** No grammar change for C2: a share grant never appears in the expression; C2 stays refused
  (`x.remote_blob_unsupported`) until grant delivery is specified, and C6 ships first.
- [ ] **Q3** A node's identity **is** its canonical `url4://` authority; no separate node id.
- [ ] **Q4** Keys are discovered at `https://<authority>/.well-known/url4/node-keys` (JWKS), outside
  the url4 grammar.
- [ ] **Q5** The `x.peer_*` codes stay `x.`-prefixed extensions with the proposed statuses;
  `x.peer_auth_expired` is 401 and retryable once after re-signing.
- [ ] **Q6** A delegation grant's `sub` is opaque; the receiver maps `(peer, sub)` to a local tenant;
  url4 defines no cross-node tenant identity.

Not a Kevin decision: consent hooks (§10, note on Q7) are outside `OME-1599`'s scope.

## 1. Why, and what this gates

Spec #1450 sets a bar before two deferred features may ship:

- **C2, remote blobs** (F1, "Bar for the follow-up remote-blob spec"): `(img:src=url4://n2.example/blob/sha256/<hex>)`.
  The bar includes "authentication of the fetching node to the remote node" and a typed auth failure.
- **C6, remote-node expressions** (F1b): `(url4://n2.example/v1(…)!'Describe')!'Summarize'`. F1b
  requires "outbound identity, credential transport and rotation, inbound authorization, replay
  behaviour, typed auth failures and tests at both nodes".

The destination half of the bar already exists: the #1521 guard (`url4/io/_source_policy.py`,
`_guarded_transport.py`) enforces https-only, address-range refusal on every hop, IP pinning, redirect
and size caps, deadlines, and a `peer_hosts` allowlist that is empty by default. This spec supplies the
missing half: **who is calling, on whose behalf, and whether the receiver allows it.**

Current state on `origin/main` (drafted at `506c091`, re-verified at `6ea6a0011` on 2026-10-28):

| Fact | Where |
|---|---|
| A `url4://` target is rewritten to `https://` and sent with only `Idempotency-Key`; no credential | `url4/io/http.py` `_get` |
| A peer hop is allowed only if its host is in `SourceGuard.peer_hosts` (empty default) | `url4/io/_source_policy.py` `check_destination` |
| The node does no requestor authentication: "Deferred by design: … requestor authentication and consent hooks (they need the URL4-Auth-Token / Part C transport spec)" | `url4/peer/server.py:15-17` |
| `Url4Node(name=…)` has a free-form name, not a verifiable identity | `url4/peer/server.py` `__init__` |
| A digest is not a bearer capability; reads are tenant + run scoped, scope checked before any cache | spec #1450 F3 |

## 2. Threat model

**Assets.** Blob bytes (tenant data, possibly personal data); model spend at the receiving node (a C6
call runs paid model calls there); run results and attribution; the receiving node's outbound
egress (a C6 inner expression makes n2 fetch sources).

**Trust assumptions.** Each node's host and its signing key are trusted by that node's operator. TLS
WebPKI is trusted to bind a DNS name to a server. Operators agree out of band which peers they
federate with. Model-level prompt injection and a compromised node host are out of scope.

| # | Threat | Attacker | Required defence |
|---|---|---|---|
| T1 | Impersonation: an arbitrary client calls n2's eval path or blob route claiming to be n1 | Anyone on the internet | Caller authentication bound to n1's identity (R1) |
| T2 | Confused deputy: tenant A on n1 makes n1 fetch tenant B's blob from n2, or makes n2 run on B's budget | A tenant on an honest node | Authorization names tenant + run + operation, not just the node (R3) |
| T3 | Replay: a captured request (or its token) is resent to repeat a paid call or re-read a blob | Network observer, log reader, malicious peer | Short validity, single-use nonce, request-bound credential (R4) |
| T4 | Token forwarding: n2 reuses n1's credential to call n3 as n1 | A malicious peer | Audience binding to the receiving authority (R3) |
| T5 | Redirect leak: n2 (or a hop) redirects a signed request to another host, which harvests the credential | A malicious peer or a hop | No redirects on peer requests (R6) |
| T6 | Key-discovery spoofing: an attacker serves a fake public key for n1 | DNS or path attacker | Keys fetched over https through the #1521 guard, from the caller's own authority only (R2) |
| T7 | Unauthenticated amplification: an unauthenticated request makes n2 fetch keys from an attacker-chosen host (SSRF) | Anyone | Allowlist check on the claimed authority **before** any key fetch (R5) |
| T8 | Key compromise | Whoever steals a node key | Rotation with bounded cache lifetime; revocation (R7) |
| T9 | Existence oracle: probing digests at n2 to learn which blobs exist | Authenticated but unauthorized peer | Out-of-grant reads are `source_not_found`, identical to missing (F3) |
| T10 | Credential leakage through logs, spans or errors | Log reader | Tokens and signatures never logged or put in spans (R8) |

## 3. Requirements

- **R1** Every peer request authenticates the calling node's identity, bound to the exact request
  (method, authority, path, query, body digest).
- **R2** A node's identity is its url4 authority; its public keys are discoverable from that authority.
- **R3** The receiver authorizes per operation, on behalf of a tenant + run, with the credential bound
  to the receiving authority (audience).
- **R4** Replay is refused within the validity window and impossible after it.
- **R5** The receiver checks the claimed caller against its inbound peer allowlist before any I/O on
  the caller's behalf.
- **R6** Peer requests follow no redirects.
- **R7** Keys rotate without downtime; a compromised key's exposure is bounded and revocable.
- **R8** Every failure is a typed `x.` code with a fixed permanence class; secrets never reach logs.
- **R9** The defaults keep v1 behaviour: with no peer configured, C2 and C6 still refuse before any I/O
  with the v1 codes.
- **R10** Peer authentication is a property of the route, not of the request: a request cannot avoid
  it by omitting the signature.
- **R11** Within a retention horizon, a paid C6 call starts its paid work at most once per
  `(caller, Idempotency-Key)`, however often it is retried or duplicated; an unprovable outcome is
  reported and reconciled, never re-run.
- **R12** Delegation never broadens access across hops; until attenuation is specified, a delegated
  run makes no further remote calls.

## 4. Options

| | A. HTTP Message Signatures (RFC 9421) with per-node keys | B. Mutual TLS | C. Short-lived bearer tokens from a trust broker |
|---|---|---|---|
| Identity | Authority + key id; keys published by the authority | Client certificate subject / SAN | Broker-issued `sub` |
| Binding to the request | Yes: signature covers method, authority, path, query, `Content-Digest` | Connection only, not the request; nothing to forward but also nothing request-specific | None: a bearer token is replayable within its lifetime unless DPoP-style proof is added |
| Replay | `created`/`expires` + `nonce` in the signature | Not applicable at TLS layer; application replay still possible over a fresh connection by the same client | Lifetime + `jti` cache; theft = full use within lifetime |
| Works through proxies, TLS-terminating load balancers, Cloud Run, Cloudflare | Yes, end to end at HTTP layer | Poorly: client certs terminate at the LB; forwarding a cert header re-creates a bearer problem | Yes |
| Operational cost | One Ed25519 key per node, one JWKS file, a nonce cache | A private CA or cross-signed CAs per federation; cert issuance and revocation | A broker service every node depends on (availability and trust root for the whole federation) |
| Federation of independent operators | Natural: each operator owns its keys, peers opt in by allowlist | Needs a shared CA or per-pair trust stores | Needs a shared broker, or one per pair |
| Delegation (on behalf of a tenant + run) | Add a signed grant, covered by the signature | Not expressible; needs an extra token anyway | Native (claims), but the broker must know every node's tenants |
| Library support (Python) | `http-message-signatures` / small own implementation over `cryptography` Ed25519 | `ssl`/httpx native | `pyjwt`/`joserfc` |

Also considered and rejected: **allowlist only** (today's #1521 `peer_hosts`): it controls where the
caller goes, not who calls the receiver (F1b's own rationale); **static shared secrets per pair**:
bearer, no request binding, N² secrets, no rotation story.

**Choice: A**, with a signed delegation grant for the on-behalf-of part. B fails T3/T4 at the
application layer and breaks on the managed ingress the engine runs behind; C adds a central
dependency the federation does not have and is a bearer credential. A satisfies R1–R8 with one key
per node and no shared infrastructure. TLS stays mandatory underneath (the #1521 guard is https-only);
mTLS may be layered on later for private deployments without changing this protocol.

## 5. Recommended design

### 5.1 Node identity

- A node's identity is its **canonical authority**: the lowercase IDNA A-label host, plus `:port`
  only when it is not 443. It is the authority peers address it by in `url4://<authority>/…`; no
  separate naming scheme. `Url4Node.name` stays a display name.
- A node holds one or more **Ed25519** signing keys. Each has a `kid` (RFC 7638 JWK thumbprint,
  base64url). The HTTP signature `keyid` is `<authority>#<kid>`.
- The private key is a secret: loaded from the deployment's secret store (in the engine/aigateway, the
  ORMStore `credential_blobs` path, never the OS keychain), never logged, never in a span.

### 5.2 Key discovery

- Public keys are published at `https://<authority>/.well-known/url4/node-keys` as a JWKS
  (`{"keys":[{"kty":"OKP","crv":"Ed25519","x":…,"kid":…,"use":"sig","url4_status":"active"|"retiring"}]}`),
  media type `application/jwk-set+json`.
- The receiver fetches it **only for an authority already on its inbound peer allowlist** (§5.5 step
  2), **from that authority only**, through the #1521 guard with: https only, the address checks,
  **no redirects**, a 64 KiB cap, and the guard's deadlines.
- Cache: honour `Cache-Control: max-age`, clamped to [5 min, 24 h]; default 1 h. On an unknown `kid`
  the receiver refetches once, at most once per authority per 60 s. A failed refetch keeps serving
  cached keys until their clamped expiry.
- Optional operator **key pinning**: an inbound peer entry may list accepted `kid`s; then discovery is
  advisory and only pinned keys verify. Recommended for high-value peers; required where the peer's
  DNS is not trusted.

### 5.3 Outbound: signing a peer request

The caller builds the request, then signs it (RFC 9421) with label `url4`:

- Covered components: `"@method"`, `"@authority"`, `"@path"`, `"@query"`, `"url4-authz-token"`,
  `"url4-auth-token"` (when present), `"content-digest"` (RFC 9530, `sha-256`, when there is a body),
  `"idempotency-key"` (when present).
- Parameters: `created` (now), `expires` (`created + 60`), `nonce` (128 random bits, base64url),
  `keyid`, `alg="ed25519"`, `tag="url4-peer"`.
- Headers sent: `Signature-Input`, `Signature`, `URL4-Authz-Token` (§5.4), `URL4-Auth-Token` (only
  when the request carries a credential for the destination, §5.4), `Content-Digest` (if body).
- Every retry is re-signed (fresh `created` and `nonce`); the `Idempotency-Key` stays the same.
  Replay protection (§5.5 step 6) therefore accepts the retry. Running it at most once is the
  receiver's idempotency store (§5.9), not the nonce cache.
- A C6 request always carries an `Idempotency-Key` (128 random bits, base64url), generated once per
  logical call and kept across every retry of that call.
- **Peer requests follow no redirects** (R6, T5). A 3xx answer to a peer request is
  `x.source_destination_blocked` (the existing #1521 code), and the `Location` is not contacted.

#### 5.3.1 Request context profile (RFC 9421 §1.4)

RFC 9421 leaves the exact request inputs to the application profile. Behind TLS-terminating proxies,
url4 fixes them as follows. Signer and verifier compute the same values on HTTP/1.1, HTTP/2 and
HTTP/3.

| Component | Signer uses | Verifier uses |
|---|---|---|
| `@method` | the method, uppercase | the method, uppercase |
| `@authority` | the target's canonical authority (§5.1) | **its own configured canonical authority**, never `Host`, `:authority`, `Forwarded` or `X-Forwarded-Host` |
| `@path` | the raw request-target path as sent, still percent-encoded, with no normalization | the raw path as received (ASGI `raw_path`), byte for byte, not decoded or normalized |
| `@query` | the raw query including the leading `?`, or `?` when empty (RFC 9421 §2.2.7) | the raw query string as received, likewise |

- So a proxy may rewrite `Host` and may terminate TLS. It must forward the request-target, the body
  and the covered fields unchanged. A proxy that decodes or normalizes the path breaks verification
  (`x.peer_auth_failed`), which is the safe failure.
- The signer refuses to build a peer request whose path has a `.` or `..` segment, or an encoded
  `/` (`%2F`) or `\` (`%5C`). The verifier refuses such a request with `x.peer_auth_failed` before
  routing. A path that routes differently from what was signed cannot verify.
- **One field line each.** A request with more than one field line for `Signature-Input`,
  `Signature`, `Content-Digest`, `URL4-Authz-Token`, `URL4-Auth-Token` or `Idempotency-Key` is refused
  with `x.peer_auth_failed`. No combining rules apply.
- **Structured fields are parsed, not split on commas.** `Signature-Input`, `Signature` (RFC 9421) and
  `Content-Digest` (RFC 9530) are Structured Field dictionaries (RFC 8941). Each is parsed as one; a
  parse failure is `x.peer_auth_failed`.
  - **Duplicate keys are refused before the dictionary is built.** RFC 8941 §4.2.2 keeps the last
    value of a repeated key, so a check on the parsed result cannot see the repeat. The verifier
    parses the members in order and refuses with `x.peer_auth_failed` the moment a member name
    repeats (for example `url4=…, url4=…` or `sha-256=…, sha-256=…`). This is a deliberate
    deviation from RFC 8941's "last wins", for these three fields only.
  - `Signature-Input` and `Signature` must each hold **exactly one member, labelled `url4`**. Any
    other member is refused, so a peer request carries one signature only. That member must carry
    `tag="url4-peer"` and `alg="ed25519"` and cover at least the §5.3 components that apply to the
    request.
  - `Content-Digest` must hold exactly one member, `sha-256`.
  - `URL4-Authz-Token` is one compact JWS, `URL4-Auth-Token` one opaque token, and `Idempotency-Key`
    one sf-string (RFC 8941). None of them may contain a comma.
- `X-Forwarded-*` and `Forwarded` are never inputs to identity, authority or authorization.

### 5.4 `URL4-Authz-Token`: the authorization grant

`URL4-Authz-Token` carries a **grant**: a compact JWS. It says *on whose behalf and for what*; the
HTTP signature says *who is sending this exact request*. The token is covered by the signature, so it
cannot be lifted onto another request.

There are two kinds. Each has its own `typ`, and **the kind comes only from `typ`**: there is no `kind`
claim to branch on. Each route accepts exactly one kind: the eval route takes `delegation`, the blob
route takes `share`. A grant of the other kind on a route is `x.peer_auth_failed`.

| | `delegation` (C6) | `share` (C2) |
|---|---|---|
| Meaning | "Run this expression for my tenant T, run R" | "Reader P may read digest D of my tenant T, run R" |
| Issued and signed by | the **calling** node | the **resource** node (the blob owner) |
| Verified with | the caller's key (`iss`) | the receiver's **own** key |
| `typ` (exact) | `url4-delegation+jwt` | `url4-share+jwt` |
| `iss` | the caller's canonical authority; must equal the `keyid` authority | the resource node's canonical authority, which is the receiver itself |
| `aud` | the receiver's canonical authority (a single string) | the resource node's canonical authority (a single string), which is the receiver itself |
| `grantee` | absent | the reader's canonical authority; must equal the `keyid` authority |
| `sub` | the caller-side tenant id (opaque string, 1–128 chars) | the resource-side tenant id (string) |
| `run` | the caller's run id (string) | the resource-side run id (string) |
| `trace` | the trace id (32 lowercase hex) | absent |
| `scope` | exactly `["eval"]` | 1–64 entries, each `blob:read:sha256:<64 lowercase hex>` |
| `budget` | optional decimal string, USD, > 0 | absent |
| `iat`, `exp`, `jti` | required; `exp − iat ≤ 300 s` | required; `exp − iat ≤ 24 h` |

**Validation profile (RFC 8725), the same for both kinds apart from the table above:**
- The header has exactly `alg`, `typ` and `kid`. `alg` is exactly `EdDSA` and `typ` is exactly the
  route's kind. `kid` names a key of the issuer. Any `crit`, `jku`, `jwk`, `x5u` or `x5c` →
  `x.peer_auth_failed`.
- Required claims must be present with the types in the table. A claim that is absent in the table
  must be absent. Unknown claims are ignored.
- `iat` may not be later than `now + 30 s` (skew). `exp` must be later than `now`. The lifetime cap
  holds. There is no `nbf`.
- `jti` is 128 random bits, base64url. It is recorded for provenance; replay is caught by the
  signature nonce (§5.5 step 6), not by `jti`.

A share grant is self-issued: `iss` and `aud` both name the resource node, and the reader is bound
through `grantee`. So it verifies only with the **receiving** node's own key, and a node can never
issue a `share` for another node's data. A blob uploaded under identity A on n2 is readable by n1 only
if n2 issued n1 a share grant naming that digest (the `OME-1599` acceptance "A's blob can't be fetched
by B without a grant"). A grant whose `grantee` is a different node fails step 2, so a share grant
cannot be forwarded either.

**Relation to `URL4-Auth-Token`.** The two headers are separate. `URL4-Auth-Token` keeps its url4
meaning (Part B §3.5, Part H §31): an encrypted credential carried from the originating requestor to
the destination node, which decrypts it and uses it, for example toward a non-url4 source. This spec
neither defines nor verifies its contents; when present it is only covered by the signature (§5.3).
`URL4-Authz-Token` is the authorization grant this spec defines, the receiver checks it before
execution (§5.5), and it never carries a credential. Open note: Part H §31 still calls the
credential header `ABC-Auth-Token`, a naming inconsistency in the url4 spec; this draft uses
`URL4-Auth-Token` and leaves the fix to the spec owner.

How a share grant reaches the reader is **open** (Q2). Working assumption: never in the expression;
C2 stays refused until delivery is specified (§10).

### 5.5 Inbound: the receiver's order (normative)

**Peer authentication is a route property (R10).** It does not depend on whether a request happens to
carry a signature.
- A node that enables C2 or C6 serves peer traffic only on its **peer routes**, under one prefix,
  `/url4/peer`. They are mounted behind the verifier, so every request on them, signed or not, runs
  the steps below. A request with no signature there is `x.peer_auth_required`. Nothing on a peer
  route can be reached without step 7 passing.
- **Address mapping.** The url4 addresses #1450 governs keep their form in expressions. Only the wire
  path gains the prefix:

  | In the expression | Outbound rewrite (caller) | Signed `@path` | Receiver dispatch |
  |---|---|---|---|
  | C6 `url4://n2.example/v1(…)!…` | `https://n2.example/url4/peer/v1?q=…` | `@path` exactly `/url4/peer/v1`; `@query` exactly `?[params&]q=…` as built by `encode_subrequest` | strip `/url4/peer` once, then run the existing `/v1` eval handler on the unchanged raw query |
  | C2 `url4://n2.example/blob/sha256/<hex>` | `https://n2.example/url4/peer/blob/sha256/<hex>` | `/url4/peer/blob/sha256/<hex>` | strip `/url4/peer` once, then run the existing blob handler |

  C6 carries the expression in the query, as url4 does today: `@path` is exactly `/url4/peer/v1`, with
  no further segments, and `@query` is the raw query that `url4.wire.subrequest.encode_subrequest`
  produces, ending in `q=` and the wire-escaped expression (`q` is always last, spec §8). Example:
  `@path` = `/url4/peer/v1`, `@query` = `?q=(ctx)!Describe`. The receiver hands that raw query, byte for
  byte, to `extract_expression_params`; it never re-encodes it. Any other path under
  `/url4/peer/v1/…` is 404.

  The caller's `url4://` → `https://` rewrite (today `url4/io/http.py`) inserts `/url4/peer` before
  the path, for peer targets only. The signature always covers the prefixed wire path. The receiver
  strips the prefix only after step 7 succeeds, and passes the verified peer context with the
  request. The bare `/v1` and `/blob` routes stay non-peer, so a peer header there is refused (next
  point). There is no second way in.
- No other HTTP route establishes a peer context. A request on any other route that carries
  `Signature-Input`, `Signature` or `URL4-Authz-Token` is refused with `x.peer_auth_failed`. The peer
  headers are never ignored and never half-honoured.
- The node's non-peer routes keep the front-door authentication they have today, which is outside
  this spec (§11). In-process SDK calls do not go through HTTP, so they need no peer authentication.
- A node with C2 and C6 off mounts no peer routes, so the prefix answers 404 (R9).

For every request on a peer route, in this order:

1. **Parse** `Signature-Input`/`Signature` (label `url4`, §5.3.1) and `URL4-Authz-Token`. If either is
   missing → `x.peer_auth_required`. A duplicate field or a malformed member → `x.peer_auth_failed`.
   `URL4-Auth-Token` is not needed for authorization; if present it must be among the covered
   components, otherwise `x.peer_auth_failed`.
2. **Allowlist before I/O** (R5, T7): the `keyid` authority must equal the grant's `iss` (delegation)
   or `grantee` (share), and must be on the receiver's **inbound peer allowlist**. Otherwise
   `x.peer_not_authorized`. No key fetch happens for an unlisted authority. The grant's payload is read
   here only to find that authority; nothing in it is trusted until step 4.
3. **Resolve the key** from cache or discovery (§5.2). Unreachable discovery with no cached key →
   `x.peer_key_unavailable`.
4. **Verify** the HTTP signature over the covered components (§5.3.1 inputs), `Content-Digest`
   against the body, and the grant's JWS under the route's validation profile (§5.4; delegation: the
   caller's key; share: the receiver's own key). Any mismatch → `x.peer_auth_failed`.
5. **Freshness:** `created` within ±30 s of the receiver's clock, `expires` not passed,
   `expires - created ≤ 60`; grant `exp` not passed. Otherwise `x.peer_auth_expired`.
6. **Replay:** `(keyid, nonce)` must be unseen within `window = 60 s + 2 × 30 s skew`; record it.
   A repeat → `x.peer_replay`. The nonce store is shared by all replicas serving one authority; if it
   is unavailable the receiver fails closed with `x.peer_key_unavailable` (retryable).
7. **Authorize:**
   - The grant's `aud` must equal the receiver's own canonical authority, for both kinds. For a share
     grant, `iss` must too, and `grantee` must equal the `keyid` authority.
   - `scope` must cover the operation: `eval` on the eval route, or `blob:read:sha256:<hex>` for
     exactly the requested blob.
   - The peer's allowlist entry must permit that scope.

   Any failure → `x.peer_not_authorized`, with one exception (T9): on the blob route, a verified share
   grant whose `scope` does not cover the requested digest is `source_not_found`, the same answer as a
   covered digest that is missing from the store (step 10). So a reader cannot tell "not granted" from
   "does not exist". No grant at all is `x.peer_auth_required` (step 1). Nested delegation is stopped where the delegated run
   executes (§5.10), not here.
8. **C6 only: claim the idempotency record** (§5.9) before anything else is created. No child run,
   execution or spend exists without a claim.
9. **Bind a local run context** (taken from the verified grant, never from the expression):
   - C6 (`delegation`): the operator maps `(peer authority, sub)` to a local tenant (default: one
     local tenant per peer, `peer:<authority>`); the receiver opens a **new child run** under it,
     carrying `trace` and the caller's run id as attribution. `budget`, if present, caps that run's
     spend, and the peer entry's own cap applies regardless.
   - C2 (`share`): tenant = `sub`, run = `run` from the receiver's own share grant.
10. **Then** spec #1450 F3's order runs unchanged: authorize the digest against that tenant + run,
    verify sha256, and only then touch caches. An in-grant digest missing from the store, and any
    out-of-scope digest, is `source_not_found` (T9).

### 5.6 Inbound peer allowlist (receiver configuration)

Separate from the outbound `SourceGuard.peer_hosts`:

```
inbound_peers:
  n1.example:
    scopes: [eval]            # and/or blob:read
    tenant: peer:n1.example   # or a sub→tenant map
    pinned_kids: []           # optional §5.2 pinning
    max_cost_usd_per_run: 5
```

Empty by default: no peer can call in.

### 5.7 Key rotation and revocation

- **Publish before use:** a new key enters the JWKS as `active` at least **24 h** (the max cache
  clamp) before the node signs with it.
- **Retire after use:** the old key stays as `retiring` for at least `24 h + 60 s` after the last
  signature it made, then is removed.
- **Emergency revocation:** remove the key from the JWKS; receivers drop it on their next refetch
  (≤ 24 h, or immediately on operator command or on a pinned-kid change). Operators of high-value
  peers should pin kids so revocation is a config change on their side.
- A grant signed with a removed key fails step 4.

### 5.8 Failure codes

All codes follow #1450 §4's wrapping rule: the calling node re-raises the receiver's code with its
permanence unchanged and adds the node path; only retryable codes are retried. Response bodies carry
the code and a generic message, never the token, signature or which component mismatched.

| Code | Owner | Status (proposed) | Class | When |
|---|---|---|---|---|
| `x.peer_auth_required` | receiving node | 401 | permanent | §5.5 step 1: signature or `URL4-Authz-Token` missing |
| `x.peer_not_authorized` | receiving node | 403 | permanent | steps 2, 7 |
| `x.peer_key_unavailable` | receiving node | 503 | retryable | step 3; nonce store down (step 6) |
| `x.peer_auth_failed` | receiving node | 401 | permanent | step 4 (signature, `Content-Digest` or `URL4-Authz-Token` JWS); step 1 (`URL4-Auth-Token` present but not covered) |
| `x.peer_auth_expired` | receiving node | 401 | retryable (re-signed; at most once) | step 5; repeated failure means clock skew |
| `x.peer_replay` | receiving node | 401 | permanent | step 6 |
| `x.peer_idempotency_required` | receiving node | 400 | permanent | §5.9: C6 request without exactly one `Idempotency-Key` |
| `x.peer_request_in_progress` | receiving node | 409 | retryable (with backoff) | §5.9: the same call is still running |
| `x.peer_outcome_unknown` | receiving node | 409 | permanent for automatic retry; resolved by reconciliation | §5.9: paid work may have happened and cannot be proven either way |
| `x.peer_idempotency_conflict` | receiving node | 422 | permanent | §5.9: same key, different request fingerprint |
| `x.peer_nested_call_refused` | the node hosting the delegated run | 422 | permanent | §5.10: a remote call from inside a delegated run; before any I/O |
| `x.peer_signing_unconfigured` | calling node | 500 | permanent | caller has a configured peer but no signing key; before any I/O |
| `x.remote_node_unsupported` / `x.remote_blob_unsupported` | calling node resolver | 422 | permanent | unchanged from #1450: the target authority is not a configured outbound peer (or the feature is off); before any I/O |
| `x.source_destination_blocked` | #1521 guard | 422 | permanent | unchanged, plus a redirect on a peer request (§5.3) |

This closes #1450 §4's "remote-node authentication failure has no v1 owner".

### 5.9 At-most-once paid execution for C6 (R11)

Replay protection (step 6) stops a captured request from being resent. It does not stop a legitimate
retry, which is re-signed with a fresh nonce on purpose (§5.3). Paid execution is made safe by the
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
  {"v":1, "method":…, "path":…, "query":…,        // §5.3.1 raw forms
   "content_digest":…,                             // the sha-256 member value, or null
   "auth_token_sha256":…,                          // sha256 hex of the URL4-Auth-Token bytes, or null
   "sub":…, "run":…, "trace":…, "scope":…, "budget":…}   // from the verified grant
  ```

  Exact encodings, so every replica computes the same bytes:
  - `v`: the integer `1`.
  - `method`: the request method as an uppercase JSON string.
  - `path`, `query`: the §5.3.1 `@path` and `@query` values as JSON strings, exactly the raw ASCII
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

  Golden vector (normative): `GET`, `@path` `/url4/peer/v1`, `@query` `?q=(ctx)!Describe`, no body,
  `URL4-Auth-Token: v1.example-encrypted-credential`, grant `sub` `tenant-a`, `run` `run-42`, `trace`
  `4bf92f3577b34da6a3ce929d0e0e4736`, `scope` `["eval"]`, `budget` `"0.50"`. The JCS string is

  ```
  {"auth_token_sha256":"f0959e74a1f77de3a6fefc1df4b165d6e900f48ae9430b6d97c5bf2ebbaddb07","budget":"0.50","content_digest":null,"method":"GET","path":"/url4/peer/v1","query":"?q=(ctx)!Describe","run":"run-42","scope":["eval"],"sub":"tenant-a","trace":"4bf92f3577b34da6a3ce929d0e0e4736","v":1}
  ```

  and the fingerprint is `428854ee62ad9cd0361f495da98fd7601bd4d3dd65c205998c7529700674b917`.

  - `URL4-Auth-Token` is in the fingerprint because the receiver decrypts it and uses the credential.
    A key reused with a different credential is a conflict, never a replay of the first credential's
    result. The caller must send the same token bytes on every retry.
  - `trace` is stable for a logical call, so it is fingerprinted. A retry under a new trace is a
    conflict.
  - Left out, because they legitimately change between retries: the signature, its nonce and
    `created`, and the grant's `iat`, `exp` and `jti`.
- **Claim (§5.5 step 8).** Before the child run is created and before any spend, one atomic
  insert-if-absent, shared by every replica serving the authority, creates
  `{phase: "claimed", fingerprint, op_id, epoch: 1, owner, lease_until}`. `op_id` is
  `sha256(caller authority ‖ Idempotency-Key)`, the stable operation identity. Then:
  - inserted → proceed;
  - exists, different fingerprint → `x.peer_idempotency_conflict`;
  - exists, same fingerprint, `completed` → **replay the saved response** (same status, body and
    `x.` code), with no new execution and no new spend;
  - exists, same fingerprint, `outcome_unknown` → `x.peer_outcome_unknown`;
  - exists, same fingerprint, `claimed` or `dispatched` with a live lease → `x.peer_request_in_progress`.
- **Fenced transitions.** Every phase change is one compare-and-set on the full expected state
  `(phase, owner, epoch)`. A write whose expected state no longer matches is rejected, and its result
  is discarded. A transition that takes the record away from an owner (takeover, or a move to
  `outcome_unknown`) **bumps `epoch` and clears `owner` in the same write**. So a stalled owner that
  resumes fails every later write, including the one that would complete the record.
- **Effect journal.** Before each external effect (a paid call, an outbound fetch that costs), the
  owner appends to the record, by the fenced compare-and-set above, an effect descriptor: provider,
  operation, the request digest, and a deterministic provider idempotency key `op_id ‖ "/" ‖ n`, where
  `n` is the effect's 0-based index in the run. Only after that write succeeds is the effect sent,
  with that key where the provider supports one. An effect that is not in the journal was never sent.
- **Phases.**
  - `claimed`: nothing external has happened yet. The child run is opened under the claim.
  - `dispatched`: set by fenced compare-and-set `claimed → dispatched` together with the first journal
    entry, before the first send.
  - `completed`: `dispatched → completed` (or `claimed → completed` for a run with no effects), by
    fenced compare-and-set, saving the result.
  - `outcome_unknown`: terminal until reconciled.
- **Failures and expired leases.**
  - Retryable failure while `claimed` (nothing external happened): the owner deletes the record by
    fenced compare-and-set, so a retry runs normally.
  - Expired lease while `claimed`: the next retry takes over by fenced compare-and-set, bumping `epoch`.
    The old owner's later writes fail, and it had sent nothing, because sending needs a journal write.
  - Any failure, or an expired lease, while `dispatched`: fenced compare-and-set
    `(dispatched, owner, epoch) → (outcome_unknown, owner: none, epoch + 1)`. The record is **never
    deleted and never taken over** for re-execution, because a provider may already have charged or
    acted. The old owner's completion now fails the fence.
- **Reconciliation of `outcome_unknown`.**
  - Automatic, only when every journaled effect went to a provider that deduplicates by idempotency
    key **and** the record is still inside that provider's documented dedup horizon (measured from the
    effect's journal time). The reconciler takes the record by fenced compare-and-set (bumping
    `epoch`), re-issues exactly the journaled effects with their journaled keys, saves the result and
    moves to `completed`. Past the shortest horizon among the journaled providers, automatic
    reconciliation is off.
  - Otherwise an operator resolves it. "Mark completed with a result" is always allowed. "Release,
    safe to re-run" needs both: (a) a **proven stop**, meaning the old owner's process is confirmed
    gone or its epoch is fenced (it is, by the transition above) **and** its lease has expired; and
    (b) a **proven negative outcome** for every journaled effect, meaning the provider reports that
    key as not executed or not charged. Without (b) the record stays `outcome_unknown`.
  - The caller surfaces `x.peer_outcome_unknown` and does not retry automatically.
- **Retention.** At least 24 h after the record reaches `completed` or is released, and never while it
  is `outcome_unknown`. The guarantee holds only inside this horizon. A key reused after it is a new
  call.
- **Store unavailable** → fail closed with `x.peer_key_unavailable` (retryable) before any execution.
- The caller treats a replayed response exactly like the original.

### 5.10 Nested delegation (R12)

A delegated run gets no enforceable parent scope, budget or expiry at a third node, so the first C6
slice does not allow chains:
- A child run opened from a delegation grant (§5.5 step 9) has C2 and C6 **off**, whatever the node's
  own settings. A `url4://` peer target or a remote blob ref inside it fails with
  `x.peer_nested_call_refused` before any I/O. No socket is opened and no grant is minted.
- The refusal happens at the node that hosts the delegated run, because only that node knows the run
  is delegated. The run's provenance (`run` and `trace` from the grant) is recorded with the failure.
- Allowing chains later needs an attenuation rule: a child grant is the intersection of the parent's
  scope, budget and expiry, carries a verifiable link to the parent grant, and every hop re-checks the
  whole chain. That is a follow-up spec, not this one.

## 6. With the #1521 guard

The guard stays the **destination** policy; this spec adds the **caller** policy. Outbound order
for a `url4://` peer target (C6) or blob ref (C2):

1. Classify the ref (unchanged). Authority not a configured outbound peer → v1 code, before I/O (R9).
2. Feature switch for that kind (C2, C6) off → v1 code, before I/O.
3. No signing key → `x.peer_signing_unconfigured`, before I/O.
4. Guard: https, address ranges, IP pinning (as today, with `peer=True`).
5. Build, attach grant, sign, send with redirects disabled; size cap and deadlines as today.

An outbound peer entry is added to `peer_hosts` only together with this signing configuration, so
"the allowlist stays empty until the auth spec exists" becomes "a peer is listed only when its
requests are signed". The guard's `trusted_first_hop` (the operator's `base_url`) never applies to a
`url4://` target.

## 7. Enabling C2 and C6

- **C6 first.** It needs §5.1–5.10: the delegation grant, the idempotency store (§5.9) and the
  nested-call refusal (§5.10). The receiver resolves inner sources
  against its own store under the child run (#1450 §3, row C6: "n2 resolves C3 against its own store"); a C3
  bare blob in the inner expression therefore resolves only to blobs ingested into that child run.
- **C2 second.** It also needs the share-grant delivery (Q2; assumed out of band, so a follow-up) and the rest of F1's remote-blob bar
  (media-type sniffing, per-run file count and byte limits). Fetched bytes are written through to the
  caller's tenant + run store and verified (F3), and the share grant's `jti` is recorded as provenance.
- Both stay off by default per node and per peer; the v1 refusals remain the behaviour of an
  unconfigured node.

## 8. Attribution and telemetry

- Where envelopes exist, record `url4_aware: true`, the peer authority, the `keyid`, and the grant
  `jti` and kind. Never the token or signature.
- OTel: one `trace_id` across the tree (url4-engine doctrine). Span attributes `url4.peer.authority`,
  `url4.peer.kid`, `url4.grant.kind`, `url4.grant.jti`; failures set the `x.peer_*` code.

## 9. Tests (both nodes)

Caller side:
- Signs exactly the §5.3 components; a body change breaks `Content-Digest`.
- Re-signs every retry with a fresh nonce and the same `Idempotency-Key`.
- Refuses a 3xx on a peer request without contacting `Location`.
- Unconfigured peer → v1 code with zero sockets opened; configured peer without a key →
  `x.peer_signing_unconfigured` with zero sockets.
- Wraps each receiver code preserving permanence; retries only the retryable ones.

Receiver side (one test per §5.5 step, in order):
- Missing signature on a peer-only route → `x.peer_auth_required`.
- Unlisted authority → `x.peer_not_authorized` and **no** JWKS fetch (assert zero outbound calls).
- Bad signature, tampered path/query/body/token, wrong-key grant → `x.peer_auth_failed`.
- `created` outside skew, expired grant → `x.peer_auth_expired`.
- Same `(keyid, nonce)` twice → second is `x.peer_replay`; two replicas sharing the store agree.
- `aud` of another node (forwarded token, T4) → `x.peer_not_authorized`.
- Share grant for digest D, request for D' → `source_not_found`, identical to a missing blob, and no
  cache or frozen-copy read (F3 order).
- Rotation: overlap period accepts both keys; removed key fails after refetch.
- End to end with two in-process nodes over ASGI: C6 happy path with trace propagation and child-run
  budget; C2 happy path with a share grant.

Route property (§5.5, R10):
- Every route the app mounts under `/url4/peer/` is enumerated from the router, and an unsigned request
  to each is `x.peer_auth_required` (this catches a peer route added without the verifier).
- Peer headers on a non-peer route → `x.peer_auth_failed`, and no peer context is bound.
- With C2 and C6 off, `/url4/peer/…` is 404 and no verifier code runs.

Grant profiles (§5.4):
- A share grant with `aud` = the receiver, `iss` = the receiver and `grantee` = the caller verifies.
  With `grantee` set to a third node it fails step 2. With `aud` set to the reader (the old shape) it
  fails step 7.
- A delegation grant on the blob route, and a share grant on the eval route → `x.peer_auth_failed`.
- Each profile rule fails on its own: wrong `alg` (including `none` and `HS256` with the public key as
  secret), wrong `typ`, `crit` present, `jku`/`jwk`/`x5u` present, a missing required claim, a claim
  that must be absent present, wrong claim types, `iat` in the future beyond skew, and a lifetime
  over the cap.

Request context (§5.3.1), each as a fixed vector (raw request plus expected signature base):
- An encoded path (`/url4/peer/blob/sha256/ab%20cd`, a UTF-8 `%C3%A9` segment) verifies byte for
  byte. The same path decoded by a proxy fails.
- `%2F`, `%5C`, `.` and `..` segments are refused by the signer and by the verifier.
- Query: `?a=1&b=2` versus `?b=2&a=1` gives different bases. An empty query signs as `?`. `+` and
  `%20` are not interchanged.
- The same signed request verifies over HTTP/1.1 and HTTP/2, and when a proxy rewrote `Host` or added
  `X-Forwarded-Host`. It fails when signed for another authority.
- A second field line for any of the six fields → `x.peer_auth_failed`.
- `Signature-Input`/`Signature` parsed as RFC 8941 dictionaries: a lone `url4` member verifies. The
  following each give `x.peer_auth_failed`:
  - `url4` plus any other member (`url4=…, other=…`);
  - two `url4` members;
  - only other members;
  - a `url4` member without `tag="url4-peer"`;
  - a value that does not parse as a dictionary.
- `Content-Digest` with a member other than `sha-256`, or with two members → `x.peer_auth_failed`.
- Duplicate keys, refused before the dictionary collapses them, each as a fixed raw field value →
  `x.peer_auth_failed`:
  - `Signature-Input: url4=("@method");tag="url4-peer", url4=("@path");tag="url4-peer"`;
  - `Signature: url4=:AAAA:, url4=:BBBB:`;
  - `Content-Digest: sha-256=:<valid>:, sha-256=:<other>:`, also with the valid value last.
  A plain RFC 8941 parser would keep the last member in each; the test asserts the refusal.
- Raw path or query bytes outside 0x21–0x7E → `x.peer_auth_failed` before routing.
  A comma inside `URL4-Authz-Token`, `URL4-Auth-Token` or `Idempotency-Key` → `x.peer_auth_failed`.

At-most-once execution (§5.9). Each test counts provider calls and spend at the receiver, using a
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
- Fingerprint vectors: the §5.9 golden vector gives exactly its JCS string and
  `428854ee…674b917`. Variants: no `URL4-Auth-Token` → `null`; a body → its `content_digest` hex; an
  empty query → `"?"`; a token with surrounding whitespace hashes the same as without. Two replicas
  compute the same fingerprint for the same request.
- Retryable failure while `claimed`: the record is deleted, and the retry makes one provider call.
- Provider charges, then its response is lost (the failure is in `dispatched`): the record becomes
  `outcome_unknown`, and a retry gets `x.peer_outcome_unknown` with zero further provider calls.
- Lease expiry in `dispatched` (the owner is paused mid-call, then resumes): no takeover. The record
  moves to `outcome_unknown` with `epoch + 1` and no owner. The resumed owner's completion is
  rejected by the fence (phase and epoch both differ), and there is one provider call in total.
- A manual "safe to re-run" racing a zombie: the release is refused until the lease has expired and
  every journaled key has a negative provider outcome. A zombie that passed its pre-send journal
  write still sends with the journaled key, so the provider deduplicates it.
- Journal before send: a failure injected between the journal write and the send leaves a journaled
  effect with no provider call; a send without a journal entry is impossible (asserted on the fake).
- Automatic reconciliation past the provider's dedup horizon is not attempted; the record stays
  `outcome_unknown`.
- Lease expiry in `claimed`: a takeover bumps `epoch`, and the stale owner's writes are rejected. One
  provider call is made in total.
- Reconciliation: with an idempotency-key provider fake, re-issuing with the same `op_id` keys
  completes the record, and the provider sees duplicates it deduplicates (one charge). With a
  provider that has no idempotency key, the record stays `outcome_unknown` until operator release.
- The claim exists before the child run: a failure injected between them leaves no orphan child run.
- A missing `Idempotency-Key`, and the store being down, refuse before any execution.

Address mapping (§5.5), end to end over ASGI with the exact #1450 expressions:
- C6: `(url4://n2.example/v1(…)!'Describe')!'Summarize'`. n1 sends
  `https://n2.example/url4/peer/v1…`, the signature covers that path, and n2 strips the prefix after
  verification and runs its `/v1` handler. The trace and child run are asserted.
- C2: `(img:src=url4://n2.example/blob/sha256/<hex>)` with a share grant →
  `/url4/peer/blob/sha256/<hex>` at n2 and the bytes are returned. With no grant →
  `x.peer_auth_required`. With a verified grant for another digest → `source_not_found`, identical to
  a covered digest that is missing.
- C6 wire form: the signed request has `@path` exactly `/url4/peer/v1` and `@query` exactly what
  `encode_subrequest` built (for example `?q=(ctx)!Describe`); n2's `extract_expression_params` gets
  that raw query unchanged. `/url4/peer/v1/extra` → 404.
- A signed request sent to bare `/v1` or `/blob/…` → `x.peer_auth_failed`. A request that is valid
  for `/url4/peer/v1…` and replayed with its path rewritten to `/v1…` fails.
- A prefix is stripped exactly once: `/url4/peer/url4/peer/v1` does not reach `/v1`.

Nested delegation (§5.10):
- Three nodes n1 → n2 → n3: the expression delegated to n2 contains a `url4://n3/…` call. n2 refuses
  with `x.peer_nested_call_refused`, n3 receives zero requests, and n2 opens zero sockets.
- The same refusal holds for a remote blob ref in the delegated run, for a delegated budget larger
  than n2's peer cap, and for a grant whose `exp` is later than the parent's. Each attempt to widen
  scope, budget or expiry is refused before any I/O.

## 10. Open questions for Kevin, with working assumptions

Each assumption is the conservative option consistent with spec #1450 (F1, F1b, F3, §4): it opens
nothing #1450 keeps closed and changes no grammar. Overruling one changes only the sections named.

**Q1 `URL4-Auth-Token` semantics. Resolved** by owner decision (Sergey, 2026-11-07) on Kevin's review
of PR #1647. `URL4-Auth-Token` keeps the url4 meaning: an encrypted credential carried from the
originating requestor to the destination node (Part B §3.5, Part H §31). The §5.4 grant moves to a new
`URL4-Authz-Token` header. This fills the authorization gap Kevin cites: Part B §5.4.2 (identity-based
access control on every url4-aware fetch), §5.6.4 (authorize the effective requestor, never ambient
authority), §5.6.9 (delegation never broadens access); Part C §11.6.2 (provenance in request headers,
TBD); Part H §29.2.1 (consumer-set disclosure), §31 (sender identity in the token), §33 (identity model
open), §35 (per-hop path header). Open note: Part H §31 still names the credential header
`ABC-Auth-Token` (§5.4). The original question and its analysis follow, kept for the record.

*Original question:* Part B §3.5 names the header; locally only the v1 package spec's
deferral mentions it (`2026-07-11-url4-package-v1-spec.md` §13). May it carry the §5.4 grant, with node
authentication in RFC 9421 `Signature` headers, or is the token meant to be the whole credential?
- *Assumption:* the token carries only the grant; the HTTP signature authenticates the node and
  covers the token.
- *Consequence:* two artefacts per request; the grant cannot be lifted onto another request (T3, T4)
  without the token itself being request-bound.
- *If Kevin says otherwise:* the token must become request-bound on its own (a JWS over method,
  authority, path, query and `Content-Digest`, with `nonce`, in the DPoP style). §5.3 and §5.4 merge,
  §5.5 steps 1 and 4 verify one JWS instead of two; R1–R8, the codes and the tests' intent stay.

**Q2 Share-grant delivery for C2.** Does `url4://n2/blob/sha256/<hex>` need a grammar slot for a grant
(for example `grant=` next to `src=`), or do grants travel only out of band and in C6 responses?
- *Assumption:* no grammar slot. A grant never appears in an authored expression; C2 stays refused
  with `x.remote_blob_unsupported` (F1) until delivery is specified in a follow-up; C6 ships first
  (§7).
- *Consequence:* this spec enables C6 only; the share-grant format (§5.4) and the receiver checks
  (§5.5) are fixed now so C2 needs no protocol change later, only a delivery path.
- *If Kevin says otherwise:* a `grant=` slot is a Part A/B grammar change. The grant then sits in
  expression text, so it must be literal like an attachment source (F1b static rule), becomes part of
  the run manifest, and is redacted from logs, spans and errors (R8). §7's C2 order and §9 gain the
  grammar tests.

**Q3 Identity = authority.** Is the `url4://` authority the node identity, or should url4 define a
separate node id (for example a key thumbprint) so a node can move hosts?
- *Assumption:* identity is the canonical authority (§5.1); `Url4Node.name` stays a display name.
- *Consequence:* no new naming scheme or registry; moving hosts is a new identity that peers
  re-allowlist.
- *If Kevin says otherwise:* grants gain a `node` claim; inbound allowlist entries are keyed by node
  id; discovery must bind authority to node id (a signed statement in the JWKS), and `keyid` becomes
  `<node-id>#<kid>`. The receiver order (§5.5) is unchanged.

**Q4 Key discovery path.** Is `/.well-known/url4/node-keys` acceptable, or should discovery be an
`@identity`-style url4 route on the node?
- *Assumption:* the `.well-known` JWKS over plain https, outside the url4 grammar.
- *Consequence:* discovery uses no expression evaluation, so it cannot recurse into peer calls; it
  reuses the #1521 guard with redirects off.
- *If Kevin says otherwise:* only the path changes; the rules stay (allowlist before fetch, from the
  claimed authority only, no redirects, 64 KiB cap, cache clamp). Fetching through the url4 evaluator
  is not allowed either way.

**Q5 Codes and statuses.** Adopt the `x.peer_*` codes into Spec C, or keep them `x.`-prefixed? Is 401
right for `x.peer_auth_expired`, and should it be retryable?
- *Assumption:* keep them `x.`-prefixed extension codes with the proposed statuses, like every #1450
  §4 code; `x.peer_auth_expired` is 401 and retryable once after re-signing.
- *Consequence:* no Spec C change needed to ship; one retry absorbs a stale signature, and a second
  failure surfaces clock skew.
- *If Kevin says otherwise:* adopted codes are renamed without the prefix, permanence unchanged. If
  expired is permanent, the caller's retry test (§9) flips and skew fails on the first attempt.

**Q6 Tenant mapping.** Should a delegation grant's `sub` be opaque, as here, or should url4 define
cross-node tenant identity?
- *Assumption:* opaque. The receiver maps `(peer authority, sub)` to a local tenant (default one
  tenant per peer, `peer:<authority>`) and opens a child run under it (§5.5 step 9).
- *Consequence:* F3 tenant + run scoping stays purely local; the confused-deputy defence (T2) rests
  on the grant naming tenant and run, not on shared tenant ids.
- *If Kevin says otherwise:* the allowlist's tenant map is keyed by the url4 tenant id, the grant
  carries it in a defined claim, and the spec must state who vouches for it (the calling node alone
  cannot). F3's order is unchanged.

**Note on Q7, consent hooks (not a Kevin decision).** `server.py` defers "consent hooks" together with
auth. `OME-1599`'s scope does not include them, so this spec leaves them to Part C. §5.5 has a natural
insertion point after step 7 that needs no protocol change.

## 11. Out of scope

mTLS profile; a trust broker; streaming (WS) transport auth (the same signature over the upgrade
request is the expected extension); end-user authentication at a node's front door; settlement and
billing between operators.
