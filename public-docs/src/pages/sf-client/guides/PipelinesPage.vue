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

const basic = `import screamingface as sf

draft = sf.Model("openrouter/openai/gpt-5.5")
review = sf.Model("openrouter/anthropic/claude-opus-4.8")

chain = sf.Pipeline([draft, review], name="review-chain")
chain`
const basicOut = `Pipeline(['gpt-5.5', 'claude-opus-4.8'], name='review-chain')`

const then = `final = sf.Model("openrouter/openai/gpt-5.5", name="polish")

draft.then(review).then(final)`
const thenOut = `Pipeline(['gpt-5.5', 'claude-opus-4.8', 'polish'])`

const flatten = `constructed = sf.Pipeline([draft, sf.Pipeline([review, final])])

[stage.name for stage in constructed.stages]`
const flattenOut = `['gpt-5.5', 'claude-opus-4.8', 'polish']`

const nestNamed = `named = sf.Pipeline([review, final], name="polish-pass")

[stage.name for stage in draft.then(named).stages]`
const nestNamedOut = `['gpt-5.5', 'polish-pass']`

const recursive = `judge = sf.Model("openrouter/anthropic/claude-opus-4.8", name="judge")
writer = sf.Model("openrouter/openai/gpt-5.5", name="writer")

sf.Fusion(
    [draft.then(review), sf.Model("openrouter/google/gemini-3.1-pro-preview")],
    synthesizer=sf.Pipeline([judge, writer]),
)`
const recursiveOut = `Fusion(['gpt-5.5->claude-opus-4.8', 'gemini-3.1-pro-preview'], synthesizer=Pipeline(['judge', 'writer']))`

const mixed = `panel = sf.Fusion([draft, review], synthesizer=final)
refine = sf.Pipeline([review, final], name="refine")

sf.Pipeline([draft, panel, refine], name="mixed")`
const mixedOut = `Pipeline(['gpt-5.5', 'gpt-5.5+claude-opus-4.8', 'refine'], name='mixed')`

const pipelineSig = `sf.Pipeline(
    stages: Sequence[str | Recipe],
    *,
    name: str | None = None,
)`
</script>

<template>
  <DocLayout
    title="Pipelines"
    description="Chain recipes in series, so each stage refines the previous stage's answer."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <strong>Pipeline</strong> is a recipe composed of an ordered list of
      <strong>stages</strong>. It doesn't run anything by itself; like every recipe, building one
      makes no requests. The stages run only during an
      <RouterLink to="/sf-client/guides/running-an-evaluation">evaluation</RouterLink>: the first
      stage answers the case, and each later stage takes the <em>previous</em> stage's answer as its
      input (a draft gets reviewed, then polished). The benchmark grades only the last stage's
      answer, so a Pipeline competes head-to-head with a solo
      <RouterLink to="/sf-client/guides/models">Model</RouterLink> or a
      <RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink>.
    </p>

    <p>
      A stage can be any recipe: a <code>Model</code>, a <code>Fusion</code>, or another
      <code>Pipeline</code>. Refine, review, or re-rank as many times as your experiment needs. Like
      all recipes, a Pipeline is immutable. Building one makes no requests.
    </p>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        class="dg"
        viewBox="0 0 906 120"
        role="img"
        aria-label="A Pipeline runs its stages in series: the first stage answers the case, each later stage takes the previous stage's answer as its input, and grading the last stage's answer produces the graded answer."
      >
        <defs>
          <marker
            id="pl-arrow"
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
        <g class="edge" marker-end="url(#pl-arrow)">
          <path d="M192 80 H240" />
          <path d="M406 80 H454" />
          <path d="M644 80 H734" />
        </g>
        <rect class="frame" x="16" y="34" width="628" height="80" />
        <text x="24" y="50" class="sub">Pipeline</text>
        <text x="216" y="66" text-anchor="middle" class="sub">stage</text>
        <text x="430" y="66" text-anchor="middle" class="sub">stage</text>
        <text x="689" y="66" text-anchor="middle" class="sub">grading</text>
        <rect class="box stage" x="32" y="60" width="160" height="40" />
        <rect class="box stage" x="246" y="60" width="160" height="40" />
        <rect class="box synth" x="460" y="60" width="168" height="40" />
        <rect class="box graded" x="744" y="60" width="150" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="112" y="84">first stage</text>
          <text x="326" y="84">next stage</text>
          <text x="544" y="84">last stage</text>
          <text x="819" y="84">Graded answer</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        The flow of information: the first stage answers the case, each later stage takes the
        previous stage's answer as its input, and grading the last stage's answer produces the
        graded answer.
      </figcaption>
    </figure>

    <div class="dgkey not-prose">
      <span><i class="stage"></i>Stage / member</span>
      <span><i class="synth"></i>Final stage (synthesizer)</span>
      <span><i class="graded"></i>Graded answer</span>
      <span><i class="pl"></i>Pipeline (dashed = unnamed, flattens)</span>
    </div>

    <h2>What you can do</h2>

    <ul>
      <li>Chain two or more recipes so each stage refines the previous answer.</li>
      <li>Build the same chain with <code>.then()</code> for a fluent API.</li>
      <li>Nest a Pipeline inside a Fusion, or vice versa.</li>
      <li>Read back the ordered stages and see the resolved name.</li>
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
          <td><code>sf.Pipeline(stages, *, name=None)</code></td>
          <td>
            Runs stages one after another. Each stage gets the previous stage's answer, and the last
            stage's answer is what the benchmark grades.
          </td>
        </tr>
        <tr>
          <td><code>recipe.then(next)</code></td>
          <td>
            Builder method on every recipe: appends a stage and returns a new Pipeline.
            <code>a.then(b).then(c)</code> reads left to right.
          </td>
        </tr>
        <tr>
          <td><code>.name</code> · <code>.stages</code></td>
          <td>Read back the resolved name and the ordered stages (as a tuple).</td>
        </tr>
        <tr>
          <td><code>sf.Recipe</code></td>
          <td>The shared base type of every candidate kind.</td>
        </tr>
      </tbody>
    </table>

    <h2>How to</h2>

    <h3>1 · Chain two recipes</h3>

    <p>
      Stages come first (positional), in the order they run. The Pipeline's name defaults to stage
      names joined with <code>-&gt;</code>. Give it an explicit <code>name</code> for a custom label
      in reports.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="basic"><NbTextOut :text="basicOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 654 120"
        role="img"
        aria-label="The review-chain Pipeline holds draft then review; grading review's answer produces the graded answer."
      >
        <defs>
          <marker
            id="pl-a1"
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
        <g class="edge" marker-end="url(#pl-a1)">
          <path d="M162 80 H240" />
          <path d="M392 80 H482" />
        </g>
        <rect class="frame" x="16" y="34" width="376" height="80" />
        <text x="24" y="50" class="sub">review-chain</text>
        <text x="204" y="66" text-anchor="middle" class="sub">stage</text>
        <text x="437" y="66" text-anchor="middle" class="sub">grading</text>
        <rect class="box stage" x="32" y="60" width="130" height="40" />
        <rect class="box synth" x="246" y="60" width="130" height="40" />
        <rect class="box graded" x="492" y="60" width="150" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="97" y="84">draft</text>
          <text x="311" y="84">review</text>
          <text x="567" y="84">Graded answer</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        The review-chain Pipeline holds draft then review; grading review's answer is the graded
        answer.
      </figcaption>
    </figure>

    <h3>2 · Build the same chain with <code>.then()</code></h3>

    <p>
      <code>.then()</code> is on every recipe. It appends a stage so chains read left to right.
      Builds the same canonical Pipeline as passing stages to the constructor.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="then"><NbTextOut :text="thenOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 868 120"
        role="img"
        aria-label="One Pipeline of draft, review and final; grading final's answer produces the graded answer."
      >
        <defs>
          <marker
            id="pl-a2"
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
        <g class="edge" marker-end="url(#pl-a2)">
          <path d="M162 80 H240" />
          <path d="M376 80 H454" />
          <path d="M606 80 H696" />
        </g>
        <rect class="frame" x="16" y="34" width="590" height="80" />
        <text x="24" y="50" class="sub">Pipeline</text>
        <text x="204" y="66" text-anchor="middle" class="sub">stage</text>
        <text x="418" y="66" text-anchor="middle" class="sub">stage</text>
        <text x="651" y="66" text-anchor="middle" class="sub">grading</text>
        <rect class="box stage" x="32" y="60" width="130" height="40" />
        <rect class="box stage" x="246" y="60" width="130" height="40" />
        <rect class="box synth" x="460" y="60" width="130" height="40" />
        <rect class="box graded" x="706" y="60" width="150" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="97" y="84">draft</text>
          <text x="311" y="84">review</text>
          <text x="525" y="84">final</text>
          <text x="781" y="84">Graded answer</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        <code>.then()</code> builds one Pipeline of three stages; only the last stage's answer is
        graded.
      </figcaption>
    </figure>

    <h3>3 · Flatten vs. nest</h3>

    <p>
      An <em>unnamed</em> Pipeline inside another Pipeline flattens into one sequence. Nesting for
      convenience never changes what runs.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="flatten"><NbTextOut :text="flattenOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 938 164"
        role="img"
        aria-label="The unnamed inner Pipeline (dashed) flattens into the outer Pipeline; grading the last stage's answer produces the graded answer."
      >
        <defs>
          <marker
            id="pl-a3"
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
        <g class="edge" marker-end="url(#pl-a3)">
          <path d="M166 106 H278" />
          <path d="M430 106 H508" />
          <path d="M676 106 H766" />
        </g>
        <rect class="frame" x="16" y="40" width="660" height="108" />
        <text x="24" y="56" class="sub">Pipeline</text>
        <rect class="frame" x="284" y="58" width="376" height="80" style="stroke-dasharray: 4 4" />
        <text x="292" y="74" class="sub">Pipeline (unnamed)</text>
        <text x="222" y="94" text-anchor="middle" class="sub">stage</text>
        <text x="721" y="94" text-anchor="middle" class="sub">grading</text>
        <rect class="box stage" x="36" y="86" width="130" height="40" />
        <rect class="box stage" x="300" y="86" width="130" height="40" />
        <rect class="box synth" x="514" y="86" width="130" height="40" />
        <rect class="box graded" x="776" y="86" width="150" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="101" y="110">draft</text>
          <text x="365" y="110">review</text>
          <text x="579" y="110">final</text>
          <text x="851" y="110">Graded answer</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        The unnamed inner Pipeline flattens into the outer one — draft → review → final runs as a
        single sequence.
      </figcaption>
    </figure>

    <p>
      Give the inner Pipeline a <code>name</code> and it is kept as a single stage instead, so a
      named chain stays a named, reusable unit.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="nestNamed"><NbTextOut :text="nestNamedOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 938 164"
        role="img"
        aria-label="The named inner Pipeline polish-pass is kept as one stage inside the outer Pipeline; grading its last stage's answer produces the graded answer."
      >
        <defs>
          <marker
            id="pl-a4"
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
        <g class="edge" marker-end="url(#pl-a4)">
          <path d="M166 106 H278" />
          <path d="M430 106 H508" />
          <path d="M676 106 H766" />
        </g>
        <rect class="frame" x="16" y="40" width="660" height="108" />
        <text x="24" y="56" class="sub">Pipeline</text>
        <rect class="frame" x="284" y="58" width="376" height="80" />
        <text x="292" y="74" class="sub">polish-pass (named · one stage)</text>
        <text x="222" y="94" text-anchor="middle" class="sub">stage</text>
        <text x="721" y="94" text-anchor="middle" class="sub">grading</text>
        <rect class="box stage" x="36" y="86" width="130" height="40" />
        <rect class="box stage" x="300" y="86" width="130" height="40" />
        <rect class="box synth" x="514" y="86" width="130" height="40" />
        <rect class="box graded" x="776" y="86" width="150" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="101" y="110">draft</text>
          <text x="365" y="110">review</text>
          <text x="579" y="110">final</text>
          <text x="851" y="110">Graded answer</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        A named inner Pipeline (polish-pass) stays one stage of the outer Pipeline: draft →
        polish-pass, itself review → final.
      </figcaption>
    </figure>

    <h3>4 · Compose recursively</h3>

    <p>
      Because a stage is any recipe and a
      <RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink>'s members and synthesizer are
      any recipe, the two compose freely: a Fusion of Pipelines, a Pipeline of Fusions, or a Fusion
      whose synthesizer is itself a Pipeline.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="recursive"><NbTextOut :text="recursiveOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 994 210"
        role="img"
        aria-label="A Fusion whose members are a draft-to-review Pipeline and gemini, combined by a synthesizer that is itself a judge-to-writer Pipeline; grading the writer's answer produces the graded answer."
      >
        <defs>
          <marker
            id="pl-a5"
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
        <text x="16" y="18" class="sub">Fusion · members</text>
        <g class="edge" marker-end="url(#pl-a5)">
          <path d="M152 70 H230" />
          <path d="M572 114 H600" />
          <path d="M372 64 C412 64 412 108 452 108" />
          <path d="M152 146 C300 146 412 108 452 108" />
          <path d="M732 108 H822" />
        </g>
        <rect class="frame" x="16" y="28" width="356" height="72" />
        <text x="24" y="44" class="sub">Pipeline</text>
        <rect class="frame" x="452" y="72" width="280" height="72" />
        <text x="460" y="88" class="sub">synthesizer · Pipeline</text>
        <text x="777" y="94" text-anchor="middle" class="sub">grading</text>
        <rect class="box stage" x="32" y="52" width="120" height="36" />
        <rect class="box stage" x="236" y="52" width="120" height="36" />
        <rect class="box stage" x="32" y="128" width="120" height="36" />
        <rect class="box stage" x="468" y="96" width="104" height="36" />
        <rect class="box synth" x="604" y="96" width="104" height="36" />
        <rect class="box graded" x="832" y="90" width="150" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="92" y="74">draft</text>
          <text x="296" y="74">review</text>
          <text x="92" y="150">gemini</text>
          <text x="520" y="118">judge</text>
          <text x="656" y="118">writer</text>
          <text x="907" y="114">Graded answer</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        A Fusion of two members, the draft → review Pipeline and gemini, combined by a synthesizer
        that is itself a judge → writer Pipeline; grading the writer's answer is the graded answer.
      </figcaption>
    </figure>

    <h3>5 · Mix recipe types as stages</h3>

    <p>
      Because a stage is just a recipe, one Pipeline can mix a <code>Model</code>, a
      <code>Fusion</code>, and a nested <code>Pipeline</code> as its stages. Each one counts as a
      single stage, and the last stage's answer is still what the benchmark grades.
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="mixed"><NbTextOut :text="mixedOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 860 152"
        role="img"
        aria-label="One Pipeline whose stages are a Model, a Fusion and a nested Pipeline; grading the last stage's answer produces the graded answer."
      >
        <defs>
          <marker
            id="pl-a6"
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
        <g class="edge" marker-end="url(#pl-a6)">
          <path d="M170 82 H240" />
          <path d="M376 82 H446" />
          <path d="M598 82 H688" />
        </g>
        <rect class="frame" x="16" y="34" width="582" height="104" />
        <text x="24" y="50" class="sub">Pipeline · mixed</text>
        <text x="643" y="70" text-anchor="middle" class="sub">grading</text>
        <rect class="box stage" x="40" y="62" width="130" height="40" />
        <rect class="box stage" x="246" y="62" width="130" height="40" />
        <rect class="box synth" x="452" y="62" width="130" height="40" />
        <rect class="box graded" x="698" y="62" width="150" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="105" y="86">draft</text>
          <text x="311" y="86">panel</text>
          <text x="517" y="86">refine</text>
          <text x="773" y="86">Graded answer</text>
        </g>
        <g class="sub" text-anchor="middle">
          <text x="105" y="124">Model</text>
          <text x="311" y="124">Fusion</text>
          <text x="517" y="124">Pipeline</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        A stage is any recipe: here a Model, a Fusion and a nested Pipeline chained in one Pipeline;
        only the last stage's answer is graded.
      </figcaption>
    </figure>

    <h2>The <code>Pipeline</code> class</h2>

    <CodeBlock :code="pipelineSig" language="python" />

    <h3>Parameters</h3>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>stages</code></td>
          <td><code>Sequence[str&nbsp;|&nbsp;Recipe]</code></td>
          <td>
            One or more stages, in order. Each can be a route string or any recipe. An
            <em>unnamed</em> nested <code>Pipeline</code> flattens into the surrounding sequence; a
            <em>named</em> one stays as a single stage.
          </td>
        </tr>
        <tr>
          <td><code>name</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            Defaults to the stage names joined with <code>-&gt;</code>, for example
            <code>gpt-5.5-&gt;claude-opus-4.8</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <h3>Attributes</h3>

    <p>
      <code>stages</code> is a <code>tuple</code> in canonical order. <code>name</code> is the
      resolved label. <code>recipe.then(next)</code>, available on every recipe, appends a stage and
      returns a new <code>Pipeline</code>.
    </p>

    <h3>Raises</h3>

    <table>
      <thead>
        <tr>
          <th>When</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>The stages are empty</td>
          <td><code>ValueError: a Pipeline requires at least one stage</code></td>
        </tr>
        <tr>
          <td><code>stages</code> is not an ordered sequence (for example a bare route string)</td>
          <td>
            <code
              >TypeError: Pipeline stages must be an ordered sequence of model routes or
              Recipes</code
            >
          </td>
        </tr>
        <tr>
          <td><code>.then()</code> is given something other than a route string or recipe</td>
          <td><code>TypeError: Pipeline stage must be …</code></td>
        </tr>
      </tbody>
    </table>

    <h2>Links</h2>

    <ul>
      <li>
        <a
          href="https://github.com/OpenMined/screamingface/blob/main/packages/screamingface/README.md"
          target="_blank"
          rel="noopener"
          >Recipe composition in the package README</a
        >
      </li>
    </ul>
  </DocLayout>
</template>

<style scoped>
/* Composition diagrams: neutral boxes, role encoded by border colour (categorical
   --data-* palette per SFDS), never status colours. Pipelines are marked with a
   labelled frame (dashed = an unnamed pipeline that flattens away). */
.dg {
  width: 100%;
  height: auto;
  font-family: var(--f-mono);
  font-size: 13px;
}
.dg .box {
  fill: var(--surface);
  stroke: var(--border);
  stroke-width: 1.75;
}
.dg .stage {
  stroke: var(--data-azure-500);
}
.dg .synth {
  stroke: var(--data-orange-500);
}
.dg .graded {
  stroke: var(--data-green-500);
}
.dg .lbl {
  fill: var(--text);
  font-weight: 500;
}
.dg .sub {
  fill: var(--text-2);
  font-size: 12px;
}
.dg .edge {
  fill: none;
  stroke: var(--text-2);
  stroke-width: 1.25;
}
.dg .frame {
  fill: none;
  stroke: var(--border-2);
  stroke-width: 1.25;
}

.dgcap {
  font-size: var(--text-sm);
  line-height: 1.55;
  color: var(--text-2);
  margin-top: var(--space-4);
  max-width: 62ch;
}

.dgkey {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3) var(--space-6);
  margin: var(--space-5) 0 var(--space-8);
  font-family: var(--f-mono);
  font-size: var(--text-sm);
  color: var(--text-2);
}
.dgkey span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.dgkey i {
  width: 12px;
  height: 12px;
  border: 2px solid;
  flex: none;
}
.dgkey .stage {
  border-color: var(--data-azure-500);
}
.dgkey .synth {
  border-color: var(--data-orange-500);
}
.dgkey .graded {
  border-color: var(--data-green-500);
}
.dgkey .pl {
  border-color: var(--border-2);
}
</style>
