---
ticket: OME-2038
stack: aigateway
status: in_progress
started: 2026-11-25
finished:
---

# frozen-copy-claim-no-actor — the claim route needs no caller address

## Intent

Owner decision 2026-11-25 (spec Q34), while the infrastructure values for the claims were drafted
(OpenMined/infrastructure#2531). Users never reach the AI gateway; only in-cluster services do, and
the NetworkPolicy is the boundary. The claim route of stack B1 still asked for a fixed address
(`AIGW_FROZEN_COPY_CLAIM_EMAILS`), and the scoreboard sent it (`SCOREBOARD_GATEWAY_ACTOR`). Any
admitted pod can send any header, so that address protected nothing. This unit removes it from both
apps. In `cloudflare_headers` mode the claim route now checks the peer network only.

## Planned changes

- aigateway: `core/auth/copy_claim.py` (peer check only), `config.py` (no
  `frozen_copy_claim_emails`), chart values, ConfigMap and README, DEPLOYMENT.md "The claim route",
  tests.
- scoreboard: `config.py` (no `gateway_actor`), `gateway_copy_claims.py` (no header), chart values,
  ConfigMap and README, DEPLOYMENT.md "Frozen copy claims", tests.
- spec: `contracts.md` K4, `prd/score-claim.md` C13, §4.1, §4.2, K-5 to K-7, K-17, §7.1,
  `00-overview.md` §7.3 and the decision row Q34, `test-plan.md` §5.2 (1).

## Test plan

- RED first: a trusted peer with no `X-User-Email` gets the claim answer (404 for an unknown id,
  200 for a sealed copy); an untrusted peer still gets 403; `jwt` mode still 503.
- The scoreboard client sends no `X-User-Email`; `Settings` accepts a gateway URL alone.
- The charts render no `AIGW_FROZEN_COPY_CLAIM_EMAILS` and no `SCOREBOARD_GATEWAY_ACTOR`.
- Tests on main that assert the removed behavior change (approved by the owner's decision Q34).

## Acceptance

- Gates green for aigateway and scoreboard.
- No mention of the claim address or the actor stays in the two apps or in the spec, except the
  decision row Q34 and this ledger.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `apps/aigateway/src/aigateway/routes/frozen_copies.py` (docstring)
  and `.github/scripts/verify_chart_wiring.py` (the scoreboard chart check: no actor key).
- **Commits:** see the PR.
- **Gates:** aigateway, scoreboard and repo: ALL GATES GREEN (2026-11-25, `--skip-append-only` until
  the approval record of the changed tests is written at PR-open).
- **Deviations:** none.
