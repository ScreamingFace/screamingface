---
ticket: OME-1378
stack: analytics
status: done
started: 2026-09-25
finished: 2026-09-25
---

# Colab origin policy — verified notebook support

## Intent

Verify actual Colab output origins and support the observed bounded host pattern
without per-notebook configuration or unrestricted website access. Owner authorized
implementation, testing and merge. General bridge enablement remains opt-in;
private dev deployment configuration is managed elsewhere.

## Planned changes

- apps/analytics settings, bridge origin policy and iframe parent validation.
- Append Python/Node security boundary tests; preserve existing exact-origin mode.
- Spec/plan, app deployment instructions and this evidence ledger.

## Test plan

- Capture real notebook output origin and ancestor evidence, including reload.
- Accept only verified HTTPS Colab output hosts; reject lookalike suffixes,
  null origins, unexpected ports, invalid labels and arbitrary websites.
- Keep origin/source/nonce checks and exact reply targets; test emitted CSP.
- Analytics gates, Helm checks, review and green CI before squash merge.

## Acceptance

Supported Colab notebooks work without manual origin registration; no global '*'
allowlist. Browser evidence clearly distinguishes observed from untested behavior.

## Outcome

Pending origin capture and implementation. Worktree starts at origin/main 494a5fa3.


## Verification and outcome

- Live Colab probe used the existing work-account experiment notebook B:
  https://colab.research.google.com/drive/1o0mD4PV9diiJYLhetgfspmYyOT2qM4vV
- Before reload: `https://6ernmmrpvem-496ff2e9c6d22116-0-colab.googleusercontent.com`.
  After reload and rerun: `https://1ruu7u27wb7-496ff2e9c6d22116-0-colab.googleusercontent.com`.
  Both reported the sole ancestor `https://colab.research.google.com` and that
  same top-level referrer. A fresh temporary CPU runtime ran only the origin
  probe; saved notebook evidence retained and temporary runtime released afterward.
- Actual changes: shared Python/browser origin grammar, opt-in Colab profile,
  exact validated parent-origin CSP, deployment values and adapter instructions,
  new Python/Node boundary tests, append-only chart check, spec/plan/ledger.
- All analytics gates green: 110 Python tests (including the Node script tests),
  99.07% branch-aware coverage, lint/format/types/lock/build. Helm lint and rendered
  chart checks pass. Existing test bodies unchanged; no new dependencies.
- Review: arbitrary googleusercontent hosts, null, credentials, explicit ports,
  paths, nested/lookalike hosts and overlong labels rejected. Dynamic CSP uses
  exact validated output plus observed top ancestor, no broad wildcard. JS replies
  remain exact and source/nonce checks remain intact. Legacy exact-origin mode
  preserved. Empty Colab parent remains frame-ancestors none, not fail-open.
- Owner authorized testing and merge of this follow-up to OME-1378. No new issue
  required for correcting the same bridge delivery. General bridge default stays
  disabled, while README supplies complete dev opt-in values for the private repo.
- Remote service deployment, full Chrome/Safari cookie lifecycle and Colab SDK
  adapter remain outside these passed checks. This change does not claim those.
- Commit: `fix(analytics): support verified changing Colab output origins`.
