<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const listing = `import screamingface as sf

[(b.id, b.case_count, b.revision) for b in sf.benchmarks.list()]`
const listingOut = `[('healthbench-professional', 525, 'd8fb037307f35415'),
 ('healthbench-worst30', 157, '39cfd96b068f7230'),
 ('ifeval', 541, '1cba769ece27f7ef'),
 ('medxpert', 2450, '791a7d5b2e961f1c')]`

const card = `ifeval = sf.benchmarks.get("ifeval")
ifeval.title, ifeval.revision, ifeval.case_count`
const cardOut = `('IFEval', '1cba769ece27f7ef', 541)`
</script>

<template>
  <DocLayout
    title="Benchmarks"
    description="Discover the benchmarks an engine publishes and pick the protocol you want to run."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <strong>benchmark</strong> is the exam. It is owned entirely by
      <RouterLink to="/learn/engine">the engine</RouterLink> and it owns everything about how
      candidates are judged: which cases exist, in what order they are asked, which judge model
      grades them, how grades become a score. Your candidate answers; it does not get a say in any
      of that.
    </p>

    <p>
      That split is the point. Because the exam is fixed and pinned, a solo Model and a
      <RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink> evaluated against it are
      genuinely comparable.
    </p>

    <blockquote>
      <strong>What you can list depends on the engine.</strong> A local engine serves four
      benchmarks and the hosted engine serves 69, including DRACO. If there's a benchmark you'd
      want to run first,
      <a href="https://github.com/ScreamingFace/screamingface/issues" target="_blank" rel="noopener"
        >we'd love to hear it</a
      >.
    </blockquote>

    <h2>What you can do with it</h2>

    <ul>
      <li>List the benchmarks this engine publishes.</li>
      <li>Read one's identity card: size, revision, and what it actually measures.</li>
      <li>Check that two results are comparable by comparing revisions.</li>
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
          <td><code>sf.benchmarks.list()</code></td>
          <td>
            Lists every benchmark this engine publishes, a free discovery request that calls no
            model.
          </td>
        </tr>
        <tr>
          <td><code>sf.benchmarks.get(benchmark_id)</code></td>
          <td>
            Fetches one benchmark's identity card: its id, title, description, revision and size.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.Benchmark</code> <code>.id</code> <code>.title</code> <code>.description</code>
            <code>.revision</code> <code>.case_count</code>
          </td>
          <td>
            The identity card itself: its id, what it measures, the opaque revision hash of the
            pinned protocol, and its size.
          </td>
        </tr>
        <tr>
          <td><code>sf.BenchmarkInfo</code></td>
          <td>
            The pinned subset a report carries, so an old result still names the exact revision it
            ran against.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      <strong>Discovery is free.</strong> Listing benchmarks and reading identity cards are plain
      engine requests; no model is called and nothing is charged. Only
      <RouterLink to="/sf-client/guides/running-an-evaluation">evaluation</RouterLink> spends.
    </p>

    <h2>How to</h2>

    <h3>1 · See what this engine publishes</h3>

    <div class="not-prose">
      <NbCell :count="1" :code="listing"><NbTextOut :text="listingOut" /></NbCell>
    </div>

    <p>
      Benchmarks differ in what grading costs. <strong>IFEval</strong> is 541 instruction-following
      prompts checked by a deterministic verifier, so its grading is <strong>free</strong> and only
      the answers cost anything. <strong>HealthBench</strong> is rubric-graded by a judge model: the
      professional exam is 525 conversations, and <code>healthbench-worst30</code> is the 157
      hardest of them. <strong>MedXpert</strong> is 2,450 expert-level medical multiple-choice
      questions. On the hosted engine, <strong>DRACO</strong> is 100 deep-research tasks graded by a
      judge model (<code>openrouter/google/gemini-3.1-pro-preview</code>) with several independent
      passes per criterion, five for <code>draco</code> and three for <code>draco-3pass</code>: the
      grading itself is the expensive part.
    </p>

    <h3>2 · Read the identity card</h3>

    <div class="not-prose">
      <NbCell :count="2" :code="card"><NbTextOut :text="cardOut" /></NbCell>
    </div>

    <p>
      The <code>revision</code> is an opaque hash of the pinned protocol, and it is stamped into
      every report produced against it. That is what keeps old results attributable: if the public
      name later points at a newer snapshot, your report still names the revision it actually ran.
    </p>

    <h3>3 · Know what discovery will not tell you</h3>

    <p>
      A <code>Benchmark</code> carries no case data, so the prompts cannot be paged before a run.
      Cases stay on the engine and grading runs there, and that separation is what makes a verified
      result meaningful rather than self-reported. The case text a candidate received, its answer,
      and the grade behind it, including the rubric criteria and the judge, all arrive with the
      report afterwards, on
      <RouterLink to="/sf-client/api/reports">CandidateResult.cases</RouterLink>.
    </p>

    <h2>Links</h2>

    <ul>
      <li>
        <a
          href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/07_ifeval.ipynb"
          target="_blank"
          rel="noopener"
          >Companion notebook: <code>07_ifeval.ipynb</code></a
        >
      </li>
    </ul>
  </DocLayout>
</template>
