---
id: OME-795
linear_url: https://linear.app/openmined/issue/OME-795/make-url4-cloud-local-mode-reach-a-successful-run-out-of-the-box
status: In Progress
type: Bug
priority: P1
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-12
closed:
---

# Make url4-cloud local mode reach a successful run out of the box

Three stacked defects stopped `url4-cloud serve --local` from completing any run on a clean
checkout, each reporting a cause that was not the cause:

1. The local gateway-address fallback was applied after the catalog was built and only to
   connections, so `/v1/models` answered 503 while `/v1/connections` answered 200 on the same
   default address.
2. Local mode installed the builtin Benchmarks unconditionally, and DRACO's install reads an
   image-only asset path — failing *every* run with `benchmark_unavailable`, including runs that
   address no Benchmark.
3. `url4.toml` declared the five Anthropic ids unprefixed while aigateway serves them prefixed,
   dropping all five from discovery and breaking the declared `default_route`. The pinning test
   could not see this: it AST-parsed aigateway's source and applied a hardcoded prefix table.

Ledger: `docs/work/2026-08-12-OME-795-local-mode-bringup.md`
