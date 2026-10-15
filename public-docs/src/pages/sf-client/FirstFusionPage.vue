<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import Note from '@/components/ui/Note.vue'
import Tabs from '@/components/ui/Tabs.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const importCell = `import screamingface as sf`

const connect = `sf.connect()  # opens the connection panel; click Log in`

const connectLocal = `sf.configure(engine_url="http://127.0.0.1:9108")
sf.connect("openrouter", api_key="sk-or-...")  # your own OpenRouter key`

const build = `fusion = sf.Fusion(
    ["openrouter/openai/gpt-5.5", "openrouter/google/gemini-3-flash-preview"],
    synthesizer="openrouter/openai/gpt-5.5",
)`

const run = `report = sf.evaluate(fusion, benchmark="ifeval", limit=3)`

const read = `candidate = report.candidates.only
candidate.score`
</script>

<template>
  <DocLayout
    title="Your first fusion"
    description="Combine two models into one, run it on a benchmark, and read the score."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A fusion is a few models answering together, combined into one answer. In this tutorial you
      build one, run it on a handful of benchmark cases, and read its score. It takes a few lines
      and a couple of minutes.
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
          The hosted engine comes with shared OpenRouter credits, so there is no key to paste. Call
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
          <RouterLink to="/sf-client/installation">Installation</RouterLink>, point the Client at it,
          and connect your own OpenRouter key. A local engine needs no login.
        </p>

        <div class="not-prose">
          <NbCell :count="2" :code="connectLocal" />
        </div>
      </template>
    </Tabs>

    <h2>3 · Build the fusion</h2>

    <p>
      Give <code>sf.Fusion</code> two model routes and a synthesizer. The two members answer the
      same question in parallel; the synthesizer reads both drafts and writes the single answer that
      gets graded. Here the first model doubles as the synthesizer — a fine way to start.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="build" />
    </div>

    <h2>4 · Run it</h2>

    <p>
      <code>sf.evaluate</code> runs your fusion against a benchmark and grades the answers.
      <code>ifeval</code> checks whether a model follows instructions; <code>limit=3</code> runs
      just three cases, so this stays quick and cheap while you are finding your feet.
    </p>

    <Note>
      <code>ifeval</code> is one of several benchmarks. A local engine also serves
      <code>healthbench-professional</code>, <code>healthbench-worst30</code> (hard medical
      conversations) and <code>medxpert</code>; the hosted engine adds <code>draco</code> (deep
      research) and more. List everything available with <code>sf.benchmarks.list()</code>, and see
      <RouterLink to="/sf-client/guides/benchmarks">Choose a benchmark</RouterLink> for how to pick
      one.
    </Note>

    <div class="not-prose">
      <NbCell :count="4" :code="run" />
    </div>

    <h2>5 · Read the score</h2>

    <p>
      The run comes back as a <RouterLink to="/sf-client/api/reports">Report</RouterLink>. You gave
      it one candidate, so <code>report.candidates.only</code> is your fusion, and its
      <code>score</code> is the fraction of cases it got right — higher is better.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="read" />
    </div>

    <p>
      That is a whole evaluation: compose, run, read. Nothing here was mocked — the same three steps
      scale from three cases to a full benchmark.
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
        <strong><RouterLink to="/sf-client/guides/fusions">Compose a candidate</RouterLink></strong>
        — weights, judges, and nesting fusions inside fusions.
      </li>
      <li>
        <strong
          ><RouterLink to="/sf-client/reproduce-draco"
            >Reproduce DRACO state-of-the-art</RouterLink
          ></strong
        >
        — put a fusion up against its solo models on a real board.
      </li>
      <li>
        <strong><RouterLink to="/sf-client/api/fusions">Fusion reference</RouterLink></strong> —
        every field and argument, in full.
      </li>
    </ul>
  </DocLayout>
</template>
