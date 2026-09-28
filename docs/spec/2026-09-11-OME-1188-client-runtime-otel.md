# OME-1188 — Runtime dependency parity

The optional Client runtime extra must provide `opentelemetry-sdk>=1.30.0` and
`opentelemetry-exporter-otlp-proto-http>=1.30.0`, matching the bundled Engine and
Gateway requirements introduced by PRs 905 and 909. Base Client requirements,
application code, and export configuration remain unchanged.

Refresh the Client lockfile without upgrading unrelated packages. The existing
runtime dependency-parity regression test must pass, along with all Client gates.
Deliver a draft PR; do not merge or close the issue.

The user explicitly approved implementing this scoped fix and creating a draft PR
on 11 September 2026.
