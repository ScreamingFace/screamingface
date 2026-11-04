# Align the SF Client docs with screamingface 0.1.10

Status: approved · Stack: repo · Epic: `OME-426`

## Problem

The SF Client docs (`public-docs`) disagree with screamingface 0.1.10, the released package (PyPI, 2026-11-04; 0.1.9 was released the same day), in four ways: false statements and stale samples, statements true on only one of the local and hosted engines, surface that no page documents, and behaviour that changed in 0.1.10. `len(sf.__all__)` is 92. `evaluate` captures a pinned cache only when asked, and `evaluate(cases=...)` exists. The team answered the open questions; the answers are the decisions below.

The pass follows the OME-898 rules: the documentation-writing rules (page types, prose, diagrams, review), the product-context rules (terminology, personas, claims), the docs-in-every-PR rule (every public name has a page) and the release docs review (code against docs, docs against product context). Each rule is restated below, so this spec does not depend on any file outside the repository.

## Context for the pass

The writing rules require fixing the context before any page is written or reviewed. A slot that no source supplies is reported as unavailable. It is not invented.

| Slot | Value |
|---|---|
| Reader | Ensemble routing researchers (priority 0, canonical). Technical developers and benchmark enthusiasts (priority 1). |
| Register | Neutral and rigorous for researchers. Direct and technical for developers. |
| Reader's goal | Install the Client, run a fusion on a benchmark, read the score and the cost, and share or replay the run. |
| Terminology casing | ScreamingFace Client, Engine, Leaderboard, Studio and Toolkit are capitalised. `url4` is lower case everywhere, including at the start of a sentence. "fusion" is the lead noun. A fusion is a system, never a "fusion model". "ensemble" is correct in a docs register. |
| Time budget | Unavailable. No source supplies it. |
| Operational metrics | Unavailable. The pass uses only values measured on 0.1.10, with their conditions. |
| House voice | The repository rules: no narrative, a colon after every run-in label, complete sentences. The OME-898 convention: no em-dashes or en-dashes. |

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
| D8 | State the cache behaviour: the local gateway caches by default, `evaluate(use_cache=False)` opts one run out, the community cache is pulled with `sf.cache.pull_from_remote`, entries do not expire. | Caching, Engine, Overview, Quickstart |
| D9 | Verification is a property of the engine that ran the submission. A submission stays unverified on the leaderboard until the hosted engine runs or replays it. | Leaderboards guide, Leaderboard concept |
| D10 | State that the Client does not keep `sf.configure(...)` across `sf.close()`. | Clients guide |
| D11 | Document that completed reports save to `~/.screamingface/results` and can be fetched after a failed run. | Evaluation guide, Clients guide and API, Reports API |
| D12 | `sf.reproduce` is not documented. Replay is documented as `sf.evaluate(pinned_cache=...)` and `sf.evaluate(score_id=...)`, with `ReproductionError`. | Caching, Leaderboard concept, guides: Leaderboards, Url4; API: Clients, Leaderboards, Modules |
| D13 | The Gateway page stays: the AI gateway reaches model providers. | none |
| D14 | Replace `hle` and the `draco-lite` and `07_ifeval_e2e` links with correct leaderboard links. | guides: Evaluation, Benchmarks, Url4, Leaderboards |
| D15 | Document `sf.reports`. | Reports API, navigation |
| D16 | The footer reads "Based on state at <version>" and links that release's PyPI page. The version is the newest non-rc `screamingface-v*` tag, read at build time; the build fails when no tag is reachable. The workflows that build `public-docs` check out full history so the tag is found. | `navigation/sf-client.ts`, `vite.config.ts`, `deploy-public-docs.yml`, `public-docs-tests.yml` |
| D17 | The title "Reproduce DRACO state-of-the-art" stays. | Quickstart |
| D18 | The `EngineUnavailableError` hint is not documented. | none |
| D19 | Shared model calls: with the cache on, a model call runs once however many candidates use it. Calls are matched by a fingerprint of the route, prompt and parameters, not by model object, so two identical model objects share one call. The first candidate to run stores the response and the next one reuses it. | Caching, Engine, Overview, Quickstart |
| D20 | Quickstart (Reproduce DRACO): the lineup is cut to the four candidates the page defines (`opus`, `gpt`, `gemini`, `frontier_trio`); the static mock panels and the BEST marker are removed; the provider list is the seven providers a local engine advertises. A local reader runs the steps on `medxpert`. | Quickstart |
| D21 | A local engine started with `screamingface up` serves `medxpert` only (measured on 0.1.10). A repository checkout serves the other benchmarks locally with `just local-stack-notebooks`. Local samples use `benchmark="medxpert"` with a small `limit=` and print output from a real run. Hosted-only samples keep the hosted ids. | Every page with a local sample; Benchmarks guide and API, First fusion, Installation, Quickstart, Engine |
| D22 | `sf.cache` and `sf.analytics` get reference pages: `pull_from_remote`, `PullResult`, `CachePullError`, `screamingface cache pull`, `use_cache=False`; `status`, `enable`, `disable`, `reset_identifier`, `screamingface analytics`, `DO_NOT_TRACK`. | New API pages, Modules, navigation |
| D23 | A non-default engine requires an explicit `scoreboard_url` in `configure` and in the environment variables. | Installation, Clients, Modules, Connections |
| D24 | The baseline is the released 0.1.10. A release candidate is not a source. | all |
| D25 | Only behaviour in the 0.1.10 wheel is documented. E4b part 1 is documented. E4b parts 2 to 7 (`Fanout`, `Gate`, `JudgePick`, `Consistency`, `ArgMax`, `ArgMin`, `First`, `Sum`) are not in `main` or in 0.1.10 and are not documented. | Reducers, Fusions, Pipelines |
| D26 | `evaluate` does not capture a pinned cache unless `capture=True` is passed. Every statement that capture is on by default is rewritten. A replay never captures. | Caching, Evaluation guide, Leaderboards guide, Clients API, CandidateResult API |
| D27 | The Reducers reference gains the E4b part 1 surface: `sf.Mean`, weights on `sf.Median` and `sf.Vote`, `Judge(order="min")`, `Filter(judge=...)`, `Pick(output=...)`, `Reduce("median"/"mean", select=...)`, and the selection input `{"input": ..., "selected": [...]}` for the stage after `Rank` or `Filter`. | Reducers, Fusions guide |
| D28 | `sf.classify(model, input)` and `Client.classify(model, input)` get a reference section: arguments, return types (`Classification`, `LabelScore`), the model-id form, and the errors. | API reference, Modules |
| D29 | Case media gets a reference section: `CaseResult.media`, `CaseMedia`, `sf.fetch_media`, `Client.fetch_media`, `FetchedMedia`, and `MediaUnavailableError` with code `media_not_kept`. | CandidateResult API, Errors API, Modules |
| D30 | The `provider_not_connected` hint and the `model_not_found` error text match 0.1.10. | Errors API, Connections guide |
| D31 | `len(sf.__all__)` is 92. | Installation |
| D32 | Analytics are on by default in 0.1.10. The first evaluation prints a notice, and `sf.analytics.disable()` or `DO_NOT_TRACK=1` turns them off. The Analytics page and every page that mentions analytics state what a clean install does, measured on a fresh config home. | Analytics, Installation, learn pages |
| D33 | The judged imported-benchmark judge input described in the engine changelog is checked against the Benchmarks guide, and the guide states the 0.1.10 behaviour. | Benchmarks guide |
| D40 | `evaluate(cases=[...])` runs a fixed list of Case ids. `Report.selected_cases`, `Report.selection_fingerprint` and `CandidateResult.selected_cases` name what was scored. Refusals, the limit that a selected run cannot be submitted to a leaderboard, and the Engine requirement are stated from measured runs. | Evaluation guide, Clients API, Reports API, CandidateResult API, Leaderboards guide |
| D34 | Prose uses "fusion" for the composed system. API names are unchanged. | all |
| D35 | Each page has one type: tutorial, how-to, reference or explanation. New reference material goes on reference pages (`api/`). A guide links forward to the reference page once. A page that serves two types is split, not balanced. | all edited pages |
| D36 | Diagrams are authored as text source in `docs/diagrams/`, rendered to SVG and PNG, and reviewed in the same change. Labels use the exact names and casing of the prose and the API. A stale diagram is deleted or corrected in this pass. | see Diagram plan |
| D37 | A sentence about a score names `reproducible` only for the `url4` line, and `auditable` for a held-out score. A sentence about a benchmark result states who authored or hosts the benchmark. No sentence states a performance, accuracy or cost figure without its method and conditions. | all |
| D38 | A sentence that says free, `$0` or no provider call is measured on a run, or it is removed. A sample that runs a full benchmark carries a note that it is paid. Calls already in the shared cache re-run for free; all other calls run on the caller's own keys. | all |
| D39 | The pass ends with a review report in the output order of the review rules (verdict, friction log, flow map, scorecard, diagram plan, top fixes, what already works). It is recorded in the work ledger. | work ledger |

## Prose rules

These hold for every sentence added or changed in this pass.

- No em-dashes and no en-dashes. A range reads "1 to 5". A comma, a colon, parentheses or a full stop replaces a dash.
- Headings use sentence case.
- No announcement of a section ("In this section we will"), no closing summary, no generic outlook, no "as mentioned above" or "as we will see".
- No adjectives for performance ("fast", "lightweight", "scalable"). Each is a number with its method and conditions, or it is deleted.
- No sales register ("seamlessly", "powerful"), no stacked hedging, no forced triad. A list has as many items as are true.
- Bold at most once per paragraph, where it carries weight. No decorative emoji.
- Parallel tabs for local and hosted keep one list of differences, and repeat a divergence at the point of use when it changes a call signature, a unit or whether something exists.
- Prefer deletion. An added sentence justifies itself.

## Diagram plan

A concept that describes structure, flow, sequence, state or a decision has a diagram, or it is simple enough not to need one. Each diagram answers one question.

| Concept | Type | The question it answers | Page |
|---|---|---|---|
| The stage after `Rank` or `Filter` receives the Case input with the selection | flow | What does the next stage receive, and from where? | Reducers |
| A reducer with `quorum` and optional members | topology | Which members reach the combine call, and where does a failure stop? | Fusions |
| Opening and fetching a Case's media | sequence | What is fetched, from where, and when does `media_not_kept` occur? | CandidateResult API |
| A pinned cache from open to sealed or partial | state | Which states exist, and what makes a capture partial? | Caching |
| `sf.classify` call path | flow | Which endpoint does the call reach, and with which model id? | classify reference |
| The local request flow on the Overview | component | Which parts exist, and what talks to what? Reviewed for current names. | Overview |

## Review rules

The pass runs the review procedure end to end on the edited pages, as the reader fixed in the context table.

- **Pass 1, the naive read.** Read in the order the docs present, without prior knowledge. Log every friction with its location and the exact sentence.
- **Pass 2, the structural read.** Map what each section assumes and where it was introduced. Record forward references, orphans, redundant re-explanations and terminology drift.
- **Pass 3, the visual pass.** For each concept: a diagram that works, one that fails, or one that is needed and missing. Each gap names the boxes, the arrows, the labels and the question, with the source.
- **Scorecard.** Nine items scored 1 to 5, each with a quoted line: first contact, time to first success, concept ordering, learning-curve shape, example quality, reference navigability, terminology discipline, honest operations, visual clarity. Not graded on a curve.
- **Trust check.** Plain limits, numbers over adjectives, operational reality at the point of decision, no marketing residue, versioning and migration statements. Each failing sentence is quoted and rewritten.
- **Examples.** Every example runs. An example that cannot run is marked unverified and checked another way: imports match usage, names match the reference, and the page shows the expected output. An example with no expected output is a finding.

## Release review

- **Code against docs.** Every user-facing entry in the current changelogs of `apps/aigateway`, `apps/aigateway-ui`, `apps/report-intake`, `apps/scoreboard`, `apps/screamingface-engine`, `packages/screamingface` and `packages/url4`, including each "Unreleased" section, is listed with its page. A new `sf.*` export has a page. Changed behaviour has an updated guide. Removed behaviour has no page that describes it.
- **Docs against product context.** Terminology casing matches. No public sentence violates the claims rules in D37. The persona set matches the reader in the context table. Anything the docs state as settled that product context marks provisional or open is flagged for its owner, not resolved here.
- **Every public name has a page.** Each name in the 0.1.10 `__all__` maps to a page under `public-docs/src/pages/sf-client/api/`. A name added to or removed from `__all__` has its page added, changed or removed. A name with no page is listed as a named exception.
- **Reviewer:** Irina Bejan.

## Corrections that need no decision

- Installation: `len(sf.__all__)` is 92; the `up` sample prints `Scoreboard`, not `Leaderboard`; the `web_search` check returns False on every route; the provider-plugin FAQ is stale (`screamingface up` enables OpenRouter); `login()` in a notebook only prints a link.
- Connections guide and Quickstart: a local engine advertises 7 providers, not one; the demo panel lists Tavily, which is not a connection.
- Models guide: the profile sample (12 parameters, `web_search`) and the `list()` counts are stale.
- Quickstart: the 16-candidate lineup uses names the page never defines (`NameError`); the report view has no BEST marker, only score, coverage and cost.
- Evaluation guide: `cost_usd` is a real value, not `Decimal('0')`.
- Events API: five event types, not four.
- Errors API: `ScreamingFaceError` does not catch argument-validation errors; the `antigravity` `get` sample does not raise.
- Benchmarks API: copied `FrozenInstanceError` text; undocumented `origin`, `interaction`, `difficulty`, `inverted_grade`, `provenance`, `saturation`, `attempts`.
- Clients API: the constructor omits `http_transport`, `scoreboard_transport`, `run_transport`, `save_results`; the async sample raises in a notebook.
- Modules API: the `b.variant` sample raises `AttributeError`.
- Url4 concept page: one grammar example does not parse (`ParseError` on the bundled url4 1.5.1).
- Leaderboards guide and Leaderboard concept: sample ids and board counts; the example submits a partial run, which is not ranked.
- Home glossary: the em-dash in the `fusion` definition becomes a comma.
- Footer: reads the newest release tag (0.1.10), with no edit.
- Every revision, count and id on an edited page is reprinted from a live 0.1.10 call.

## Missing surface to document

- Reducers and blocks: `Vote`, `Median`, `Reduce`, `Extract`, `Pick`, `Merge`, `FieldRule`, `Rank`, `Concat`, `Filter`, `Judge`, `matches`, `signal`, `samples`, `Mean`; `Fusion(quorum=, optional=)`.
- Result and accounting types: `Answer`, `OperationAccounting`, `OperationCache`, `CaseResult.answers()`, `trace()` and `media`, `Report.trace_dict()`, `CandidateResult` cache and capture fields.
- Notices and errors: `DuplicateMembersWarning`, `FixedSeedSittingWarning`, `EngineCapabilityError`, `LeaderboardRankingNotice`, `MediaUnavailableError`.
- Classification and media: `sf.classify`, `Client.classify`, `Classification`, `LabelScore`, `sf.fetch_media`, `Client.fetch_media`, `CaseMedia`, `FetchedMedia`.
- Home: Fusions guide and API for combinators, Reports and CandidateResult API for accounting and trace, Events and Errors API for notices.

## Out of scope

- Package bugs `OME-1620` to `OME-1628`.
- E4b parts 2 to 7 and the map, select and reduce recipe surface: not in `main` or in 0.1.10.
- The url4 SDK page's CLI examples: they belong to the standalone `url4` package, which a screamingface install does not provide.
- Adding `sf.reports` to the public-surface snapshot (package change).

## Verification

- Gates: `npm run type-check`, `npm run lint`, `npm run build` in `public-docs`.
- Fresh 0.1.10 install: `uv venv`, then `uv pip install "screamingface[notebook,runtime]==0.1.10"`. Start the local stack with `screamingface up`.
- Every sample on an edited page runs on 0.1.10 against the local engine, and its printed output is reprinted from the run. A hosted sample prints no output that was not observed.
- Link check over the built site: every internal route resolves and every external link answers 200.
- A search of `public-docs/src` finds none of: an em-dash, an en-dash used as a connector, `cases=`, `Fanout`, `JudgePick`.

## Acceptance

- No page states a dev host as a default.
- No page lists a slash benchmark id, `sf.reproduce`, `hle` or the `draco-lite` link.
- No page states that capture is on by default.
- Each page that differs between local and hosted has a section for each.
- Every sample on an edited page was run on 0.1.10 and matches its printed output, or is marked unverified with the reason.
- Every name in the 0.1.10 `__all__` has a page, or is a listed named exception.
- No page documents a name that is not in the 0.1.10 `__all__`.
- Every diagram in the Diagram plan exists as source, SVG and PNG, with labels that match the prose.
- The review report exists, in the required order, with a quoted line for each of the nine scores and a before and after for each top fix.
- No edited page contains an em-dash, and no heading is in title case.
- The footer names the newest release tag.
- Type-check, lint and build pass.
- One pull request on `main` under `OME-426`. The body follows `.github/pull_request_template.md`, with `**Refs:** OME-426`. Every commit is approved before it is made.
