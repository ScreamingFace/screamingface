---
id: OME-1200
linear_url: https://linear.app/openmined/issue/OME-1200/introduce-the-provider-access-port-with-a-profile-backed-read
status: done
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-09-14
closed: 2026-09-14
---

# Introduce the provider-access port with a Profile-backed read implementation

Stage A1 of `OME-1138`: new `core/provider_access/` package, Profile-backed implementation by relocation, HTTP-edge rendering table, compatibility shims; zero behaviour change; follows `OME-1198` and `OME-1199`; stop for review after completion.

Ledger: `docs/work/2026-09-14-OME-1200-provider-access-port.md`.
Spec: `docs/spec/2026-09-09-OME-1138-converge-connections.md`. Plan: `docs/plan/2026-09-09-OME-1138-converge-connections.md`.

A1 done 2026-09-14: `core/provider_access/` + HTTP table + shims + wiring; 170 provider-access tests;
existing tests unedited; stack gate, consumer gates and OpenAPI byte-identity green; stopped for
owner review before A2. Details in the ledger Outcome.
- 2026-09-14: owner review findings F1–F6 fixed on the branch (port shape per spec §3.3, substitution-honouring lookup, admin Protocol shape, side-effect contract tests, touch-order declared, annotations); aigateway + Engine gates ALL GREEN.
- 2026-09-14 (round 2): F4 residual (missing Connection blob contract + fake) and F5 residual (headers normalised before the touch; owner accepted touch-before-sealing as a parity exception) fixed; aigateway gate ALL GREEN; committed as the OME-1200 unit.
