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

## Decisions requested from Kevin

Tick or overrule; details, consequences and the alternative for each are in §10.

- [ ] **Q1** `URL4-Auth-Token` carries only the delegation/share **grant** (JWS); node authentication is
  the RFC 9421 `Signature` that covers it.
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

- Covered components: `"@method"`, `"@authority"`, `"@path"`, `"@query"`, `"url4-auth-token"`,
  `"content-digest"` (RFC 9530, `sha-256`, when there is a body), `"idempotency-key"` (when present).
- Parameters: `created` (now), `expires` (`created + 60`), `nonce` (128 random bits, base64url),
  `keyid`, `alg="ed25519"`, `tag="url4-peer"`.
- Headers sent: `Signature-Input`, `Signature`, `URL4-Auth-Token` (§5.4), `Content-Digest` (if body).
- Every retry is re-signed (fresh `created` and `nonce`); the `Idempotency-Key` stays the same, so
  replay protection and idempotent retry do not interfere.
- **Peer requests follow no redirects** (R6, T5). A 3xx answer to a peer request is
  `x.source_destination_blocked` (the existing #1521 code), and the `Location` is not contacted.

### 5.4 `URL4-Auth-Token`: the grant

`URL4-Auth-Token` carries a **grant**: a compact JWS (`alg: EdDSA`, `typ: url4-grant+jwt`, `kid`). It
says *on whose behalf and for what*; the HTTP signature says *who is sending this exact request*. The
token is covered by the signature, so it cannot be lifted onto another request. Two kinds:

| Kind | Issued by | Used for | Claims |
|---|---|---|---|
| `delegation` | the **calling** node | C6: "run this expression for my tenant T, run R" | `iss` caller authority, `aud` receiver authority, `sub` caller-side tenant id (opaque), `run` caller run id, `trace` trace id, `scope: ["eval"]`, `budget` (optional cost cap), `iat`, `exp` (≤ `iat + 300`), `jti` |
| `share` | the **resource** node (the blob owner) | C2: "peer P may read digest D of my tenant T, run R" | `iss` resource authority, `aud` the reader's authority, `sub` resource-side tenant id, `run` resource-side run id, `scope: ["blob:read:sha256:<hex>", …]`, `iat`, `exp`, `jti` |

A node never self-issues a `share` for another node's data: a share grant verifies only with the
**receiving** node's own key. So a blob uploaded under identity A on n2 is readable by n1 only if n2
issued n1 a share grant naming that digest (the `OME-1599` acceptance "A's blob can't be fetched by B
without a grant").

How a share grant reaches the reader is **open** (Q2). Working assumption: never in the expression;
C2 stays refused until delivery is specified (§10).

### 5.5 Inbound: the receiver's order (normative)

For every request on the eval path, a data route or `/blob/…` that carries a signature, and for every
request on a route the operator marks peer-only:

1. **Parse** `Signature-Input`/`Signature` (label `url4`) and `URL4-Auth-Token`. Missing on a
   peer-only route → `x.peer_auth_required`.
2. **Allowlist before I/O** (R5, T7): the `keyid` authority must equal the grant's `iss` (delegation)
   or `aud` (share), and must be on the receiver's **inbound peer allowlist**. Otherwise
   `x.peer_not_authorized`. No key fetch happens for an unlisted authority.
3. **Resolve the key** from cache or discovery (§5.2). Unreachable discovery with no cached key →
   `x.peer_key_unavailable`.
4. **Verify** the HTTP signature over the covered components, `Content-Digest` against the body, and
   the grant's JWS (delegation: caller's key; share: the receiver's own key). Any mismatch →
   `x.peer_auth_failed`.
5. **Freshness:** `created` within ±30 s of the receiver's clock, `expires` not passed,
   `expires - created ≤ 60`; grant `exp` not passed. Otherwise `x.peer_auth_expired`.
6. **Replay:** `(keyid, nonce)` must be unseen within `window = 60 s + 2 × 30 s skew`; record it.
   A repeat → `x.peer_replay`. The nonce store is shared by all replicas serving one authority; if it
   is unavailable the receiver fails closed with `x.peer_key_unavailable` (retryable).
7. **Authorize:** grant `aud` equals the receiver's own authority; `scope` covers the operation
   (`eval` for the eval path; `blob:read:sha256:<hex>` for that exact blob); the peer's allowlist entry
   permits that scope. Otherwise `x.peer_not_authorized`.
8. **Bind a local run context** (taken from the verified grant, never from the expression):
   - C6 (`delegation`): the operator maps `(peer authority, sub)` to a local tenant (default: one
     local tenant per peer, `peer:<authority>`); the receiver opens a **new child run** under it,
     carrying `trace` and the caller's run id as attribution. `budget`, if present, caps that run's
     spend, and the peer entry's own cap applies regardless.
   - C2 (`share`): tenant = `sub`, run = `run` from the receiver's own share grant.
9. **Then** spec #1450 F3's order runs unchanged: authorize the digest against that tenant + run,
   verify sha256, and only then touch caches. An in-grant digest missing from the store, and any
   out-of-scope digest, is `source_not_found` (T9).

A request without a signature on a route that is not peer-only keeps today's behaviour; this spec
adds no authentication for local SDK callers.

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
| `x.peer_auth_required` | receiving node | 401 | permanent | §5.5 step 1 |
| `x.peer_not_authorized` | receiving node | 403 | permanent | steps 2, 7 |
| `x.peer_key_unavailable` | receiving node | 503 | retryable | step 3; nonce store down (step 6) |
| `x.peer_auth_failed` | receiving node | 401 | permanent | step 4 |
| `x.peer_auth_expired` | receiving node | 401 | retryable (re-signed; at most once) | step 5; repeated failure means clock skew |
| `x.peer_replay` | receiving node | 401 | permanent | step 6 |
| `x.peer_signing_unconfigured` | calling node | 500 | permanent | caller has a configured peer but no signing key; before any I/O |
| `x.remote_node_unsupported` / `x.remote_blob_unsupported` | calling node resolver | 422 | permanent | unchanged from #1450: the target authority is not a configured outbound peer (or the feature is off); before any I/O |
| `x.source_destination_blocked` | #1521 guard | 422 | permanent | unchanged, plus a redirect on a peer request (§5.3) |

This closes #1450 §4's "remote-node authentication failure has no v1 owner".

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

- **C6 first.** It needs only §5.1–5.8 plus the delegation grant. The receiver resolves inner sources
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

## 10. Open questions for Kevin, with working assumptions

Each assumption is the conservative option consistent with spec #1450 (F1, F1b, F3, §4): it opens
nothing #1450 keeps closed and changes no grammar. Overruling one changes only the sections named.

**Q1 `URL4-Auth-Token` semantics.** Part B §3.5 names the header; locally only the v1 package spec's
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
  tenant per peer, `peer:<authority>`) and opens a child run under it (§5.5 step 8).
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
