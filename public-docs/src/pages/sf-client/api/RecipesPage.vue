<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const equality = `a = sf.Model("openrouter/deepseek/deepseek-v4-pro")
b = sf.Model("openrouter/deepseek/deepseek-v4-pro")

a == b`
const equalityOut = `True`

const correctiveSig = `sf.CorrectiveLoop(
    members: Sequence[str | Recipe],
    *,
    judge: str | Recipe,
    max_rounds: int = 3,
    name: str | None = None,
)`

const selfCorrectiveSig = `sf.SelfCorrective(
    model: str | Recipe,
    *,
    max_rounds: int = 3,
    name: str | None = None,
)`

const correctiveExample = `loop = sf.CorrectiveLoop(
    ["openrouter/deepseek/deepseek-v4-pro", "openrouter/qwen/qwen3.8-2.4t-a95b", "openrouter/z-ai/glm-5.2"],
    judge="openrouter/moonshotai/kimi-k3",
    max_rounds=3,
)
report = sf.evaluate(loop, benchmark="ifeval", limit=1)`
</script>

<template>
  <DocLayout
    title="Recipes"
    description="The abstract Recipe base every candidate shares, where each concrete type is documented, and the corrective loops that draft under a benchmark's check."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A recipe tells ScreamingFace how to produce one answer — that's what a benchmark grades. This
      page documents <code>Recipe</code>, the abstract base every candidate shares. The three
      concrete types each have their own home: a single model route in
      <RouterLink to="/sf-client/api/models">Models</RouterLink>, several members combined by a
      synthesizer (<code>sf.Fanout(...) &gt;&gt; sf.Synthesize(...)</code>) in the
      <RouterLink to="/sf-client/guides/fusions">Fusions guide</RouterLink>, and
      stages chained in series in the
      <RouterLink to="/sf-client/guides/pipelines">Pipelines guide</RouterLink>.
    </p>

    <p>
      Every constructible recipe is frozen and holds no client. Building one makes no network
      requests, so you can compose them before connecting to anything. Recipes nest: a fusion or a
      <code>Pipeline</code> can contain a <code>Model</code>, another fusion, or another
      <code>Pipeline</code>, in any combination.
    </p>

    <Note>
      Recipes compare by value. Two recipes built with identical arguments are equal, and
      <RouterLink to="/learn/engine">the engine</RouterLink> treats them as one candidate. Give a
      <code>Model</code> an explicit <code>name</code> for an independent sample. Recipes are
      unhashable: you can't use them as dict keys or put them in sets.
    </Note>

    <div class="not-prose">
      <NbCell :count="1" :code="equality"><NbTextOut :text="equalityOut" /></NbCell>
    </div>

    <h2>Recipe</h2>

    <p>
      <code>Recipe</code> is the abstract base the concrete types inherit from. You can't
      instantiate it directly. It exists for type annotations and so a <code>Fanout</code> or a
      <code>Pipeline</code> can hold a mixed list of members.
    </p>

    <p>
      Every recipe has one public attribute: <code>name</code> (a <code>str</code>).
      <code>a &gt;&gt; b</code> joins two recipes and returns a
      <RouterLink to="/sf-client/guides/pipelines">Pipeline</RouterLink>. A corrective loop is a
      whole candidate: it cannot be a stage.
    </p>

    <p>Calling <code>sf.Recipe()</code> directly raises:</p>

    <CodeBlock
      code="TypeError: Can't instantiate abstract class Recipe without an implementation for abstract method '_recipe_marker'"
      language="text"
    />

    <h2>Where each type is documented</h2>

    <ul>
      <li>
        <strong><RouterLink to="/sf-client/api/models">Model</RouterLink></strong
        >: a single model route. Its constructor, parameters, attributes, and errors live on the
        Models page.
      </li>
      <li>
        <strong><RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink></strong
        >: members combined by a synthesizer, built with <code>sf.Fanout</code> and
        <code>sf.Synthesize</code>. The Fusions guide carries its full reference.
      </li>
      <li>
        <strong><RouterLink to="/sf-client/guides/pipelines">Pipeline</RouterLink></strong
        >: stages chained in series. The Pipelines guide carries its full reference.
      </li>
    </ul>

    <h2>Corrective loops</h2>

    <p>
      Two further recipes, documented here, draft under the benchmark's own check and retry until a
      draft passes. Members draft in parallel; the benchmark marks each draft; the first passing
      draft is submitted word for word. A round where nothing passes buys one judge coaching call
      and a retry, up to <code>max_rounds</code> — a cost cap, not a target. The whole loop compiles
      into one candidate expression on the client, so it runs on any benchmark that advertises a
      check.
    </p>

    <p>
      The two corrective recipes are the bottom row of a small grid: the same models, run with or
      without a correction loop.
    </p>

    <table>
      <thead>
        <tr>
          <th></th>
          <th>Solo</th>
          <th>Panel</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>No loop</strong></td>
          <td><code>Model</code></td>
          <td><code>Fanout &gt;&gt; Synthesize</code></td>
        </tr>
        <tr>
          <td><strong>Corrective</strong></td>
          <td><code>SelfCorrective</code></td>
          <td><code>CorrectiveLoop</code></td>
        </tr>
      </tbody>
    </table>

    <Note>
      What a correction round costs depends on the benchmark's check surface. A deterministic
      verifier such as <code>ifeval</code> checks every draft for free, so only the correction
      rounds add model spend. A rubric-graded benchmark such as <code>healthbench-worst30</code> or
      <code>draco</code> spends a judge call per draft on every round, first-round pass included,
      and <code>max_rounds</code> caps that.
    </Note>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        viewBox="0 0 720 170"
        role="img"
        aria-label="Members draft in parallel; the benchmark check marks each draft; the first passing draft is submitted verbatim. A round where nothing passes returns to the members through a judge coaching call, retried up to max_rounds."
        style="width: 100%; height: auto; font-family: var(--f-mono)"
      >
        <defs>
          <marker
            id="cl-arrow"
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

        <rect
          x="24"
          y="34"
          width="150"
          height="54"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="99" y="58" text-anchor="middle" style="fill: var(--text); font-size: 13px">
          members
        </text>
        <text x="99" y="76" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          draft in parallel
        </text>

        <rect
          x="270"
          y="34"
          width="170"
          height="54"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="355" y="58" text-anchor="middle" style="fill: var(--text); font-size: 13px">
          benchmark check
        </text>
        <text x="355" y="76" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          marks each draft
        </text>

        <rect
          x="548"
          y="34"
          width="150"
          height="54"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="623" y="58" text-anchor="middle" style="fill: var(--text); font-size: 13px">
          passing draft
        </text>
        <text x="623" y="76" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          submitted verbatim
        </text>

        <g style="stroke: var(--text-2); stroke-width: 1; fill: none">
          <path d="M174 61 H270" marker-end="url(#cl-arrow)" />
          <path d="M440 61 H548" marker-end="url(#cl-arrow)" />
          <path d="M355 88 V132 H99 V88" marker-end="url(#cl-arrow)" />
        </g>
        <text x="222" y="53" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          drafts
        </text>
        <text x="494" y="53" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          first pass
        </text>
        <text x="227" y="150" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          no pass — judge coaches, retry ≤ max_rounds
        </text>
      </svg>
    </figure>

    <h3>CorrectiveLoop</h3>

    <p>
      A panel of members drafting under the check. The single <code>judge</code> plays two roles the
      loop keeps apart: it selects among passing drafts, and it coaches after a no-pass round. It
      never writes the answer itself. A panel needs at least two members.
    </p>

    <CodeBlock :code="correctiveSig" language="python" />

    <table>
      <thead>
        <tr>
          <th>Attribute</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>name</code></td>
          <td><code>str</code></td>
          <td>
            The loop's name. Inferred by joining member names with <code>+</code> unless you pass
            one.
          </td>
        </tr>
        <tr>
          <td><code>members</code></td>
          <td><code>tuple[Recipe, ...]</code></td>
          <td>The panel that drafts. At least two.</td>
        </tr>
        <tr>
          <td><code>judge</code></td>
          <td><code>Recipe</code></td>
          <td>
            Selects among passing drafts and coaches after a no-pass round. Never writes the answer.
          </td>
        </tr>
        <tr>
          <td><code>max_rounds</code></td>
          <td><code>int</code></td>
          <td>
            The most rounds the loop will run. A cost cap, not a target; defaults to <code>3</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="2" :code="correctiveExample" />
    </div>

    <h3>SelfCorrective</h3>

    <p>
      The solo shape: one model drafts under the same check and writes its own retry feedback from
      the check's sanitized violations: the coaching role the panel gives to a separate judge,
      played by the only model present.
    </p>

    <CodeBlock :code="selfCorrectiveSig" language="python" />

    <table>
      <thead>
        <tr>
          <th>Attribute</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>name</code></td>
          <td><code>str</code></td>
          <td>The recipe's name. Taken from the member unless you pass one.</td>
        </tr>
        <tr>
          <td><code>member</code></td>
          <td><code>Recipe</code></td>
          <td>The single model that drafts and coaches itself between rounds.</td>
        </tr>
        <tr>
          <td><code>max_rounds</code></td>
          <td><code>int</code></td>
          <td>
            The most rounds it will run. A cost cap, not a target; defaults to <code>3</code>.
          </td>
        </tr>
      </tbody>
    </table>
  </DocLayout>
</template>
