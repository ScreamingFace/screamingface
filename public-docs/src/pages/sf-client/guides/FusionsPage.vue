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

opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
gpt = sf.Model("openrouter/openai/gpt-5.5")

pair = sf.Fusion([opus, gpt], synthesizer="openrouter/anthropic/claude-opus-4.8")
pair`
const basicOut = `Fusion(['claude-opus-4.8', 'gpt-5.5'], synthesizer=Model('openrouter/anthropic/claude-opus-4.8'))`

const inspect = `pair.name, [m.name for m in pair.members]`
const inspectOut = `('claude-opus-4.8+gpt-5.5', ['claude-opus-4.8', 'gpt-5.5'])`

const synth = `sf.Fusion(
    [opus, gpt],
    name="pair-gpt-synth",
    synthesizer=sf.Model(
        "openrouter/openai/gpt-5.5",
        prompt="Write the final answer from the drafts.",
    ),
)`
const synthOut = `Fusion(['claude-opus-4.8', 'gpt-5.5'], name='pair-gpt-synth', synthesizer=Model('openrouter/openai/gpt-5.5', prompt='Write the final answer from the drafts.'))`

const nested = `haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")

sf.Fusion([pair, haiku], name="nested", synthesizer="openrouter/openai/gpt-5.5")`
const nestedOut = `Fusion(['claude-opus-4.8+gpt-5.5', 'claude-haiku-4.5'], name='nested', synthesizer=Model('openrouter/openai/gpt-5.5'))`

const fusionSig = `sf.Fusion(
    members: Sequence[str | Recipe],
    *,
    name: str | None = None,
    synthesizer: str | Recipe,
)`
</script>

<template>
  <DocLayout
    title="Fusions"
    description="Combine members into one answer through a synthesizer."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <strong>Fusion</strong> sends the same question to all its members, then a
      <strong>synthesizer</strong> reads their answers and produces one final answer. The benchmark
      grades that final answer, so a Fusion competes with a solo
      <RouterLink to="/sf-client/guides/models">Model</RouterLink>.
    </p>

    <p>
      The synthesizer is itself a recipe. Usually a model that reads the candidate answers and picks
      or writes the winner, but it can be a
      <RouterLink to="/sf-client/guides/pipelines">Pipeline</RouterLink> or another Fusion.
      Synthesis composes the same way members do.
    </p>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        viewBox="0 0 680 236"
        role="img"
        aria-label="A fusion sends one question to several members; a synthesizer combines their answers into the single answer the benchmark grades."
        style="width: 100%; height: auto; font-family: var(--f-mono); font-size: 12px"
      >
        <defs>
          <marker
            id="fx-arrow"
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
          marker-end="url(#fx-arrow)"
        >
          <path d="M112 118 H152" />
          <path d="M112 118 C 134 118, 134 44, 156 44" />
          <path d="M112 118 C 134 118, 134 192, 156 192" />
          <path d="M300 44 C 334 44, 334 118, 366 118" />
          <path d="M300 118 H366" />
          <path d="M300 192 C 334 192, 334 118, 366 118" />
          <path d="M520 118 H568" />
        </g>
        <g style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1">
          <rect x="16" y="98" width="96" height="40" />
          <rect x="160" y="22" width="140" height="44" />
          <rect x="160" y="96" width="140" height="44" />
          <rect x="160" y="170" width="140" height="44" />
          <rect x="572" y="96" width="96" height="44" />
        </g>
        <rect
          x="370"
          y="86"
          width="150"
          height="64"
          style="fill: none; stroke: var(--accent); stroke-width: 1.5"
        />
        <g text-anchor="middle" style="fill: var(--text)">
          <text x="64" y="122">question</text>
          <text x="230" y="48">member 1</text>
          <text x="230" y="122">member 2</text>
          <text x="230" y="196">member 3</text>
          <text x="445" y="114">synthesizer</text>
          <text x="620" y="122">answer</text>
        </g>
        <text x="445" y="132" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          a model or any recipe
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
        Members answer the same question; the synthesizer combines them into the one answer the
        benchmark grades.
      </figcaption>
    </figure>

    <p>Like a Model, a Fusion is immutable. Building one makes no requests.</p>

    <h2>What you can do</h2>

    <ul>
      <li>Combine two or more Models into one candidate.</li>
      <li>Pick your synthesizer. Control how a model synthesizer is prompted.</li>
      <li>Nest a Fusion or Pipeline inside another Fusion.</li>
      <li>Read back the members and the resolved name.</li>
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
          <td><code>sf.Fusion(members, *, name=None, synthesizer)</code></td>
          <td>
            Combines members through a synthesizer that reads their answers and produces one final
            answer for the benchmark to grade. Synthesizer is required.
          </td>
        </tr>
        <tr>
          <td><code>synthesizer=</code> (route string or recipe)</td>
          <td>
            Any recipe works: a route string or <code>sf.Model</code> has a model write the final
            answer; an
            <RouterLink to="/sf-client/guides/pipelines"><code>sf.Pipeline</code></RouterLink> or
            nested <code>sf.Fusion</code> lets you do multi-step synthesis.
          </td>
        </tr>
        <tr>
          <td><code>.name</code> · <code>.members</code> · <code>.synthesizer</code></td>
          <td>Read back the resolved shape: members, synthesizer, and name.</td>
        </tr>
        <tr>
          <td><code>sf.Recipe</code></td>
          <td>The shared base type of every candidate kind.</td>
        </tr>
      </tbody>
    </table>

    <h2>How to</h2>

    <h3>1 · Combine two models</h3>

    <p>Members come first (positional). Synthesizer is required (keyword-only).</p>

    <div class="not-prose">
      <NbCell :count="1" :code="basic"><NbTextOut :text="basicOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 620 150"
        role="img"
        aria-label="The pair fusion sends the question to opus and gpt; opus, reused as the synthesizer, writes the graded answer."
      >
        <defs>
          <marker
            id="fg-a1"
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
        <g class="edge" marker-end="url(#fg-a1)">
          <path d="M174 45 C 208 45, 208 75, 250 75" />
          <path d="M174 105 C 208 105, 208 75, 250 75" />
          <path d="M400 75 H448" />
        </g>
        <text x="103" y="18" text-anchor="middle" class="sub">members</text>
        <text x="325" y="49" text-anchor="middle" class="sub">synthesizer</text>
        <rect class="box stage" x="32" y="25" width="142" height="40" />
        <rect class="box stage" x="32" y="85" width="142" height="40" />
        <rect class="box synth" x="250" y="55" width="150" height="40" />
        <rect class="box graded" x="448" y="55" width="160" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="103" y="49">opus</text>
          <text x="103" y="109">gpt</text>
          <text x="325" y="79">opus</text>
          <text x="528" y="79">Graded answer</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        <code>pair</code> asks opus and gpt the same question; opus, reused as the synthesizer,
        writes the one answer the benchmark grades.
      </figcaption>
    </figure>

    <p>
      A Fusion always needs an explicit <code>synthesizer</code> (no default) and at least one
      member. Skip the synthesizer or pass an empty member list and construction fails.
    </p>

    <h3>2 · Read the resolved name</h3>

    <p>
      Without an explicit <code>name</code>, the Fusion's name is its members' names joined with
      <code>+</code>. Reports show that name.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="inspect"><NbTextOut :text="inspectOut" /></NbCell>
    </div>

    <h3>3 · Choose the synthesizer</h3>

    <p>
      The <strong>synthesizer</strong> decides how the members' answers become one. It's itself a
      recipe. Pass a route string or <code>sf.Model</code> to have a model read the drafts and write
      the final answer, or pass an
      <RouterLink to="/sf-client/guides/pipelines"><code>sf.Pipeline</code></RouterLink> or nested
      <code>sf.Fusion</code> for multi-step synthesis. Swapping synthesizers is the main lever: same
      members, different synthesizer, different candidate.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="synth"><NbTextOut :text="synthOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 620 160"
        role="img"
        aria-label="The same two members, opus and gpt, but now gpt with its own prompt is the synthesizer that writes the graded answer."
      >
        <defs>
          <marker
            id="fg-a3"
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
        <g class="edge" marker-end="url(#fg-a3)">
          <path d="M174 45 C 208 45, 208 75, 250 75" />
          <path d="M174 105 C 208 105, 208 75, 250 75" />
          <path d="M400 75 H448" />
        </g>
        <text x="103" y="18" text-anchor="middle" class="sub">members</text>
        <text x="325" y="49" text-anchor="middle" class="sub">synthesizer</text>
        <rect class="box stage" x="32" y="25" width="142" height="40" />
        <rect class="box stage" x="32" y="85" width="142" height="40" />
        <rect class="box synth" x="250" y="55" width="150" height="40" />
        <rect class="box graded" x="448" y="55" width="160" height="40" />
        <g class="lbl" text-anchor="middle">
          <text x="103" y="49">opus</text>
          <text x="103" y="109">gpt</text>
          <text x="325" y="79">gpt</text>
          <text x="528" y="79">Graded answer</text>
        </g>
        <text x="325" y="112" text-anchor="middle" class="sub">its own prompt</text>
      </svg>
      <figcaption class="dgcap">
        Same members, different synthesizer: swap in gpt (with its own prompt) and it is a different
        candidate, though opus and gpt still answer as members.
      </figcaption>
    </figure>

    <p>
      A model synthesizer has its own <code>prompt</code> and <code>params</code>, controlling how
      it writes the final answer, separate from how members answer. Set a different prompt on a
      member by setting it on that Model.
    </p>

    <h3>4 · Nest a fusion</h3>

    <p>
      A member can be a Fusion or Pipeline, so a pair can become a member in a larger fusion. The
      inner recipe shows up under its resolved name.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="nested"><NbTextOut :text="nestedOut" /></NbCell>
    </div>

    <figure class="not-prose" style="margin: var(--space-6) 0">
      <svg
        class="dg"
        viewBox="0 0 720 214"
        role="img"
        aria-label="The nested fusion: the pair fusion (opus and gpt combined by opus) and haiku are the two members; gpt synthesizes their answers into the graded answer."
      >
        <defs>
          <marker
            id="fg-a4"
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
        <rect class="frame" x="16" y="18" width="312" height="120" />
        <text x="26" y="36" class="sub">pair (a fusion)</text>
        <g class="edge" marker-end="url(#fg-a4)">
          <path d="M132 63 C 166 63, 166 86, 200 86" />
          <path d="M132 111 C 166 111, 166 86, 200 86" />
          <path d="M304 86 C 372 86, 372 116, 432 116" />
          <path d="M132 178 C 300 178, 330 116, 432 116" />
          <path d="M552 116 H594" />
        </g>
        <rect class="box stage" x="28" y="48" width="104" height="30" />
        <rect class="box stage" x="28" y="96" width="104" height="30" />
        <rect class="box synth" x="200" y="71" width="104" height="30" />
        <rect class="box stage" x="28" y="163" width="104" height="30" />
        <rect class="box synth" x="432" y="96" width="120" height="40" />
        <rect class="box graded" x="594" y="96" width="112" height="40" />
        <text x="492" y="88" text-anchor="middle" class="sub">synthesizer</text>
        <g class="lbl" text-anchor="middle">
          <text x="80" y="67">opus</text>
          <text x="80" y="115">gpt</text>
          <text x="252" y="90">opus</text>
          <text x="80" y="182">haiku</text>
          <text x="492" y="120">gpt</text>
          <text x="648" y="120">Graded answer</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        The <code>nested</code> fusion has two members, the <code>pair</code> fusion and haiku, and
        gpt synthesizes their answers. The inner pair shows up under its own resolved name.
      </figcaption>
    </figure>

    <p>
      Members must be recipes: a <code>Model</code>, <code>Fusion</code>, or
      <code>Pipeline</code> (or a route string, which gets normalized to a <code>Model</code>).
    </p>

    <h2>The <code>Fusion</code> class</h2>

    <CodeBlock :code="fusionSig" language="python" />

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
          <td><code>members</code></td>
          <td><code>Sequence[str&nbsp;|&nbsp;Recipe]</code></td>
          <td>
            One or more members, in order. Each can be a route string, <code>Model</code>,
            <code>Fusion</code>, or <code>Pipeline</code>. Ensembles nest.
          </td>
        </tr>
        <tr>
          <td><code>name</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            Defaults to the member names joined with <code>+</code>, for example
            <code>claude-opus-4.8+gpt-hot</code>.
          </td>
        </tr>
        <tr>
          <td><code>synthesizer</code></td>
          <td><code>str&nbsp;|&nbsp;Recipe</code></td>
          <td>
            <strong>Required, keyword-only.</strong> A route string or any recipe (a
            <code>Model</code>, <code>Fusion</code>, or <code>Pipeline</code>) that reads the
            members' answers and writes the final one. No default.
          </td>
        </tr>
      </tbody>
    </table>

    <h3>Attributes</h3>

    <p>
      <code>members</code> is a <code>tuple</code> in the order you gave. <code>name</code> is the
      resolved label. <code>synthesizer</code> is the recipe you passed (route strings normalize to
      <code>Model</code>). No <code>reducer</code> attribute.
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
          <td>No <code>synthesizer</code> is given</td>
          <td><code>TypeError: missing a required keyword-only argument: 'synthesizer'</code></td>
        </tr>
        <tr>
          <td>The members are empty</td>
          <td><code>ValueError: a Fusion requires at least one member</code></td>
        </tr>
        <tr>
          <td><code>members</code> is not an ordered sequence (for example a bare route string)</td>
          <td>
            <code
              >TypeError: Fusion members must be an ordered sequence of model routes or
              Recipes</code
            >
          </td>
        </tr>
        <tr>
          <td>A member or the synthesizer is not a route string or a supported recipe</td>
          <td>
            <code>TypeError: … must be a model route or sf.Model, sf.Fusion, or sf.Pipeline</code>
          </td>
        </tr>
      </tbody>
    </table>

    <h2>Links</h2>

    <ul>
      <li>
        <a
          href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb"
          target="_blank"
          rel="noopener"
          >Companion notebook: <code>00_quickstart.ipynb</code></a
        >
      </li>
    </ul>
  </DocLayout>
</template>

<style scoped>
/* Composition diagrams (shared style with the Pipelines guide): neutral boxes,
   role encoded by border colour from the SFDS categorical --data-* palette. */
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
</style>
