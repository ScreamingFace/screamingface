<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const runIt = `import screamingface as sf

client = sf.Client()
report = client.evaluate(
    sf.Model("openrouter/anthropic/claude-haiku-4.5"),
    benchmark="ifeval",
    limit=1,
)
report`
const runItOut = `Report(benchmark='ifeval', candidates=['claude-haiku-4.5'], ok=True)`

const summary = `report.ok, report.case_count, report.duration_ms`
const summaryOut = `(True, 1, 5248)`

const only = `candidate = report.candidates.only
candidate.name, candidate.kind, candidate.score, candidate.coverage`
const onlyOut = `('claude-haiku-4.5', 'model', 1.0, 1.0)`

const byName = `report.candidates["claude-haiku-4.5"] is candidate`
const byNameOut = `True`

const dict = `sorted(report.to_dict())`
const dictOut = `['benchmark', 'candidates', 'completed_at', 'schema', 'started_at', 'usage']`

const bench = `report.benchmark`
const benchOut = `BenchmarkInfo(id='ifeval', revision='1cba769ece27f7ef', case_count=541, inverted_grade=False)`
</script>

<template>
  <DocLayout
    title="Reports"
    description="Report and everything it carries."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <code>Report</code> is what an evaluation returns, and it is the only thing worth keeping:
      it carries the scores, what was spent, what failed, and the exact expression that ran. This
      page covers <code>Report</code> itself. It holds
      <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink> values, each of
      which may hold <code>MemberResult</code> and <code>OperationInfo</code> values, and both a
      report and each candidate carry a <RouterLink to="/sf-client/api/usage">Usage</RouterLink> and
      any <code>Failure</code> records. See the
      <RouterLink to="/sf-client/guides/running-an-evaluation">evaluation guide</RouterLink> for
      running one.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="runIt"><NbTextOut :text="runItOut" /></NbCell>
    </div>

    <p>Every example below reads from that report.</p>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        viewBox="0 0 720 348"
        role="img"
        aria-label="A Report holds one BenchmarkInfo and many CandidateResult values. Each CandidateResult holds many OperationInfo (the plan DAG), many CaseResult (per-case grades), a Usage, its url4 expression, and — for a fusion — many MemberResult values."
        style="width: 100%; height: auto; font-family: var(--f-mono)"
      >
        <defs>
          <marker
            id="rp-arrow"
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

        <!-- Report -->
        <rect
          x="40"
          y="24"
          width="160"
          height="56"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="120" y="50" text-anchor="middle" style="fill: var(--text); font-size: 15px">
          Report
        </text>
        <text x="120" y="68" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          one evaluation
        </text>

        <!-- BenchmarkInfo -->
        <rect
          x="300"
          y="14"
          width="180"
          height="48"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="390" y="42" text-anchor="middle" style="fill: var(--text); font-size: 13px">
          BenchmarkInfo
        </text>

        <!-- CandidateResult -->
        <rect
          x="300"
          y="96"
          width="180"
          height="56"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="390" y="122" text-anchor="middle" style="fill: var(--text); font-size: 13px">
          CandidateResult
        </text>
        <text x="390" y="140" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          one per candidate
        </text>

        <!-- edges from Report -->
        <g style="stroke: var(--text-2); stroke-width: 1; fill: none">
          <path d="M200 42 H300" marker-end="url(#rp-arrow)" />
          <path d="M200 60 V124 H300" marker-end="url(#rp-arrow)" />
        </g>
        <text x="250" y="34" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          one
        </text>
        <text x="250" y="80" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          many
        </text>

        <!-- leaves off CandidateResult -->
        <g>
          <rect
            x="540"
            y="94"
            width="150"
            height="34"
            style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
          />
          <text x="615" y="115" text-anchor="middle" style="fill: var(--text); font-size: 12px">
            OperationInfo
          </text>

          <rect
            x="540"
            y="144"
            width="150"
            height="34"
            style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
          />
          <text x="615" y="165" text-anchor="middle" style="fill: var(--text); font-size: 12px">
            CaseResult
          </text>

          <rect
            x="540"
            y="194"
            width="150"
            height="34"
            style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
          />
          <text x="615" y="215" text-anchor="middle" style="fill: var(--text); font-size: 12px">
            MemberResult
          </text>

          <rect
            x="540"
            y="244"
            width="150"
            height="34"
            style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
          />
          <text x="615" y="265" text-anchor="middle" style="fill: var(--text); font-size: 12px">
            Usage
          </text>

          <rect
            x="540"
            y="294"
            width="150"
            height="34"
            style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
          />
          <text x="615" y="315" text-anchor="middle" style="fill: var(--text); font-size: 12px">
            url4
          </text>
        </g>

        <g style="stroke: var(--text-2); stroke-width: 1; fill: none">
          <path d="M480 124 C 510 124, 510 111, 540 111" marker-end="url(#rp-arrow)" />
          <path d="M480 124 C 510 124, 510 161, 540 161" marker-end="url(#rp-arrow)" />
          <path d="M480 124 C 510 124, 510 211, 540 211" marker-end="url(#rp-arrow)" />
          <path d="M480 124 C 510 124, 510 261, 540 261" marker-end="url(#rp-arrow)" />
          <path d="M480 124 C 510 124, 510 311, 540 311" marker-end="url(#rp-arrow)" />
        </g>

        <g text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          <text x="615" y="88">many · the plan DAG</text>
          <text x="615" y="138">many · per-case grade</text>
          <text x="615" y="188">many · fusion members</text>
          <text x="615" y="238">tokens / cost</text>
          <text x="615" y="288">the expression</text>
        </g>
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
        A report holds one benchmark identity and one result per candidate; each candidate carries
        its plan, its cases, its members, its usage, and its url4.
      </figcaption>
    </figure>

    <h2>Report</h2>

    <p>
      A <code>Report</code> represents one evaluation. Its constructor is public, but in normal use
      a <RouterLink to="/sf-client/api/clients">Client</RouterLink> returns it and it is never
      constructed directly.
    </p>

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
          <td><code>benchmark</code></td>
          <td><code>BenchmarkInfo</code></td>
          <td>Which benchmark, at which revision, this ran against.</td>
        </tr>
        <tr>
          <td><code>case_count</code></td>
          <td><code>int</code></td>
          <td>How many cases this run actually covered.</td>
        </tr>
        <tr>
          <td><code>candidates</code></td>
          <td>sequence of <code>CandidateResult</code></td>
          <td>One entry per candidate you evaluated, in the order you passed them.</td>
        </tr>
        <tr>
          <td><code>ok</code></td>
          <td><code>bool</code></td>
          <td>
            <code>True</code> when nothing failed anywhere in the run, at candidate or member level.
          </td>
        </tr>
        <tr>
          <td><code>failures</code></td>
          <td><code>tuple[Failure, ...]</code></td>
          <td>Every failure from every candidate and every member, flattened into one tuple.</td>
        </tr>
        <tr>
          <td><code>usage</code></td>
          <td><code>Usage</code></td>
          <td>The whole run's accounting, summed across candidates.</td>
        </tr>
        <tr>
          <td><code>started_at</code> / <code>completed_at</code></td>
          <td><code>datetime</code></td>
          <td>Earliest start and latest finish across candidates. Always timezone-aware.</td>
        </tr>
        <tr>
          <td><code>duration_ms</code></td>
          <td><code>int</code></td>
          <td>Wall-clock milliseconds between those two.</td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="2" :code="summary"><NbTextOut :text="summaryOut" /></NbCell>
    </div>

    <Note>
      <code>report.case_count</code> and <code>report.benchmark.case_count</code> are different
      numbers. The first is what this run covered; the second is the benchmark's full size.
    </Note>

    <div class="not-prose">
      <NbCell :count="3" :code="bench"><NbTextOut :text="benchOut" /></NbCell>
    </div>

    <p>
      Two reports are only comparable when both the id and the revision match.
    </p>

    <h3>candidates</h3>

    <p>
      <code>report.candidates</code> is a read-only sequence supporting iteration, positional
      indexing and slicing. It also indexes by candidate name, and offers <code>.only</code> for the
      common case of a single candidate.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="only"><NbTextOut :text="onlyOut" /></NbCell>
      <NbCell :count="5" :code="byName"><NbTextOut :text="byNameOut" /></NbCell>
    </div>

    <p>
      <code>.only</code> raises <code>ValueError</code> when the report holds more than one
      candidate, and indexing by an unknown name raises <code>KeyError</code>. Candidate names are
      unique within a report.
    </p>

    <p>
      Each entry is a
      <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink>, one candidate's
      outcome, holding its score, its cases, its operation graph, its members, its
      <RouterLink to="/sf-client/api/usage">Usage</RouterLink>, and its url4.
    </p>

    <h3>Serialisation</h3>

    <p>
      <code>to_dict()</code> returns a plain JSON-compatible dictionary and
      <code>to_json()</code> returns it as a compact string. Both carry a <code>schema</code> field,
      <code>screamingface.report.v1</code>, so a consumer can tell what it is reading.
      <code>export(path="report.json")</code> writes that same document to disk, creating parent
      directories and replacing an existing file, and returns the path it wrote.
      <code>export(path, *, format="json", candidate=None)</code> also takes
      <code>format="inspect"</code>, which writes one candidate's run, named by
      <code>candidate=</code>, as an inspect <code>.eval</code> log. That format needs the
      <code>inspect</code> extra (<code>pip install "screamingface[inspect]"</code>), which does not
      install in the same environment as the <code>runtime</code> extra.
      <code>trace_dict()</code> returns the per-operation trace as a dictionary with a
      <code>schema</code> and a <code>candidates</code> key.
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="dict"><NbTextOut :text="dictOut" /></NbCell>
    </div>

    <h2>Saved reports</h2>

    <p>
      A Client saves every completed report to <code>~/.screamingface/results</code> unless it was
      built with <code>save_results=False</code>. That folder is outside the engine's data
      directory and shared by every environment on the machine, and the files hold the prompts and
      outputs of each run. A run that ends with failures is saved too. The <code>sf.reports</code>
      module reopens them.
    </p>

    <table>
      <thead>
        <tr>
          <th>Function</th>
          <th>Returns</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.reports.list(*, directory=None)</code></td>
          <td>
            A list of <code>SavedReportInfo</code>, one per saved report, with <code>id</code>,
            <code>candidates</code>, <code>directory</code>, <code>downloaded</code> and
            <code>size_bytes</code>. The order is not guaranteed.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.reports.get(report_id, *, directory=None, destination=None)</code>
          </td>
          <td>The saved <code>Report</code>. <code>get_async</code> is the awaitable form.</td>
        </tr>
        <tr>
          <td><code>sf.reports.delete(report_id, *, directory=None)</code></td>
          <td><code>None</code>. Removes the saved report from disk.</td>
        </tr>
      </tbody>
    </table>

    <p>
      <code>directory=</code> points the call at a different folder than
      <code>~/.screamingface/results</code>.
    </p>

    <h2>Beyond the report</h2>

    <p>
      Each candidate's outcome lives on the
      <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink> page, which
      covers <code>CandidateResult</code> itself alongside <code>MemberResult</code>,
      <code>OperationInfo</code> and <code>CaseResult</code>. The token and cost accounting a report
      and its candidates carry, and the <code>Failure</code> records they hold, are on the
      <RouterLink to="/sf-client/api/usage">Usage</RouterLink> page.
    </p>
  </DocLayout>
</template>
