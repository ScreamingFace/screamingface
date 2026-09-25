# Bridge-aware analytics readiness

Approved implementation: fix the reported PR #1072 readiness bug and open a PR.
Kubernetes removes a not-ready pod from Service endpoints, so readiness must
represent both available service capabilities rather than event ingestion alone.

Readiness is `(ingestion enabled OR bridge enabled) AND NOT draining`.
It is not PostHog reachability. Both-disabled behavior remains 503. Shutdown
always returns 503. Event admission still depends on ingestion.enabled; bridge
readiness must never enable event forwarding. Consent and opt-out remain usable
with ingestion disabled. Liveness and route contracts otherwise remain unchanged.
