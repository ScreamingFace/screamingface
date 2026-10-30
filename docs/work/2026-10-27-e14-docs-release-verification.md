---
ticket: OME-1655
stack: repo
status: done
started: 2026-10-27
finished: 2026-10-27
---

# E14 documentation release verification

## Intent

Verify the public replay documentation against the released SDK, replace its source
baseline with the verified release. Production copied-button acceptance remains separate.
The remaining-child reconciliation is being discussed separately with the owner and is
not part of this documentation change.

## Planned changes

- Update the SF Client sidebar release baseline and any replay guidance that fails verification.
- Reconcile the OME-1655 mirror with merged work and live dev acceptance.

## Test plan

- Install the published SDK in an isolated environment; inspect documented API contracts.
- Execute the documented pinned-cache replay against the existing complete dev capture,
  with reproduction recording disabled; require exact agreement and zero provider spend.
- Build/type-check the docs, lint the changed source, and inspect the rendered guidance.
- Run repository gates and whitespace checks.

## Acceptance

- Sidebar identifies the published SDK that was verified.
- Replay examples and prerequisites agree with that SDK and the live dev result.
- Linear writes require the user's approval; this docs change makes none.

## Outcome

Implementation and local verification complete; publication and production acceptance
remain outstanding. This ledger's `done` status does not close OME-1655 or E14.
No Linear changes made by this work.

- **Actual files:** the two planned public-docs sources, OME-1655 task mirror and this ledger.
- **Changes:** sidebar links to SDK 0.1.7 on PyPI; guide pins the installation version,
  explicitly pairs Engine/Scoreboard URLs, and explains capture location and upgrade limits.
  Mirror reflects the merged PR and accepted dev rollout.
- **Commit:** this ledger is included with the documentation correction; see this file's git history.
- **Gates:** `npm ci --no-audit --no-fund`; Node 22.23.4 (CI lane Node 22),
  `npm run build` (Vue type-check + Vite), full `npx oxlint .` and `npx eslint .` all passed.
  Prettier check passed for both changed public-docs files. `run_gates.py repo --base origin/main`
  reported ALL GATES GREEN; mirror validation after its update and `git diff --check` passed.
- **Browser:** live docs still showed source commit `ac2c8cb2` before this correction.
  Built local preview displayed the 0.1.7 PyPI link, prerequisites and updated snippet.
  Copy-to-clipboard contained explicit configuration, `pinned_cache` and the recording opt-out.
  No browser console errors; Plausible's localhost-ignore warnings are expected.
- **Deviations:** no product code or automated test files changed. System Node 24.10.0 did
  not meet the site's engine range, so verification used Node 22.23.4. Repository gates
  initially lacked PyYAML in system Python; they passed with the isolated environment on PATH.
  Replays used dev URLs and disabled recording rather than adding duplicate reproduction records.
  The publication branch has no issue ID to avoid automatically closing the still-open
  production acceptance ticket. The owner requested this docs-only merge; reconciliation
  decisions and Linear updates remain separate.

## Released SDK verification

Installed `screamingface==0.1.7` into a fresh Python 3.13 virtual environment, without
an editable checkout. PyPI reported 0.1.7 as the latest release on 2026-10-27; its wheel
digest is `e311e4afcad34b7d8d499eab3b9b765ee412d5f552d2e5eeca5cdcb10137f86b`.
Inspected `sf.evaluate`, `Client.evaluate`, `sf.configure`, `sf.leaderboards.edit` and
`metadata_events` signatures. Four replay code snippets compile. API availability does
not mean the separate deployed edit-history route bug passed.

Extracted the actual guide snippets for live execution, substituted the existing dev
capture/score and dev service URLs, and instrumented calls with progress/spend observation
and `record_reproduction=False`. The guide's second full-replay call demonstrates the
opt-out; it was not repeated because the harness applied that option to every call.

- Capture: `430abe40-7555-49da-8de6-720a0591304f`.
- Score: `cde86fb8-675e-4457-bf5d-f8e0aec10ddb`.
- Benchmark: DRACO, revision `e8c3ad925dcd4d4a`.

| Example | Cases | Score/verdict | New provider spend | Run |
| --- | --- | --- | --- | --- |
| `sf.evaluate(pinned_cache=...)` | 100 | 0.3593, exact; no missed cases or recording error | $0 | `O7PEHl78Ee2mjJMNSQKlpotZW14vtmyzNQdfvANsQtMfEH3KV70CyfwUu4fd0TVy` |
| `sf.evaluate(pinned_cache=..., limit=1)` | 1 | `reproduction=None` | $0 | `SQYYjtyy6mlT3soFayj4XIf7cijbVS7QyqQENyUY9zfYF2E66O7Lzf5DV3vlmvuu` |
| `sf.evaluate(score_id=...)` | 100 | 0.3593, exact; no missed cases or recording error | $0 | `9711qPJSWm6dzPmU30f6PrstP45HGg8A5OA6SaZy0GifljyaLRCjFXBjQr18A3yr` |

Both exact results have `recorded=False` as requested by the harness. The score-ID
example used a public owned score; this does not claim live private-score authorization
coverage. The unsubmitted-capture example was syntax/API checked, not live executed.
No new capture or production run was started. Total new provider spend: **$0**.

## Publication and hand-off

Docs are prepared locally, not deployed. OME-1655 remains In Review. Once the correction
is published, confirm the public sidebar and guidance before completing its docs checkbox.
Production copied-button acceptance still waits for the Scoreboard rollout.

Ask the owner before posting or changing anything in Linear; shared results must be
inline or uploaded, never local paths. Remaining-child decisions are outside this PR.
