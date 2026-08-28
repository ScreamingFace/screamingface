<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const read = `c = report.candidates.only
c.url4          # the exact expression the engine ran

# Or build one from a string somebody handed you.
sf.Url4("(candidate='…compiled url4…')!'$model_0'")`

const remix = `plan = report.candidates["frontier-trio"].url4   # or any url4 string you were given

plan.to_python()    # editable sf.Model / sf.Fusion / sf.Pipeline code, no spend
sf.evaluate(plan)   # or replay it exactly as it ran, benchmark included`

const ops = `c = report.candidates.only
len(c.operations), [o.kind for o in c.operations]`
const opsOut = `(1, ['model'])`

const runId = `c.run_id`
const runIdOut = `'z4DrOL5qGcURcfEVB6evxPDlHyg0T2Cwjso10dJ1p5O4TocWXK5FLcYgdbPcnSnQ'`

const share = `report.to_dict()   # schema: screamingface.report.v1
report.to_json()   # the same, as one string`

const readable = `(member_1:0.0:/openrouter/anthropic/claude-opus-4.8?temperature=0&max_tokens=8192&q=($question)!'You are answering a research-quality prompt. …', recipe_result:0.0:{schema: 'screamingface.recipe-result.v1', members: {member_1: {model: 'openrouter/anthropic/claude-opus-4.8', answer: '$member_1'}}, answer: '$member_1'})!'$recipe_result'`
</script>

<template>
  <DocLayout
    title="Reproduce &amp; share (url4)"
    description="Read the exact plan a run executed, and hand it to someone else."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Every candidate result carries a <RouterLink to="/learn/url4"><code>url4</code></RouterLink>
      string: the complete plan <RouterLink to="/learn/engine">the engine</RouterLink> actually ran —
      your candidate, the benchmark's routes, retry prompts, and protocol revision — written as a
      single line of text you can read, diff, and share.
    </p>

    <p>
      The shape is always <code>(sources)!intent</code>: inputs in parentheses, then what to do with
      them after the <code>!</code>. A source can itself be another url4, so the format is
      recursive, which is how a fusion nests inside a larger expression without special handling.
    </p>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        viewBox="0 0 680 196"
        role="img"
        aria-label="A url4 has the shape (sources)!intent: sources in parentheses, then an intent after the bang. A source can itself be another url4, so expressions nest."
        style="width: 100%; height: auto; font-family: var(--f-mono)"
      >
        <defs>
          <marker
            id="u4-arrow"
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
        <g style="stroke: var(--text-2); stroke-width: 1; fill: none">
          <path d="M44 74 V60 H340 V74" />
          <path d="M392 74 V60 H600 V74" />
        </g>
        <g
          text-anchor="middle"
          style="
            fill: var(--text-2);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
          "
        >
          <text x="192" y="50">the inputs</text>
          <text x="496" y="50">what to do with them</text>
        </g>
        <text x="22" y="116" style="fill: var(--text-2); font-size: 26px">(</text>
        <rect
          x="44"
          y="82"
          width="296"
          height="56"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="192" y="108" text-anchor="middle" style="fill: var(--text); font-size: 14px">
          sources
        </text>
        <text x="192" y="126" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          models · data · nested url4
        </text>
        <text x="346" y="116" style="fill: var(--text-2); font-size: 26px">)</text>
        <text x="371" y="117" style="fill: var(--accent); font-size: 26px; font-weight: 600">!</text>
        <rect
          x="392"
          y="82"
          width="208"
          height="56"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="496" y="108" text-anchor="middle" style="fill: var(--text); font-size: 14px">
          intent
        </text>
        <text x="496" y="126" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          a prompt, or code
        </text>
        <path
          d="M120 138 C 120 172, 150 172, 176 172"
          style="stroke: var(--text-2); stroke-width: 1; fill: none"
          marker-end="url(#u4-arrow)"
        />
        <text x="188" y="176" style="fill: var(--text-2); font-size: 11px">
          a source can be another url4, so expressions nest
        </text>
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
        Every url4 is sources in parentheses, then an intent after the bang.
      </figcaption>
    </figure>

    <p>
      Here is a real one, a single
      <RouterLink to="/sf-client/guides/models">Model</RouterLink> answering one DRACO case (its
      long answer prompt trimmed to <code>…</code>):
    </p>

    <CodeBlock :code="readable" language="text" />

    <p>Read it outside-in:</p>

    <ul>
      <li>
        The outer <code>( … )!'$recipe_result'</code> is the whole run: named sources inside the
        parentheses, and a final intent that returns <code>$recipe_result</code>.
      </li>
      <li>
        <code>member_1</code> is the first source: a call to the model route
        <code>/openrouter/anthropic/claude-opus-4.8</code> with its parameters
        (<code>temperature</code>, <code>max_tokens</code>), the benchmark <code>$question</code>
        bound as <code>q</code>, and its own intent, the answer prompt. The <code>0.0</code> after
        the name is its weight.
      </li>
      <li>
        <code>recipe_result</code> is the second source: a structured value that collects the
        members and names the final answer, here just <code>$member_1</code>.
      </li>
    </ul>

    <p>
      A <RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink> reads the same way, with more
      members (<code>member_2</code>, <code>member_3</code>, …) and a <code>recipe_answer</code>
      step (the synthesizer that reads members and writes the synthesis) before
      <code>recipe_result</code>. Nothing is held back from the line: the routes, the parameters,
      the prompts, and the pinned protocol are all written into it. See
      <RouterLink to="/learn/url4">url4</RouterLink> for the full grammar and protocol.
    </p>

    <p>
      This makes results auditable. A score alone is just a claim. A score with its url4 shows
      exactly what produced it. And since the expression is also an address the engine can resolve,
      that same string reruns the evaluation or calls the fusion like a single model, in whatever
      workflow you use. See <RouterLink to="/learn/url4">url4</RouterLink> for the protocol itself.
    </p>

    <h2>What you can do</h2>

    <ul>
      <li>Read the <code>url4</code> that any candidate in a report actually ran.</li>
      <li>Turn a <code>url4</code> string back into editable code, then rerun or remix it.</li>
      <li>See what actually ran, including defaults you never set.</li>
      <li>Check which benchmark revision the run used.</li>
      <li>Inspect the operation graph a candidate compiled to.</li>
      <li>Serialize a whole report and pass it along.</li>
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
          <td><code>sf.Url4(text)</code></td>
          <td>
            Wrap a url4 string you were given, so a copied expression becomes the same first-class
            value a report hands back.
          </td>
        </tr>
        <tr>
          <td><code>Url4.to_python()</code></td>
          <td>
            Reconstruct editable <code>sf.Model</code> / <code>sf.Fusion</code> /
            <code>sf.Pipeline</code> code from an expression, including the
            <code>sf.evaluate(...)</code> line when the url4 embeds a benchmark. Local and free.
          </td>
        </tr>
        <tr>
          <td><code>CandidateResult.url4</code></td>
          <td>
            The complete expression the engine ran, as a string you can read, diff, and rerun.
          </td>
        </tr>
        <tr>
          <td><code>CandidateResult.operations</code></td>
          <td>
            Same plan as structured data: a DAG of <code>sf.OperationInfo</code> values, each with
            <code>id</code>, <code>kind</code>, <code>label</code>, and <code>depends_on</code>
            edges.
          </td>
        </tr>
        <tr>
          <td><code>CandidateResult.run_id</code></td>
          <td>The engine's identifier for this run.</td>
        </tr>
        <tr>
          <td><code>Report.benchmark.revision</code></td>
          <td>The pinned protocol revision the run used, which appears inside the url4's routes.</td>
        </tr>
        <tr>
          <td><code>Report.to_dict()</code> · <code>Report.to_json()</code></td>
          <td>
            Serialise the whole report, as a dict or one JSON string, carrying schema
            <code>screamingface.report.v1</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <h2>How to</h2>

    <h3>1 · Read a url4</h3>

    <p>
      A url4 comes from a completed run. Each candidate in a report carries the expression that
      actually executed as <code>report.candidates[name].url4</code>. A Recipe on its own does not
      have one yet, because the benchmark's routes and pinned revision are only linked in at
      evaluation time. If somebody sends you an expression as plain text, wrap it in
      <code>sf.Url4()</code> to get the same object back.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="read" />
    </div>

    <p>
      What you get back is the full expression in the shape annotated above: the routes, the
      parameters, the answer prompt, and the pinned benchmark revision. Even a small run can produce
      a few thousand characters, because everything the SDK filled in on your behalf is written out
      explicitly, but all of it is meant to be read.
    </p>

    <h3>2 · Turn a url4 back into code</h3>

    <p>
      Because a <code>url4</code> is a complete plan, it converts back into the recipe that produced
      it. <code>to_python()</code> reconstructs the <code>sf.Model</code>, <code>sf.Fusion</code>,
      and <code>sf.Pipeline</code> calls, nested as they originally were, so you can edit one part
      and run the result as your own next attempt. It costs nothing, since it is a local
      transformation rather than a run. Passing the expression to
      <code>sf.evaluate()</code> instead replays it as it stands, which does spend.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="remix" />
    </div>

    <h3>3 · Inspect the operation graph</h3>

    <p>
      <code>operations</code> is the same plan as structured data: a directed acyclic graph of
      <code>OperationInfo</code> values, each with an <code>id</code>, a <code>kind</code>, a
      <code>label</code> and its <code>depends_on</code> edges.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="ops"><NbTextOut :text="opsOut" /></NbCell>
    </div>

    <p>
      A solo model is one operation. A
      <RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink>
      contributes one per member plus the synthesis step, so this is where you read a fusion's shape
      rather than inferring it from its name.
    </p>

    <h3>4 · Identify the run</h3>

    <div class="not-prose">
      <NbCell :count="4" :code="runId"><NbTextOut :text="runIdOut" /></NbCell>
    </div>

    <h3>5 · Share the whole report</h3>

    <div class="not-prose">
      <NbCell :count="5" :code="share" />
    </div>

    <p>
      The dict carries a <code>schema</code> field, <code>screamingface.report.v1</code>, so a
      consumer can tell what shape it is reading. Every candidate's <code>url4</code>, scores,
      metrics, usage and the pinned benchmark revision travel with it.
    </p>

    <h2>What "reproduce" means here</h2>

    <p>
      A url4 pins the run's <strong>definition</strong>. Replay it against the hosted ScreamingFace
      engine and you get a <strong>cache hit</strong>: the engine already ran that exact expression,
      so it returns the identical score at <strong>$0</strong> rather than paying to run it again.
    </p>

    <p>
      Bypass the cache and it genuinely reruns, asking the same models the same questions under the
      same protocol. Models are not deterministic, so a fresh run can diverge slightly. A cached
      replay reproduces the number exactly; a bypassed rerun reproduces the experiment, and the
      score may move a little.
    </p>

    <h2>Links</h2>

    <ul>
      <li>
        <a
          href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/07_ifeval_e2e.ipynb"
          target="_blank"
          rel="noopener"
          >Companion notebook: <code>07_ifeval_e2e.ipynb</code></a
        >, which prints a full expression
      </li>
    </ul>
  </DocLayout>
</template>
