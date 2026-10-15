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

const listRun = `import screamingface as sf

client = sf.Client(engine_url="http://127.0.0.1:9108")
[(b.id, b.case_count) for b in client.benchmarks.list()]`
const listRunOut = `[('healthbench-professional', 525), ('healthbench-worst30', 157), ('ifeval', 541), ('medxpert', 2450)]`
</script>

<template>
  <DocLayout
    title="Benchmarks"
    description="Benchmark and the read-only values discovery returns."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A benchmark is a fixed set of cases, owned by the engine and pinned by a revision. This page
      covers <code>Benchmark</code> itself, alongside <code>BenchmarkInfo</code> for the compact
      identity a report keeps of it. See the
      <RouterLink to="/sf-client/guides/benchmarks">Benchmarks guide</RouterLink> for choosing which
      benchmark to run, and the <RouterLink to="/sf-client/api/models">Models page</RouterLink> for
      the model routes the engine can run a benchmark against.
    </p>

    <p>
      A <RouterLink to="/sf-client/api/clients">Client</RouterLink> returns these values, which are
      all read-only, and assigning to a field raises
      <code>FrozenInstanceError: cannot assign to field 'id'</code>. They also never refresh
      themselves, so the Client needs to be called again when current data is desired.
    </p>

    <h2>Benchmark</h2>

    <p>
      A <code>Benchmark</code> is the engine's record of one benchmark, carrying its identity, its
      size, and what it measures. <code>client.benchmarks.get(id)</code> returns a single benchmark
      and <code>client.benchmarks.list()</code> returns every benchmark the engine offers. The list
      depends on the engine: a local engine returns the benchmarks it has prepared, and the hosted
      engine returns more.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="listRun"><NbTextOut :text="listRunOut" /></NbCell>
    </div>

    <h3>Attributes</h3>

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
          <td><code>id</code></td>
          <td><code>str</code></td>
          <td>
            Stable identifier, one flat lowercase identifier such as <code>ifeval</code> or
            <code>draco-3pass</code>. This is what you pass as <code>benchmark=</code> when
            evaluating.
          </td>
        </tr>
        <tr>
          <td><code>title</code></td>
          <td><code>str</code></td>
          <td>Display name, such as <code>IFEval</code>.</td>
        </tr>
        <tr>
          <td><code>description</code></td>
          <td><code>str</code></td>
          <td>
            Prose describing what the benchmark measures and how it is graded.
          </td>
        </tr>
        <tr>
          <td><code>revision</code></td>
          <td><code>str</code></td>
          <td>
            Opaque content hash of this benchmark's current state. Two reports are only comparable
            when their revisions match.
          </td>
        </tr>
        <tr>
          <td><code>case_count</code></td>
          <td><code>int</code></td>
          <td>How many cases the benchmark holds in total.</td>
        </tr>
        <tr>
          <td><code>origin</code></td>
          <td><code>str</code></td>
          <td>
            Where the benchmark comes from, as the engine serves it. <code>'screamingface'</code>
            when an older engine serves none.
          </td>
        </tr>
        <tr>
          <td><code>interaction</code></td>
          <td><code>str | None</code></td>
          <td>
            How a case is asked, such as <code>'single_shot'</code> or <code>'multi_turn'</code>.
            <code>None</code> when the engine does not serve it.
          </td>
        </tr>
        <tr>
          <td><code>difficulty</code></td>
          <td><code>str | None</code></td>
          <td>
            The engine's tier for the benchmark, such as <code>'medium'</code> or
            <code>'hard'</code>. <code>None</code> when the engine does not serve it.
          </td>
        </tr>
        <tr>
          <td><code>inverted_grade</code></td>
          <td><code>bool</code></td>
          <td>
            <code>True</code> when every case score is already 1 minus the eval's grade, as for a
            benchmark scored by refusal rate. It is a mark, not an instruction: never flip a score
            with it.
          </td>
        </tr>
        <tr>
          <td><code>provenance</code></td>
          <td><code>BenchmarkProvenance | None</code></td>
          <td>
            The benchmark's cover sheet: <code>paper_url</code>, <code>authors</code>,
            <code>citation</code>, <code>inspect_contributors</code>, <code>homepage_url</code>,
            <code>harness_url</code>, <code>license</code>, <code>license_note</code>,
            <code>content_warning</code>, <code>human_baseline</code>, <code>frontier_score</code>
            (each score a <code>PublishedScore</code> with <code>score</code>,
            <code>source_url</code>, <code>model</code> and <code>as_of</code>) and
            <code>notebook</code>. <code>None</code> when the engine serves none.
          </td>
        </tr>
        <tr>
          <td><code>saturation</code></td>
          <td><code>str</code></td>
          <td>
            The engine's verdict on whether frontier models already top the benchmark:
            <code>'saturated'</code>, <code>'open'</code> or <code>'unknown'</code>.
          </td>
        </tr>
        <tr>
          <td><code>attempts</code></td>
          <td><code>int</code></td>
          <td>
            How many times each case is asked. A check counts as met if any attempt met it.
            <code>1</code> for an ordinary benchmark.
          </td>
        </tr>
      </tbody>
    </table>

    <Note>
      A <code>Benchmark</code> carries no case data. The Client cannot page a benchmark's prompts,
      because the cases stay on the engine. Case text becomes visible after a run, through the <code>CaseResult</code> values on
      <RouterLink to="/sf-client/api/reports">CandidateResult.cases</RouterLink>.
    </Note>

    <h2>BenchmarkInfo</h2>

    <p>
      A <code>BenchmarkInfo</code> is the pinned identity of a benchmark as it stood when a run took
      place. It is the value embedded in a
      <RouterLink to="/sf-client/api/reports">Report</RouterLink>, which is why it carries a
      revision but no title or description: its purpose is to make a result reproducible rather than
      to describe the benchmark.
    </p>

    <Note>
      <code>BenchmarkInfo.case_count</code> is the benchmark's full size, not the number of cases a
      run covered. The two differ: after evaluating with <code>limit=1</code>,
      <code>report.case_count</code> is <code>1</code> while
      <code>report.benchmark.case_count</code> remains <code>541</code>.
    </Note>

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
          <td><code>id</code></td>
          <td><code>str</code></td>
          <td>The benchmark identifier.</td>
        </tr>
        <tr>
          <td><code>revision</code></td>
          <td><code>str</code></td>
          <td>The revision the run was executed against.</td>
        </tr>
        <tr>
          <td><code>case_count</code></td>
          <td><code>int</code></td>
          <td>
            The benchmark's full size. For what the run covered, read
            <code>report.case_count</code>.
          </td>
        </tr>
        <tr>
          <td><code>inverted_grade</code></td>
          <td><code>bool</code></td>
          <td>
            The benchmark's refusal-rate mark as it stood at the run. <code>False</code> for an
            ordinary benchmark.
          </td>
        </tr>
      </tbody>
    </table>

    <h2>Validation</h2>

    <p>
      Both types validate their arguments on construction, so a malformed value cannot exist. Blank
      strings raise <code>ValueError</code>, non-strings raise <code>TypeError</code>, and
      <code>case_count</code> rejects zero and negative values:
    </p>

    <CodeBlock code="ValueError: Benchmark case_count must be a positive integer" language="text" />
  </DocLayout>
</template>
