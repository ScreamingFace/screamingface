<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import NbStateCarousel from '@/components/nb/NbStateCarousel.vue'
import ProviderConnections from '@/components/nb/ProviderConnections.vue'
import type { Provider } from '@/components/nb/ProviderConnections.vue'
import CandidateScores from '@/components/nb/CandidateScores.vue'
import type { NbRowForm } from '@/components/nb/types'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

// Every provider a local engine advertises, read from its registry.
const providers: Provider[] = [
  { id: 'anthropic', name: 'Anthropic', status: 'disconnected' },
  { id: 'antigravity', name: 'Antigravity', status: 'disconnected' },
  { id: 'codex', name: 'Codex', status: 'disconnected' },
  { id: 'gemini-cli', name: 'Gemini CLI', status: 'disconnected' },
  { id: 'huggingface', name: 'Hugging Face', status: 'disconnected' },
  { id: 'openai', name: 'OpenAI', status: 'disconnected' },
  { id: 'openrouter', name: 'OpenRouter', status: 'disconnected' },
]

const connected = (id: string): Provider[] =>
  providers.map((p) => (p.id === id ? { ...p, status: 'connected' } : p))

// The connection flow, one state per step. Each is a plain prop set: the row
// holds no state of its own, so the sequence is readable in one place.
const connectSteps: { caption: string; providers: Provider[]; forms: Record<string, NbRowForm> }[] =
  [
    {
      caption:
        'Every provider the engine advertises, with its live status. Nothing is connected yet.',
      providers,
      forms: {},
    },
    {
      caption: 'Press Connect and the row offers the methods that provider supports.',
      providers,
      forms: { openrouter: { kind: 'options', choices: ['API key'], cancel: 'Cancel' } },
    },
    {
      caption: 'Choosing API key opens a field. The key travels to the engine, never to the page.',
      providers,
      forms: {
        openrouter: { kind: 'entry', placeholder: 'API key', confirm: 'Save', cancel: 'Cancel' },
      },
    },
    {
      caption: 'Paste the key. It is masked as you type and cleared after the attempt.',
      providers,
      forms: {
        openrouter: {
          kind: 'entry',
          value: 'sk-or-v1-0000000000',
          secret: true,
          focused: true,
          confirm: 'Save',
          cancel: 'Cancel',
        },
      },
    },
    {
      caption: 'Saving hands the key to the engine, which validates it before storing.',
      providers: providers.map((p) => (p.id === 'openrouter' ? { ...p, status: 'pending' } : p)),
      forms: {},
    },
    {
      caption:
        'OpenRouter is connected. One engine-scoped key covers every model route in this study.',
      providers: connected('openrouter'),
      forms: {},
    },
  ]

// The published full-benchmark result, not output from the code on this page.
// Three solo models did not complete every task; their coverage is shown as-is.
const publishedDraco = [
  { id: 'fable-gpt', name: 'Fable 5 + GPT-5.5', score: 68.6, casesScored: 100, casesTotal: 100 },
  {
    id: 'opus-gpt-ds',
    name: 'Opus + GPT-5.5 + DeepSeek',
    score: 67.0,
    casesScored: 100,
    casesTotal: 100,
  },
  {
    id: 'opus-gpt-gem',
    name: 'Opus 4.8 + GPT-5.5 + Gemini 3.1 Pro',
    score: 65.7,
    casesScored: 100,
    casesTotal: 100,
  },
  { id: 'opus-gpt', name: 'Opus 4.8 + GPT-5.5', score: 64.2, casesScored: 100, casesTotal: 100 },
  {
    id: 'ds-kimi-gpt',
    name: 'DeepSeek + Kimi + GPT-5.5',
    score: 61.9,
    casesScored: 100,
    casesTotal: 100,
  },
  { id: 'gpt-solo', name: 'GPT-5.5 (solo)', score: 60.2, casesScored: 100, casesTotal: 100 },
  { id: 'opus-opus', name: 'Opus 4.8 + Opus 4.8', score: 58.5, casesScored: 100, casesTotal: 100 },
  {
    id: 'budget-trio',
    name: 'Gemini 3 Flash + Kimi + DeepSeek',
    score: 58.5,
    casesScored: 100,
    casesTotal: 100,
  },
  {
    id: 'fable-solo',
    name: 'Claude Fable 5 (solo)',
    score: 57.8,
    casesScored: 92,
    casesTotal: 100,
    coverage: 92,
  },
  {
    id: 'ds-kimi-qwen',
    name: 'DeepSeek + Kimi + Qwen',
    score: 56.6,
    casesScored: 100,
    casesTotal: 100,
  },
  { id: 'ds-kimi', name: 'DeepSeek + Kimi', score: 54.3, casesScored: 100, casesTotal: 100 },
  {
    id: 'opus-solo',
    name: 'Claude Opus 4.8 (solo)',
    score: 51.8,
    casesScored: 100,
    casesTotal: 100,
  },
  {
    id: 'gemini-pro-solo',
    name: 'Gemini 3.1 Pro (solo)',
    score: 50.9,
    casesScored: 47,
    casesTotal: 100,
    coverage: 47,
  },
  { id: 'ds-solo', name: 'DeepSeek V4 Pro (solo)', score: 49.3, casesScored: 100, casesTotal: 100 },
  {
    id: 'flash-solo',
    name: 'Gemini 3 Flash (solo)',
    score: 35.9,
    casesScored: 100,
    casesTotal: 100,
  },
  {
    id: 'kimi-solo',
    name: 'Kimi K2.6 (solo)',
    score: 34.0,
    casesScored: 89,
    casesTotal: 100,
    coverage: 89,
  },
]

const configure = `import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)`

const connect = `sf.connect()`

const connectScript = `import os

sf.connect("openrouter", api_key=os.environ["OPENROUTER_API_KEY"])
sf.connections.list()        # the same status the panel shows
sf.disconnect("openrouter")  # remove it again`

const compose = `ANSWER = "Answer this research prompt thoroughly, in prose, with specific evidence."
SYNTHESIS = "Combine the panel's answers into one unified prose answer. Add no new facts."

opus = sf.Model("openrouter/anthropic/claude-opus-4.8", prompt=ANSWER)
gpt = sf.Model("openrouter/openai/gpt-5.5", prompt=ANSWER)
gemini = sf.Model("openrouter/google/gemini-3.1-pro-preview", prompt=ANSWER, params={"max_tokens": 8192})

frontier_trio = sf.Fanout([opus, gpt, gemini], name="frontier-trio") >> sf.Synthesize(
    sf.Model(
        "openrouter/anthropic/claude-opus-4.8",
        prompt=SYNTHESIS,
        params={"max_tokens": 8192},
    )
)

candidates = [opus, gpt, gemini, frontier_trio]   # 3 solo models and 1 fusion`

const load = `draco = sf.benchmarks.get("draco-3pass")
draco.title, draco.revision, draco.case_count`

const evaluate = `report = sf.evaluate(candidates, benchmark="draco-3pass", limit=1)`

const evaluateLocal = `report = sf.evaluate(candidates, benchmark="medxpert", limit=1)`

const loadLocal = `medxpert = sf.benchmarks.get("medxpert")
medxpert.title, medxpert.revision, medxpert.case_count`

const loadLocalOut = `('MedXpertQA', '1e5a3b8a461a52f7', 2450)`

const scoresLocal = `{c.name: c.score for c in report.candidates}`

const scoresLocalOut = `{'claude-opus-4.8': 0.0, 'gpt-5.5': 1.0, 'gemini-3.1-pro-preview': 1.0, 'frontier-trio': 1.0}`

const checkReport = `report.ok          # False if any candidate or member failed
report.failures    # what failed, and why`
</script>

<template>
  <DocLayout
    title="Reproduce OpenRouter's DRACO results"
    description="Run a DRACO subset end to end to compare fusions with its solo models."
    :navigation="navigation"
    :version="version"
  >
    <p>
      By the end, you'll have a scored comparison of <strong>four recipes</strong>: three solo
      models and one fusion built from them, all on one case (<code>limit=1</code>). On the hosted
      engine the case comes from
      <a href="https://arxiv.org/abs/2602.11685" target="_blank" rel="noopener">DRACO</a> and each
      answer is judged three times. On a local engine the case comes from <code>medxpert</code>,
      graded by exact match with no judge.
    </p>

    <blockquote>
      You'll need the <RouterLink to="/learn/engine">ScreamingFace Engine</RouterLink> running and
      an OpenRouter connection first. See
      <RouterLink to="/sf-client/installation">Installation</RouterLink>. Every model below is an
      OpenRouter route, so one connection covers everything. DRACO runs on the hosted engine, which
      needs an account with access. On a local engine, <code>medxpert</code> is ready by default, so
      with a local engine run the same steps on <code>medxpert</code>.
    </blockquote>

    <h2>1 · Configure the engine</h2>

    <p>
      The <RouterLink to="/learn/engine"><strong>ScreamingFace Engine</strong></RouterLink> is a
      separate process that grades the benchmarks and calls the models on your behalf. On a local
      engine it holds your provider credentials; on the hosted engine the operator manages them. The
      Client hands all of that work to the engine, so this first step tells the Client where to find
      it.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="configure" />
    </div>

    <p>
      <code>sf.configure()</code> validates and stores the URLs without making a network request.
      The example above points at a <strong>local engine</strong> on
      <code>http://127.0.0.1:9108</code> and its leaderboard on <code>http://127.0.0.1:9106</code>,
      so local scores stay local. A non-default <code>engine_url</code> requires
      <code>scoreboard_url</code>; <code>configure</code> raises <code>ValueError</code> without it.
      To run one yourself, install the <code>[runtime]</code> extra and start the stack with
      <code>screamingface up</code>. The
      <RouterLink to="/sf-client/installation">Installation</RouterLink> guide walks through that
      end to end.
    </p>

    <p>
      To use the <strong>hosted ScreamingFace engine</strong> instead, name it: the Client's default
      engine is the hosted one, <code>https://fusion.screamingface.ai</code>, and its leaderboard is
      <code>https://leaderboard.screamingface.ai</code>. With no <code>configure</code> call and a
      local stack running, the Client uses the local stack instead and prints
      <code>connected to the local stack at http://127.0.0.1:9108</code>. Hosted access is granted
      by the OpenMined team, so reach out to them before it will run evaluations for your account.
    </p>

    <p>
      <strong>If the engine isn't reachable</strong>, the first call that needs it will raise
      <code>EngineUnavailableError</code>. You can check a local one beforehand with
      <code>curl http://127.0.0.1:9108/healthz</code>. Provider connection calls require HTTPS
      outside loopback.
    </p>

    <h2>2 · Connect a provider</h2>

    <p>
      <strong>On the hosted engine</strong> there is nothing to connect:
      <code>sf.connect()</code> shows a panel with a Log in button, and after login every provider
      the OpenMined team has enabled for your account shows as connected. A provider that is not
      enabled shows as unavailable. <strong>On a local engine</strong> the engine holds your
      credentials, and you need at least one provider connected before you can call a model.
      <code>sf.connect()</code> with no arguments shows a panel of every provider the engine
      supports. The example below connects <strong>OpenRouter</strong> with an API key on a local
      engine, walking through all six states of the auth flow.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="connect">
        <NbStateCarousel :steps="connectSteps" label="Connecting a provider">
          <template #default="{ step }">
            <ProviderConnections
              :providers="step.providers"
              :forms="step.forms"
              :busy="step.providers.some((p) => p.status === 'pending') ? ['openrouter'] : []"
              engine-url="http://127.0.0.1:9108"
            >
            </ProviderConnections>
          </template>
        </NbStateCarousel>
      </NbCell>
    </div>

    <blockquote>
      You'll need the <RouterLink to="/learn/engine">ScreamingFace Engine</RouterLink> running and
      an OpenRouter connection first. See
      <RouterLink to="/sf-client/installation">Installation</RouterLink>. Every model below is an
      OpenRouter route, so one connection covers everything. DRACO runs on the hosted engine, which
      needs an account with access. On a local engine, <code>medxpert</code> is ready by default, so
      with a local engine run the same steps on <code>medxpert</code>.
    </blockquote>

    <h2>1 · Configure the engine</h2>

    <p>
      The <RouterLink to="/learn/engine"><strong>ScreamingFace Engine</strong></RouterLink> is a
      separate process that grades the benchmarks and calls the models on your behalf. On a local
      engine it holds your provider credentials; on the hosted engine the operator manages them. The
      Client hands all of that work to the engine, so this first step tells the Client where to find
      it.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="configure" />
    </div>

    <p>
      <code>sf.configure()</code> validates and stores the URLs without making a network request.
      The example above points at a <strong>local engine</strong> on
      <code>http://127.0.0.1:9108</code> and its leaderboard on <code>http://127.0.0.1:9106</code>,
      so local scores stay local. A non-default <code>engine_url</code> requires
      <code>scoreboard_url</code>; <code>configure</code> raises <code>ValueError</code> without it.
      To run one yourself, install the <code>[runtime]</code> extra and start the stack with
      <code>screamingface up</code>. The
      <RouterLink to="/sf-client/installation">Installation</RouterLink> guide walks through that
      end to end.
    </p>

    <p>
      To use the <strong>hosted ScreamingFace engine</strong> instead, name it: the Client's default
      engine is the hosted one, <code>https://fusion.screamingface.ai</code>, and its leaderboard is
      <code>https://leaderboard.screamingface.ai</code>. With no <code>configure</code> call and a
      local stack running, the Client uses the local stack instead and prints
      <code>connected to the local stack at http://127.0.0.1:9108</code>. Hosted access is granted
      by the OpenMined team, so reach out to them before it will run evaluations for your account.
    </p>

    <p>
      <strong>If the engine isn't reachable</strong>, the first call that needs it will raise
      <code>EngineUnavailableError</code>. You can check a local one beforehand with
      <code>curl http://127.0.0.1:9108/healthz</code>. Provider connection calls require HTTPS
      outside loopback.
    </p>

    <h2>2 · Connect a provider</h2>

    <p>
      <strong>On the hosted engine</strong> there is nothing to connect:
      <code>sf.connect()</code> shows a panel with a Log in button, and after login every provider
      the OpenMined team has enabled for your account shows as connected. A provider that is not
      enabled shows as unavailable. <strong>On a local engine</strong> the engine holds your
      credentials, and you need at least one provider connected before you can call a model.
      <code>sf.connect()</code> with no arguments shows a panel of every provider the engine
      supports. The example below connects <strong>OpenRouter</strong> with an API key on a local
      engine, walking through all six states of the auth flow.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="connect">
        <NbStateCarousel :steps="connectSteps" label="Connecting a provider">
          <template #default="{ step }">
            <ProviderConnections
              :providers="step.providers"
              :forms="step.forms"
              :busy="step.providers.some((p) => p.status === 'pending') ? ['openrouter'] : []"
              engine-url="http://127.0.0.1:9108"
            >
            </ProviderConnections>
          </template>
        </NbStateCarousel>
      </NbCell>
    </div>

    <h3>Reading the panel</h3>

    <p>
      Each row shows one provider: its display name, <strong>live status</strong>, and what you can
      do. On a local engine the status is one of <code>not connected</code>, <code>pending</code>,
      <code>connected</code>, <code>needs reauth</code> or <code>error</code>. On the hosted engine
      it is <code>Connected</code> or <code>Unavailable</code>, with no buttons, because a hosted
      engine takes no keys of its own. The header shows which engine you're talking to, so you won't
      accidentally send a key to the wrong one.
    </p>

    <blockquote>
      We're using OpenRouter here for simplicity, but you can build fusions with models from any of
      the providers listed above. One caveat:
      <strong>caching covers OpenRouter, Anthropic, OpenAI and Hugging Face routes</strong>, so runs
      on Codex, Gemini CLI and Antigravity aren't reused.
    </blockquote>

    <h3>Configure OpenRouter via script</h3>

    <p>
      Scripts skip the panel by naming the provider and passing the key directly. Pull the key from
      the environment instead of hardcoding it.
    </p>

    <CodeBlock :code="connectScript" language="python" />

    <p>
      <code>sf.connect(...)</code> returns a <code>Connection</code> with validated status, so a bad
      key fails right here, not later during evaluation. <code>sf.connections.list()</code> gives
      you one per provider (same data the panel shows), and on a local engine
      <code>sf.disconnect(...)</code> is safe to call even if you've never connected. A hosted
      engine refuses both <code>connect</code> with a key and <code>disconnect</code>.
    </p>

    <p>
      The panel states, the OAuth flow for Codex, Antigravity, Anthropic and Gemini CLI, and the
      hosted engine's read-only connections are in the
      <RouterLink to="/sf-client/guides/connections">Connections guide</RouterLink> and the
      <RouterLink to="/sf-client/api/connections">Connections reference</RouterLink>.
    </p>

    <h2>3 · Compose the candidates</h2>

    <p>
      A <strong>candidate</strong> is anything you are submitting to be scored, whether that is a
      single model or a fusion.
    </p>

    <ul>
      <li>
        <code>sf.Model</code>: one configured call (route, prompt, parameters). On its own, it's a
        solo candidate.
      </li>
      <li>
        <code>sf.Fanout(...) &gt;&gt; sf.Synthesize(...)</code>: a fusion.
        <code>sf.Fanout</code> sends the question to several members.
        <code>sf.Synthesize</code> adds an explicit <strong>synthesizer</strong>. Here, the
        synthesizer is another model that combines the members' answers into one.
      </li>
    </ul>

    <div class="not-prose">
      <NbCell :count="3" :code="compose" />
    </div>

    <p>
      <code>frontier_trio</code> fuses the three frontier models. Its score next to each solo model
      shows whether adding models helps on this case.
    </p>

    <h3>The request cache</h3>

    <p>
      With the cache on, a model call that was made before is served from the cache instead of being
      paid for again. Calls are matched by route, prompt and parameters, not by model object, so
      <strong>an identical call is served from the cache</strong>. Cache entries do not expire.
    </p>

    <p>
      A local engine starts with the cache on and empty.
      <code>evaluate(..., use_cache=False)</code> opts one run out, and
      <code>export AIGW_REQUEST_CACHE_ENABLED=false</code> before
      <code>screamingface up</code> turns it off. <code>sf.cache.pull_from_remote()</code> copies
      the community cache into a local engine. On the hosted engine the cache is shared across the
      community: if anyone has already run that model config against a benchmark, you get a cache
      hit at no cost.
    </p>

    <h2>4 · Look up the benchmark</h2>

    <p>
      Benchmarks live on the engine, not in the Client. Fetching one returns its identity and the
      protocol revision it is pinned to, so you can see what you are about to be graded against
      before spending anything. This call is free. It needs an engine that serves the benchmark: the
      hosted engine serves <code>draco-3pass</code>, and a local engine started with
      <code>screamingface up</code> comes with <code>medxpert</code> ready to run. To run more
      benchmarks on a local engine from a repository checkout, run
      <code>just local-stack-notebooks</code> from
      <code>packages/screamingface/</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="load" />
    </div>

    <p>On a local engine, look up <code>medxpert</code>:</p>

    <div class="not-prose">
      <NbCell :count="5" :code="loadLocal"><NbTextOut :text="loadLocalOut" /></NbCell>
    </div>

    <p>
      It does <strong>not</strong> download the actual questions. Cases are loaded engine-side at
      eval time.
    </p>

    <p>
      <code>sf.benchmarks.list()</code> shows what this engine has. The hosted engine lists
      <code>draco</code> and <code>draco-3pass</code> among its benchmarks. On a local engine,
      <code>medxpert</code> is ready by default, so on a local engine run this tutorial on
      <code>medxpert</code>.
    </p>

    <p>
      <code>draco-3pass</code> runs the same 100-case dataset and rubric as the canonical
      <code>draco</code> board, judging each answer three times instead of five. Passing
      <code>limit=1</code> pins this tutorial to a single case. The <code>medxpert</code> run below
      cost $0.717229 for the four candidates.
    </p>

    <h2>5 · Evaluate</h2>

    <p>
      One call sends all four candidates as a <strong>single request</strong>. The benchmark id is
      passed here rather than to the lookup above, because the lookup was only for reading the
      protocol.
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="evaluate" />
    </div>

    <p>
      On a local engine started with <code>screamingface up</code>, use <code>medxpert</code>, which
      is ready by default:
    </p>

    <div class="not-prose">
      <NbCell :count="7" :code="evaluateLocal" />
    </div>

    <p>
      Before the first model call, the Client checks the whole plan: that the benchmark agrees with
      what the engine has, that every model route exists in the catalog, and that each candidate
      compiles. Anything wrong with the plan raises <code>PlanningError</code>, which names the
      specific problem in its message; a provider that is not connected raises
      <code>ProviderConnectionError</code> instead. All of this happens before anything is spent.
    </p>

    <blockquote>
      <strong>This step costs money.</strong> Each candidate answers the case once. On DRACO a judge
      model then grades each answer three or five times; <code>medxpert</code> has no judge. Read
      <code>report.usage.cost_usd</code> after a run before you scale it up.
      <code>draco-3pass</code> at all 100 cases, or the five-pass <code>draco</code>, costs far more
      than one case.
    </blockquote>

    <p>
      If a model fails, only the candidates using it are affected, and the rest still score. A
      failure lowers that candidate's coverage instead of counting as zero, so a partial result
      looks partial. <code>evaluate</code> still returns a report, so check it before you read the
      scores:
    </p>

    <CodeBlock :code="checkReport" language="python" />

    <p>
      With the cache on, a repeated call that already succeeded is served from the cache. A call
      whose input changed, such as the second turn of a <code>medxpert</code> case, is paid again.
    </p>

    <h2>6 · Read the study</h2>

    <p>
      The report lists each candidate in the order you declared them, with its score and coverage.
    </p>

    <p>On the local run above, each candidate's score:</p>

    <div class="not-prose">
      <NbCell :count="8" :code="scoresLocal"><NbTextOut :text="scoresLocalOut" /></NbCell>
    </div>

    <h3>What the columns mean</h3>

    <ul>
      <li>
        <strong>Score</strong>: The candidate's benchmark score. On DRACO a case is judged against a
        fixed set of criteria, so values land on a coarse grid instead of anywhere in 0 to 100%. On
        <code>medxpert</code> the score is the fraction of cases answered correctly.
      </li>
      <li>
        <strong>Coverage</strong>: How much of the case set produced a grade. Below 100% means
        something failed, and the score then covers only what completed.
      </li>
    </ul>

    <h3>Reading it in code</h3>

    <ul>
      <li><code>report.candidates["frontier-trio"].score</code>: one candidate's score.</li>
      <li>
        <code>max(report.candidates, key=lambda c: c.score or 0)</code>: the top scorer. Check
        <code>report.ok</code> first, because a failed candidate has a score of
        <code>None</code> and counts as 0 here. There is no <code>best</code> field, because picking
        a winner is a judgement about your own experiment rather than something the report should
        decide.
      </li>
      <li>
        <code>len(report.candidates["frontier-trio"].cases)</code> against
        <code>report.case_count</code>: how many cases produced a result, next to how many ran.
      </li>
      <li>
        <code>report.candidates["frontier-trio"].url4</code>: that candidate's expression. The url4
        belongs to a candidate, not to the report, since each one compiled separately.
      </li>
      <li><code>report.to_dict()</code>: everything above as plain JSON-compatible values.</li>
    </ul>

    <blockquote>
      <strong>Don't over-read a single run.</strong> One case is an integration check, not a
      measurement. Run it twice and the winner may change. Treat the result as a shape worth
      exploring rather than a finding.
    </blockquote>

    <h2>What the full benchmark shows</h2>

    <p>
      The real claim is demonstrated on all 100 DRACO tasks, not this one-case sample. These are
      published figures rather than output from the code above, so your own numbers will differ. The
      live <code>draco-3pass</code> board lists 15 entries, and its top score is 68.69%. Live scores
      are on the
      <a
        href="https://leaderboard.screamingface.ai/benchmark.html?id=draco-3pass"
        target="_blank"
        rel="noopener"
        >leaderboard</a
      >.
    </p>

    <div class="not-prose">
      <CandidateScores
        :candidates="publishedDraco"
        title="Published DRACO result"
        benchmark="draco"
        case-label="100 tasks"
        section-label="Score by candidate"
        :limit="8"
      />
    </div>

    <p>
      The best fusion beat the best solo model by <strong>8.4 points</strong>, and five different
      fusions beat every individual model. Three solo models didn't finish every task (Gemini 3.1
      Pro only completed 47 of 100), so their scores are averages over completed tasks and aren't
      directly comparable. Full chart and method:
      <a
        href="https://andrewtrask.substack.com/p/6-weeks-ago-frontier-ai-labs-lost"
        target="_blank"
        rel="noopener"
        >published results</a
      >.
    </p>
  </DocLayout>
</template>
