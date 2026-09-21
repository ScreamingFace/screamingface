---
id: OME-1245
linear_url: https://linear.app/openmined/issue/OME-1245/move-the-hosted-engine-listing-onto-the-availability-successor
status: in_progress   # code stage started 2026-09-21 after OME-1244 merged
type: task
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1138
blocked_by: [OME-1244]
created: 2026-09-21
closed:
---

# Move the Hosted Engine listing onto the availability successor

Stage A4 of `OME-1138`, Engine half (plan unit U4e). The Hosted Engine's `/v1/connections` listing
aggregates the gateway's legacy `GET /v1/auth/profiles` body locally
(`connections/profile_availability.py`). Once `OME-1244` publishes `GET /v1/provider-access`, the
Hosted branch reads that listing, `X-Profile` is not forwarded on it, the local decoder is
removed, and `listing_source` gives way to the D15 explicit mutability rule (Hosted
`mutable=False`, Local `mutable=True`; Hosted mutations refused before any upstream I/O). The
Engine `/v1/connections` DTO field set and the Local Engine behaviour stay unchanged.

Ledger: `docs/work/2026-09-21-OME-1245-hosted-engine-availability-successor.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md` §3.5, §4, §5 A4, §8 (D15, D17).
Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md` §2 U4e, §3 A4.

- 2026-09-21: issue filed as plan unit U4e, blocked by `OME-1244`. Decision F-A4-1 raised on the
  issue: the prior suite `tests/unit/test_connections_profile_availability.py` pins
  `listing_source="profiles"` and the local aggregation and cannot stay green unmodified once the
  plan's "decoder replaced" acceptance is met; recommendation is re-expression at the successor
  seam. **Gate:** Needs Owner. No code written.
- 2026-09-21: owner approved the issue as filed and decided F-A4-1: the prior suite is
  re-expressed at the successor seam when this unit starts; `listing_source="profiles"` is not
  kept alive. **Gate:** Todo, blocked by `OME-1244`.
- 2026-09-21: `OME-1244` merged to `main` as `2da45896` (PR #1006) and closed Done, which lifts
  the blocker. Unit started from that commit on branch
  `OME-1245-hosted-engine-availability-successor`; design coverage re-verified against design
  `main` (PR #22: `protocol/provider-access-availability` v1 Hosted Engine consumer section,
  `product/engine` v3) — no design change needed. Ledger created. **Gate:** In Progress.
- 2026-09-21: RED → GREEN complete. Hosted `list()` reads `GET /v1/provider-access` after the
  catalogue through the new strict decoder `connections/provider_access_availability.py`, with
  `X-Profile` dropped on that request only; `connections/profile_availability.py` deleted;
  `listing_source` replaced by `mutable` (Hosted `False`, Local `True`), required at
  `build_connections`. Prior suite re-expressed per F-A4-1 as
  `tests/unit/test_connections_provider_access_availability.py`. Engine gate runner ALL GATES
  GREEN vs `2da45896` (append-only skipped for that one re-expressed path only); full suite
  3283 passed / 16 skipped / 93.54%. **Gate:** Needs Owner — authorization to stage, commit,
  push and open the PR.
