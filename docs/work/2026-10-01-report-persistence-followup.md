---
ticket: OME-1448
stack: screamingface
status: complete
started: 2026-10-01
finished: 2026-10-01
---

# Persistence and CI follow-up

## Intent

Resolve the supplied completion/persistence, partial-recovery and notebook findings against current HEAD. Restore the existing golden replay without updating expected results.

## Planned changes

Encode candidate metadata without recursively copying excluded immutable parameter assignments. Move ready transitions to final/handled-partial report boundaries, preserve interrupted recovery and deliberately update source/destination markers. Translate per-candidate filesystem failures to SDK storage errors. Reuse compact accounting in static rendering, prefer exact string identities, and synchronize live case selection without unsafe inline scripts.

## Test plan

New regression tests first: parameterized sync/async transport persistence; progress completion pending; unreadable sibling partial reports; destination markers; exact string/numeric identities; bounded static accounting; browser selection. Run targeted tests, SDK gates, then verify golden replay and latest CI checks. Goldens unchanged. No paid model calls.

## Acceptance

Actionable failures reproduced and corrected, no bare filesystem exception aborts sibling recovery, no completion callback marks unfinished evaluations ready, static fallback avoids all-case accounting rows, exact IDs and manual selection preserved. Existing CI expected scores remain unchanged.

## Outcome

Confirmed every supplied failure against the current branch before fixing it. The CI job supplied by the reviewer failed IFEval after Engine completion with the exact mappingproxy deepcopy error. Candidate recovery metadata now explicitly encodes retained fields; parameter preflight assignments are excluded without copying, while their compiled URL4 remains intact.

Report construction is pure. Final evaluation and handled partial-report boundaries own ready marking; grouped recovery stays running between fetches/decodes and deliberately updates source/destination records when returning the full or handled partial report. Per-candidate filesystem/SQLite errors use the existing result_storage_failed contract and preserve healthy siblings. Static report cards and bounded case previews share compact saved accounting context. Exact string case IDs take precedence; manual selection retains the actual ID type across candidate filters.

The original rail/detail layout is retained. A small ipyevents dependency bridges native click events to kernel focus; CSS selection still happens immediately. The preview server was restarted to load its JupyterLab extension, using the original authentication settings. Clicked case 23 in candidate-0 then switched to candidate-1: the checked row and visible CASE 23 · CANDIDATE-1 detail both persisted. Screenshot is assets/OME-1422-case-selection-preserved.png. Callback regression tests pin selection and mixed numeric/string identities; live browser validation checks actual frontend event delivery.

The unchanged real IFEval golden replay passed locally on the Engine plus isolated cache-only gateway (31.5s). No provider keys or paid model calls; no golden/workflow/expected-result edits. Independent Standards/Spec reviewers found no new concrete blocker and 66 focused recovery/selection tests passed.

Static _repr_html_ and forced widget-free fallback were measured in a fresh process over the saved 11 × 4,182 (~2.22 GB) fixture: 25 panes, 109,765 HTML bytes, 74.59 MiB peak RSS. Evidence: assets/OME-1448-static-render-validation.json. These are macOS synthetic measurements, not hosted/Ubuntu/VSCode proof.

Final SDK gates passed: append-only tests, Ruff lint/format, Pyright, full pytest with >=95% coverage, deterministic notebook verification, wheel/sdist build and distribution checks. Fresh GitHub CI is tracked in the draft PR after push; the unchanged local golden replay passed.

Wisdom: explicit serialization avoids recursive copying of irrelevant fields; lifecycle belongs to operation boundaries; no schema or exported score changes. File failures stay visible as SDK errors, no credentials persisted. Existing committed tests unchanged; tests are append-only. Notebook frontend event support must be present in the server/VSCode frontend as for other custom widgets; real VSCode validation remains pending.
