---
ticket: OME-1013
stack: repo
status: blocked
started: 2026-09-07
finished:
---

# OME-1013 — Check real notebook reporting prerequisites

## Intent

Verify report-service authentication reuse and anonymous Turnstile integration before building
the combined notebook UI. Separate admission evidence from successful persistence and delivery.

## Planned changes

- This evidence ledger only; no application changes or deployment configuration changes.

## Test plan

- Discover available notebook/browser access using the installed browser skill.
- Compare public Access challenges for the configured Engine and internal report service.
- Run existing Client authentication tests without modifying user files.
- Perform real notebook submissions only with valid report credentials/Turnstile and inspect
  backend evidence when deployment access is available.

## Acceptance

- Authentication reuse is demonstrated or its actual prerequisite identified.
- Real browser and backend-access limitations are recorded without claiming end-to-end success.

## Outcome

- **Actual files:** this ledger and the integration-evidence note in the consolidated plan.
- **Commits:** this iteration's `docs(screamingface): record reporting auth integration evidence`.
- **Gates:** 79 existing Client authentication tests passed at PR #756 head `4a9abe64`,
  including matching-audience login reuse and distinct-audience isolation. Initial sandbox
  run had 75 passes and four local-server bind permission failures; full rerun with socket
  access passed. No application files changed.
- **Live evidence:** unauthenticated GET requests to the configured Engine
  `https://fusion.dev.screamingface.ai/v1/models` and internal reporting endpoint both returned
  Access 302 and the same audience (`f9d2d35a2db5c5d89fb2493b2e26c8343c9b3d83a11b9345b40097c6de6f47bf`).
  Only public challenge metadata was inspected. Existing Client auth owns a token store per Client,
  shared by Engine/Scoreboard auth objects; report auth must be wired to that same store.
- **Blockers:** no running local notebook was found; browser bootstrap failed because its trusted
  worker imports the missing `browser/26.814.41407/scripts/browser-service.mjs`, while the installed
  plugin is `26.825.32147`. No browser cookies, tokens or profile stores were inspected. Public
  report Turnstile site key/allowed notebook origin was not found in scoped configuration;
  requested the public key/configuration location and intended notebook from the owner.
  kubectl still has no current context, so deployed sink and stored rows cannot be verified.
- **Deviations:** real notebook flow, valid Turnstile issuance, accepted internal/anonymous POSTs
  and backend delivery remain unverified. No valid live report was submitted, no auth gate
  bypassed and no application/deployment configuration changed. Matching public audiences plus
  passing mocked/local auth tests establish feasibility, not successful live reporting.
