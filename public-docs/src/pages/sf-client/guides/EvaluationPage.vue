<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import { SF_ENGINE_URL } from '@/lib/engine'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const run = `import screamingface as sf

haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")
report = sf.evaluate(haiku, benchmark="ifeval", limit=3)
report`
const runOut = `Report(benchmark='ifeval', candidates=['claude-haiku-4.5'], ok=True)`

const score = `c = report.candidates.only
c.name, c.score, report.case_count, report.benchmark`
const scoreOut = `('claude-haiku-4.5', 1.0, 3, BenchmarkInfo(id='ifeval', revision='22ca96fe77b0f7de', case_count=541))`

const metrics = `dict(c.metrics)`
const metricsOut = `{'inst_level_strict_accuracy': 1.0,
 'prompt_level_loose_accuracy': 1.0,
 'inst_level_loose_accuracy': 1.0,
 'pass_rate': 1.0}`

const many = `opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
gpt = sf.Model("openrouter/openai/gpt-5.5")

sf.evaluate(
    [opus, gpt, sf.Fusion([opus, gpt], synthesizer="openrouter/openai/gpt-5.5")],
    benchmark="draco",
    limit=1,
)`

const compare = `base = sf.evaluate(haiku, benchmark="ifeval", limit=3)
corr = sf.evaluate(haiku, benchmark="ifeval/self-corrective", limit=3)

{"canonical":       {"score": base.candidates.only.score, "tokens": base.usage.output_tokens},
 "self-corrective": {"score": corr.candidates.only.score, "tokens": corr.usage.output_tokens,
                     "corrected": corr.candidates.only.metrics["corrected_cases"]}}`
const compareOut = `{'canonical': {'score': 1.0, 'tokens': 1167},
 'self-corrective': {'score': 1.0, 'tokens': 3686, 'corrected': 0.0}}`

const usage = `report.usage`
const usageOut = `Usage(input_tokens=3691, output_tokens=3686, cache_read_tokens=0,
      cache_creation_tokens=0, reasoning_tokens=0, cost_usd=Decimal('0'))`

const watch = `def observe(event: sf.Event) -> None:
    print(event.kind)

sf.evaluate(haiku, benchmark="ifeval", limit=1, on_event=observe, progress=False)`

const clients = `# once, at the top: every later sf.evaluate() call uses it
sf.configure(engine_url="${SF_ENGINE_URL}")

# or hold a client yourself
client = sf.Client(engine_url="${SF_ENGINE_URL}")
report = client.evaluate(haiku, benchmark="ifeval", limit=3)
client.close()`
</script>

<template>
  <DocLayout
    title="Running an evaluation"
    description="Evaluate one or many candidates against a benchmark and get one Report."
    :navigation="navigation"
    :version="version"
  >
    <p>
      <code>sf.evaluate()</code> is the one call that costs money. You give it candidates and a
      benchmark id. It compiles each candidate against that benchmark's protocol, runs them
      concurrently on <RouterLink to="/learn/engine">the engine</RouterLink>, and returns a single
      <code>Report</code>.
    </p>

    <p>
      Everything expensive happens inside this call, but validation happens first and in full. An
      unknown benchmark, an unreachable route, or a malformed candidate all fail
      <strong>before the first paid request</strong>.
    </p>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        viewBox="0 0 680 200"
        role="img"
        aria-label="Candidates and a benchmark go into the engine, which runs every candidate on every case and grades them behind the trust boundary, returning one report."
        style="width: 100%; height: auto; font-family: var(--f-mono); font-size: 12px"
      >
        <defs>
          <marker
            id="ev-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0 0 L8 4 L0 8 z" style="fill: var(--text-2)" />
          </marker>
        </defs>
        <g
          style="stroke: var(--text-2); stroke-width: 1.25; fill: none"
          marker-end="url(#ev-arrow)"
        >
          <path d="M164 66 C 206 66, 206 100, 246 100" />
          <path d="M164 140 C 206 140, 206 100, 246 100" />
          <path d="M450 100 H534" />
        </g>
        <g style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1">
          <rect x="20" y="42" width="144" height="48" />
          <rect x="20" y="116" width="144" height="48" />
          <rect x="538" y="76" width="124" height="48" />
        </g>
        <rect
          x="250"
          y="62"
          width="200"
          height="76"
          style="fill: none; stroke: var(--accent); stroke-width: 1.5"
        />
        <g text-anchor="middle" style="fill: var(--text)">
          <text x="92" y="62">candidates</text>
          <text x="92" y="136">benchmark</text>
          <text x="350" y="96">engine</text>
          <text x="600" y="96">report</text>
        </g>
        <g text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          <text x="92" y="78">models &amp; fusions</text>
          <text x="92" y="152">cases + rubric</text>
          <text x="350" y="114">run + grade</text>
          <text x="350" y="158">answer keys + grading stay here</text>
          <text x="600" y="112">score per candidate</text>
        </g>
      </svg>
      <figcaption
        style="
          font-family: var(--f-mono);
          font-size: var(--text-label);
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: var(--text-2);
          margin-top: var(--space-3);
        "
      >
        One call runs every candidate on the same cases, grades them behind the trust boundary, and
        returns one report.
      </figcaption>
    </figure>

    <h2>What you can do</h2>

    <ul>
      <li>Evaluate one candidate, or run several at once.</li>
      <li>Cap the number of cases with <code>limit</code>.</li>
      <li>Pick a protocol variant by naming its own benchmark id.</li>
      <li>Watch the run live, or turn off the progress display.</li>
      <li>Use an explicit Client, sync or with <code>await</code>.</li>
    </ul>

    <h2>Main APIs</h2>

    <table>
      <thead>
        <tr>
          <th>API</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <code
              >sf.evaluate(candidates, *, benchmark, limit=None, on_event=None, progress=None)</code
            >
          </td>
          <td>
            Runs one or more candidates against a benchmark's protocol concurrently, returning a
            single <code>sf.Report</code>. Validates everything before the first paid request.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.Client.evaluate(...)</code> · <code>await sf.AsyncClient.evaluate(...)</code>
          </td>
          <td>
            Same call on an explicit Client you manage yourself, sync or with <code>await</code>.
            Only way to talk to two engines from one process.
          </td>
        </tr>
        <tr>
          <td><code>sf.configure(engine_url=…)</code></td>
          <td>
            Repoints the shared Client so every later <code>sf.evaluate()</code> call uses that
            engine.
          </td>
        </tr>
        <tr>
          <td><code>sf.close()</code></td>
          <td>Releases the shared Client.</td>
        </tr>
      </tbody>
    </table>

    <h2>How to</h2>

    <h3>1 · Evaluate one candidate</h3>

    <p>
      The benchmark id is <strong>required</strong>, with no default and no implicit choice.
      <code>limit</code> caps the case count and is your main cost control.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="run"><NbTextOut :text="runOut" /></NbCell>
    </div>

    <p>
      The repr is a summary: which benchmark, which candidates, whether anything failed.
      <code>ok</code> is <code>True</code> only when no candidate and no member had a failure.
    </p>

    <h3>2 · Read the score</h3>

    <p>
      Scores live on candidates rather than on the report, since a report can hold several. With one
      candidate, <code>.only</code> gets you right to it.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="score"><NbTextOut :text="scoreOut" /></NbCell>
    </div>

    <p>
      Notice the two case counts: <code>report.case_count</code> is how many cases <em>ran</em>;
      <code>report.benchmark.case_count</code> is how many the benchmark has. Running 3 of 541 is a
      smoke test, and the report keeps both numbers visible so that stays obvious later.
    </p>

    <p>
      <code>score</code> is always higher-is-better, and can be <code>None</code> if a candidate
      failed. Benchmark-specific diagnostics live under <code>metrics</code>:
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="metrics"><NbTextOut :text="metricsOut" /></NbCell>
    </div>

    <p>
      Read <code>coverage</code> beside the score. It is the fraction of the selected cases the
      score was computed from, and anything below <code>1.0</code> means the engine graded only part
      of the run and the score describes that part. A candidate can also finish with both a score
      and entries in <code>failures</code>, which is a completed run carrying warnings worth reading
      rather than a broken one.
    </p>

    <h3>3 · Evaluate several at once</h3>

    <p>
      Pass a list. Every candidate runs against the same pinned exam in the same call. That's what
      makes the comparison fair. It's the only way to compare, because a report has no "baseline" or
      "gain" field. You put the solo model and the fusion in one run and read both scores.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="many" />
    </div>

    <p>
      Results come back in declared order. Mind the cost here: this is DRACO, where every criterion
      is graded by five judge passes, so even <code>limit=1</code> is a real spend.
    </p>

    <h3>4 · Compare two protocols</h3>

    <p>
      Because each protocol variant is a separate benchmark id, comparing them is two runs. This is
      IFEval's canonical single-pass protocol against its self-corrective retry chain on the same
      three cases:
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="compare"><NbTextOut :text="compareOut" /></NbCell>
    </div>

    <p>
      An honest result: identical scores, <strong>3.2× the output tokens</strong>. On this slice the
      retry loop bought nothing. <code>corrected_cases</code>, a metric only the corrective variants
      report, is <code>0.0</code>, meaning no case failed first and passed later. That is what a
      three-case sample of a capable model looks like, and it is the reason to run more cases before
      concluding anything.
    </p>

    <h3>5 · Read what it cost</h3>

    <div class="not-prose">
      <NbCell :count="6" :code="usage"><NbTextOut :text="usageOut" /></NbCell>
    </div>

    <p>
      <code>cost_usd</code> is <code>Decimal('0')</code> here because this engine has no pricing
      data: a zero means "not reported", not "free". Token counts are the reliable measure. Any
      field is <code>None</code> if even one candidate run failed to report it, rather than being
      silently summed as a partial total.
    </p>

    <h3>6 · Watch a run</h3>

    <p>
      <code>on_event</code> receives typed events in sequence as the run executes, and
      <code>progress=False</code> silences the default display. If your callback raises, the Client
      cancels every active run and re-raises your exception.
    </p>

    <div class="not-prose">
      <NbCell :count="7" :code="watch" />
    </div>

    <h3>7 · Point at the engine</h3>

    <p>
      <code>sf.evaluate()</code> never asks where the engine is. Left unconfigured it falls back to
      <code>DEFAULT_ENGINE_URL</code>, a hosted engine, which is not what you want when the engine
      you mean is your own, so name it once with <code>sf.configure()</code> and every later call
      uses it.
    </p>

    <p>
      Holding your own <code>sf.Client</code> is the alternative, and the only way to address two
      engines from one process. <code>sf.AsyncClient</code> has the same interface with
      <code>await</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="8" :code="clients" />
    </div>

    <h2>When it fails</h2>

    <p>
      <code>PlanningError</code> means the run never started: change the candidate, benchmark or
      configuration. <code>ExecutionError</code> means it reached the engine and ended without a
      valid report. <code>EngineUnavailableError</code> means the engine was not reachable at all.
      Each carries a stable <code>code</code> and a <code>hint</code>.
    </p>

    <h2>Links</h2>

    <ul>
      <li>
        <a
          href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/05_draco_lite_e2e.ipynb"
          target="_blank"
          rel="noopener"
          >Companion notebook: <code>05_draco_lite_e2e.ipynb</code></a
        >
      </li>
    </ul>
  </DocLayout>
</template>
