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

pair = sf.Fanout([opus, gpt]) >> sf.Synthesize("openrouter/anthropic/claude-opus-4.8")
pair`
const basicOut = `Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5']) >> Synthesize('openrouter/anthropic/claude-opus-4.8')`

const inspect = `fanout, writer = pair.steps
pair.name, [m.name for m in fanout.members]`
const inspectOut = `('claude-opus-4.8+gpt-5.5', ['claude-opus-4.8', 'gpt-5.5'])`

const synth = `sf.Fanout([opus, gpt], name="pair-gpt-synth") >> sf.Synthesize(
    sf.Model(
        "openrouter/openai/gpt-5.5",
        prompt="Write the final answer from the drafts.",
    )
)`
const synthOut = `Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5'], name='pair-gpt-synth') >> Synthesize(Model('openrouter/openai/gpt-5.5', prompt='Write the final answer from the drafts.'))`

const nested = `haiku = sf.Model("openrouter/anthropic/claude-haiku-4.5")

sf.Fanout([pair, haiku], name="nested") >> sf.Synthesize("openrouter/openai/gpt-5.5")`
const nestedOut = `Fanout([Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5']) >> Synthesize('openrouter/anthropic/claude-opus-4.8'), 'openrouter/anthropic/claude-haiku-4.5'], name='nested') >> Synthesize('openrouter/openai/gpt-5.5')`

const shortcut = `same = sf.Fusion([opus, gpt], synthesizer="openrouter/anthropic/claude-opus-4.8")
same == pair`
const shortcutOut = `True`

const fanoutSig = `sf.Fanout(
    members: Sequence[str | Recipe],
    *,
    signals: Mapping[str, SignalSource] | None = None,
    quorum: int | Literal["all"] = "all",
    name: str | None = None,
    prompt: str | None = None,
)`

const synthesizeSig = `sf.Synthesize(
    model: str | Recipe,
    *,
    prompt: str | None = None,
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
      A <strong>fusion</strong> sends the same question to all its members, then a
      <strong>synthesizer</strong> reads their answers and produces one final answer. The benchmark
      grades that final answer, so a fusion competes with a solo
      <RouterLink to="/sf-client/guides/models">Model</RouterLink>.
    </p>

    <p>
      You build a fusion as a chain of two steps. <code>sf.Fanout(members)</code> sends the question
      to every member. <code>sf.Synthesize(model)</code> is the synthesizer.
      <code>&gt;&gt;</code> joins the two steps into one recipe.
    </p>

    <p>
      The synthesizer is itself a recipe. Usually it is a model that reads the candidate answers and
      writes the winner. It can also be a
      <RouterLink to="/sf-client/guides/pipelines">Pipeline</RouterLink> or another fusion.
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

    <p>Like a Model, a fusion is immutable. Building one makes no requests.</p>

    <h2>What you can do</h2>

    <ul>
      <li>Combine two or more Models into one candidate.</li>
      <li>Pick your synthesizer. Control how a model synthesizer is prompted.</li>
      <li>Nest a fusion or a Pipeline inside another fusion.</li>
      <li>Read back the steps, the members and the resolved name.</li>
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
            <code>sf.Fanout(members, *, signals=None, quorum="all", name=None, prompt=None)</code>
          </td>
          <td>
            Sends the question to every member in parallel. It opens a block. A synthesizer (or a
            reducer) closes the block.
          </td>
        </tr>
        <tr>
          <td><code>sf.Synthesize(model, *, prompt=None)</code></td>
          <td>
            The synthesizer. It reads the members' answers and writes one final answer for the
            benchmark to grade. A route string or <code>sf.Model</code> has a model write the
            answer. An
            <RouterLink to="/sf-client/guides/pipelines"><code>sf.Pipeline</code></RouterLink> or
            another fusion gives multi-step synthesis.
          </td>
        </tr>
        <tr>
          <td><code>a &gt;&gt; b</code></td>
          <td>
            Joins steps left to right and returns an <code>sf.Pipeline</code>.
            <code>sf.Fanout(...) &gt;&gt; sf.Synthesize(...)</code> is a fusion.
          </td>
        </tr>
        <tr>
          <td><code>.name</code> · <code>.steps</code></td>
          <td>
            Read back the resolved name and the steps: the <code>Fanout</code> step, then the
            <code>Synthesize</code> step.
          </td>
        </tr>
        <tr>
          <td><code>sf.Recipe</code></td>
          <td>The shared base type of every candidate kind.</td>
        </tr>
      </tbody>
    </table>

    <h2>How to</h2>

    <h3>1 · Combine two models</h3>

    <p>
      <code>sf.Fanout</code> takes the members first (positional). <code>sf.Synthesize</code> takes
      the synthesizer. The value shows in the same <code>Fanout(...) &gt;&gt; Synthesize(...)</code>
      form.
    </p>

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
      A fusion needs at least one member. An empty member list fails when you build it. A
      <code>sf.Fanout</code> also needs a step after it. A chain that ends after
      <code>sf.Fanout</code> fails when you compile or evaluate it, before any spend.
    </p>

    <h3>2 · Read the resolved name</h3>

    <p>
      Without an explicit <code>name</code> on <code>sf.Fanout</code>, the fusion's name is its
      members' names joined with <code>+</code>. Reports show that name. <code>.steps</code> holds
      the two steps: the <code>Fanout</code>, then the <code>Synthesize</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="inspect"><NbTextOut :text="inspectOut" /></NbCell>
    </div>

    <h3>3 · Choose the synthesizer</h3>

    <p>
      The <strong>synthesizer</strong> decides how the members' answers become one. It is itself a
      recipe. Give <code>sf.Synthesize</code> a route string or <code>sf.Model</code> to have a model
      read the drafts and write the final answer. Or give it an
      <RouterLink to="/sf-client/guides/pipelines"><code>sf.Pipeline</code></RouterLink> or another
      fusion for multi-step synthesis. Swapping synthesizers is the main lever: same members,
      different synthesizer, different candidate.
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
      A model synthesizer has its own <code>prompt</code> and <code>params</code>. They control how
      it writes the final answer, separate from how members answer. Set a different prompt on a
      member by setting it on that Model. <code>sf.Synthesize(model, prompt=...)</code> also sets
      the synthesizer prompt, when the model has no prompt of its own.
      <code>sf.Fanout(members, prompt=...)</code> sets the prompt of each member that has none.
    </p>

    <p>
      A synthesizer is one way to close the block. A reducer closes it with a rule instead:
      <code>sf.Vote</code>, <code>sf.Median</code>, <code>sf.Mean</code>, <code>sf.ArgMax</code>,
      <code>sf.ArgMin</code>, <code>sf.First</code>, <code>sf.Merge</code>,
      <code>sf.JudgePick</code> or <code>sf.Gate</code>. An optional <code>sf.Judge</code> and the
      narrow steps <code>sf.Rank</code>, <code>sf.Filter</code> and <code>sf.Concat</code> can come
      before the last step. The
      <a
        href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/README.md"
        target="_blank"
        rel="noopener"
        >package README</a
      >
      gives a recipe for each.
    </p>

    <h3>4 · Nest a fusion</h3>

    <p>
      A member can be a fusion or a Pipeline, so a pair can become a member in a larger fusion. The
      inner recipe shows up in full inside the outer <code>Fanout</code>.
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
      Members must be recipes: a <code>Model</code>, a <code>Pipeline</code>, or another fusion (or
      a route string, which becomes a <code>Model</code>).
    </p>

    <h3>5 · Use the <code>sf.Fusion</code> shortcut</h3>

    <p>
      <code>sf.Fusion</code> is a shortcut for the same chain. It takes the members, then the
      synthesizer as a keyword. It returns an equal value with the same url4. The value shows in the
      <code>Fanout(...) &gt;&gt; Synthesize(...)</code> form. It also takes <code>signals</code>,
      <code>quorum</code>, <code>name</code> and <code>prompt</code> for the <code>sf.Fanout</code>,
      and <code>optional=True</code>, which wraps the chain as
      <code>sf.Pipeline([...], optional=True)</code>. It refuses <code>optional=True</code> with a
      narrow step (<code>sf.Rank</code>, <code>sf.Filter</code>, <code>sf.Concat</code>) as the
      synthesizer, because an optional chain must be a closed block. It refuses a bare
      <code>sf.Judge</code> as the synthesizer, because a judge only scores.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="shortcut"><NbTextOut :text="shortcutOut" /></NbCell>
    </div>

    <h2>The building blocks</h2>

    <h3><code>sf.Fanout</code></h3>

    <CodeBlock :code="fanoutSig" language="python" />

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
            One or more members, in order. Each can be a route string, a <code>Model</code>, a
            <code>Pipeline</code>, or another fusion. Ensembles nest.
          </td>
        </tr>
        <tr>
          <td><code>signals</code></td>
          <td><code>Mapping[str,&nbsp;SignalSource]&nbsp;|&nbsp;None</code></td>
          <td>
            Named numbers that the run measures from each member answer. A later step of the same
            block reads them. <code>sf.Synthesize</code> right after <code>sf.Fanout</code> reads no
            signal, so that block refuses <code>signals</code>.
          </td>
        </tr>
        <tr>
          <td><code>quorum</code></td>
          <td><code>int&nbsp;|&nbsp;"all"</code></td>
          <td>
            The least number of members that must answer: <code>"all"</code> (the default) or a
            number from 0 to the member count.
          </td>
        </tr>
        <tr>
          <td><code>name</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            Defaults to the member names joined with <code>+</code>, for example
            <code>claude-opus-4.8+gpt-hot</code>. The fusion takes this name.
          </td>
        </tr>
        <tr>
          <td><code>prompt</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            Sets the prompt of each member that is a route string or a <code>Model</code> with no
            prompt. A member that has its own prompt is refused.
          </td>
        </tr>
      </tbody>
    </table>

    <h3><code>sf.Synthesize</code></h3>

    <CodeBlock :code="synthesizeSig" language="python" />

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
          <td><code>model</code></td>
          <td><code>str&nbsp;|&nbsp;Recipe</code></td>
          <td>
            The synthesizer: a route string or any recipe (a <code>Model</code>, a
            <code>Pipeline</code>, or another fusion). It reads the members' answers and writes the
            final one.
          </td>
        </tr>
        <tr>
          <td><code>prompt</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            The synthesizer prompt. Use it only with a route string or a <code>Model</code> that has
            no prompt. With no prompt, the default synthesis prompt applies.
          </td>
        </tr>
      </tbody>
    </table>

    <h3>Attributes</h3>

    <p>
      A fusion is an <code>sf.Pipeline</code>. Its <code>steps</code> is a <code>tuple</code>: the
      <code>Fanout</code> step, then the <code>Synthesize</code> step. Its <code>name</code> is the
      resolved label of the <code>Fanout</code>. The <code>Fanout</code> step keeps
      <code>members</code> (a <code>tuple</code> in the order you gave, route strings become
      <code>Model</code>), <code>name</code>, <code>prompt</code>, <code>quorum</code> and
      <code>signals</code>. The <code>Synthesize</code> step keeps <code>model</code> (a route string
      becomes a <code>Model</code>) and <code>prompt</code>.
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
          <td>The members are empty</td>
          <td><code>ValueError: a sf.Fanout requires at least one member</code></td>
        </tr>
        <tr>
          <td><code>members</code> is not an ordered sequence (for example a bare route string)</td>
          <td>
            <code
              >TypeError: sf.Fanout members must be an ordered sequence of model routes or
              Recipes</code
            >
          </td>
        </tr>
        <tr>
          <td>A member is not a route string or a supported recipe</td>
          <td>
            <code>TypeError: sf.Fanout member must be a model route, a sf.Model or a sf.Pipeline</code>
          </td>
        </tr>
        <tr>
          <td>The synthesizer is not a route string or a supported recipe</td>
          <td>
            <code
              >TypeError: sf.Synthesize model must be a model route, a sf.Model or a
              sf.Pipeline</code
            >
          </td>
        </tr>
        <tr>
          <td>A recipe comes right after <code>sf.Fanout</code>, with no synthesizer between</td>
          <td>
            <code
              >ValueError: a sf.Fanout block needs a reducer or sf.Synthesize before the next
              stage</code
            >
          </td>
        </tr>
        <tr>
          <td>
            The chain ends after <code>sf.Fanout</code> (raised by compile and
            <code>sf.evaluate</code>, before any spend)
          </td>
          <td>
            <code
              >ValueError: the chain ends inside a sf.Fanout block: add a reducer or
              sf.Synthesize</code
            >
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
