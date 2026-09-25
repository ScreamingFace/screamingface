# Colab bridge service implementation plan

Spec: ../spec/2026-09-25-analytics-colab-bridge-spec.md

1. Owner selected browser-mediated delivery on 25 September 2026.
2. Add failing consent/cookie contract tests and origin/size/cache rejection tests.
3. Implement narrow consent/identity core and HTTP cookie adapter, optional router
   wiring and explicit validated deployment settings. Keep ingestion core isolated.
4. Add bridge HTML/script message protocol with validated source/origin/nonce/schema;
   no third-party scripts, unique data in HTML/URLs or wildcard reply destinations.
5. Implement the chosen consent-checked delivery/revocation path and test races,
   accepted-before-decline semantics and stale runtime behavior.
6. Run analytics gate runner, package checks and browser protocol verification;
   document ingress routes, CSP ancestors, cookie lifetime and log requirements.
7. Commit after gates pass; no PR or Linear issue until separately requested.

Deployment/browser checks requiring the new dev endpoint cannot be represented as
completed by local unit tests. Colab SDK integration stays in a subsequent unit.
