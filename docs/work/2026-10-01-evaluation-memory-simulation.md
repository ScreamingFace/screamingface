---
ticket: OME-1448
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# Full evaluation memory simulation

## Intent
Exercise the real Client.evaluate, HTTP/WebSocket transport, large streamed downloads, indexing, report construction, export and fresh-process recovery without paid calls.

## Planned changes
Add a development-only subprocess harness using the existing Engine wire fixtures and a chunked on-disk artifact responder. Exercise 11 concurrent candidates with 4182 cases and roughly 200 MB each, a decode process crash, remote re-fetch with saved tickets, and offline reopening. Keep source and test results for inspection.

## Test plan
Small subprocess smoke test first, then full-size run. Assert complete candidate/case counts, retained prompts, stable export digests, no run starts during recovery, fresh capabilities and peak worker RSS below 512 MiB. Measure client memory in separate fresh worker processes, excluding the simulator. All SDK gates.

## Acceptance
Do not replace the SDK transport or report builder; only simulate external Engine/model execution. No paid calls. Report limitations: simulator is not actual hosted infra, Engine aggregation or VSCode renderer.

## Outcome
Implemented `scripts/check_evaluation_memory.py` and a small subprocess regression. The development-only server reuses the Engine wire/catalog fixtures, gives each concurrent run a distinct identity, expires its start capability, and serves the on-disk artifact in 64 KiB chunks. The real SDK discovery, compilation, HTTP/WebSocket transport, download verification, candidate scheduling, indexing, report construction and export remain untouched.

RED: missing harness failed the subprocess test. GREEN: two candidates × 30 cases pass all phases. Full workload: 11 candidates × 4182 cases, 201,892,405 bytes per candidate, no paid calls. Evidence is saved in `docs/work/assets/OME-1448-evaluation-validation.json`.

| Phase | Peak client RSS (MiB) | Elapsed (s) |
| --- | ---: | ---: |
| Full Client.evaluate + export | 82.1 | 42.9 |
| Fresh local decode after crash | 65.0 | 41.1 |
| Remote re-fetch + decode + export | 94.0 | 45.2 |
| Offline reopening + export | 58.1 | 17.6 |

Each phase returned all 46,002 cases; all peaks remained below 512 MiB. Local, remote and offline exports for the crashed evaluation have the same SHA-256 and preserve all 2,219,539,272 bytes. Run starts were 22 before and after recovery (11 normal + 11 interrupted evaluation); artifact fetches were 33 (11 normal, 11 interrupted, 11 remote recovery), using fresh capabilities. Offline runs succeed with no listening server. Process exits 73 during decode and 74 during export deliberately bypass Python cleanup; the latter retains the prior complete export, then fresh offline recovery succeeds.

The full online run was launched before the export/local additions. Those final phases were completed against its retained evidence: preserved pre-index raw files were hard-linked into a fresh local store with copied manifests and no index/cache, and the export crash used the retained recovered store. No original researcher/demo results were removed. The final harness executes all phases in one command; its small regression verifies that sequence.

Limitations: synthetic identical candidate bodies with deterministic grades, not the researcher's exact fusion/operation payload. Forced termination models abrupt kernel death, not an actual OS OOM event. This macOS loopback server does not validate real hosted authentication/TLS/bucket lifecycle, Ubuntu resource limits, Engine aggregation, or VSCode's renderer. Server RSS was not recorded; client workers are separate processes, and the responder never reads the whole artifact. JupyterLab's large-fixture rendering was verified separately.

Wisdom: wire fixtures must assign unique run IDs to concurrent candidates; reusing the original single-run ID made saved records overwrite one another in the initial harness, caught by the fresh recovery assertion. Fix was confined to simulator event identities, with no SDK changes.

Repeat from the SDK package: `python scripts/check_evaluation_memory.py --directory /fresh/output/dir`. Optional `--source /path/to/fixture.json` reuses the earlier fixture. Retain outputs for inspection; the harness refuses a nonempty output directory.

Final validation: small end-to-end regression passes with local/remote/offline hash equality, forced decode/export exits and unchanged run-start counts. All SDK gates green (Ruff, format, Pyright, full pytest with ≥95% coverage, notebooks, build, distribution); append-only check remains skipped for the earlier owner-approved UI/API contract changes on this branch. Self-review: harness is test-only, real SDK transport stays intact, no dependencies or credentials are added, outputs are isolated and original fixtures retained.
