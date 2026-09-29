---
status: draft 2026-09-29
epic: OME-1308 (E18 · A local app)
---

# Studio ↔ library parity matrix (OME-1308)

**Goal (from the epic):** everything you can do in the library (`packages/screamingface`), you
can also do in Studio (`apps/screamingface-studio`). The library is the reference. Each Studio
unit under OME-1308 closes one or more rows in this matrix. It does not un-mock a page as it
stands.

**Studio today:** every page is mock data, except the desktop update window. The frontend makes
no network calls. The Tauri shell starts the real runtime sidecar (Gateway `:9105`, Scoreboard
`:9106`, Engine `:9108`), but the webview never talks to it.

Status key: **real** = backed by the Engine or Scoreboard · **mocked** = a Studio page fakes it
· **missing** = no Studio surface · **in progress** = a unit is open.

## 1. Matrix

| # | Area | Library capability (API) | Demonstrated in | Endpoint | Studio surface | Status |
|---|---|---|---|---|---|---|
| 1 | Endpoints | Point at an Engine and a Scoreboard, local or hosted (`sf.configure`, `sf.Client`, env vars) | `02_connection` | — | none | missing |
| 2 | Auth | Cloudflare Access login and logout for a hosted Engine (`login`, `logout`, `.authenticated`) | `01`, `02` | `/cdn-cgi/access/*` | sidebar "Connect OpenMined" (unrelated mock) | missing |
| 3 | Connections | List and get provider connections | `01` | `GET /v1/connections` | Models | in progress (`studio-models-unmock`) |
| 4 | Connections | BYOK API key (`sf.connect(p, api_key=)`) | `02`, `01` | `PUT /v1/connections/{p}` | Models | in progress |
| 5 | Connections | OAuth: authorize URL, wait, cancel (`sf.connect(p, method="oauth")`) | `01` | `POST …/oauth` + poll | Models | in progress |
| 6 | Connections | Disconnect (`sf.disconnect`) | `01` | `DELETE /v1/connections/{p}` | Models | in progress |
| 7 | Models | List models (`sf.models.list`) | `01` | `GET /v1/models` | Models, composer picker | in progress |
| 8 | Models | Model details: parameter schemas, tools, stale/degraded (`sf.models.get`) | `01` | `GET /v1/model-parameters?model=` | composer ParamEditor (static `PARAM_CATALOG`) | mocked |
| 9 | Benchmarks | List and get: origin, revision, case count (`sf.benchmarks`) | `01`, `12` | `GET /v1/benchmarks[/{id}]` | composer RunsPanel (5 fake benchmarks) | mocked |
| 10 | Recipes | `sf.Model(model, prompt, params)` | all | local | composer Solo | local, same shape |
| 11 | Recipes | `sf.Fusion(members, synthesizer)` | `01`, `06`, `08`, `10`–`13` | local | composer Fusion | local, same shape |
| 12 | Recipes | `sf.Pipeline` / `.then` | API only | local | composer Pipeline | local, same shape |
| 13 | Recipes | `sf.SelfCorrective`, `sf.CorrectiveLoop` | `07`, `09` | Engine corrective route | none | missing |
| 14 | URL4 | Canonical URL4, `.to_python()` fork, exact replay (`sf.evaluate("<url4>")`) | `00` | — | url4 preview and copy; import | mocked (non-canonical `url4://…?models=` format) |
| 15 | Evaluate | Run candidates on a benchmark, with `limit` or a full run (`sf.evaluate`) | all | `POST /token`, `GET /?q=` async, WS `/ws`, `GET /artifacts/{id}` | RunsPanel | mocked (`setInterval`, hashed scores) |
| 16 | Evaluate | Several candidates in one run | `06`–`13` | same | none | missing |
| 17 | Evaluate | Run-level `answer_seed` | `12` | header | per-model "seed" param only | missing |
| 18 | Progress | Live progress and typed events (`Started`, `Log`, `Span`, `Usage`, `Terminated`) | `00`, `01` | WS | RunsPanel progress bar | mocked |
| 19 | Progress | Cancel a run | automatic | `DELETE /` + capability | RunsPanel Cancel | mocked |
| 20 | Progress | Reconnect a dropped stream; wait on an Engine 503 | automatic | — | none | missing |
| 21 | Report | Score, metrics, usage/cost, failures, duration (`Report`, `CandidateResult`) | `00`, `01` | artifacts | RunDetail | mocked |
| 22 | Report | Per-case grade, checks, evidence and judge explanation, conversation, finish/refusal (`CaseResult`) | `10`–`12` | artifacts | RunDetail question traces | mocked |
| 23 | Report | Export `report.json` / Inspect log (`report.export`) | `00`, `01` | — | none | missing |
| 24 | Errors | Typed errors shown to the user (auth, unavailable, planning, provider, execution) | `01` | — | none | missing |
| 25 | Leaderboard | List boards (`sf.leaderboards.list`) | `00` | Scoreboard `GET /v1/benchmarks` | Leaderboard tabs | mocked |
| 26 | Leaderboard | Read a board: entries, baselines, notices (`get`) | `00` | `GET /v1/leaderboard/{id}` | Leaderboard, Home "Top fusions" | mocked |
| 27 | Leaderboard | Submit a score (`submit`) | `00`, `06`–`09` | `POST /v1/scores` | RunDetail "Publish Score" | mocked (localStorage flag) |
| 28 | Leaderboard | Fetch a published score and fork or replay its URL4 (`get_score`) | `00` | `GET /v1/scores/{id}` | Leaderboard fork / copy | mocked |
| 29 | Runtime | `screamingface up/down/status/logs/doctor` | "Before running" | CLI | Tauri starts and stops the sidecar; no UI | partial |
| 30 | Runtime | `screamingface prepare <bench>` (benchmark assets) | "Before running" | CLI | none | missing |

Studio-only, no library equivalent, keep: desktop auto-updates (`app/updates`, real).

## 2. Mock features with no library equivalent: owner decision needed

"Everything in the library is in Studio" does not say whether Studio may do *more*. Each item
below is either **dropped**, or **filed as library-first work** so that parity still holds.

| Mock feature | Where | Suggested |
|---|---|---|
| Python reduce/loop **scripts** | Scripts page, `script-store.ts` | Drop, or hide. The library reduces through a synthesizer model, and Studio never executes these scripts. |
| Fusion **strategies** (`majority_vote`, `weighted_avg`, `best_of_n`, `merge`) and per-slot `weight` | composer | Drop. Replace with the synthesizer, as in row 11. |
| **Cache** toggles (use/save cache) | RunsPanel | Drop until the Engine exposes caching. |
| **OpenMined compute budget** / subsidized key | sidebar, Models | Replace with rows 1–2, hosted credits after login (spec D5 follow-up). |
| **Custom dataset upload** as a benchmark | RunsPanel | Library-first, or drop. |
| Fake benchmarks (GPQA, HumanEval+, MATH-500) | RunsPanel, Leaderboard | Replace with row 9. |
| "Gain over best single model" column; private-data lock badges | Leaderboard | Keep only if Scoreboard serves the data. |
| Home counters (9,431 fusions, 184k evals) and "irina" greeting | Home | Replace with row 26, or drop. |

## 3. Proposed unit order under OME-1308

Each unit is one leaf, landing `app › desktop`, unless it needs Engine or library work. Work
touching those gets its own sub-issue.

1. **Models page.** Rows 3–7. In progress: spec and plan `2026-09-29-studio-models-unmock`.
2. **Engine switch and hosted login.** Rows 1–2 and 24 (first slice). Replaces the OpenMined
   mock. Cloudflare Access sign-in likely runs on the Rust side.
3. **Benchmark catalog and model parameters in the composer.** Rows 8–9. The RunsPanel and
   ParamEditor read the real catalog.
4. **Canonical URL4.** Row 14. *Design fork:* the library compiles URL4 client-side in
   Python. Studio needs either a TypeScript port of that compilation or an Engine
   compile/parse endpoint. Decide in that unit's spec, before rows 15–16 build on it.
5. **Run an evaluation.** Rows 15–20. Token, async start, WS stream, cancel, reconnect.
6. **Report view.** Rows 21–23. Per-case grades, judge evidence, usage/cost, export.
7. **Leaderboard.** Rows 25–28 and the Home page. Scoreboard read, submit, and fork a published
   URL4.
8. **Corrective loops in the composer.** Row 13.
9. **Runtime panel.** Rows 29–30. Status, logs (the epic's "daemon with a log the app can open"),
   doctor, and preparing benchmark assets.

Cross-cutting prerequisites, flagged but not yet filed:
- Studio CI plus an SDLC card stack.
- ~~The stale `runtime/uv.lock` bug~~: fixed with the Models page unit.
