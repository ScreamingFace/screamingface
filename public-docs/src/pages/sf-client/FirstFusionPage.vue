<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const importCell = `import screamingface as sf`

const connect = `import os

sf.connect("openrouter", api_key=os.environ["OPENROUTER_API_KEY"])
sf.connect("anthropic", api_key=os.environ["ANTHROPIC_API_KEY"])`

const build = `fusion = sf.Fusion(
    ["openrouter/deepseek/deepseek-v4-pro", "anthropic/claude-opus-4-8"],
    synthesizer="anthropic/claude-opus-4-8",
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
      <RouterLink to="/sf-client/installation">Installation</RouterLink>) and API keys for
      OpenRouter and Anthropic. This tutorial talks to the hosted engine and connects both providers
      explicitly below; the
      <RouterLink to="/sf-client/guides/connections">Connect a provider</RouterLink> guide covers
      OAuth and the interactive panel.
    </Note>

    <h2>1 · Import the library</h2>

    <p>Everything you need hangs off the top-level <code>sf</code> module.</p>

    <div class="not-prose">
      <NbCell :count="1" :code="importCell" />
    </div>

    <h2>2 · Connect your providers</h2>

    <p>
      The fusion below uses one model from OpenRouter and one from Anthropic, so connect both. Each
      call hands a key to the engine, which stores it encrypted and uses it to reach that provider;
      the key never lands in your recipe or your report. Read keys from the environment rather than
      pasting them into a cell.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="connect" />
    </div>

    <h2>3 · Build the fusion</h2>

    <p>
      Give <code>sf.Fusion</code> two model routes and a synthesizer. The two members answer the
      same question in parallel; the synthesizer reads both drafts and writes the single answer that
      gets graded. Here the second model plays both roles — a member and the synthesizer — which is
      a fine way to start.
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
      <code>ifeval</code> is one of several benchmarks the engine publishes. Others include
      <code>draco</code> (deep research) and <code>healthbench-worst30</code> (hard medical
      conversations); list everything available with <code>sf.benchmarks.list()</code>, and see
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
