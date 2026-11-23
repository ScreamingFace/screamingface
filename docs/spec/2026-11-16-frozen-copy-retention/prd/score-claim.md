# PRD: a Score claims its frozen copy

**Source:** ans:Q2, ans:Q9, ans:Q10, ans:Q11, ans:Q14, ans:Q17, ans:Q20, ans:Q25, ans:Q28,
ans:Q29 ·
**Priority:** P0 (must be live in production before the expiry rule is released)
**Lifecycle:** existing (characterize + delta) in `apps/scoreboard`; planned in `apps/aigateway`
**Owner:** unassigned

Paths are relative to the repo root.

## 1. Summary and user story

As a submitter, I want the pinned cache of my Score to stay available, so that other persons can
reproduce my Score at any later time.

The expiry rule of `prd/copy-sweep.md` deletes a sealed copy that no Score uses. Thus the
gateway must know which copies a Score uses. The scoreboard tells the gateway at submit: it
**claims** the copy before it stores the Score. A claimed copy never expires. `[stated ans:Q2]`

A Score with a pinned cache is stored only when the gateway confirms that the copy is sealed.
`[stated ans:Q10]`

Two automatic mechanisms set a claim: the claim at submit, and a claim pass that the
scoreboard runs at each start for all stored Scores `[stated ans:Q25]`. The pass claims the
copies of the Scores that exist before this release, and it repairs a claim that is missing.
An operator can run the same pass as a command. No job on a schedule, no table and no
interlock exist. `[stated ans:Q17]`

## 2. Background and constraints

- "Delete a sealed copy if no Score links to it … Copies linked to a Score stay forever … a
  submit after [the period] fails with a clear error." `[stated ans:Q2]`
- "Fail with 503 … A stored Score thus always has its claim." `[stated ans:Q9]`
- "Refuse with 422: a Score can name only a sealed copy that the gateway confirms … Cost: a run
  whose seal failed, and a local-runtime run with capture, cannot be submitted with no SDK
  change." `[stated ans:Q10]`
- "Stays claimed": no code path removes a claim. `[stated ans:Q11]`
- "Own allow list" for the caller of the claim route. `[stated ans:Q14]`
- "Claim at submit only: no daily job, no table, no interlock." `[stated ans:Q17]`
- "Scoreboard claims at start": each time the scoreboard starts, it claims the copies of all
  stored Scores in the background. This changes the first words of Q17; the rest of Q17
  stays. `[stated ans:Q25]`
- The expiry rule has no switch and no approval step `[stated ans:Q22]` `[stated ans:Q23]`.
  The claims are thus the only protection of the copy of a Score.
- No SDK change. `[stated ans:Q8]`
- This PRD uses the states and rules of `erd.md` §2.

### 2.1 Current behavior

- The SDK sends `frozen_copy_id` and `capture_status` in `POST /v1/scores` when the run
  captured.
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:858-893]`
  The `Idempotency-Key` is the attempt id of the run.
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:182]`
- A saved result can be submitted at any later time. No code checks its age.
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:326-425]`
- The scoreboard checks only that no other Score names the same copy (422
  `frozen_copy_claimed`).
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:282-297]`
  `[existing apps/scoreboard/src/scoreboard/scores/models/score.py:219]`
- The scoreboard does not check that the copy exists or is sealed. It makes no call to the
  gateway in a request. Its only HTTP client is in the seed command.
  `[existing apps/scoreboard/src/scoreboard/seed.py:12]`
- One path makes a Score or fills its copy field: the submit route calls `store.submit`.
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:385]` This path also serves a
  repeat with the same `Idempotency-Key`, which returns the stored Score before an insert
  `[existing apps/scoreboard/src/scoreboard/scores/store.py:2103-2124]`, and a repeat by the
  same owner, which can fill `frozen_copy_id` on a Score that has none
  `[existing apps/scoreboard/src/scoreboard/scores/store.py:458-478]`.
- After submit, no route can change `frozen_copy_id`.
  `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:1246-1258]`
- Two operator commands delete Scores: `delete_scores` and `purge_private_benchmark`. They tell
  the gateway nothing.
  `[existing apps/scoreboard/src/scoreboard/delete_scores.py:155-223]`
  `[existing apps/scoreboard/src/scoreboard/purge_private_benchmark.py:120]`
- The SDK shows the `code` and `message` of a scoreboard error as they are.
  `[existing packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:552-562]`
  It makes 3 attempts in total for a submit that gets 503
  `[existing packages/screamingface/src/screamingface/_core/retry.py:38-40]`, each with the same
  key (the header is set one time, before the attempts).
- In the gateway, admin routes read the caller from the `X-User-Email` header, after a check of
  the peer network, and compare it with a fixed list. No account row is made.
  `[existing apps/aigateway/src/aigateway/core/auth/admin.py:79-129]`
- A run whose seal failed reports `partial` with the id of an open copy.
  `[existing apps/screamingface-engine/src/screamingface_engine/capture_outcomes.py:178-188]`
  Today the scoreboard stores a Score with such an id.
- On 2026-11-16, 376 Scores named a copy, and each of those copies was `sealed`.

**Delta.** The gateway gets a claim route. The scoreboard calls it in the submit route, before
the store call, and refuses the submit when the copy is not a sealed copy. At each start, the
scoreboard claims the copies of all stored Scores in the background. A new operator command
does the same pass by hand.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **C1. A submit with a sealed copy claims it.** `[stated ans:Q2]` Must
  - Given the scoreboard has a gateway URL, and a submit carries the id of a `sealed` copy
  - When the scoreboard handles the submit
  - Then it calls the claim route before it calls the store
  - And the copy has `claimed_at` set
  - And the Score is stored as it is today.
- **C2. A submit with no copy makes no call.** `[implied]` Must
  - Given a submit with no `frozen_copy_id`
  - Then the scoreboard makes no call to the gateway, and the result is as it is today.
- **C3. A repeat claim is safe.** `[implied]` Must
  - Given a copy that is claimed
  - When the claim route gets the same id again
  - Then it answers 200 with `already: true`, and `claimed_at` keeps its first value.
- **C4. The operator claims the copies of all Scores.** `[implied]` Must
  - Given the Scores in the scoreboard (376 name a copy on 2026-11-16)
  - When the operator runs `python -m scoreboard.claim_copies`
  - Then it reads each Score that has a `frozen_copy_id` with one query that has no filter on
    the board or on its visibility, and it sends a claim for each copy
  - And it prints one line for each copy and a summary by result
  - And a second run gives `already` for each of them.
  - The command is run by hand. No release step needs it, because the start pass does the
    same work (C18). It lets an operator repair claims with no restart (`erd.md` §2.8).
    `[stated ans:Q21]`

### 3.2 Error paths

- **C5. The copy expired.** `[stated ans:Q2]` Must
  - Given a submit carries the id of a copy with status `expired`
  - When the scoreboard claims it
  - Then the gateway answers 410 with `state: expired`
  - And the scoreboard answers 422 with `detail.code = frozen_copy_expired` and the message of
    `contracts.md` K5
  - And no Score is stored.
- **C6. The copy is not a sealed copy.** `[stated ans:Q10]` Must
  - Given a submit carries the id of a copy that is `open`, or `abandoned`, or that this
    gateway does not know
  - When the scoreboard claims it
  - Then the gateway answers 409 `frozen_copy_not_sealed`, or 410 with `state: abandoned`, or
    404 `frozen_copy_not_found`
  - And the scoreboard answers 422 with `detail.code = frozen_copy_unavailable` and the message
    of `contracts.md` K5
  - And no Score is stored.
  - This refuses two inputs that are accepted today: a run whose seal failed, and a run on the
    local runtime whose copy is only in the local gateway. The user can run the evaluation
    again and submit the new result; the request cache makes the second run cheap. The owner
    accepted this cost. `[stated ans:Q10]`
- **C7. The gateway does not answer.** `[stated ans:Q9]` Must
  - Given a submit with a `frozen_copy_id`
  - When the claim call fails with a timeout, a connection error, a 5xx status, or an answer
    that the table of §3.4 does not name
  - Then the scoreboard answers 503 with `detail.code = frozen_copy_check_unavailable` and a
    `Retry-After` header
  - And no Score is stored. The SDK makes 3 attempts in total with the same key.
  - A 200 counts as a claim only when its body is a JSON object with `status: "sealed"` and
    with `already` as true or false; if the body has an `id`, it must be the copy id of the
    submit. Each other 200 is such an answer: the submit fails closed. `[proposed]`
  - A 404 with no `detail.code`, or with a different code, is such an answer. It comes from a
    wrong gateway URL, or from a gateway that does not have the claim route. Only a 404 with
    `detail.code = frozen_copy_not_found` means "the gateway does not know this copy" (C6).
    `[proposed]`

### 3.3 Derived scenarios (risk order)

- **C8. A claim at the expiry time.** `[proposed]` H×L Must
  - Given an unclaimed copy that is past its period but that the sweep did not mark yet
  - When a claim comes
  - Then the claim wins: the copy gets `claimed_at` and stays `sealed`. (The race itself is S12
    of `prd/copy-sweep.md`.)
- **C9. No gateway URL.** `[proposed]` H×M Must
  - Given `SCOREBOARD_GATEWAY_URL` is empty (the default; local and test installs)
  - Then the scoreboard makes no claim call, and each submit is handled as it is today.
  - And for each submit that carries a `frozen_copy_id`, it logs one record at WARNING that
    says the Score was stored with no claim.
  - And `claim_copies` exits with status 2, and no claim pass runs at start (C22).
  - In production, an empty URL makes Scores with no claim, and nothing fails (`erd.md` §2.8,
    case 1). The log record is the only signal. The next start with a URL claims those copies
    (C18). Until then, each such copy has only the time that remains in its period.
    `[stated ans:Q25]`
- **C10. The store refuses after the claim.** `[proposed]` M×M Must
  - Given the claim succeeded
  - When the store then refuses the submit (422, 403 or 409)
  - Then the copy stays claimed, and the scoreboard does not call the gateway again.
  - Reason: no code path removes a claim `[stated ans:Q11]`. A claim with no Score costs only
    storage.
- **C11. A repeat that fills the copy field.** `[implied]` M×L Must
  - Given a Score with no capture fields, and a repeat submit by its owner that carries a
    `frozen_copy_id`
  - Then the claim call is made before the store call, as in C1. If that copy is not a sealed
    copy, the answer is the 422 of C5 or C6, where it is a 200 today.
- **C12. A repeat with the same key.** `[implied]` M×M Must
  - Given a submit that the SDK sends again with the same `Idempotency-Key`
  - Then the scoreboard claims again (the gateway answers `already: true`) and returns the
    stored Score with status 200, as it does today.
  - Given the Score was stored before this release (by a scoreboard with no claim), and its
    copy is not a sealed copy now
  - Then the repeat gets the 422 of C5 or C6, where it got the stored Score before. The
    stored Score does not change. This is accepted behavior: the claim is before the store
    call for each submit. `[stated ans:Q10]`
- **C13. The caller of the claim route is not allowed.** `[stated ans:Q14]` H×L Must
  - Given the gateway runs in `cloudflare_headers` mode
  - When a call comes from a peer in neither `AIGW_ALLOWED_NETWORKS` nor
    `AIGW_FROZEN_COPY_CLAIM_NETWORKS`, or with an email that is not in
    `AIGW_FROZEN_COPY_CLAIM_EMAILS`
  - Then the gateway answers 403 and changes nothing. With an empty list it answers 503. With
    no identity header it answers 401.
  - Given the gateway runs in `jwt` mode, it answers 503, as the admin routes do
    `[existing apps/aigateway/src/aigateway/core/auth/admin.py:104-105]`.
  - Given the gateway runs in `disabled` mode (loopback only, local development), it accepts
    the call with no list. `[proposed]`
- **C14. A bad copy id.** `[implied]` L×M Must
  - Given a claim for an id that is not a UUID
  - Then the gateway answers 404 `frozen_copy_not_found`. (The scoreboard already refuses a
    `frozen_copy_id` that is not a UUID
    `[existing apps/scoreboard/src/scoreboard/scores/schemas.py:499-510]`.)
- **C15. The command finds a copy that is not claimed.** `[proposed]` H×L Must
  - Given `claim_copies` gets a result that is not `claimed` or `already` for the copy of a
    Score (`expired`, `abandoned`, `not_sealed` or `not_found`)
  - Then it prints the Score id and the copy id with that result, continues with the next
    Score, and exits with status 3 at the end.
  - Each such result means that a stored Score names a copy that cannot be replayed. After
    this release, the submit route refuses such a Score (C5, C6), so the result can come only
    from a Score stored before the release, from a Score stored while the scoreboard had no
    gateway URL (C9), or from a copy that was deleted.
  - The start pass writes the same Scores in one WARNING record (C21). The list is
    information for the owner: the Score stays on the board, nothing is deleted, and no
    release step waits for it (`test-plan.md` §5.2). `[stated ans:Q20]`
- **C16. The command gets no answer.** `[proposed]` M×M Must
  - Given the gateway does not answer for one copy
  - Then the command stops at once with status 1. A later run starts again from the first
    Score; this is safe because of C3.
- **C17. A Score is deleted.** `[stated ans:Q11]` L×L Must
  - Given the operator deletes a Score
  - Then its copy stays claimed, and is kept forever.
- **C18. The scoreboard claims the copies of all Scores at start.** `[stated ans:Q25]` H×M Must
  - Given a scoreboard pod starts with a gateway URL, and the database holds Scores that name
    a copy
  - Then a background task sends one claim for the copy of each such Score, on all boards,
    with no filter on the visibility, one call at a time
  - And each sealed copy has `claimed_at` set when the pass ends.
  - Each pod does this at each start. A second pass gives `already` for each copy (C3).
- **C19. The pass does not delay the start.** `[stated ans:Q25]` M×M Must
  - Given the pass is in progress, or the gateway is slow
  - Then the scoreboard is ready and serves requests as normal. The pass is not a part of
    startup or of the readiness check.
- **C20. The gateway does not answer during the pass.** `[proposed]` H×M Must
  - Given one claim of the pass gets an `unavailable` result (§3.4, last row)
  - Then the pass stops, and the task writes one WARNING record
  - And the task waits 10 minutes and starts the pass again from the first Score
  - And it repeats this until one pass completes. Then the task ends.
  - Given a database error stops a pass
  - Then the task writes one ERROR record with the type of the error, waits the same 10
    minutes and starts a new pass. The task does not end before one pass completes.
    `[stated ans:Q29]`
- **C21. The pass reports its result.** `[stated ans:Q20]` M×M Must
  - Given a pass completes
  - Then the task writes one INFO record with the number of Scores and the count of each
    result
  - And if one or more results are not `claimed` or `already`, it writes one WARNING record
    with the Score ids and the copy ids of those results. It is one record, not one for each
    Score. The records have no user identity.
- **C22. No gateway URL, no pass.** `[proposed]` M×M Must
  - Given `SCOREBOARD_GATEWAY_URL` is empty
  - Then the scoreboard starts no task and makes no call.
- **C23. Shutdown stops the pass.** `[proposed]` L×M Must
  - Given the task is in a pass, or waits for the next attempt
  - When the scoreboard shuts down
  - Then the lifespan cancels the task and waits until the task ended. It does not wait for
    the pass to complete.
  - The order at shutdown is: cancel the task and wait for it, then close the claim client,
    then close the database
    `[existing apps/scoreboard/src/scoreboard/main.py:101-107]`. A task that is still in a
    claim call must not find a closed client or a closed database.
- **Not applicable.** Reproduction records name the copy of their Score
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:745-761]`, so they need no claim
  of their own. Concurrent submits of one copy by two Scores: the claim is the same for both,
  and the unique index decides which Score is stored, as today.

### 3.4 Decision table for the submit route

| Gateway answer to the claim | The scoreboard does this |
|---|---|
| 200 with `status: "sealed"` and `already` true or false (C7) | call the store; the Score is stored |
| 410 with `detail.state = expired` | answer 422 `frozen_copy_expired`; store nothing |
| 409 with `detail.code = frozen_copy_not_sealed` | answer 422 `frozen_copy_unavailable`; store nothing |
| 410 with `detail.state = abandoned` | answer 422 `frozen_copy_unavailable`; store nothing |
| 404 with `detail.code = frozen_copy_not_found` | answer 422 `frozen_copy_unavailable`; store nothing |
| each other answer (a different 200, a different 404, 401, 403, 5xx), a timeout, a connection error | answer 503 `frozen_copy_check_unavailable`; store nothing |

The value of `capture_status` in the submit does not change this table. `[stated ans:Q10]`

## 4. Non-functional requirements

### 4.1 Settings

| Setting | Service | Type | Default | Source |
|---|---|---|---|---|
| `AIGW_FROZEN_COPY_CLAIM_EMAILS` | gateway | comma list of emails | empty | `[stated ans:Q14]` |
| `AIGW_FROZEN_COPY_CLAIM_NETWORKS` | gateway | comma list of CIDR networks; peers trusted on the claim route only | empty | `[proposed]` (review fix 2026-11-23) |
| `SCOREBOARD_GATEWAY_URL` | scoreboard | string | empty (claims off) | `[proposed]` |
| `SCOREBOARD_GATEWAY_ACTOR` | scoreboard | email | none; necessary when the URL is set | `[proposed]` |
| `SCOREBOARD_GATEWAY_TIMEOUT_S` | scoreboard | float | `5.0` | `[proposed]` |

- Declare the gateway list as `admin_emails` is declared (`NoDecode`, lower case)
  `[existing apps/aigateway/src/aigateway/config.py:88-89]`
  `[existing apps/aigateway/src/aigateway/config.py:349-364]`.
- The scoreboard settings go into `Settings` with the `SCOREBOARD_` prefix
  `[existing apps/scoreboard/src/scoreboard/config.py:37-39]`, the chart `config:` block
  `[existing apps/scoreboard/charts/scoreboard/values.yaml:30-48]` and its ConfigMap template.
  The chart checks (the three keys are in the ConfigMap; the default URL is empty) go into
  `.github/scripts/verify_chart_wiring.py`. The scoreboard tests have no Helm test and no YAML
  library, and this spec adds none. `[proposed]`
- The scoreboard refuses to start when the URL is set and the actor is empty. `[proposed]`

### 4.2 Security

- **Least privilege.** The claim route has its own list of allowed emails. The scoreboard's
  actor is not in `AIGATEWAY_ADMIN_EMAILS`. `[stated ans:Q14]`
- **The actor address** must be one that cannot log in through Cloudflare Access, so that no
  person can present it from outside the cluster. `[proposed]`
- **Trust.** The gateway believes `X-User-Email` only from a peer in its trusted networks, and
  only pods that its NetworkPolicy admits can connect
  `[existing apps/aigateway/charts/aigateway/templates/networkpolicy.yaml:2-4]`. The scoreboard
  pod must be added as a client (`00-overview.md` §7.3). Each pod that the policy admits (the
  runner pods also) can send the actor header. This is the same exposure that the admin routes
  have today. `[implied]`
- **What a claim can do.** A claim can only keep a sealed copy. It cannot read an entry, and it
  cannot delete. A wrong claim costs storage only. `[implied]`
- **A user can keep a copy with a refused submit** (C10). This needs a valid submit body and
  the copy id. The claim does not check the owner of the copy, so this can be each sealed copy
  whose id the user knows. The cost is the storage of that copy. Accepted. `[proposed]`
- The claim call sends the copy id only. It sends no user identity and no Score data.
  `[proposed]`

### 4.3 Performance

- One more call inside the cluster for each submit that carries a copy. Budget: 5 seconds
  timeout, no retry inside the scoreboard (the SDK repeats the submit). `[proposed]`
- The claim call is made outside each database transaction of the scoreboard. The store holds a
  row lock during its insert
  `[existing apps/scoreboard/src/scoreboard/scores/store.py:2127-2146]`; an HTTP call under that
  lock would block other submits to the same board. `[proposed]`
- The gateway claim is one row lock and one update. `[proposed]`
- The claim pass (start task and command) makes one call for each Score that names a copy
  (376 today), one after the other. Each pod does this at each start. The pass reads the
  Score ids and copy ids only, not the full Scores. `[proposed]`

### 4.4 Observability

- The scoreboard logs one record at WARNING for each claim that did not answer 200, with the
  result and the copy id, and with no user identity. `[proposed]`
- The scoreboard logs one record at WARNING for each Score with a `frozen_copy_id` that it
  stores with no claim because it has no gateway URL (C9). `[proposed]`
- The gateway logs one record at INFO for each first claim of a copy. `[proposed]`
- The start pass writes the records of C20 and C21. It writes no record for each claim that
  answers 200. `[proposed]`
- No metric and no alert. `[stated ans:Q6]`

## 5. Out of scope

- **Release of a claim.** `[stated ans:Q11]`
- **A job on a schedule that claims the copies again, a table for it, and a rule that stops
  the expiry when claims are missing.** `[stated ans:Q17]` The claim pass at start is in scope
  `[stated ans:Q25]`. The window that remains is in `erd.md` §2.8.
- A change of the SDK. `[stated ans:Q8]`
- A notice in the SDK result that shows when a copy expires. `[stated ans:Q8]`

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

**Order:** gateway route first (the scoreboard depends on it), then the scoreboard client, then
the submit route, then the claim pass (function, command, start task). Risk first inside each group.

Test files: `apps/aigateway/tests/unit/test_frozen_copy_claim.py`,
`apps/scoreboard/tests/unit/test_copy_claims.py`,
`apps/scoreboard/tests/unit/test_submit_claims_copy.py`,
`apps/scoreboard/tests/unit/test_claim_copies_cli.py`,
`apps/scoreboard/tests/unit/test_claim_pass_at_start.py`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| CH-1 | CHAR: a submit with a `frozen_copy_id` that another Score names answers 422 `frozen_copy_claimed` | integration | `[existing routes/scores.py:282-297]` | — | passes today |
| CH-2 | CHAR: a submit with a repeated `Idempotency-Key` returns the stored Score with 200 | integration | `[existing store.py:2103-2124]` | — | passes today |
| CH-3 | CHAR: with no gateway URL, a submit with a `frozen_copy_id` is stored and no HTTP call is made (C9) | integration | `[proposed]` | — | passes today; it pins the default |
| K-1 | gateway: a claim of a sealed copy sets `claimed_at` and answers 200 `already: false` (C1) | unit | `[stated ans:Q2]` | H×M | new store method under `select_for_update` |
| K-2 | gateway: a second claim answers 200 `already: true` and keeps the first `claimed_at` (C3) | unit | `[implied]` | H×M | return when `claimed_at` is set |
| K-3 | gateway: a claim of an `expired` copy answers 410 with `state: expired` and changes nothing (C5) | unit | `[stated ans:Q2]` | H×M | status check under the lock |
| K-4 | gateway: a claim of an `open` copy answers 409 `frozen_copy_not_sealed`; of an `abandoned` copy 410 `state: abandoned`; of an unknown or malformed id 404 `frozen_copy_not_found` (C6, C14) | unit | `[stated ans:Q10]` | H×M | one branch for each state |
| K-5 | gateway, `cloudflare_headers` mode: an email outside the claim list answers 403; an empty list 503; no header 401; an untrusted peer 403 (C13) | unit | `[stated ans:Q14]` | H×L | new dependency modeled on `require_admin` |
| K-6 | gateway: `jwt` mode answers 503; `disabled` mode accepts the call with an empty list (C13) | unit | `[proposed]` | M×M | mode branches |
| K-7 | gateway: an email in `AIGATEWAY_ADMIN_EMAILS` only cannot claim, and an email in the claim list only cannot call an admin route | unit | `[stated ans:Q14]` | H×L | two separate lists |
| K-8 | scoreboard client: a 200 with `status: "sealed"` and `already` as a boolean, 404 `frozen_copy_not_found`, 409, 410 (both states) each map to one typed result; a 200 with an empty object, with a different `status`, with an `already` that is not a boolean or with a different `id`, a 404 with no code or with `detail: "Not Found"`, a 401, a 403, a 5xx, a timeout and a connection error all map to `unavailable` (C7) | unit | `[proposed]` | H×M | small class over `httpx.AsyncClient` with a mock transport; one lookup table on the status with `detail.code`, `detail.state` or the 200 body; each answer that is not in the table is `unavailable` |
| K-9 | submit: an `expired` result answers 422 `frozen_copy_expired`, and the store is not called (C5) | integration | `[stated ans:Q2]` | H×M | claim before `store.submit` |
| K-10 | submit: `not_sealed`, `abandoned` and `not_found` each answer 422 `frozen_copy_unavailable`, and the store is not called (C6) | integration | `[stated ans:Q10]` | H×M | one refusal branch |
| K-11 | submit: an `unavailable` result answers 503 `frozen_copy_check_unavailable` with `Retry-After`, and the store is not called (C7) | integration | `[stated ans:Q9]` | H×M | map in one helper |
| K-12 | submit: a claimed result calls the store, and the claim was made before it (C1) | integration | `[stated ans:Q2]` | H×M | fake client records the call order |
| K-13 | submit: no `frozen_copy_id` makes no claim call (C2) | integration | `[implied]` | M×M | guard on the field |
| K-14 | submit: a store refusal after a claim makes no second gateway call (C10) | integration | `[proposed]` | M×M | no compensation code |
| K-15 | submit: a repeat with the same key claims again and answers 200 (C12) | integration | `[implied]` | M×M | claim is before the store's replay check |
| K-16 | submit: with no gateway URL, a Score with a `frozen_copy_id` is stored and one WARNING record says that it has no claim (C9) | integration | `[proposed]` | H×M | log in the helper |
| K-17 | the scoreboard refuses to start with a URL and no actor (§4.1) | unit | `[proposed]` | M×L | validator in `Settings` |
| K-18 | command: sends a claim for each copy that a Score names, public and private boards, and prints one line each (C4) | integration | `[implied]` | H×M | one query with no visibility filter |
| K-19 | command: a second run reports `already` for each copy (C4) | integration | `[implied]` | M×M | uses C3 |
| K-20 | command: a result that is not `claimed` or `already` is printed, the run continues, and the exit status is 3 (C15) | integration | `[proposed]` | H×L | collect, then exit |
| K-21 | command: an `unavailable` result stops the run with exit status 1 (C16) | integration | `[proposed]` | H×M | raise on the first `unavailable` |
| K-22 | command: with no gateway URL, exits 2 and makes no call (C9) | unit | `[proposed]` | M×M | check the settings first |
| K-23 | the claim record in the scoreboard log has the copy id and no user identity (§4.4) | unit | `[proposed]` | L×L | log in the helper |
| K-24 | submit: a repeat by the owner that fills `frozen_copy_id` on a Score with none makes the claim before the store call; with a `not_sealed` result it answers 422 and the Score keeps its empty field (C11) | integration | `[implied]` | M×L | the same helper serves this path |
| K-25 | gateway: a claim of an unclaimed sealed copy that is past its period and not marked answers 200 and sets `claimed_at` (C8) | unit | `[proposed]` | H×L | this test is in pull request C1, where the expiry rule exists; it pins that the claim does not evaluate the expiry rule |
| K-26 | CHAR: `delete_scores` makes no gateway call (C17) | integration | `[stated ans:Q11]` | L×L | passes with no change to `delete_scores.py`; a fake claim client records no call. It pins that no release call is added |
| K-27 | command: `--dry-run` prints each Score that names a copy and makes no gateway call (K9) | integration | `[proposed]` | L×M | branch before the client call |
| K-28 | start: with a gateway URL, the app start sends one claim for the copy of each stored Score, public and private boards (C18) | integration | `[stated ans:Q25]` | H×M | the lifespan starts one task that calls the pass function of K-18 |
| K-29 | start: the app serves a request while the pass waits on a claim that does not return (C19) | integration | `[stated ans:Q25]` | M×M | `asyncio.create_task`; do not await it in the lifespan |
| K-30 | start: an `unavailable` result stops the pass with one WARNING record; after the wait of 10 minutes the pass starts again from the first Score, and the task ends after one complete pass; a database error in a pass gives one ERROR record and the same wait (C20) | unit | `[proposed]` `[stated ans:Q29]` | H×M | loop with injected `sleep` |
| K-31 | start: a complete pass writes one INFO record with the counts; results that are not `claimed` or `already` give one WARNING record with their Score ids and copy ids, and no user identity (C21) | unit | `[stated ans:Q20]` | M×M | build both records from the result list |
| K-32 | start: with no gateway URL, the lifespan starts no task and no HTTP call is made (C22) | integration | `[proposed]` | M×M | guard on the setting |
| K-33 | start: shutdown cancels the task while it waits for the next attempt, and the lifespan exits (C23) | unit | `[proposed]` | L×M | cancel and await the task in the lifespan exit |
| K-34 | start: shutdown cancels the task while a pass is in progress (a claim call that does not return); the lifespan waits for the task, then closes the claim client, then closes the database (C23) | unit | `[proposed]` | M×M | cancel and await the task before the client and before `close_db()` |
| K-35 | submit: a repeat with the same `Idempotency-Key` for a Score that was stored before this release, and whose copy is not sealed now, answers 422 `frozen_copy_unavailable` and does not change the stored Score (C12) | integration | `[stated ans:Q10]` | M×L | the claim is before the store's replay check |

### 7.1 Implementation notes

- **Gateway route.** `POST /v1/frozen-copies/{copy_id}/claim` in
  `apps/aigateway/src/aigateway/routes/frozen_copies.py`. Shape in `contracts.md` K4. The guard
  is a new dependency in `core/auth/` that follows `require_admin` step by step
  `[existing apps/aigateway/src/aigateway/core/auth/admin.py:79-129]`, with the claim list in
  place of the admin list, and with the difference for `disabled` mode of C13. It makes no
  account row.
- **Scoreboard client.** A small class (for example `CopyClaims`) that owns one
  `httpx.AsyncClient`. Make it in `create_app`, put it on `app.state` as `score_store` is
  `[existing apps/scoreboard/src/scoreboard/main.py:186-190]`, and close it in the lifespan
  `[existing apps/scoreboard/src/scoreboard/main.py:101-107]`. `httpx` is already a runtime
  dependency. The scoreboard has no pattern for a faked HTTP dependency; let `create_app` accept
  the client as an optional argument so that a test passes a fake.
- **Submit route.** Put the claim and its mapping in one helper. `submit_score` is at the
  complexity limit of the repo
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:285-287]`. Call the helper after
  the benchmark check and before `store.submit`
  `[existing apps/scoreboard/src/scoreboard/routes/scores.py:385]`. In the OpenAPI document of
  the route, only the description text of the 503 and of the 422 changes. The response model
  of the 503 does not change, so no scoreboard test changes. `[stated ans:Q28]`
- **Claim pass.** One function reads the Scores and sends the claims. It returns the result
  for each Score. It stops at the first `unavailable` result. Put it next to the claim client.
- **Command.** `apps/scoreboard/src/scoreboard/claim_copies.py`, run with `python -m`. Exemplar
  for the argument and exit style: `delete_scores.py`. It has a `--dry-run` flag that lists the
  copies and makes no call. It calls the pass function.
- **Start task.** The lifespan starts one task after the claim client exists, keeps a
  reference to it, and stops it at exit
  `[existing apps/scoreboard/src/scoreboard/main.py:101-107]`. Order at exit: cancel the task
  and await it, close the claim client, then `close_db()`. The task calls the pass
  function in the retry loop of C20, with an injected `sleep` for the tests. The loop also
  tries again after a database error `[stated ans:Q29]`.
- **Do not** call the gateway inside `ScoreStore.submit` or inside a transaction.
- **Do not** add a release call, a job on a schedule or a CronJob. The one background task
  that is permitted is the claim pass at start `[stated ans:Q25]`: it ends after one complete
  pass and does not run again until the next start. Do not change `delete_scores.py`
  or `purge_private_benchmark.py`.
