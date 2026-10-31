---
status: accepted   # owner approval 2026-10-29, §10 Q1-Q2 decided
issue: OME-1778
parent: OME-1138
date: 2026-10-29
base: origin/main ee7fc24b6
---

# Provider availability follows the resolver (D17 fold-in, OME-1138)

Owner decision taken 2026-10-29: fold Connection-backed pairs into the availability listing
(option (a)), rather than waive the epic's end state. Plan:
`docs/plan/2026-10-29-availability-fold-in.md`; ledger: `docs/work/2026-10-29-availability-fold-in.md`.

## 1. Problem

`GET /v1/provider-access` (`ConnectionBackedProviderAccess.availability`,
`core/provider_access/connection_backed.py:304-337`) reports a status only for a pair whose marker
is `migrated`; every other pair reads `not_connected`. Chat resolves the same pairs differently:
`resolve` (`:131-146`) serves an unmarked or `none` pair through its Connections by label, and a
`migrated` pair with no effective reference through the same label path
(`_resolve_migrated_by_label`).

Native writes never promote a pair: `claim_native_write` keeps the observed state
(`connection_native.py:50-66`, "no auto-promotion, D14"). So a provider connected through
`/v1/oauth/connections` after the E4 census answers chat and still reads `not_connected` in the
listing, which the Hosted Engine relays (`screamingface_engine/connections/aigateway.py:79-86`).
A second case: a `migrated` pair whose effective row was disconnected, then reconnected natively,
dispatches through the new row and lists `not_connected`.

Both rules are pinned by passing tests:
`test_connection_only_resolve.py::test_an_unmarked_pair_resolves_its_one_active_connection_without_the_index`
and `::test_availability_reports_a_non_migrated_pair_as_not_connected[none]`. No test states that
the two answers agree.

## 2. Intent on record

- Epic spec §1 end state: "one resolver for chat, model parameters, admission, availability".
- Epic spec §3.3 op 6: Connection-only accounts show `not_connected` in the window; "folding
  Connections in is a later flagged behaviour change".
- D17 (`:456`) posed "whether Connection-only accounts fold into the window listing" and answered
  only the route shape. §10 (`:488-489`): the semantics change at the backing switch "unless
  deliberately reproduced".
- OME-1209 plan E4a (`:222-223`) kept "D17 unchanged"; no later landing returned to it.
- Owner plan (`implementation_plan.md:133-135, 255`): availability of one effective Connection
  through the common resolver; the legacy aggregate only until the switch.

## 3. Goal

For every listed provider, `connected` means the default (selector-less) chat resolve finds a
usable stored credential for the pair, and every other status says why it does not. The selection
rule exists once and both paths call it.

## 4. Behaviour

Rows stay as they are: registered providers this account may VIEW (OME-1721), sorted, `provider`
and `status` only, from the closed five-value family.

| Pair (marker) | Today | After |
|---|---|---|
| no marker, no Connection | `not_connected` | `not_connected` |
| `migrated`, effective reference set | effective row's status | unchanged |
| `quarantined` | `not_connected` | unchanged (chat refuses 409; no writer since E5c) |
| no marker, `none`, or `migrated` with no reference | `not_connected` | the label rule below |

Label rule, over the pair's non-revoked Connections, with the default selector:

| Rows | Chat today | Availability after |
|---|---|---|
| exactly one `active` | served | that row's operational status: `connected`, or `needs_reauth` / `error` from the credential's recorded outcome, the function migrated pairs already use |
| two or more `active` | 409 `connection_ambiguous` | `error` (Q1, decided) |
| no `active`, at least one `pending` | refused (`TargetMissing`) | `pending` |
| no `active`, no `pending`, at least one `error` | refused | `error` |
| none of the above | refused | `not_connected` |

A `none` pair's resolve does not consult the credential's recorded outcome; availability does, as
for migrated pairs. Recorded outcomes are written only for migrated pairs (`begin_dispatch`), so for
a `none` pair this changes the answer only when the credential record is missing, where chat also
refuses: `authorize` cannot read the key and answers 401 re-authentication.

Accepted consequences (review, 2026-10-29), each already true for migrated pairs or invisible to
users:

- A recorded `insufficient_credits` outcome lists `error` while chat still dispatches, so the
  provider can recover (`connection_authority.py`, "remains dispatchable for recovery").
- An OAuth-tagged row whose credential record is missing lists `connected`; chat answers 401 and
  marks the row, after which the pair lists `error`.
- An abandoned OAuth start leaves a `pending` row that nothing expires, so a pair with no active row
  lists `pending` until a connection completes. The Hosted SDK shows `pending` and `not_connected`
  alike, as unavailable.

## 5. Invariants kept

- No secret read, no refresh, no mutation. In particular the API-key retag
  (`_repair_api_key_only`) stays on the resolve path only. The credential record read is metadata
  only, exactly as for migrated pairs today.
- The marker is read once per pair per call; an unreadable marker or Connection store propagates
  and fails the request (an unreadable credential record answers 503), never a silent
  `not_connected`.
- One Connection listing per call for the account, not one per provider.
- Resolve behaviour is unchanged: every existing resolve test passes unmodified.
- The five-value vocabulary, the route, OpenAPI, the Engine DTO and the SDK decoder are unchanged.

## 6. Scope

- `core/provider_access/connection_backed.py`: extract the label selection from
  `_active_connection` into one pure function over a pair's rows; resolve and availability both
  call it. Availability applies §4.
- Docstrings that state the window rule (`availability`, `test_provider_access_availability.py`
  module docstring) describe the new rule.
- Tests, first (RED):
  - an agreement table over the §4 cases: availability reads `connected` exactly when the default
    resolve returns a stored target;
  - the migrated-without-reference case;
  - the new path reads no secret, writes nothing and lists Connections once;
  - one route-level case through `GET /v1/provider-access`.
- One prior test changes, under an owner manifest
  (`.claude/test-change-approvals/OME-N.json`):
  `test_availability_reports_a_non_migrated_pair_as_not_connected` keeps its `quarantined` case;
  its `none` case moves to the agreement table with the new expectation.
- The epic spec's op 6 gets a dated line pointing at this leaf.

## 7. Out of scope

- Promoting `none` pairs to `migrated` on native writes, or a one-off promotion of existing ones
  (§9).
- The Local Engine's managed-label selection (review finding F2): a separate owner decision.
- Providers that resolve without a stored credential (no-auth or chatless plugins): they read
  `not_connected` today and did in the Profile era; unchanged here.
- `quarantined` retirement, `FakeProviderAccess` vocabulary, and the other review clean-ups.

## 8. Release

One `feat(aigateway)` change, not breaking: the vocabulary and shape are unchanged; listed statuses
become accurate. The release note says that Connection-backed providers now list their real status
in `GET /v1/provider-access` and the Hosted Engine. No runtime flag (Q2): the change is stateless
and writes no data, so rolling back the image restores the old listing.

## 9. Alternative considered

Promote on write: every native write marks the pair `migrated` with that row as effective, and a
one-off step promotes existing `none` pairs; the label path and this listing rule could then be
deleted. It removes the two-state model at its root but needs a data step per environment, a
disposition for pairs with several active rows (kept unmigrated by the Stage B window rule, D12),
and changes to the writer floor. Not chosen for this leaf; a candidate follow-up.

## 10. Owner decisions (2026-10-29)

- Q1. Two or more active Connections list `error`: chat refuses, and `not_connected` would invite
  connecting yet another row.
- Q2. No runtime flag: "flagged" in op 6 is read as an announced change; rollback is the image.

## 11. Acceptance

- The agreement table passes. The `none` and migrated-without-reference cases list `connected`
  when chat is served.
- All existing resolve, admission, model-parameters and route tests pass unmodified; the one
  changed availability test is in the manifest.
- The AIGateway gate passes (lint, format, types, enterprise guard, full suite with coverage); the
  `needs_postgres` suites pass.
- Engine and SDK suites need no change and stay green.
