---
status: accepted   # owner, 2026-11-03, with the no-auth listing rule (§6.3)
issue: OME-1819   # L7a (aigateway); L7b (screamingface-engine) is filed at its own PR-open
parent: OME-1138
date: 2026-10-29
base: origin/main ffdc7e93f (L1, L4a, L4b, L5 and L10 merged)
---

# L7 — the Local Engine manages the Connection chat uses

Close-out spec §4.7, owner answer Q3 (option A; a new Engine falls back to the label rule for one
release against an older gateway). This spec fixes the three things §4.7 left to the leaf: the
`effective` rule, the create and repair table, and the version-skew rule.

It refines §4.7 in two places. The status always comes from `/v1/provider-access` (§4.7: only when
no row is effective), by the owner's answer of 2026-11-02. An Engine create carries the label
`screamingface` (§4.7: no label), because Anthropic refuses an unlabelled create (§3).

§2a (L7c, added 2026-11-04 on base `origin/main` `15bea1200`) adds the conditional delete the
stale-row repair of §3 needs.

## 1. Problem

The Local Engine adapter (`apps/screamingface-engine/src/screamingface_engine/connections/aigateway.py`)
works only on the row labelled `screamingface` (`_MANAGED_LABEL`, `:44`; `_select`, `:253-259`).
Chat uses the row the default resolve serves (L1). So:

- a provider connected in the gateway UI lists `not_connected` locally while chat works;
- with two active rows, one labelled `screamingface`, the Engine lists `connected` while chat
  answers 409;
- `disconnect` can delete a row chat does not use and leave the one it does.

## 2. The gateway marks the effective row (L7a)

**Rule.** For each provider pair of the caller, at most one Connection is effective: the row the
default chat resolve serves.

| Pair | Effective row |
|---|---|
| provider declares only `none` | none, whatever its marker or rows |
| `migrated` with an effective reference | the referenced row, whatever its status |
| otherwise (no marker, `none`, `migrated` without reference) | the single `active` row; none when there are zero or two or more |

The first row comes before the marker, as in resolve and availability (D17,
`core/provider_access/connection_backed.py:330-334`). A stray `active` row under a no-auth
provider's string, or a `migrated` reference to one, is therefore listed with `effective: false`;
`tests/unit/core/provider_access/test_availability_follows_resolve.py:317-345` pins the same case
for its status. Such a provider's public status is the one `/v1/provider-access` lists
(`not_connected`, `connection_backed.py:301`). No row's `auth_method` or `account_label` is
published as effective for it.

Only a provider availability lists has an effective row: one the registry knows and the caller may
VIEW (OME-1721, `connection_backed.py:311-323`). A row of any other provider is listed with
`effective: false` (owner, 2026-11-03). The endpoint policy grants every operation alike
(`plugins/remote_endpoint/policy.py:20-31`), so chat refuses such a provider too.

Since L4a a stored marker in any other state is a data error (`PairAuthorityDataError`,
`core/provider_access/pair_authority.py:61-66,128`): the listing fails as chat does and flags
nothing.

**One function.** A pure core function in `core/provider_access/` computes the effective ids from
the account's markers and Connections. L1's `availability`
(`core/provider_access/connection_backed.py:295-370`) is re-expressed on it: a pair with an
effective row lists that row's operational status; a pair without one lists `error` for two or
more active rows, else `pending`, else `error`, else `not_connected`. Resolve keeps L1's
`_select_by_label` (`:95-111`). An agreement test pins, over L1's table, that the flagged row is exactly the
row the default resolve returns.

**Wire.** `GET /v1/oauth/connections` (`routes/oauth_connections.py:66-77`) rows gain a required,
read-only `effective: bool`, through a list-row schema that extends `OAuthConnectionResponse`
(`core/oauth/schemas.py:20-37`). The single-row GET and the write responses
do not carry it; the Engine never reads it there. The route computes `effective` over the caller's
full, unfiltered set of rows and markers (one marker listing, `PairAuthorityStore.list`
`pair_authority.py:108`, and one Connection listing per call),
then applies the `provider` and `status` filters. A filtered listing therefore still flags the
right row. Without a `status` filter the store hides `revoked` rows (`core/oauth/store.py:46-49`);
the route lists the effective row whatever its status, so a migrated reference to a revoked row
is visible as `E` (owner, 2026-11-02, §8.3). The two listings are fenced by the pair
generations, as the admin inventory's are (`pair_admin.py:206-222`): a marker that moved between
them is read again once, and a second move answers 503 `credential_store_unavailable`, so a delete
landing between the reads never flags its revoked row. The listing reads no secret and writes
nothing.

**An `expired` effective row is unusable (owner, 2026-11-02, §8.1).** L7a adds `expired` to
`UNUSABLE_EFFECTIVE` (`core/provider_access/connection_native.py:88`), so a labelled create
replaces an `expired` effective row as it replaces an `error` or `revoked` one. This completes
the Stage E rule (R6, OME-1209 E1b), whose invariant already names only `active` and `pending`
as usable (`tests/unit/core/provider_access/test_native_oauth_replaces_unusable_effective.py`);
nothing writes `expired` today. A `pending` effective row stays usable, as R6 decided, and is
never displaced; it arises only through a migrated reference, because an OAuth flow moves the
reference in its callback, in the transaction that activates the new row
(`routes/auth.py:651-660`). No prior test changes.

**OpenAPI.** Additive. L9 regenerates the UI schema after this merges.

## 2a. A delete can require the row's status (L7c)

Owner, 2026-11-04, after the L7b review. The stale-row repair of §3 decides from one listing and
then deletes. Between the two requests the row can start serving:

1. The Engine lists a `pending` row labelled `screamingface` and plans to remove it.
2. That row's OAuth callback commits: `complete_pending` turns it `active`
   (`core/oauth/store.py:191-218`, from `routes/auth.py:640-677`).
3. The Engine's `DELETE` arrives. `_delete_connection` (`routes/oauth_connections.py`) reads the
   row as it is now, claims the pair at its new generation, revokes the row whatever its status
   and deletes its blob.
4. `connect` then creates the replacement and sends the key.

The pair marker does not stop this. The callback and the delete both claim it first, so they are
ordered, but a delete that comes second claims the generation the callback published and wins. An
`error` API-key row that a concurrent key write re-activates has the same window
(`PUT …/{id}/api-key`; the admin console, `core/provider_access/connection_admin.py:202`).
Re-reading before the `DELETE` only moves the window. The check has to run inside the delete's own
transaction.

**The parameter.** `DELETE /v1/oauth/connections/{id}?expected_status=<pending|error>`.

- **Without it**, the route is unchanged.
- **With it**, after the delete's pair claim (`claim_for_connection`) and inside its transaction,
  the row is removed only when both hold:
  - it is not its pair's effective reference (`effective_pair_of` returns `None`);
  - its status still equals `expected_status`.

  Otherwise the gateway answers 409 `connection_conflict` and changes nothing: the transaction
  rolls back, the claim included.
- **Values.** Only `pending` and `error`, the two statuses a stale row can have (§3). Any other
  value is 422. A conditional delete never targets a working row.
- **Unchanged answers.** 204 when removed, 404 when the row is gone.

**Why it holds.** The callback (`claim_observed`, or `replace_effective` when it repairs a
migrated pair), a key write (`claim_for_connection`) and the delete all take the pair marker as
their first write.

- On PostgreSQL (READ COMMITTED) the marker's row lock orders them. A callback or key write that
  comes second finds the row revoked or the generation moved and loses, as before. A delete that
  comes second re-checks the row as it now is and refuses.
- On SQLite the single writer serializes them anyway.

The status check takes the row's own lock: a locking read, `SELECT … WHERE id = :id AND status =
:expected FOR UPDATE` (`lock_if_status`, `core/provider_access/connection_native.py`), right
before `mark_revoked`. Under READ COMMITTED it waits for a writer holding the row and re-checks
the status on what that writer committed; a row it locks keeps its status until the delete
commits. The lock order stays the same: lower rows, then the own row, then higher rows. No row
locked is the 409.

**Owner answers (2026-11-04).**

- The parameter names a status (`?expected_status=`): an optimistic precondition, and the gateway
  learns no Engine vocabulary such as "unused".
- L9 waits for L7c and regenerates the UI schema once.

**Engine (L7b).**

- Every stale-row repair `DELETE` carries `expected_status`, set to the status its listing
  showed. A 409 is `ConnectionConflict`. Removal precedes any create or start, so the key never
  leaves the Engine.
- `disconnect` deletes `E` with a plain `DELETE`, the user's explicit intent.
- Under the §4 fallback the stale set is always empty, so a gateway older than L7a receives no
  conditional `DELETE`. A gateway with `effective` but without L7c ignores the parameter. Only
  `main` builds between L7a and L7c are in that state, and no release is if L7c merges before
  gateway 1.0.0.

**Tests.**

- SQLite route tests:
  - a row still `pending`, or still in `error`, is removed (204; its blob goes);
  - a row that turned `active` since the listing, by a finished sign-in or a key fix, is kept with
    its blob and its pair generation (409);
  - a row in another unusable status is refused;
  - the effective row is refused, `pending` or in `error`;
  - without the parameter a `pending` and an `active` row both go;
  - any other value is 422; a missing row is 404.
- PostgreSQL (`needs_postgres`, `AIGW_TEST_PG=1`), with no effective row and with a broken one:
  - a callback that commits after the delete read the row and before its claim → the delete
    answers 409, and the row stays `active` with its blob;
  - a delete that claims first → the callback loses (409), and the row is revoked.

**OpenAPI.** One optional query parameter on the route.

## 3. The Engine selects the effective row (L7b)

`E` is the provider's row with `effective: true`; `A` is the number of its `active` rows.

**Two reads, two jobs (owner, 2026-11-02).**

- `GET /v1/oauth/connections` gives the rows: which row is `E`, its id, auth type and account
  label, and so the target of every write. The Engine filters this listing by `provider` only,
  never by `status`: a `status` filter could hide a non-active `E`.
- `GET /v1/provider-access` gives the public status of every provider, the answer the Hosted
  Engine shows. The gateway owns the selection rule, availability follows it (D17), and an
  `active` row is not necessarily `connected`: a recorded API-key outcome lists `needs_reauth`,
  and `insufficient_credits` lists `error` (`core/provider_access/connection_authority.py:266-290`).
  A provider absent from the listing reads `not_connected`, as on Hosted (`aigateway.py:84`). The
  gateway lists every registered provider the caller may view, `not_connected` included, so a
  provider is absent only when it is hidden from or unknown to the caller.

The Engine never derives a status from a row's lifecycle. `E`, when present, adds `auth_method`
and `account_label`. The two reads are not one transaction, so the Engine does not check them
against each other: a concurrent write can make them differ for a moment.

**Failures.** A malformed or contract-breaking response from either read is
`ConnectionBadResponse` (502); the strict availability decoder already does this
(`connections/provider_access_availability.py:19-44`). An unreachable
gateway stays `ConnectionUnavailable` (503) and a timeout `ConnectionTimeout` (504).

**Listing checks.** Under a gateway that sends `effective`, each of these is
`ConnectionBadResponse`:

- `effective` on some rows and missing on others, across the response: the gateway sets it on
  every row it lists;
- for a provider `/v1/providers` lists, two or more of its rows flagged `effective`;
- for a provider `/v1/providers` lists, exactly one `active` row and none flagged: the §2 rule
  makes that row effective, so the response contradicts the contract.

The last two apply to credential-bearing providers only. `/v1/providers` lists a provider only
when it declares `api_key` or `oauth` (`routes/providers.py:34-37`), and the Engine refuses any
other method (`_validate_provider`, `connections/aigateway.py:301-326`), so every provider the
Engine lists bears a credential. A provider that declares only `none` has no effective row
whatever its stored rows (§2), so a stray `active` row of it, flagged `false`, is valid. The
Engine ignores the rows of a provider it does not list: it never selects, checks or writes them,
and takes no `auth_method` or `account_label` from them. Neither the Local nor the Hosted list
shows such a provider (both iterate `/v1/providers`, `aigateway.py:79-93`); its public status is
the one `/v1/provider-access` lists.

No `E` with two or more `active` rows is the legitimate conflict case below.

**Create and repair table.**

| Case | `connect` (API key) | `start_oauth` | `disconnect` |
|---|---|---|---|
| `E` active, API key | `PUT …/{E}/api-key` (replace in place) | `ConnectionAlreadyConnected` | `DELETE …/{E}` |
| `E` active, OAuth | `ConnectionAlreadyConnected` | `ConnectionAlreadyConnected` | `DELETE …/{E}` |
| `E` `error`, `expired` or `revoked` (the last two only as a migrated reference) | API-key `E` in `error`: `PUT` in place. Otherwise (OAuth `E`, or API-key `E` in `revoked`): stale-row repair, then `POST …/api-key` with label `screamingface`; the gateway replaces an unusable effective row (`effective_to_replace`, `core/provider_access/connection_native.py:95-114`; `expired` added by L7a, §2). An `active` row other than `E` labelled `screamingface`: `ConnectionConflict` | stale-row repair, then `POST` start with label `screamingface`; the callback replaces `E`. An `active` row other than `E` labelled `screamingface`: `ConnectionConflict` | `DELETE …/{E}` |
| `E` `pending` (a migrated reference; usable under R6, §2) | `ConnectionConflict`: the user finishes or removes that sign-in in the gateway | `ConnectionConflict` | `DELETE …/{E}` |
| no `E`, `A` ≥ 2 | `ConnectionConflict` | `ConnectionConflict` | `ConnectionConflict` |
| no `E`, `A` = 0 | own `error` API-key row: `PUT` in place. Otherwise stale-row repair, then `POST …/api-key` with label `screamingface` | stale-row repair, then `POST` start with label `screamingface` | stale-row repair only; idempotent when there is nothing to remove |

**What `connect` and `disconnect` return.** The provider's status from `/v1/provider-access`,
read after the writes: never one derived from the written row, and never a fixed `connected` or
`not_connected`. For `connect`, the written row still passes the response checks below and gives
`auth_method`; the status is whatever the gateway lists once the write is done. Deleting `E` clears the pair's effective reference
(`retire_effective`, `routes/oauth_connections.py:473-475`, `connection_native.py:237`), so the
pair falls back to the
one-active-row rule. If the user has another active row, that row becomes effective and the
provider stays `connected`, and chat goes on using it. With nothing else left the answer is
`not_connected`. A user row that is `pending` or in `error` lists as such.

**The label `screamingface`.** It is the label of an Engine create, because Anthropic requires a
label on both creates (`requires_oauth_connection_label`, `plugins/anthropic_provider/plugin.py:332-333`;
422 `label_required`, `routes/oauth_connections.py:108-111,246-249`). It is never read
for selection. Its only other reader is the stale-row repair below, which takes it as the mark of
a row the Engine created.

**Stale-row repair (the label collision).** A label is unique per pair whatever the row's
status (`core/oauth/models/oauth_connection.py:39-41`, `unique_together`). Two Engine rows can keep the
label `screamingface` while serving nothing: an abandoned OAuth start (`pending`), and an API-key
row in `error`, which keeps its label so it can be re-keyed in place (`OAuthConnectionStore.mark_error`,
`core/oauth/store.py:261-279`). OAuth rows in `error` and every `revoked` row are parked under
`error:` / `revoked:` placeholders (`store.py:267-268,287,363`) and never collide. With no `E`:

- `connect` re-keys the Engine's own `error` API-key row in place (`PUT`), the gateway's designed
  repair;
- otherwise the Engine first deletes the provider's `pending` and `error` rows labelled
  `screamingface` (its own, serving nothing), then creates.

With an unusable `E` that a labelled create replaces (owner, 2026-11-04), the Engine first deletes
the provider's `pending` and `error` rows labelled `screamingface` other than `E`, then creates or
starts. A
pre-L7b Engine created such a row beside a migrated `E` whenever no row held the label; once `E`
is unusable it would block every replacing create with `label_conflict`, because the gateway
exempts only `E`'s own label (`routes/oauth_connections.py:136-152,263-272`). An `active` row
other than `E` holding the label is never removed, since it may serve the user elsewhere:
`connect` and `start_oauth` refuse with `ConnectionConflict` before any write and before the key
leaves, and disconnecting `E` makes that row the effective one.

**The repair is conditional (owner, 2026-11-04; L7c, §2a).** Each repair `DELETE` carries
`expected_status`, the status the listing showed. A row that started serving since the listing (a
sign-in finished, a key fixed) is refused with 409, which is `ConnectionConflict`. The repair runs
before any create or start, so the key never leaves the Engine and the user's row stays. A
labelled row in any other status (`expired`, which nothing writes today) is not repaired, and the
create then meets `label_conflict`. `disconnect` deletes `E` with a plain `DELETE`, the user's
explicit intent.

Rows under any other label belong to the user and are never deleted by the Engine: the Local
Engine does not own the user's OAuth, `error` or `pending` rows. A 409 `label_conflict` that still
occurs (a concurrent create) maps to `ConnectionConflict`.

**Accepted limitation.** A non-active row the user named `screamingface` cannot be told apart from
an Engine row: the label is the only mark of one. With no `E`, such a row meets one of two fates;
beside an unusable `E`, the second.

- `connect` re-keys an `error` API-key row of that label in place: the user's row turns `active`
  with the key the Engine was given, and keeps its label.
- Any other such row, and on `start_oauth` and `disconnect` an `error` API-key row too, is
  removed by the stale-row repair.

Either way the row served nothing (it is neither `E` nor `active`), and since the label is unique
per pair it would block the Engine's create with `label_conflict` anyway.

**Response checks.** `connect` keeps its checks of status code, `auth_type` and `active` status,
and drops the label check: an in-place `PUT` on a row the user named keeps that name.

**Hosted.** `mutable=False` is unchanged.

## 4. Version skew (Q3)

When no listed row carries `effective` (a gateway older than L7a), the Engine selects by today's
label rule for one Engine release, and logs once per process that the gateway predates the
field. The decision is per response: no row carries the field → the older gateway; some rows
carry it → `ConnectionBadResponse` (§3). A listing with zero rows reads the same under both rules.
The status still comes from `/v1/provider-access`, which every gateway since A4 serves. The
fallback is removed in the release after L7b ships. The gateway side needs no skew rule: an older
Engine ignores the field.

## 5. Tests

- **Gateway (RED).** Over L1's agreement cases (migrated with a reference, unmarked or `none` with
  one active row, two active, pending only, no rows): `effective` is set on exactly the row the
  default resolve returns, and on none otherwise. A `provider` or `status` filter keeps the flag.
  A provider that declares only `none` flags no row: a stray `active` row of it, alone or named by
  a `migrated` reference, lists `effective: false`, as does a row of a provider the registry does
  not know or the caller may not view. The listing reads no secret, writes nothing, and lists
  markers and Connections once when no write lands between them; a delete between the reads is
  read again, and a marker that keeps moving answers 503. PG: the listing route on PostgreSQL.
- **Engine (RED).** Every row of §3's table, with a fake gateway. A label-only gateway listing
  (no `effective`) selects by label. Also:
  - `list` shows the provider-access status, including `needs_reauth` and `error` on an `active`
    `E`, and `not_connected` for a provider absent from it;
  - each listing check of §3 raises `ConnectionBadResponse`; an unreachable gateway raises
    `ConnectionUnavailable`;
  - a stray `active` row of a provider `/v1/providers` does not list (a no-auth provider),
    flagged `false`, raises no `ConnectionBadResponse`: the Engine builds nothing from it, and
    every listed provider keeps its `/v1/provider-access` status;
  - `connect` returns the provider-access status read after its write, not one derived from the
    written row: a gateway that lists `needs_reauth` or `error` after a successful write gets that
    status back;
  - `disconnect` of `E` while the user has a second active row returns `connected`;
  - the stale-row repair leaves a non-active row under any other label;
  - the accepted limitation, pinned: with no `E`, an `error` API-key row the user labelled
    `screamingface` is re-keyed in place by `connect` and removed by `start_oauth`'s repair.

  The hosted adapter's suite is unchanged.

## 6. Owner answers

1. **Disconnect with no effective row (2026-11-02):** the stale-row repair only. The Engine
   removes its own non-active `screamingface` rows and leaves the user's rows alone. Deleting
   every non-active row was rejected: the Local Engine does not own the user's rows.
2. **Local status source (2026-11-02):** always `/v1/provider-access`, so Local and Hosted show
   one answer. The row listing serves the row-specific data and the write target (§3).
3. **A no-auth provider and the listing checks (2026-11-03):** "exactly one `active` row and none
   flagged" is a bad response only for a credential-bearing provider. A provider that declares
   only `none` has no effective row whatever its stored rows: the gateway flags a stray `active`
   row of it `false`, as the D17 no-auth tests pin, its public status comes from
   `/v1/provider-access`, and no row's `auth_method` or `account_label` is published as effective
   for it (§2, §3).

## 7. Out of scope

- Promote-on-write (the gateway still does not promote a pair to `migrated` on a native write).
- The Hosted adapter, the gateway UI, and the catalog (L3).

## 8. Open points (code check, 2026-11-02)

The code differed from §3 on three points (checked at `3009c8362`; the cited lines are unchanged
at the base above). The owner resolved all three on 2026-11-02; each resolution is folded into §2
or §3 and recorded after the point.

1. **An `expired` or `pending` effective row is not replaced by a labelled create.**
   `effective_to_replace` treats only `error` and `revoked` as unusable (`UNUSABLE_EFFECTIVE`,
   `core/provider_access/connection_native.py:88`). Otherwise it replaces the effective row only for
   an unlabelled write or one that names that row's own label (`:108-113`). A `POST …/api-key` or an
   OAuth start labelled `screamingface` against an `expired` or `pending` OAuth `E` under another
   label therefore adds a plain row beside `E`; `E` stays effective and the new row serves nothing.
   §3's third table row holds for `error` and `revoked` only.
   **Resolved:** the gateway also treats `expired` as unusable (§2, L7a). A `pending` effective
   row stays usable, as Stage E decided (R6), so the Engine answers it with `ConnectionConflict`
   rather than creating a row that serves nothing (§3, L7b).
2. **`PUT …/{id}/api-key` accepts only an `active` or `error` row** (`routes/oauth_connections.py:326`,
   409 `connection_not_api_key` otherwise). "API-key `E`: `PUT` in place" in the third table row
   holds for `error` only.
   **Resolved:** an API-key row is only ever `active`, `error` or `revoked`. API-key `E` is
   replaced in place when `active` or `error`; a `revoked` one gets a new row (`POST` with label
   `screamingface`), which the gateway puts in its place. `PUT` is not widened to `revoked`, which
   would blur what revoking means (§3, L7b).
3. **The listing hides `revoked` rows.** Without a `status` filter, `OAuthConnectionStore.list`
   excludes them (`core/oauth/store.py:46-49`). A migrated reference to a revoked row, which §2's
   "whatever its status" admits and `UNUSABLE_EFFECTIVE` anticipates, is never listed, so the Engine
   sees no `E`. If that pair also has exactly one other active row, §3's third listing check raises
   `ConnectionBadResponse` although the gateway followed its rule. A delete clears the reference
   before it revokes the row (`retire_effective`), and a replacement moves it first, so whether
   such a reference is reachable decides whether the check or the route needs a rule for it.
   **Resolved:** the listing always includes the effective row, whatever its status (§2, L7a).
   The listing check stays strict.
