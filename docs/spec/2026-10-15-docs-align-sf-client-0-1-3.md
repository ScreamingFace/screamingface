# Align the SF Client docs with screamingface 0.1.8

Status: approved · Stack: repo · Epic: `OME-426`

## Problem

The SF Client docs (`public-docs`) disagree with screamingface 0.1.8, the released package, in three ways: false statements and stale samples, statements true on only one of the local and hosted engines, and 0.1.8 surface that no page documents. The docs describe the released package, 0.1.8. The team answered the open questions; the answers are the decisions below.

## Decisions

| # | Decision | Pages |
|---|---|---|
| D1 | Pages split into a hosted section and a local section wherever behaviour differs, as Installation and Caching already do. | Installation, First fusion, Quickstart (Reproduce DRACO), guides: Connections, Benchmarks, Models, Clients, Evaluation, Leaderboards; API: Clients, Connections, Models, Benchmarks |
| D2 | Hosted access and leaderboard `submit` need access granted by the OpenMined team. Without it, use the local engine. | Installation, First fusion, Connections guide, Leaderboards guide and API |
| D3 | Production hosts everywhere. No dev host remains. | `lib/engine.ts`, Installation, Overview, guides: Clients, Evaluation, Leaderboards, Connections; API: Clients, Modules |
| D4 | The Overview's DRACO numbers link to the live leaderboard (`https://leaderboard.screamingface.ai/benchmark.html?id=draco-3pass`). | Overview |
| D5 | Rubrics, judges and the whole run report are returned to the Client. | Overview, Engine, Architecture, Gateway |
| D6 | Supported model parameters depend on the provider. The `reasoning` example and `temperature` on `claude-opus-4.8` leave the docs. | Models guide, Quickstart (Reproduce DRACO) |
| D7 | Remove every slash benchmark id. | guides: Evaluation, Benchmarks; API: Reports, Clients, Leaderboards, Modules, Benchmarks |
| D8 | State the cache behaviour on 0.1.8: the local gateway caches by default, `evaluate(use_cache=False)` opts one run out, the community cache is pulled with `sf.cache.pull_from_remote`, entries do not expire. | Caching, Engine, Overview, Quickstart |
| D9 | Verification is a property of the engine that ran the submission. A submission stays unverified on the leaderboard until the hosted engine runs or replays it. | Leaderboards guide, Leaderboard concept |
| D10 | State that the Client does not keep `sf.configure(...)` across `sf.close()`. | Clients guide |
| D11 | Document that completed reports save to `~/.screamingface/results` and can be fetched after a failed run. | Evaluation guide, Clients guide and API, Reports API |
| D12 | `sf.reproduce` is not documented: 0.1.8 removed it. Replay is documented as `sf.evaluate(pinned_cache=...)` and `sf.evaluate(score_id=...)`, with `ReproductionError`. | Caching, Leaderboard concept, guides: Leaderboards, Url4; API: Clients, Leaderboards, Modules |
| D13 | The Gateway page stays: the AI gateway reaches model providers. | none |
| D14 | Replace `hle` and the `draco-lite` and `07_ifeval_e2e` links with correct leaderboard links. | guides: Evaluation, Benchmarks, Url4, Leaderboards |
| D15 | Document `sf.reports`. | Reports API, navigation |
| D16 | The footer reads "Based on state at <version>" and links that release's PyPI page. The version is the newest non-rc `screamingface-v*` tag, read at build time; the build fails when no tag is reachable. The workflows that build `public-docs` check out full history so the tag is found. | `navigation/sf-client.ts`, `vite.config.ts`, `deploy-public-docs.yml`, `public-docs-tests.yml` |
| D17 | The title "Reproduce DRACO state-of-the-art" stays. | Quickstart |
| D18 | The `EngineUnavailableError` hint is not documented. | none |
| D19 | Shared model calls: with the cache on, a model call runs once however many candidates use it. Calls are matched by a fingerprint of the route, prompt and parameters, not by model object, so two identical model objects share one call. The first candidate to run stores the response and the next one reuses it. | Caching, Engine, Overview, Quickstart |
| D20 | Quickstart (Reproduce DRACO): the lineup is cut to the four candidates the page defines (`opus`, `gpt`, `gemini`, `frontier_trio`); the static mock panels and the BEST marker are removed; the provider list is the seven providers a local engine advertises. A local reader runs the steps on `ifeval`. | Quickstart |
| D21 | A local engine serves only `medxpert`. Local samples use `benchmark="medxpert"` with a small `limit=` and print output from a real run. Hosted-only samples keep the hosted ids. | Every page with a local sample |
| D22 | `sf.cache` and `sf.analytics` get reference pages: `pull_from_remote`, `PullResult`, `CachePullError`, `screamingface cache pull`, `use_cache=False`; `status`, `enable`, `disable`, `reset_identifier`, `screamingface analytics`, `DO_NOT_TRACK`. | New API pages, Modules, navigation |
| D23 | A non-default engine requires an explicit `scoreboard_url` in `configure` and in the environment variables. | Installation, Clients, Modules, Connections |

## Corrections that need no decision

Each is verified false on 0.1.8.

- Installation: `len(sf.__all__)  # 56` is 82; the `up` sample prints `Scoreboard`, not `Leaderboard`; the `web_search` check returns False on every route; the provider-plugin FAQ is stale (`screamingface up` enables OpenRouter); `login()` in a notebook only prints a link.
- Connections guide and Quickstart: a local engine advertises 7 providers, not one; the demo panel lists Tavily, which is not a connection.
- Models guide: the profile sample (12 parameters, `web_search`) and the `list()` counts are stale.
- Quickstart: the 16-candidate lineup uses names the page never defines (`NameError`); the report view has no BEST marker, only score, coverage and cost; the `reasoning`-free compose block runs on 0.1.8 (`ifeval`, four candidates).
- Evaluation guide: `cost_usd` is a real value, not `Decimal('0')`.
- Events API: five event types, not four.
- Errors API: `ScreamingFaceError` does not catch argument-validation errors; the `antigravity` `get` sample does not raise.
- Benchmarks API: copied `FrozenInstanceError` text; undocumented `origin`, `interaction`, `difficulty`, `inverted_grade`, `provenance`, `saturation`, `attempts`.
- Clients API: the constructor omits `http_transport`, `scoreboard_transport`, `run_transport`, `save_results`; the async sample raises in a notebook.
- Modules API: the `b.variant` sample raises `AttributeError`.
- Url4 concept page: one grammar example does not parse (`ParseError` on the url4 1.5.1 bundled with 0.1.8).
- Leaderboards guide and Leaderboard concept: sample ids and board counts; the example submits a partial run, which is not ranked.
- Every revision, count and id on an edited page is reprinted from a live 0.1.8 call.

## Missing 0.1.8 surface to document

- Reducers and blocks: `Vote`, `Median`, `Reduce`, `Extract`, `Pick`, `Merge`, `FieldRule`, `Rank`, `Concat`, `Filter`, `Judge`, `matches`, `signal`, `samples`; `Fusion(quorum=, optional=)`.
- Result and accounting types: `Answer`, `OperationAccounting`, `OperationCache`, `CaseResult.answers()` and `trace()`, `Report.trace_dict()`, `CandidateResult` cache and capture fields.
- Notices: `DuplicateMembersWarning`, `FixedSeedSittingWarning`, `EngineCapabilityError`, `LeaderboardRankingNotice`.
- Home: Fusions guide and API for combinators, Reports and CandidateResult API for accounting and trace, Events and Errors API for notices.

## Out of scope

- Package bugs `OME-1620` to `OME-1628`.
- The url4 SDK page's CLI examples: they belong to the standalone `url4` package, which a screamingface install does not provide.
- Adding `sf.reports` to the public-surface snapshot (package change).

## Verification

- Gates: `npm run type-check`, `npm run lint`, `npm run build` in `public-docs`.
- Every sample on an edited page runs on a fresh 0.1.8 install, local engine and hosted where access allows; printed output is reprinted from the run.
- Link check over the built site.
- Each edited page is reread for accuracy against 0.1.8 and plain wording: no narrative, numbers instead of adjectives.

## Acceptance

- No page states a dev host as a default.
- No page lists a slash benchmark id, `sf.reproduce`, `hle` or the `draco-lite` link.
- Each page that differs between local and hosted has a section for each.
- Every sample on an edited page was run on 0.1.8 and matches the printed output.
- Every reference page documents the 0.1.8 surface listed above.
- The footer names 0.1.8.
- Type-check, lint and build pass.
