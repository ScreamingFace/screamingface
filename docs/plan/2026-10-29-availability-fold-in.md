---
status: accepted   # owner approval 2026-10-29
issue: OME-1778
parent: OME-1138
date: 2026-10-29
base: origin/main ee7fc24b6
---

# Provider availability follows the resolver (D17 fold-in) — plan (OME-1138)

Implements `docs/spec/2026-10-29-availability-fold-in.md` (accepted 2026-10-29: Q1 `error` for
an ambiguous pair, Q2 no runtime flag). One leaf under
`OME-1138`, one PR in this repo, landing `aigateway`.

## 1. Layout

| Tree | Purpose |
|---|---|
| `.claude/worktrees/availability-fold-in` (branch `availability-fold-in` from `origin/main`) | code, tests, spec, plan, ledger |

`uv sync --locked` in `apps/aigateway` of that worktree. Nothing is edited in the shared checkout.

## 2. Steps

1. **Ledger first.** `docs/work/2026-10-29-availability-fold-in.md` from `docs/work/TEMPLATE.md`
   (`ticket: unfiled`; Intent, Planned changes, Test plan, Acceptance). Copy the spec and this plan
   to `docs/spec/2026-10-29-availability-fold-in.md` and `docs/plan/2026-10-29-availability-fold-in.md`.
2. **Baseline.** On the fresh worktree, the focused suites pass:
   `tests/unit/core/provider_access/` (resolve, availability, port shape, operational outcomes),
   `tests/unit/test_provider_access_availability_route.py` and
   `tests/unit/openrouter/test_migrated_rejected_key_availability.py`.
3. **RED.** New module `tests/unit/core/provider_access/test_availability_follows_resolve.py` on
   `ConnectionBackedHarness` with the Anthropic test plugin (not chatless):
   - the agreement table, parametrized over the marker (absent, `none`, `migrated` with no
     reference) and the rows (one active OAuth, one active API key, two active, pending only, error
     only, revoked only, none). Each case asserts the spec §4 status, and that it is `connected`
     exactly when chat would be served: the default resolve returns a stored target and
     `authorize` accepts it. Availability is read first, since a refused `authorize` marks the row;
   - an active API-key row whose credential record is missing lists `needs_reauth` on every marker
     (chat refuses at `authorize` with re-authentication); a recorded `needs_reauth` outcome lists
     `needs_reauth` on a `migrated` pair with no reference, where resolve refuses the same way.
     Outcomes are recorded only on migrated pairs, so a `none` pair never carries one;
   - the new path reads no secret, writes no Connection, marker or credential record, and lists
     the account's Connections once per call (spies on the wired stores);
   - an unreadable Connection store propagates from `availability` instead of listing
     `not_connected`.

   One route-level test is appended to `tests/unit/test_provider_access_availability_route.py`: a
   `none` pair with one active Connection lists `connected` through `GET /v1/provider-access`.
   The prior `test_availability_reports_a_non_migrated_pair_as_not_connected` keeps only its
   `quarantined` case; the `none` case now lives in the agreement table. This is the one prior-test
   change (manifest at step 9). Each new test fails for the stated reason (`not_connected` where
   the table expects otherwise) before any production change.
4. **GREEN.** In `core/provider_access/connection_backed.py`:
   - extract the selection in `_active_connection` into one pure function over a pair's active
     rows and the selector (one row, `SelectorAmbiguous` or `SelectorUnknown`, or none). Resolve
     keeps its I/O and its API-key retag; its behaviour does not change;
   - `availability` lists the account's non-revoked Connections once, groups them by provider,
     and for a pair that is not served by its effective reference applies spec §4 through the same
     function: one active row → `operational_availability_status_for`; `SelectorAmbiguous` →
     `error`; no active row → `pending`, else `error`, else `not_connected`. Providers with
     Connections but no marker are covered, not only the markers' providers;
   - if the file grows past 450 lines, the availability rule moves into its own module under
     `core/provider_access/`.

   Then the full AIGateway suite. Retries are bounded at 10 per failing signal.
5. **Comments and docs.** The `availability` docstring states the new rule (the D17 window `WHY`
   goes). The module docstring of `test_provider_access_availability.py` says the same. The epic
   spec `docs/spec/2026-09-09-OME-1138-converge-connections.md` op 6 gets a dated line naming this
   leaf. New comments use the `WHY` / `INVARIANT` / `FEATURE` / `STORY` anchors only.
6. **Gates.**
   - `uv run .claude/scripts/run_gates.py aigateway` from the repo root: lint, format, types,
     enterprise guard, full suite with coverage.
   - `AIGW_TEST_PG=1 uv run pytest -m needs_postgres` from `apps/aigateway`, with the PostgreSQL 16
     client first on `PATH`.
   - Engine adapter tests (`apps/screamingface-engine`, connections suites), unchanged code, to
     confirm the pass-through.
7. **Review.** An independent read-only review of the branch diff before PR-open; material findings
   are fixed or reported.
8. **Ledger outcome.** Actual files, commits, gate results, deviations.
9. **PR-open, on the owner's word for each external step.** Confirm the leaf first:
   - Title: "Fold Connection-backed pairs into the provider availability listing (D17)".
   - Labels `aigateway`, `agentic`, `autonomous`; priority High; parent `OME-1138`; assignee me.
   - Rename the branch to `OME-N-availability-fold-in`.
   - Write `.claude/test-change-approvals/OME-N.json` for the one changed prior test (base and
     approved blobs), and the `docs/tasks` mirror.
   - Stage, on approval of these exact Markdown paths: the spec, the plan, the ledger, the mirror
     and the epic spec.
   - Commit `feat(aigateway): …`; PR body from `pr_template.md` with `Refs: OME-N`, a release note
     line, no tool mentions and no attribution lines.
10. **Close.** Close comment and Done; close the mirror and the ledger.

## 3. Risks

- **Hosted listing changes for real users.** Providers connected natively start reading
  `connected` (or their true status). This is the intended change; the release note names it.
- **Ambiguous pairs read `error`.** The Hosted SDK view already collapses every non-connected
  status to unavailable, so users see no new state.
- **One more query per listing.** One Connection listing per account per call, not per provider.
- **Resolve drift during the extraction.** Every existing resolve test stays unmodified and must
  pass; the agreement table is the guard from now on.

## 4. Not in this plan

Promote-on-write and existing `none` pairs (spec §9); the Local Engine label rule; no-auth and
chatless providers; `quarantined` retirement; `FakeProviderAccess` vocabulary; the other review
clean-ups.
