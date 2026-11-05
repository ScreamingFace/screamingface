<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import Tabs from '@/components/ui/Tabs.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const importCell = `import screamingface as sf`

const connect = `sf.connect()  # opens the connection panel; click Log in`

const connectLocal = `sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
sf.connect("openrouter", api_key="sk-or-...")  # your own OpenRouter key`

const build = `fusion = sf.Fanout(
    ["openrouter/openai/gpt-5.5", "openrouter/google/gemini-3-flash-preview"],
) >> sf.Synthesize("openrouter/openai/gpt-5.5")`

const run = `report = sf.evaluate(fusion, benchmark="ifeval", limit=3)`

const runLocal = `report = sf.evaluate(fusion, benchmark="medxpert", limit=3)`

const read = `candidate = report.candidates.only
candidate.score`

const readOut = `0.6667`
</script>

<template>
  <DocLayout
    title="Your first fusion"
    description="Combine two models into one, run it on a benchmark, and read the score."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A fusion is a composed system of different models, working as one. In this tutorial you build
      one, run it on three benchmark cases, and read its score.
    </p>

    <Note>
      You need the Client installed (see
      <RouterLink to="/sf-client/installation">Installation</RouterLink>) and an engine to run on.
      On the hosted engine your account needs access, which the OpenMined team grants, and no
      provider keys are needed. On a local engine you connect your own OpenRouter key. Step 2 shows
      both.
    </Note>

    <h2>1 · Import the library</h2>

    <p>Everything you need hangs off the top-level <code>sf</code> module.</p>

    <div class="not-prose">
      <NbCell :count="1" :code="importCell" />
    </div>

    <h2>2 · Connect to an engine</h2>

    <Tabs :labels="['Hosted engine', 'Your own engine']">
      <template #tab-0>
        <p>
          The hosted engine runs on compute the OpenMined team allocates to your account, so there
          is no key to paste. Call
          <code>sf.connect()</code> to open the connection panel. It shows a Log in button; log in
          through your browser. For an account with access the panel then lists OpenRouter as
          connected. For an account without access every provider shows as unavailable, and an
          evaluation is refused: ask the OpenMined team for access, or use your own engine.
        </p>

        <div class="not-prose">
          <NbCell :count="2" :code="connect" />
        </div>
      </template>

      <template #tab-1>
        <p>
          Start the local stack as described in
          <RouterLink to="/sf-client/installation">Installation</RouterLink>, point the Client at
          it, and connect your own OpenRouter key. A local engine needs no login.
        </p>

        <div class="not-prose">
          <NbCell :count="2" :code="connectLocal" />
        </div>
      </template>
    </Tabs>

    <h2>3 · Build the fusion</h2>

    <p>
      Give <code>sf.Fanout</code> two model routes. The two members answer the same question in
      parallel. Then <code>&gt;&gt;</code> adds <code>sf.Synthesize</code>, the synthesizer: it
      reads both drafts and writes the single answer that gets graded. Here the first model doubles
      as the synthesizer. Recipes also compose into routed ensembles and into sequential cascades
      and gates.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="build" />
    </div>

    <h2>4 · Run it</h2>

    <p>
      <code>sf.evaluate</code> runs your fusion against a benchmark and grades the answers.
      <code>limit=3</code> runs three cases.
    </p>

    <Tabs :labels="['Hosted engine', 'Your own engine']">
      <template #tab-0>
        <p>
          <code>ifeval</code> checks whether a model follows instructions, graded by deterministic
          verification.
        </p>

        <div class="not-prose">
          <NbCell :count="4" :code="run" />
        </div>
      </template>

      <template #tab-1>
        <p>
          A local engine serves <code>medxpert</code>: 2,450 expert-level medical multiple-choice
          questions, graded by exact match against the published key, so no judge model is called.
        </p>

        <div class="not-prose">
          <NbCell :count="4" :code="runLocal" />
        </div>
      </template>
    </Tabs>

    <Note>
      A local engine started with <code>screamingface up</code> serves <code>medxpert</code>; the
      hosted engine serves <code>ifeval</code>, <code>draco</code> (deep research) and more. To
      serve the other benchmarks locally, run <code>just local-stack-notebooks</code> from
      <code>packages/screamingface/</code> in a repository checkout. List what an engine serves with
      <code>sf.benchmarks.list()</code>, and see
      <RouterLink to="/sf-client/guides/benchmarks">Choose a benchmark</RouterLink> for how to pick
      one.
    </Note>

    <h2>5 · Read the score</h2>

    <p>
      The run comes back as a <RouterLink to="/sf-client/api/reports">Report</RouterLink>. You gave
      it one candidate, so <code>report.candidates.only</code> is your fusion, and its
      <code>score</code> is the fraction of cases it got right, and higher is better. On
      <code>medxpert</code> with <code>limit=3</code> the fusion answered two of three correctly.
      The run cost $0.17, read from <code>report.usage.cost_usd</code>:
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="read"><NbTextOut :text="readOut" /></NbCell>
    </div>

    <p>
      That is a whole evaluation: compose, run, read. The same three steps scale from three cases to
      a full benchmark.
    </p>

    <h2>How far this goes</h2>

    <p>
      What you built is a <strong>parallel fan-out</strong>: each member answers the question on its
      own and a synthesizer folds their drafts into one. That is one of two ways recipes compose.
      The other is a <RouterLink to="/sf-client/api/pipelines">Pipeline</RouterLink>, the serial
      counterpart, where each stage refines the previous stage's answer instead of running alongside
      it.
    </p>

    <p>
      Recipes nest, so these two types compose into much larger systems. A member, a synthesizer, or
      a pipeline stage can itself be a
      <RouterLink to="/sf-client/api/fusions">Fusion</RouterLink> or a Pipeline: a fusion of
      pipelines, a pipeline whose last stage is a fusion, a fusion whose synthesizer is itself a
      fusion. Every one is built from those same two moves, parallel and serial. Start flat, like
      here, and add depth when a task needs it.
    </p>

    <h2>Where to go next</h2>

    <ul>
      <li>
        <strong><RouterLink to="/sf-client/guides/fusions">Compose a candidate</RouterLink></strong
        >: weights, judges, and nesting fusions inside fusions.
      </li>
      <li>
        <strong
          ><RouterLink to="/sf-client/reproduce-draco"
            >Reproduce DRACO state-of-the-art</RouterLink
          ></strong
        >: put a fusion up against its solo models on a real board.
      </li>
      <li>
        <strong><RouterLink to="/sf-client/api/fusions">Fusion reference</RouterLink></strong
        >: every field and argument, in full.
      </li>
    </ul>
  </DocLayout>
</template>
