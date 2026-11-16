<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

// ---------------------------------------------------------------------------
// MOCK roadmap. Items are a hand-curated snapshot of real Engineering work,
// rewritten into user-facing titles. Each topline + detail is grounded in the
// actual Linear ticket (or, for the strategic epics, the requirements capture),
// not invented. Internal flags (e.g. "at risk") are NOT surfaced.
// status comes from the real Linear state: 'in-progress' (literally In Progress)
// drives the badge; 'done' is Shipped; 'planned' is queued / not started.
// Buckets sit on a timeline with per-bucket month bands; specific per-card
// months appear only where we actually know them (Now + Shipped). Votes/
// comments live in localStorage (no backend); this is a prototype to react to.
// ---------------------------------------------------------------------------

type Bucket = 'now' | 'next' | 'exploring' | 'shipped'
type Status = 'in-progress' | 'planned' | 'done'

interface Item {
  id: string // unique key (used for vote/comment/expand storage + v-for)
  epic: string // short epic-family label shown as a tag
  theme: string // epic marker, e.g. "E13", or "idea"
  ome?: string // optional OME-N reference shown on the card
  title: string // user-facing
  blurb: string // topline — one plain sentence, shown collapsed
  detail?: string // faithful scope, revealed by "Read more"
  bucket: Bucket
  status: Status
  eta?: string // Now only, a range
  votes: number // placeholder demand count; the voting UI is deferred to a separate ticket
  shipped?: string // Shipped only
}

const ITEMS: Item[] = [
  // ----------------------------- NOW -----------------------------
  {
    id: 'C14',
    epic: 'Bring your own model',
    theme: 'E13',
    ome: 'OME-1306',
    title: 'Bring your own model',
    blurb:
      'Use a model you run yourself in a fusion, and optionally publish it to the shared gateway so others can call it.',
    detail:
      'Point a fusion at a model you host, with your own keys or your own endpoint, and have it scored like any other model in the fusion. There is also a path to publish a model to the shared gateway, which is how a trained router or a small custom model becomes reusable across fusions instead of staying on your machine.\n\nLocal Ollama already works, and a Qwen plus classifier setup is under test. We do not host open-weight models for you; the gateway path is for making the models you bring reachable to others.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov 2026',
    votes: 42,
  },
  {
    id: 'CLS',
    epic: 'Classifiers & decision models',
    theme: 'models',
    title: 'Decision models',
    blurb:
      'Use small models like encoders and classifiers to make decisions in a fusion, not just chat models.',
    detail:
      'Bring in small specialized models, like encoders and classifiers, to help a fusion decide which model to run, whether to stop, or how much to trust an answer. They do not write text themselves; they steer the models that do.\n\nThey plug straight into routers and ensembles.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov 2026',
    votes: 15,
  },
  {
    id: 'C1',
    epic: 'url4 images',
    theme: 'url4',
    ome: 'OME-1529',
    title: 'Image support in url4',
    blurb: 'Compose fusions over images and PDFs end to end, including in benchmarks.',
    detail:
      'Images pass through a fusion the same way text does, so vision models receive them and image cost is tracked, including inside benchmarks.\n\nThe goal is that an image task runs exactly like a text task.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov 2026',
    votes: 31,
  },
  {
    id: 'C25',
    epic: 'Open submissions',
    theme: 'E1',
    title: 'Open submit to leaderboard',
    blurb: 'Anyone can submit to the leaderboard, not just an allow-listed few.',
    detail:
      'Submitting moves from a hand-picked allow-list to anyone with an account. Per-user limits and spend caps protect the free compute behind it.\n\nThis is what lets researchers sign themselves up instead of waiting for an invite.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov 2026',
    votes: 26,
  },
  {
    id: 'C27',
    epic: 'Run management',
    theme: 'E5',
    ome: 'OME-1294',
    title: 'Manage evaluation runs',
    blurb:
      'List, resume, and cancel evaluations from the Client, and detach a long run to come back to it later.',
    detail:
      'Each run gets its own id, a status you can follow, and a searchable history. Launch a run, close your laptop, and reconnect to it later, set a budget, and compare one run against another.\n\nIt builds on saved reports.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov–Dec 2026',
    votes: 33,
  },
  {
    id: 'BUDGET',
    epic: 'Budget management',
    theme: 'E5',
    title: 'Budget management',
    blurb: 'Run up to a cost cap, estimate a run before it starts, and see the balance left.',
    detail:
      'Set a hard cost cap on a run so it stops instead of overspending, get a dry-run estimate of what a run will cost before you launch it, and check how much subsidized budget you have left.\n\nIt builds on the per-call cost signal.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov–Dec 2026',
    votes: 19,
  },
  {
    id: 'C7',
    epic: 'Fusion methods',
    theme: 'E4c',
    ome: 'OME-1291',
    title: 'Routers, cascades, gates',
    blurb: 'Decide per case what runs: route, cascade, gate, and cap, so only the needed models are called.',
    detail:
      'A fusion can decide what to run before spending anything, so the paths it skips cost nothing. Route by keyword, by an LLM classifier, or by a small decision model; send a case to one model or to several; and build cascades that only escalate to a bigger model when the cheap one fails or looks unsure.\n\nIt also adds gates that trigger on agreement, a judge that runs only when it is actually needed, and a hard budget cap per fusion. The report shows what was skipped and why.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov 2026',
    votes: 18,
  },
  {
    id: 'C22',
    epic: 'External results',
    theme: 'E20',
    ome: 'OME-1309',
    title: 'External results',
    blurb: 'See how a method did on established leaderboards, as grounding, not as a reproducible entry.',
    detail:
      'Results from other leaderboards and arenas are shown for context: they tell you how a method did on established boards and how that compares, which is informative. They are marked as outside results, grayed out, with a source link, and do not become first-class, reproducible entries on our leaderboard.\n\nEach records where it came from, the date it was read, and who added it. Hand-entered results stay editable without losing their history.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov 2026',
    votes: 14,
  },
  {
    id: 'C15',
    epic: 'Cost & cache',
    theme: 'E2',
    ome: 'OME-1287',
    title: 'Cost across providers',
    blurb: 'Accurate cost on every model call, across every provider, with caching you can trust.',
    detail:
      'The gateway caches calls for Anthropic, OpenAI, Gemini, Hugging Face, and OpenRouter the same way, and prices each call from what the provider reports or a central price table. Calls that cannot be priced are marked as such, not silently counted as zero.\n\nThat cost feeds budget caps, routing decisions, and the cost ranking on the leaderboard.',
    bucket: 'next',
    status: 'planned',
    votes: 20,
  },
  {
    id: 'C2',
    epic: 'Scale & limits',
    theme: 'E6',
    title: 'Scale the platform',
    blurb: 'Many more people can submit evaluations and have them run in parallel, under fair limits.',
    detail:
      'Load testing and fair-share scheduling raise how many users can run evaluations at the same time, with balancing so one heavy run does not starve the rest. Usage stays under fair per-user limits.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov–Dec 2026',
    votes: 7,
  },
  {
    id: 'C18',
    epic: 'Benchmarks',
    theme: 'E10e',
    title: 'Sandboxed evaluations',
    blurb: 'Run benchmarks that need a code sandbox within a single turn.',
    detail:
      'Some evals execute code to check an answer, so the harness runs that step in a sandbox inside the turn. It extends benchmark support to tasks that cannot be scored by text match alone.\n\nScope is single-turn sandboxed execution, not long-running agent sessions.',
    bucket: 'next',
    status: 'planned',
    votes: 16,
  },
  {
    id: 'C31',
    epic: 'Agent DX',
    theme: 'DX',
    ome: 'OME-473',
    title: 'Claude Code & Codex',
    blurb: 'Using ScreamingFace from Claude Code or Codex should just work.',
    detail:
      'The aim is that an agent can propose an experiment and run it with the Client doing most of the work. It covers a help section under the API, a tutorial, and a possible skill, tested in real sessions.\n\nIt is done when the team finds the agent experience good enough in daily use.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov 2026',
    votes: 24,
  },
  {
    id: 'C30',
    epic: 'Docs',
    theme: 'docs',
    ome: 'OME-1313',
    title: 'Auto-generated docs',
    blurb: 'Keep the docs generated from the source of truth so they do not drift.',
    detail:
      'Docs are regenerated from the product itself whenever it changes, in the OpenMined voice, then reviewed before they go live. A cleanup pass fixes places where today\'s docs have fallen behind.\n\nThe result is docs that keep up with the product instead of being hand-maintained.',
    bucket: 'now',
    status: 'in-progress',
    eta: 'Nov 2026',
    votes: 9,
  },

  // ----------------------------- NEXT -----------------------------
  {
    id: 'C28',
    epic: 'Streaming progress',
    theme: 'E3',
    title: 'Live eval progress',
    blurb: 'Watch an evaluation as it runs, step by step, instead of waiting for one final result.',
    detail:
      'See what is queued, running, and finished as it happens, with counts and cost for each step. You can open a single model\'s answer, or a result reused from cache, before the whole run finishes.\n\nNo more waiting for one final result at the end.',
    bucket: 'next',
    status: 'planned',
    votes: 29,
  },
  {
    id: 'C16',
    epic: 'Model discovery',
    theme: 'platform',
    ome: 'OME-1315',
    title: 'Live model discovery',
    blurb: 'New models show up automatically as providers release them.',
    detail:
      'New models from providers like OpenRouter, Anthropic, and Hugging Face show up on their own, without us shipping an update, and retired ones drop off the list.\n\nYour keys are never exposed while this happens.',
    bucket: 'next',
    status: 'planned',
    votes: 12,
  },
  {
    id: 'C19',
    epic: 'Desktop app',
    theme: 'E18',
    ome: 'OME-1308',
    title: 'A local desktop app',
    blurb: 'Run and watch fusions from a local app, not only the command line.',
    detail:
      'Install the app, sign in, pick a recipe, and run a small experiment, all without the command line. It uses the same engine underneath, so results and cost tracking match the Client exactly.',
    bucket: 'next',
    status: 'planned',
    votes: 33,
  },
  {
    id: 'C29',
    epic: 'Local inference',
    theme: 'E9',
    title: 'Fusions in any harness',
    blurb: 'Run any url4 fusion in any harness, and swap in the best one for your case.',
    detail:
      'Drop a url4 into your editor, notebook, or app and run it like a normal model, through an OpenAI-compatible endpoint. Because every fusion is just a url4, you can switch one out for another with ease and pick the best performer for your case along the cost-and-score frontier.\n\nIt runs locally; the focus is running it yourself, not a hosted service.',
    bucket: 'next',
    status: 'planned',
    votes: 21,
  },
  {
    id: 'DECOMP',
    epic: 'Task decomposition',
    theme: 'methods',
    title: 'Task decomposition',
    blurb: 'Break a task into sub-tasks, solve each, and recombine.',
    detail:
      'A fusion can split a problem into parts, run each, and merge the results, instead of answering in one shot. This opens divide-and-conquer methods on top of the existing fan-out and reduce.\n\nPlanned for early 2027.',
    bucket: 'next',
    status: 'planned',
    votes: 20,
  },
  {
    id: 'LAT',
    epic: 'Latency tracking',
    theme: 'platform',
    title: 'Latency tracking',
    blurb: 'Track latency on every call, on par with how cost is tracked.',
    detail:
      'Every model call records its latency alongside its cost, rolled up per node and per run, so you can see and compare how fast a fusion is, not just how much it costs. Latency becomes a first-class signal you can route, gate, and rank on.\n\nIt mirrors the cost work.',
    bucket: 'next',
    status: 'planned',
    votes: 18,
  },
  {
    id: 'PROMPT',
    epic: 'Prompt optimization',
    theme: 'methods',
    ome: 'OME-1364',
    title: 'Prompt optimization',
    blurb: 'Automatically tune the prompts in a fusion, instead of hand-editing them.',
    detail:
      'Let the toolkit search for better prompts against your benchmark, the way DSPy does, rather than tuning them by hand. Each model\'s prompt can be pushed toward higher scores at lower cost.\n\nA frequent request from researchers.',
    bucket: 'next',
    status: 'planned',
    votes: 17,
  },
  {
    id: 'SWEEP',
    epic: 'Config sweeps',
    theme: 'platform',
    ome: 'OME-1466',
    title: 'Config sweeps',
    blurb: 'Run a grid of model and parameter combinations and compare them in one place.',
    detail:
      'Define a sweep over models, parameters, or fusion settings, run the combinations, and compare them on score and cost side by side, with early stopping so weak runs do not finish.\n\nReplaces hand-edited config files and one-off scripts.',
    bucket: 'next',
    status: 'planned',
    votes: 14,
  },
  {
    id: 'CODEBENCH',
    epic: 'Benchmarks',
    theme: 'benchmarks',
    ome: 'OME-1349',
    title: 'Coding benchmarks',
    blurb: 'Run fusions against coding benchmarks like SWE-bench and LiveCodeBench.',
    detail:
      'Add coding and software-engineering benchmarks such as SWE-bench, LiveCodeBench, and BigCodeBench, scored with the sandbox so the code is actually run and checked.\n\nThe most-requested benchmark area.',
    bucket: 'next',
    status: 'planned',
    votes: 24,
  },

  // ----------------------------- EXPLORING 2027 -----------------------------
  {
    id: 'C4',
    epic: 'Fusion as endpoint',
    theme: 'E8',
    title: 'Fusion as an endpoint',
    blurb: 'Turn a fusion into a named, callable endpoint.',
    detail:
      'A fusion gets a name, a version, and a URL, and can be called like any chat model. The same fusion is the research submission, the leaderboard entry, and the thing you call in production.\n\nMuch of the serving and citation work builds on this.',
    bucket: 'exploring',
    status: 'planned',
    votes: 13,
  },
  {
    id: 'C23',
    epic: 'Leaderboard UX',
    theme: 'E21',
    title: 'Shareable reports',
    blurb: 'Turn any leaderboard row into a self-contained report you can share.',
    detail:
      'A row expands into a standalone page with the method, the models, the scores, and the cost, ready to link. It gives a submission a citable surface.\n\nThis sits on top of the reproducible-artifact work.',
    bucket: 'exploring',
    status: 'planned',
    votes: 19,
  },
  {
    id: 'AGENT',
    epic: 'Agentic fusions',
    theme: 'methods',
    title: 'Agentic loops & debate',
    blurb: 'Run multi-agent loops, debate, and shared memory across turns.',
    detail:
      'Let the models argue, revise, and share what they know across rounds, not just answer once and combine. This covers multi-agent debate, back-and-forth reasoning loops, and memory carried between turns.\n\nOne of the most requested capabilities from researchers.',
    bucket: 'exploring',
    status: 'planned',
    votes: 31,
  },
  {
    id: 'TOOLS',
    epic: 'Tools in fusions',
    theme: 'methods',
    title: 'Tools in fusions',
    blurb: 'Plug external tools into a fusion, like a code runner or a proof checker.',
    detail:
      'Members can call tools as first-class steps: code execution, retrieval, a SQL engine, or an external verifier like a Lean proof checker. Researchers extend the platform without changing the core.\n\nA common request from formal-methods and scientific-discovery work.',
    bucket: 'exploring',
    status: 'planned',
    votes: 22,
  },
  {
    id: 'RETR',
    epic: 'Retrieval stores',
    theme: 'methods',
    title: 'Per-agent retrieval store',
    blurb: 'Give each agent its own retrieval store, beyond the shared search and fetch tools.',
    detail:
      'Each member or agent in a fusion can have its own retrieval store, a private index it builds and queries, so different agents draw on different knowledge. This goes past the shared search and fetch tools everyone already has.\n\nDirectional for 2027.',
    bucket: 'exploring',
    status: 'planned',
    votes: 17,
  },
  {
    id: 'TRAIN',
    epic: 'Train on-platform',
    theme: 'methods',
    title: 'Train routers',
    blurb: 'Train and adapt routers on the platform, including reinforcement learning.',
    detail:
      'Let a router or small decision model be trained or adapted on-platform, rather than only brought in pre-trained. This includes reinforcement-learning and search-based routing approaches.\n\nA frequent request from routing researchers.',
    bucket: 'exploring',
    status: 'planned',
    votes: 14,
  },
  {
    id: 'MT',
    epic: 'Benchmarks',
    theme: 'benchmarks',
    title: 'Multi-turn benchmarks',
    blurb: 'Run fusions against multi-turn benchmarks that carry state across turns.',
    detail:
      'Support evals where a candidate holds a conversation across turns, carrying state, and where the next message can depend on what the model just said. This includes replaying logged dialogues turn by turn.\n\nA common request for conversational and agentic tasks.',
    bucket: 'exploring',
    status: 'planned',
    votes: 16,
  },
  {
    id: 'TOK',
    epic: 'Token-level ensembling',
    theme: 'methods',
    title: 'Token-level ensembling',
    blurb: 'Combine models at the token level, not just on final answers.',
    detail:
      'Fuse member models on their token logits rather than only merging completed answers. This needs open weights and white-box access, so it is a research-grade capability.\n\nDirectional for 2027.',
    bucket: 'exploring',
    status: 'planned',
    votes: 13,
  },
  {
    id: 'FOREST',
    epic: 'Benchmarks',
    theme: 'benchmarks',
    title: 'ForestBench support',
    blurb: 'Run fusions against ForestBench.',
    detail:
      'Add ForestBench to the supported benchmark set, with the same faithfulness checks as the rest of the pack.\n\nDirectional for 2027.',
    bucket: 'exploring',
    status: 'planned',
    votes: 8,
  },
  {
    id: 'DOMBENCH',
    epic: 'Benchmarks',
    theme: 'benchmarks',
    title: 'More domain benchmarks',
    blurb: 'Add medical, legal, finance, and security benchmarks.',
    detail:
      'Broaden the benchmark pack beyond the current core into domain-specific sets people keep asking for: medical, legal, finance, cybersecurity, and formal methods. Coding has its own card.\n\nA frequent request for benchmarks we do not yet support.',
    bucket: 'exploring',
    status: 'planned',
    votes: 18,
  },
  {
    id: 'JOIN',
    epic: 'Fusion methods',
    theme: 'methods',
    ome: 'OME-1293',
    title: 'Custom join functions',
    blurb: 'Upload your own rule for combining answers when the built-in library does not have it.',
    detail:
      'Supply a small Python function, run safely in a sandbox, to combine model answers with a rule the standard toolkit does not have, for methods too specialized to pre-build.\n\nAn escape hatch so your method is never blocked waiting for the library to grow.',
    bucket: 'exploring',
    status: 'planned',
    votes: 12,
  },
  {
    id: 'PROV',
    epic: 'Provenance & citation',
    theme: 'leaderboard',
    ome: 'OME-1316',
    title: 'Recipe provenance',
    blurb: 'Carry author, lineage, and citation with every recipe.',
    detail:
      'A recipe records its author, a link to its paper, and its fork lineage, so readers can trace where a method came from and credit travels with the submission.\n\nUnderpins citation, the thing researchers care about most.',
    bucket: 'exploring',
    status: 'planned',
    votes: 15,
  },
  {
    id: 'VERIF',
    epic: 'Trust',
    theme: 'leaderboard',
    ome: 'OME-1319',
    title: 'Verified submissions',
    blurb: 'Show clearly which results were independently re-run and verified.',
    detail:
      'Mark whether a result was self-reported or actually re-run by OpenMined, backed by a service that re-runs and checks it. It also guards against a provider quietly serving a different model than the one asked for, and closes gaps where data could leak or entries could be duplicated.\n\nThis is what keeps the leaderboard trustworthy as it opens up.',
    bucket: 'next',
    status: 'planned',
    votes: 11,
  },

  // ------------------------ EXPLORING 2027 (continued) ------------------------
  {
    id: 'C8',
    epic: 'Private data',
    theme: 'url4',
    title: 'Private data in url4',
    blurb: 'Reference private data from a url4 line, so a fusion can run over data that cannot leave home.',
    detail:
      'A url4 expression could point at a private data resource, via Syftspace, as an input. This lets a fusion run over sensitive data that stays where it lives.\n\nScope and demand are still open.',
    bucket: 'exploring',
    status: 'planned',
    votes: 6,
  },
  {
    id: 'ORPIN',
    epic: 'Provider pinning',
    theme: 'platform',
    title: 'Pin OpenRouter providers',
    blurb: 'Lock which underlying provider OpenRouter uses, for control and reproducibility.',
    detail:
      'OpenRouter can route the same model to different backend providers, which can change results and cost. Pinning lets you fix exactly which provider serves a call, so a fusion stays reproducible and comparable.\n\nDirectional for 2027.',
    bucket: 'exploring',
    status: 'planned',
    votes: 9,
  },
  {
    id: 'MOD-AUDIO',
    epic: 'Modalities',
    theme: 'modalities',
    title: 'Audio and speech',
    blurb: 'Run fusions over audio and speech, not just text and images.',
    detail:
      'Support audio inputs so fusions can work on speech recognition, synthesis, and other acoustic tasks.\n\nDirectional for 2027.',
    bucket: 'exploring',
    status: 'planned',
    votes: 12,
  },
  {
    id: 'MOD-VIDEO',
    epic: 'Modalities',
    theme: 'modalities',
    title: 'Video',
    blurb: 'Run fusions over video, for motion and temporal tasks.',
    detail:
      'Support video inputs so fusions can handle video understanding and action recognition.\n\nOne of the larger gaps in what people want to evaluate.',
    bucket: 'exploring',
    status: 'planned',
    votes: 18,
  },
  {
    id: 'MOD-TABULAR',
    epic: 'Modalities',
    theme: 'modalities',
    title: 'Tabular data',
    blurb: 'Run fusions over tables and structured data.',
    detail:
      'Support structured tabular inputs like CSVs and relational data, so fusions can work on numerical and feature-based tasks.\n\nDirectional for 2027.',
    bucket: 'exploring',
    status: 'planned',
    votes: 16,
  },
  {
    id: 'MOD-GRAPH',
    epic: 'Modalities',
    theme: 'modalities',
    title: 'Graph data',
    blurb: 'Run fusions over graphs and network data.',
    detail:
      'Support graph-structured inputs like knowledge graphs and networks, for relational tasks.\n\nDirectional for 2027.',
    bucket: 'exploring',
    status: 'planned',
    votes: 14,
  },
  {
    id: 'MOD-3D',
    epic: 'Modalities',
    theme: 'modalities',
    title: '3D and sensor data',
    blurb: 'Run fusions over 3D, point-cloud, and time-series data.',
    detail:
      'Support 3D and point-cloud geometry, and sequential sensor or time-series inputs.\n\nEarly and low-demand so far, but asked for.',
    bucket: 'exploring',
    status: 'planned',
    votes: 6,
  },

  // ----------------------------- SHIPPED -----------------------------
  {
    id: 'PIPE',
    epic: 'Compose',
    theme: 'pipelines',
    title: 'Pipelines',
    blurb: 'Chain steps into pipelines, including map-reduce.',
    detail:
      'Compose fusions into sequential pipelines and map-reduce flows, so the output of one step feeds the next. This is documented in the Pipelines and map-reduce guides.',
    bucket: 'shipped',
    status: 'done',
    votes: 16,
    shipped: 'Oct 2026',
  },
  {
    id: 'VBENCH',
    epic: 'Benchmarks',
    theme: 'benchmarks',
    title: 'Image + text benchmarks',
    blurb: 'Benchmarks can take image inputs alongside text.',
    detail:
      'Benchmarks can take image inputs next to text, so vision-and-text tasks can be scored. Running images all the way through a fusion is still being finished separately.',
    bucket: 'shipped',
    status: 'done',
    votes: 10,
    shipped: 'Oct 2026',
  },
  {
    id: 'FILTER',
    epic: 'Fusion methods',
    theme: 'methods',
    title: 'Filter and rank',
    blurb: 'Narrow and order the answers before combining them, not just merge them.',
    detail:
      'Alongside the rules that combine answers, you can filter out answers that do not match a rule and rank the rest, keeping only the strongest. These narrow steps run before the final combine.',
    bucket: 'shipped',
    status: 'done',
    votes: 12,
    shipped: 'Oct 2026',
  },
  {
    id: 'C5',
    epic: 'Fusion methods',
    theme: 'E4a',
    ome: 'OME-1289',
    title: 'Deterministic combine',
    blurb:
      'Combine answers with majority vote, weighted average, and other deterministic rules, no extra model needed.',
    detail:
      'After the models answer, the toolkit picks or merges the answers without calling another model: majority or weighted vote, copy the best one, merge field by field, keep the top few, or join them together. Every rule gives the same result each time.\n\nThe report shows the tally and why an answer won.',
    bucket: 'shipped',
    status: 'done',
    votes: 24,
    shipped: 'Oct 2026',
  },
  {
    id: 'C6',
    epic: 'Fusion methods',
    theme: 'E4b',
    ome: 'OME-1290',
    title: 'Cross-provider signals',
    blurb: 'Attach confidence signals to each answer and combine on them.',
    detail:
      'Each model answer can come with a signal: a confidence score it states out loud, the model\'s own probability, how consistent it is across tries, plus cost and latency. Your rules can use those signals to weight votes, keep the strongest answers, or require agreement.\n\nReports show the signal and where it came from.',
    bucket: 'shipped',
    status: 'done',
    votes: 15,
    shipped: 'Oct 2026',
  },
  {
    id: 'C11',
    epic: 'Benchmarks',
    theme: 'E10a',
    ome: 'OME-1299',
    title: 'Single-turn benchmarks',
    blurb: 'Run fusions against single-turn text benchmarks.',
    detail:
      'A candidate reads text and writes text; the harness loads the dataset, calls once per item, and scores it. Scoring covers exact and numeric match, multiple choice, judge-scored free text, and automatic text metrics, with cost and tokens tracked per item.\n\nMost of the method papers we care about use this shape.',
    bucket: 'shipped',
    status: 'done',
    votes: 18,
    shipped: 'Oct 2026',
  },
  {
    id: 'C-E10b',
    epic: 'Benchmarks',
    theme: 'E10b',
    title: 'Retrieval benchmarks',
    blurb: 'Run fusions against read-only retrieval benchmarks.',
    detail:
      'Extends single-turn scoring to tasks that read from a fixed set of passages. The retrieval is read-only, so there is no external search to vary results.\n\nIt reuses the same scoring library as the text benchmarks.',
    bucket: 'shipped',
    status: 'done',
    votes: 8,
    shipped: 'Oct 2026',
  },
  {
    id: 'C20',
    epic: 'Leaderboard',
    theme: 'leaderboard',
    ome: 'OME-1282',
    title: 'Pareto frontier wins',
    blurb: 'See where a fusion wins on the score-for-cost frontier, not just on raw score.',
    detail:
      'The leaderboard marks which entries sit on the cost-versus-score Pareto frontier and which are open-weights. Each submission declares its model identity so the frontier is computed correctly.\n\nThis fixed an earlier inaccuracy in how wins were shown.',
    bucket: 'shipped',
    status: 'done',
    votes: 20,
    shipped: 'Oct 2026',
  },
  {
    id: 'C21',
    epic: 'Reproducibility',
    theme: 'E14',
    ome: 'OME-1307',
    title: 'Reproducible artifacts',
    blurb: 'Reproduce any leaderboard result from a single url4 line.',
    detail:
      'Each submission freezes its author metadata, paper link, and a full copy of its requests and answers. Replaying it with a pinned cache returns the exact result with zero spend.\n\nOwners can still edit metadata like authors and the linked paper without breaking the frozen run.',
    bucket: 'shipped',
    status: 'done',
    votes: 29,
    shipped: 'Oct 2026',
  },
  {
    id: 'C24',
    epic: 'Release',
    theme: 'E11',
    ome: 'OME-1304',
    title: 'Production release',
    blurb: 'The Client and leaderboard run against production.',
    detail:
      'Production was stood up, the gateway and benchmark and cache databases were migrated, and the Client is pinned to prod.\n\nIt is the release that made the public leaderboard real.',
    bucket: 'shipped',
    status: 'done',
    votes: 20,
    shipped: 'Oct 2026',
  },
  {
    id: 'C17',
    epic: 'Community cache',
    theme: 'E22',
    title: 'Community cache',
    blurb: 'Reuse cached runs the community has already paid for.',
    detail:
      'When someone has already run a given call, its cached result can be served to others instead of paying for it again. It lowers the cost of reproducing and building on existing submissions.\n\nIt rides on the same per-call cache the cost work introduced.',
    bucket: 'shipped',
    status: 'done',
    votes: 17,
    shipped: 'Oct 2026',
  },
  {
    id: 'C26',
    epic: 'Analytics',
    theme: 'E12',
    ome: 'OME-1768',
    title: 'Consented analytics',
    blurb: 'Opt-in, privacy-respecting analytics so we can see what needs work.',
    detail:
      'The SDK sends anonymous usage like API calls, SDK version, and whether you run local or hosted, on by default with a clear opt-out. No prompts, credentials, or outputs are ever collected.\n\nTurn it off with sf.analytics.disable() or DO_NOT_TRACK=1.',
    bucket: 'shipped',
    status: 'done',
    votes: 5,
    shipped: 'Nov 2026',
  },
]

interface BucketDef {
  key: Bucket
  label: string
  band: string // the time anchor shown on the timeline
  note: string
}

// Order is the vertical stack order: forward buckets first, Shipped last.
const BUCKETS: BucketDef[] = [
  { key: 'now', label: 'Now', band: 'Nov–Dec 2026', note: 'Being built.' },
  { key: 'next', label: 'Next', band: 'Q1 2027', note: 'Planned next. No firm dates yet.' },
  {
    key: 'exploring',
    label: 'Exploring 2027',
    band: '2027',
    note: 'In scope for 2027, but we hope the community will weigh in on what we should tackle first.',
  },
  { key: 'shipped', label: 'Shipped', band: 'Shipped', note: 'Done and in your hands.' },
]

// The forward buckets shown on the horizontal time rail (Shipped sits before "now").
const RAIL = BUCKETS.filter((b) => b.key !== 'shipped')

type Filter = 'all' | Bucket
const active = ref<Filter>('all')

const countFor = (b: Bucket) => ITEMS.filter((i) => i.bucket === b).length
const itemsFor = (b: Bucket) => ITEMS.filter((i) => i.bucket === b)
const visibleBuckets = computed(() =>
  active.value === 'all' ? BUCKETS : BUCKETS.filter((b) => b.key === active.value),
)

// ---- inline "Read more" expand state (session-only, not persisted) ----
const expanded = ref<Record<string, boolean>>({})
const isExpanded = (id: string) => !!expanded.value[id]
function toggleDetail(id: string) {
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] }
}

// "Suggest an idea" → prefilled GitHub issue. A dedicated issue template is
// aspirational; the title/body/label prefill works without one.
const GITHUB = 'https://github.com/ScreamingFace'
const SUGGEST_URL = 'https://github.com/ScreamingFace/screamingface/issues/new/choose'

// ---- contributors: pulled live from the public GitHub repo ----
interface Contributor {
  login: string
  html_url: string
  avatar_url: string
  contributions: number
}
// People to guarantee in the list even if the repo's contributor API misses them
// (contributions under another account, or non-code work). Bennett comes through
// the live pull already.
const EXTRA_CONTRIBUTORS: { login: string }[] = [{ login: 'dbckz' }]
const CONTRIB_API =
  'https://api.github.com/repos/ScreamingFace/screamingface/contributors?per_page=100'
const contributors = ref<Contributor[]>([])

onMounted(async () => {
  let list: Contributor[] = []
  try {
    const res = await fetch(CONTRIB_API, { headers: { Accept: 'application/vnd.github+json' } })
    if (res.ok) {
      const data = (await res.json()) as Contributor[]
      list = data
        .filter((c) => c.login && !c.login.includes('[bot]'))
        .map((c) => ({
          login: c.login,
          html_url: c.html_url,
          avatar_url: c.avatar_url,
          contributions: c.contributions ?? 0,
        }))
    }
  } catch {
    // offline or rate-limited — fall back to the seeded extras below
  }
  // merge the guaranteed extras, de-duped by login (case-insensitive)
  const seen = new Set(list.map((c) => c.login.toLowerCase()))
  for (const e of EXTRA_CONTRIBUTORS) {
    if (!seen.has(e.login.toLowerCase())) {
      list.push({
        login: e.login,
        html_url: `https://github.com/${e.login}`,
        avatar_url: `https://github.com/${e.login}.png?size=80`,
        contributions: 0,
      })
    }
  }
  list.sort((a, b) => b.contributions - a.contributions || a.login.localeCompare(b.login))
  contributors.value = list
})
</script>

<template>
  <div class="road">
    <!-- ============ HERO ============ -->
    <section class="hero band">
      <p class="kicker">ScreamingFace · roadmap</p>
      <h1 class="hero__title">
        What we're building,<br />
        <span class="hero__title-2">in the open.</span>
      </h1>
      <p class="lead">
        Where ScreamingFace is headed, and how to shape it. Upvote what you want next. Leave a short
        note on what it would unblock.
      </p>
      <p class="lead__note">
        Add new feature requests as GitHub issues in
        <a
          class="lead__link"
          href="https://github.com/ScreamingFace/screamingface/issues/new/choose"
          target="_blank"
          rel="noopener noreferrer"
          >screamingface/screamingface</a
        >.
      </p>

      <div class="actions">
        <a class="btn btn--primary" :href="SUGGEST_URL" target="_blank" rel="noopener noreferrer"
          >Suggest an idea</a
        >
        <a class="btn btn--sec" href="#buckets">How the buckets work</a>
      </div>
    </section>

    <!-- ============ TIME RAIL + FILTERS ============ -->
    <section class="board band">
      <div class="rail" aria-hidden="true">
        <span class="rail__past">✓ Shipped</span>
        <span class="rail__line"></span>
        <span v-for="(b, i) in RAIL" :key="b.key" class="rail__stop">
          <span class="rail__dot" :class="{ 'rail__dot--open': b.key === 'exploring' }"></span>
          <span class="rail__label">{{ b.label }}</span>
          <span class="rail__band">{{ b.band }}</span>
          <span v-if="i < RAIL.length - 1" class="rail__seg"></span>
        </span>
      </div>

      <div class="filters" role="tablist" aria-label="Filter the roadmap by bucket">
        <button
          class="tab"
          :class="{ 'tab--on': active === 'all' }"
          role="tab"
          :aria-selected="active === 'all'"
          @click="active = 'all'"
        >
          All<span class="tab__count">{{ ITEMS.length }}</span>
        </button>
        <button
          v-for="b in BUCKETS"
          :key="b.key"
          class="tab"
          :class="{ 'tab--on': active === b.key }"
          role="tab"
          :aria-selected="active === b.key"
          @click="active = b.key"
        >
          {{ b.label }}<span class="tab__count">{{ countFor(b.key) }}</span>
        </button>
      </div>

      <!-- ============ VERTICAL TIMELINE ============ -->
      <div class="timeline">
        <section
          v-for="b in visibleBuckets"
          :key="b.key"
          class="tl-section"
          :class="{ 'tl-section--shipped': b.key === 'shipped' }"
        >
          <header class="tl-head">
            <span class="tl-dot" :class="{ 'tl-dot--done': b.key === 'shipped' }"></span>
            <h2 class="tl-title">{{ b.label }}</h2>
            <span class="tl-band">{{ b.band }}</span>
            <span class="tl-count">{{ countFor(b.key) }}</span>
          </header>
          <p class="tl-note">{{ b.note }}</p>

          <div class="grid">
            <article
              v-for="item in itemsFor(b.key)"
              :key="item.id"
              class="card"
              :class="{ 'card--done': item.status === 'done' }"
            >
              <div class="card__top">
                <span class="card__epic">{{ item.epic }}</span>
                <span v-if="item.eta || item.shipped" class="card__tags">
                  <span v-if="item.eta" class="chip chip--eta">{{ item.eta }}</span>
                  <span v-if="item.shipped" class="chip chip--shipped">✓ {{ item.shipped }}</span>
                </span>
              </div>

              <h3 class="card__title">{{ item.title }}</h3>
              <p class="card__desc">{{ item.blurb }}</p>

              <!-- faithful detail, collapsed by default -->
              <template v-if="item.detail">
                <transition name="reveal">
                  <div v-if="isExpanded(item.id)" class="card__detail">
                    <p v-for="(para, i) in item.detail.split('\n\n')" :key="i">{{ para }}</p>
                    <p v-if="item.ome" class="card__ref">Tracked in {{ item.ome }}</p>
                  </div>
                </transition>
                <button
                  class="readmore"
                  :aria-expanded="isExpanded(item.id)"
                  @click="toggleDetail(item.id)"
                >
                  {{ isExpanded(item.id) ? 'Read less' : 'Read more' }}
                  <span aria-hidden="true">{{ isExpanded(item.id) ? '▴' : '▾' }}</span>
                </button>
              </template>

            </article>
          </div>
        </section>
      </div>
    </section>

    <!-- ============ HOW THE BUCKETS WORK ============ -->
    <section id="buckets" class="legend band">
      <p class="kicker">How the buckets work</p>
      <dl class="defs">
        <div v-for="b in BUCKETS" :key="b.key" class="def">
          <dt>{{ b.label }}<span class="def__band">{{ b.band }}</span></dt>
          <dd>{{ b.note }}</dd>
        </div>
      </dl>
    </section>

    <!-- ============ CONTRIBUTORS ============ -->
    <section v-if="contributors.length" class="people band">
      <p class="kicker">Built by</p>
      <p class="people__intro">
        <strong class="people__count">{{ contributors.length }}+ contributors</strong> and counting.
        ScreamingFace is open source, and the roadmap above is shaped by people who show up. Pick
        something you want to exist and
        <a class="lead__link" :href="GITHUB" target="_blank" rel="noopener noreferrer"
          >build it with us</a
        >.
      </p>
      <ul class="people__grid">
        <li v-for="c in contributors" :key="c.login" class="person">
          <a class="person__link" :href="c.html_url" target="_blank" rel="noopener noreferrer">
            <img
              class="person__avatar"
              :src="c.avatar_url"
              :alt="c.login"
              width="32"
              height="32"
              loading="lazy"
            />
            <span class="person__login">{{ c.login }}</span>
          </a>
        </li>
      </ul>
    </section>

    <!-- ============ FOOTER ============ -->
    <footer class="foot band">
      <div class="foot__brand">
        <span class="foot__mark" aria-hidden="true">😱</span>
        <span><span class="foot__name">ScreamingFace</span></span>
      </div>
      <nav class="foot__links">
        <a :href="SUGGEST_URL" target="_blank" rel="noopener noreferrer">Suggest an idea</a>
        <a :href="GITHUB" target="_blank" rel="noopener noreferrer">GitHub</a>
      </nav>
    </footer>
  </div>
</template>

<style scoped>
/* SFDS v2 marketing register (gold accent is set globally). Structure reads from
   hairline seams and square edges; two families (Plex Sans + Mono) + Parastoo on
   the one hero line. Mirrors HomePage.vue so the roadmap reads as the same site. */
.road {
  --rail-h: 0px;
  color: var(--text);
  font-family: var(--f-sans);
}
.band {
  max-width: 1140px;
  margin: 0 auto;
  padding-left: var(--space-7);
  padding-right: var(--space-7);
}
.kicker {
  font-family: var(--f-mono);
  font-size: var(--text-label);
  font-weight: var(--weight-medium);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--accent-text-low);
  margin: 0 0 var(--space-6);
}
em {
  font-style: normal;
  color: var(--text);
  font-weight: var(--weight-medium);
}

/* ---------- HERO ---------- */
.hero {
  padding-top: var(--space-12);
  padding-bottom: var(--space-10);
}
.hero__title {
  font-family: var(--f-display);
  font-weight: var(--weight-display);
  font-size: var(--text-hero);
  line-height: var(--leading-hero);
  letter-spacing: var(--tracking-tight);
  margin: 0 0 var(--space-6);
}
.hero__title-2 {
  color: var(--text-2);
}
.lead {
  font-size: var(--text-lead);
  line-height: var(--leading-snug);
  color: var(--text-2);
  max-width: 64ch;
  margin: 0 0 var(--space-8);
}
.lead__note {
  font-size: var(--text-sm);
  line-height: var(--leading-snug);
  color: var(--text-2);
  margin: calc(-1 * var(--space-6)) 0 var(--space-8);
}
.lead__link {
  color: var(--accent-text-low);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.lead__link:hover {
  color: var(--accent-text);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
.btn {
  display: inline-flex;
  align-items: center;
  font-family: var(--f-sans);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  padding: 10px 18px;
  border: 1px solid transparent;
  border-radius: var(--radius-none);
  text-decoration: none;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}
.btn.sm {
  padding: 6px 12px;
  font-size: var(--text-sm);
}
.btn--primary {
  background: var(--accent-solid);
  color: var(--accent-contrast-text);
}
.btn--primary:hover {
  background: var(--accent-solid-hover);
}
.btn--sec {
  border-color: var(--border);
  color: var(--text);
  background: transparent;
}
.btn--sec:hover {
  border-color: var(--accent-border-strong);
  color: var(--accent-text-low);
}

/* ---------- BOARD wrap ---------- */
.board {
  padding-top: var(--space-9);
  padding-bottom: var(--space-10);
  border-top: 1px solid var(--border);
}

/* ---------- TIME RAIL ---------- */
.rail {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--space-3) var(--space-5);
  padding-bottom: var(--space-6);
  margin-bottom: var(--space-6);
  border-bottom: 1px solid var(--border);
}
.rail__past {
  font-family: var(--f-mono);
  font-size: var(--text-label);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--success-text-low);
}
.rail__line {
  flex: 0 0 var(--space-6);
  height: 1px;
  align-self: center;
  background: var(--border-2);
}
.rail__stop {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-2);
}
.rail__dot {
  width: 7px;
  height: 7px;
  align-self: center;
  background: var(--accent-solid);
  border: 1px solid var(--accent-solid);
}
.rail__dot--open {
  background: transparent;
  border-color: var(--border-2);
}
.rail__label {
  font-family: var(--f-mono);
  font-size: var(--text-label);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--text);
}
.rail__band {
  font-size: var(--text-label);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.rail__seg {
  width: var(--space-5);
  height: 1px;
  align-self: center;
  background: var(--border-2);
}

/* ---------- FILTERS ---------- */
.filters {
  display: inline-flex;
  flex-wrap: wrap;
  border: 1px solid var(--border);
  margin-bottom: var(--space-8);
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--f-mono);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-2);
  background: transparent;
  border: none;
  border-right: 1px solid var(--border);
  padding: 8px 14px;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}
.tab:last-child {
  border-right: none;
}
.tab:hover {
  color: var(--text);
  background: var(--surface);
}
.tab--on {
  background: var(--accent-solid);
  color: var(--accent-contrast-text);
}
.tab--on:hover {
  background: var(--accent-solid-hover);
  color: var(--accent-contrast-text);
}
.tab__count {
  font-size: var(--text-label);
  opacity: 0.8;
  font-variant-numeric: tabular-nums;
}

/* ---------- VERTICAL TIMELINE ---------- */
.timeline {
  position: relative;
}
.tl-section {
  position: relative;
  padding-left: var(--space-7);
  padding-bottom: var(--space-9);
  border-left: 1px solid var(--border);
}
.tl-section:last-child {
  border-left-color: transparent;
  padding-bottom: 0;
}
.tl-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}
.tl-dot {
  position: absolute;
  left: -5px;
  top: 6px;
  width: 9px;
  height: 9px;
  background: var(--accent-solid);
  border: 1px solid var(--accent-solid);
}
.tl-dot--done {
  background: var(--success-solid, var(--success-text-low));
  border-color: var(--success-border);
}
.tl-title {
  font-family: var(--f-mono);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--text);
  margin: 0;
}
.tl-band {
  font-size: var(--text-label);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.tl-count {
  margin-left: auto;
  font-family: var(--f-mono);
  font-size: var(--text-label);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.tl-note {
  font-size: var(--text-sm);
  color: var(--text-2);
  margin: 0 0 var(--space-5);
}

/* ---------- cards ---------- */
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
  align-items: stretch;
}
.card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--bg);
  border: 1px solid var(--border);
  padding: var(--space-4) var(--space-5) var(--space-5);
}
/* Shipped reads green — a subtle success seam, not a gold interaction. */
.card--done {
  border-left: 2px solid var(--success-border);
}
.card__top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  min-height: 20px;
}
.card__epic {
  flex: 1;
  min-width: 0;
  font-family: var(--f-mono);
  font-size: var(--text-label);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  line-height: var(--leading-snug);
  color: var(--text-2);
}
/* status + time tags pinned top-right as one cluster, so the month and the
   "In progress" badge land in the same place regardless of the epic length. */
.card__tags {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
.chip {
  font-family: var(--f-mono);
  font-size: var(--text-label);
  letter-spacing: 0.04em;
  padding: 1px 7px;
  border: 1px solid var(--border);
  white-space: nowrap;
}
/* ETA is neutral — an ETA is NOT "the win", so never gold. */
.chip--eta {
  color: var(--text-2);
  border-color: var(--border-2);
}
/* Shipped uses success (green ≠ gold). */
.chip--shipped {
  color: var(--success-text-low);
  border-color: var(--success-border);
}
/* Fixed line-boxes so a 1-line title and a 3-line topline reserve the same
   space on every card — collapsed cards then line up at equal height. */
.card__title {
  font-size: var(--text-lead);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-tight);
  color: var(--text);
  margin: 0;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
  line-clamp: 1;
  overflow: hidden;
}
.card__desc {
  font-size: var(--text-sm);
  line-height: var(--leading-snug);
  color: var(--text-2);
  margin: 0;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  overflow: hidden;
}

/* ---------- read more ---------- */
.card__detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  overflow: hidden;
}
.card__detail p {
  font-size: var(--text-sm);
  line-height: var(--leading-snug);
  color: var(--text-2);
  margin: 0;
}
.readmore {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--f-mono);
  font-size: var(--text-label);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--accent-text-low);
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
}
.readmore:hover {
  text-decoration: underline;
}
.reveal-enter-active,
.reveal-leave-active {
  transition:
    max-height 0.2s ease,
    opacity 0.2s ease;
  max-height: 400px;
}
.reveal-enter-from,
.reveal-leave-to {
  max-height: 0;
  opacity: 0;
}

.card__ref {
  margin-top: var(--space-1);
  font-family: var(--f-mono);
  font-size: var(--text-label);
  letter-spacing: 0.02em;
  color: var(--text-2);
  opacity: 0.75;
  font-variant-numeric: tabular-nums slashed-zero;
}

/* ---------- contributors ---------- */
.people {
  padding-top: var(--space-9);
  padding-bottom: var(--space-10);
  border-top: 1px solid var(--border);
}
.people__intro {
  font-size: 1.0625rem;
  line-height: var(--leading-snug);
  color: var(--text-2);
  max-width: 64ch;
  margin: 0 0 var(--space-6);
}
.people__count {
  color: var(--text);
  font-weight: var(--weight-semibold);
}
.people__grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
}
.person {
  background: var(--bg);
}
.person__link {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  text-decoration: none;
  color: var(--text);
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}
.person__link:hover {
  background: var(--surface);
  color: var(--accent-text-low);
}
.person__avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  object-fit: cover;
}
.person__login {
  font-family: var(--f-sans);
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------- LEGEND ---------- */
.legend {
  padding-top: var(--space-10);
  padding-bottom: var(--space-10);
  border-top: 1px solid var(--border);
  scroll-margin-top: calc(var(--rail-h) + var(--space-6));
}
.defs {
  margin: 0;
  display: grid;
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
}
.def {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: var(--space-6);
  background: var(--bg);
  padding: var(--space-4) var(--space-6);
}
.def dt {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-family: var(--f-mono);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text);
}
.def__band {
  font-size: var(--text-label);
  font-weight: var(--weight-regular);
  color: var(--text-2);
}
.def dd {
  margin: 0;
  font-size: var(--text-sm);
  line-height: var(--leading-snug);
  color: var(--text-2);
  max-width: 60ch;
}
/* ---------- FOOTER ---------- */
.foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  padding-top: var(--space-9);
  padding-bottom: var(--space-10);
  border-top: 1px solid var(--border);
}
.foot__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.foot__mark {
  font-size: 22px;
  line-height: 1;
}
.foot__name {
  display: block;
  font-weight: var(--weight-medium);
  color: var(--text);
}
.foot__links {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
}
.foot__links a {
  font-size: var(--text-sm);
  color: var(--text-2);
  text-decoration: none;
}
.foot__links a:hover {
  color: var(--accent-text-low);
}

/* ---------- RESPONSIVE ---------- */
@media (max-width: 960px) {
  .grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 640px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .def {
    grid-template-columns: 1fr;
    gap: var(--space-2);
  }
  .hero {
    padding-top: var(--space-10);
  }
  .tl-section {
    padding-left: var(--space-5);
  }
}
</style>
