<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import Collapsible from '@/components/ui/Collapsible.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbStateCarousel from '@/components/nb/NbStateCarousel.vue'
import ProviderConnections from '@/components/nb/ProviderConnections.vue'
import type { Provider } from '@/components/nb/ProviderConnections.vue'
import EvaluationReport from '@/components/nb/EvaluationReport.vue'
import CandidateScores from '@/components/nb/CandidateScores.vue'
import type { NbCheckItem, NbRowForm, NbStat } from '@/components/nb/types'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

// Every provider the development engine advertises, read from its registry.
const providers: Provider[] = [
  { id: 'codex', name: 'OpenAI Codex', status: 'disconnected' },
  { id: 'gemini', name: 'Google Gemini', status: 'disconnected' },
  { id: 'anthropic', name: 'Anthropic', status: 'disconnected' },
  { id: 'openrouter', name: 'OpenRouter', status: 'disconnected' },
  { id: 'huggingface', name: 'Hugging Face', status: 'disconnected' },
  { id: 'tavily', name: 'Tavily', status: 'disconnected' },
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

// Ten distinct researched model nodes, nine synthesizers, 16 candidate roots.
const runStats: NbStat[] = [
  { label: 'Models', value: '10/10' },
  { label: 'Synthesis', value: '9/9' },
  { label: 'Scoring', value: '16/16' },
  { label: 'Results', value: '16/16' },
]

const runRecent: NbCheckItem[] = [
  { label: 'Finalized best-open-source (1/1 cases scored)' },
  { label: 'Finalized pareto-lean (1/1 cases scored)' },
  { label: 'Finalized pareto-cross (1/1 cases scored)' },
]

// Scores from a draco-3pass run: one case (limit=1), ten criteria, three judge passes.
const studyCandidates = [
  { id: 'claude-fable-5', name: 'claude-fable-5', score: 88.0, casesScored: 1, casesTotal: 1 },
  { id: 'claude-opus-4.8', name: 'claude-opus-4.8', score: 100.0, casesScored: 1, casesTotal: 1 },
  { id: 'gpt-5.5', name: 'gpt-5.5', score: 88.0, casesScored: 1, casesTotal: 1 },
  {
    id: 'gemini-3.1-pro',
    name: 'gemini-3.1-pro-preview',
    score: 78.3,
    casesScored: 1,
    casesTotal: 1,
  },
  {
    id: 'gemini-3-flash',
    name: 'gemini-3-flash-preview',
    score: 88.0,
    casesScored: 1,
    casesTotal: 1,
  },
  { id: 'kimi-k2.5', name: 'kimi-k2.5', score: 75.9, casesScored: 1, casesTotal: 1 },
  { id: 'deepseek-v4-pro', name: 'deepseek-v4-pro', score: 88.0, casesScored: 1, casesTotal: 1 },
  { id: 'fable-plus-gpt', name: 'fable-plus-gpt', score: 88.0, casesScored: 1, casesTotal: 1 },
  { id: 'frontier-trio', name: 'frontier-trio', score: 100.0, casesScored: 1, casesTotal: 1 },
  { id: 'opus-plus-gpt', name: 'opus-plus-gpt', score: 100.0, casesScored: 1, casesTotal: 1 },
  { id: 'opus-self-fusion', name: 'opus-self-fusion', score: 78.3, casesScored: 1, casesTotal: 1 },
  { id: 'budget-trio', name: 'budget-trio', score: 100.0, casesScored: 1, casesTotal: 1 },
  { id: 'beat-runner-up', name: 'beat-runner-up', score: 100.0, casesScored: 1, casesTotal: 1 },
  { id: 'pareto-cross', name: 'pareto-cross', score: 88.0, casesScored: 1, casesTotal: 1 },
  { id: 'pareto-lean', name: 'pareto-lean', score: 75.9, casesScored: 1, casesTotal: 1 },
  { id: 'best-open-source', name: 'best-open-source', score: 75.9, casesScored: 1, casesTotal: 1 },
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

sf.configure(engine_url="http://127.0.0.1:9108")`

const connect = `sf.connect()`

const connectScript = `import os

sf.connect("openrouter", api_key=os.environ["OPENROUTER_API_KEY"])
sf.connections.list()        # the same status the panel shows
sf.disconnect("openrouter")  # remove it again`

const connectOauth = `flow = sf.connect("codex", method="oauth")
flow.authorize_url           # open this in a browser
connection = flow.wait()     # blocks until you authorize, or the flow expires`

const compose = `ANSWER = "Answer this research prompt thoroughly, in prose, with specific evidence."
SYNTHESIS = "Combine the panel's answers into one unified prose answer. Add no new facts."

opus = sf.Model("openrouter/anthropic/claude-opus-4.8", prompt=ANSWER)
gpt = sf.Model("openrouter/openai/gpt-5.5", prompt=ANSWER)
gemini = sf.Model("openrouter/google/gemini-3.1-pro-preview", prompt=ANSWER, params={"temperature": 0, "max_tokens": 8192})

frontier_trio = sf.Fusion(
    [opus, gpt, gemini],
    name="frontier-trio",
    synthesizer=sf.Model(
        "openrouter/anthropic/claude-opus-4.8",
        prompt=SYNTHESIS,
        params={"temperature": 0, "max_tokens": 8192},
    ),
)`

const lineup = `# Seven solo models answer on their own.
solos = [opus, gpt, gemini, fable, gemini_flash, kimi, deepseek]

# Nine Fusions combine them through a synthesizer. Reusing a Model object
# means that answer is computed once and shared, not requested twice.
fusions = [
    fable_plus_gpt,      # two frontier models
    frontier_trio,       # three frontier models
    opus_plus_gpt,
    opus_self_fusion,    # the same model sampled twice at temperature 0.7
    budget_trio,         # three cheaper models
    beat_runner_up,
    pareto_cross,
    pareto_lean,
    best_open_source,
]

candidates = (*solos, *fusions)   # 16 candidate roots, one shared case set`

const load = `draco = sf.benchmarks.get("draco-3pass")
draco.title, draco.revision, draco.case_count`

const evaluate = `report = sf.evaluate(candidates, benchmark="draco-3pass", limit=1)`
</script>

<template>
  <DocLayout
    title="Reproduce DRACO state-of-the-art"
    description="Run a DRACO subset end to end to compare fusions with its solo models."
    :navigation="navigation"
    :version="version"
  >
    <p>
      By the end, you'll have a scored comparison of <strong>16 candidates</strong>: seven solo
      models and nine fusions built from those models, all on one
      <a href="https://arxiv.org/abs/2602.11685" target="_blank" rel="noopener">DRACO</a> case
      (<code>limit=1</code>) with ten criteria and three judge passes each.
    </p>

    <blockquote>
      You'll need the <RouterLink to="/learn/engine">ScreamingFace Engine</RouterLink> running and
      an OpenRouter connection first. See
      <RouterLink to="/sf-client/installation">Installation</RouterLink>. Every model below is an
      OpenRouter route, so one connection covers everything.
    </blockquote>

    <h2>1 · Configure the engine</h2>

    <p>
      The <RouterLink to="/learn/engine"><strong>ScreamingFace Engine</strong></RouterLink> is a
      separate process that holds your provider credentials, keeps the benchmark answer keys, calls
      the models on your behalf, and does the grading. The Client hands all of that work to it, so
      this first step tells the Client where to find the engine.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="configure" />
    </div>

    <p>
      <code>sf.configure()</code> validates and stores the URL without making a network request. The
      example above points at a <strong>local engine</strong> on
      <code>http://127.0.0.1:9108</code> — to run one yourself, install the
      <code>[runtime]</code> extra and start the stack with <code>screamingface up</code>. The
      <RouterLink to="/sf-client/installation">Installation</RouterLink> guide walks through that
      end to end.
    </p>

    <p>
      To use the <strong>hosted ScreamingFace engine</strong> instead, point at its URL rather than
      loopback. Access is currently granted person by person through peer-to-peer approval, so you
      need to be approved before it will answer. Omitting the URL entirely falls back to
      <code>DEFAULT_ENGINE_URL</code>, which is that hosted engine, so naming the one you mean is
      worth doing explicitly.
    </p>

    <p>
      <strong>If the engine isn't reachable</strong>, the first call that needs it will raise
      <code>EngineUnavailableError</code>. You can check a local one beforehand with
      <code>curl http://127.0.0.1:9108/healthz</code>. Remote engines must use HTTPS, because
      provider credentials will not travel over plain HTTP outside loopback.
    </p>

    <h2>2 · Connect a provider</h2>

    <p>
      The engine holds credentials. You need at least one provider connected before you can call a
      model. <code>sf.connect()</code> with no arguments shows a panel of every provider this engine
      supports. The example below connects <strong>OpenRouter</strong> with an API key, walking
      through all six states of the auth flow.
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
              <strong>Note:</strong> Dataset access is separate and <code>HF_TOKEN</code> belongs in
              the engine <code>.env</code> file, not in a provider connection.
            </ProviderConnections>
          </template>
        </NbStateCarousel>
      </NbCell>
    </div>

    <h3>Reading the panel</h3>

    <p>
      Each row shows one provider: its display name, <strong>live status</strong>, and what you can
      do. Status comes fresh from the engine each time (not cached), and will be one of
      <code>NOT CONNECTED</code>, <code>CONNECTING</code>, <code>CONNECTED</code>,
      <code>NEEDS REAUTH</code>, or <code>ERROR</code>. The header shows which engine you're talking
      to, so you won't accidentally send a key to the wrong one.
    </p>

    <blockquote>
      We're using OpenRouter here for simplicity, but you can build fusions with models from any of
      the providers listed above. One caveat:
      <strong>caching is currently available only for OpenRouter and Anthropic</strong>, so runs on
      the other providers aren't reused yet — extending it to the rest is work in progress.
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
      you one per provider (same data the panel shows), and <code>sf.disconnect(...)</code> is safe
      to call even if you've never connected.
    </p>

    <p>
      Providers that use OAuth instead of API keys (Codex and Anthropic) return an
      <code>OAuthFlow</code>, which you finish in a browser:
    </p>

    <CodeBlock :code="connectOauth" language="python" />

    <p>
      The flow expires eventually, so <code>flow.wait()</code> will raise an error instead of
      blocking forever. <code>flow.expired</code> tells you if that's happened, and
      <code>flow.cancel()</code> abandons the attempt. Connection calls won't work over plain HTTP
      unless the engine is on loopback, since remote engines must use HTTPS.
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
        <code>sf.Fusion</code>: several members combined through an explicit
        <strong>synthesizer</strong>. Here, the synthesizer is another model that combines the
        members' answers into one.
      </li>
    </ul>

    <div class="not-prose">
      <NbCell :count="3" :code="compose" />
    </div>

    <h3>Caching keeps reruns cheap</h3>

    <p>
      Every model call gets cached. When a fusion reuses the same model, the response comes from
      cache instead of being paid for again. Runs get cheaper the more candidates share models. The
      cache is also shared across the community: if anyone's already run that model config against a
      benchmark, you get a cache hit at no cost.
    </p>

    <p>
      One thing worth understanding now:
      <strong>reusing a Model object means its answer is computed once and shared</strong> across
      every candidate using it. That makes 16 candidates affordable. A single failing model only
      breaks the candidates that depend on it.
    </p>

    <Collapsible title="The full 16-candidate lineup">
      <CodeBlock :code="lineup" language="python" />
    </Collapsible>

    <p>The lineup explores three patterns, each testing a different hypothesis:</p>

    <ul>
      <li>
        <strong>Pairs and trios of frontier models</strong>: Does adding another strong model help?
      </li>
      <li>
        <strong><code>opus-self-fusion</code></strong
        >: One model fused with a second sample of itself at higher temperature. Does fusion help
        without adding a second model?
      </li>
      <li>
        <strong><code>budget-trio</code></strong
        >: Three cheaper models. Can they hit a frontier model's score at lower cost?
      </li>
    </ul>

    <h2>4 · Look up the benchmark</h2>

    <p>
      Benchmarks live on the engine, not in the Client. Fetching one returns its identity and the
      protocol revision it is pinned to, so you can see what you are about to be graded against
      before spending anything. This call is free.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="load" />
    </div>

    <p>
      It does <strong>not</strong> download the actual questions. Cases are loaded engine-side at
      eval time. A gated dataset reads the <code>HF_TOKEN</code> from the <strong>engine's</strong>
      environment, not the Client's. Set it where the engine runs:
    </p>

    <ul>
      <li>
        <strong>Your own engine:</strong> Put <code>HF_TOKEN=hf_…</code> in the engine's
        <code>.env</code> file, or <code>export</code> it before starting the engine, then restart.
        See <RouterLink to="/sf-client/installation">Installation</RouterLink> for the start
        command.
      </li>
      <li>
        <strong>Hosted engine:</strong> The operator sets the token, so gated datasets only work if
        they've configured one. You can't pass it from the Client.
      </li>
    </ul>

    <p>
      <code>sf.benchmarks.list()</code> shows what this engine has. <code>draco-3pass</code> only
      appears if its judge model is in the gateway catalog, so if it is missing, the engine's
      configuration is the place to look rather than your own code.
    </p>

    <p>
      <code>draco-3pass</code> runs the same 100-case dataset and rubric as the canonical
      <code>draco</code> board, judging each answer three times instead of five. Passing
      <code>limit=1</code> pins this tutorial to a single case, keeping costs low; the
      full 100-case run is a completely different scale of spend.
    </p>

    <h2>5 · Evaluate</h2>

    <p>
      One call sends all 16 candidates as a <strong>single request</strong>. The benchmark id is
      passed here rather than to the lookup above, because the lookup was only for reading the
      protocol.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="evaluate">
        <EvaluationReport
          title="16 candidates"
          benchmark="draco-3pass"
          phase="complete"
          elapsed="4M 51S"
          :done="16"
          :total="16"
          :stats="runStats"
          :recent="runRecent"
          recent-extra="+1 MORE"
          caption="Operation-level progress · model output appears when each call completes"
        />
      </NbCell>
    </div>

    <p>
      Before the first model call, the Client checks the whole plan: that the benchmark agrees with
      what the engine has, that every model route exists in the catalog, that the parameters you set
      are ones those models accept, and that each candidate compiles. Anything wrong with the plan
      raises <code>PlanningError</code>, which names the specific problem in its message; a provider
      that is not connected raises <code>ProviderConnectionError</code> instead. All of this happens
      before anything is spent, so a misconfigured run costs nothing.
    </p>

    <p>
      The panel updates live as the run proceeds. <code>MODELS</code> counts distinct answering
      calls (ten, not sixteen, because shared members are computed once).
      <code>SYNTHESIS</code> counts the nine synthesizers, <code>SCORING</code> the graded
      candidates, and <code>RESULTS</code> the finalized ones. Progress moves on real grader
      results, never timers, so if a counter stalls, work actually stalled.
    </p>

    <blockquote>
      <strong>This step costs money.</strong> Expect ten model answers, nine syntheses, and thirty
      judge passes per graded candidate (ten criteria × three passes), for one case. It's minutes
      and cents rather than hours and dollars, but it's not free. <code>draco-3pass</code> at all
      100 cases — or the five-pass <code>draco</code> — is a completely different scale of spend.
    </blockquote>

    <p>
      If a model fails, only the candidates using it are affected, and the rest still score. A
      failure lowers that candidate's coverage instead of counting as zero, so a partial result
      looks partial. Since every completed call is cached, re-running after a failure is free for
      work that already succeeded, so you only pay for new, uncached calls.
    </p>

    <h2>6 · Read the study</h2>

    <p>
      The report shows each candidate in the order you declared them, with their scores, and marks
      the best one. Nine are shown here; the rest are summarized as <code>+7 MORE</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="6" code="report">
        <CandidateScores
          :candidates="studyCandidates"
          benchmark="draco-3pass"
          case-label="1 case"
          :limit="9"
        />
      </NbCell>
    </div>

    <h3>What the columns mean</h3>

    <ul>
      <li>
        <strong>Score</strong>: The candidate's normalized rubric score. Ten criteria get judged, so
        values land on a coarse grid instead of anywhere in 0–100%.
      </li>
      <li>
        <strong>Coverage</strong>: How much of the case set produced a grade. Below 100% means
        something failed, and the score then covers only what completed.
      </li>
      <li><strong>BEST</strong>: Marks the top scorer. Ties go to the first in declared order.</li>
    </ul>

    <h3>Reading it in code</h3>

    <ul>
      <li><code>report.candidates["frontier-trio"].score</code>: one candidate's score.</li>
      <li>
        <code>max(report.candidates, key=lambda c: c.score or 0)</code>: the top scorer. There is no
        <code>best</code> field, because picking a winner is a judgement about your own experiment
        rather than something the report should decide.
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
      <strong>Don't over-read a single run.</strong> One case judged once is an integration check,
      not a measurement. Run it twice and the winner may change. Treat the result as a shape worth
      exploring rather than a finding.
    </blockquote>

    <h2>What the full benchmark shows</h2>

    <p>
      The real claim is demonstrated on all 100 DRACO tasks, not this one-case sample. These are
      published figures rather than output from the code above, so your own numbers will differ.
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
