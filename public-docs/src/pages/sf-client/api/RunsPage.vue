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

const list = `import screamingface as sf

sf.runs.list(limit=3)`
const listOut = `[Run(id='run_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6', state='complete',
     created_at=datetime.datetime(2026, 11, 14, 9, 30, 12, tzinfo=datetime.timezone.utc),
     finished_at=datetime.datetime(2026, 11, 14, 9, 31, 44, tzinfo=datetime.timezone.utc),
     benchmark='ifeval', candidates=(CandidateRun(name='gemini-3-flash-preview',
     state='succeeded', cost_usd=Decimal('0.0123'), error_code=None),)),
 Run(id='run_0f1e2d3c4b5a69788796a5b4c3d2e1f0', state='running', ...),
 Run(id='run_11223344556677889900aabbccddeeff', state='partial', ...)]`

const filter = `from datetime import UTC, datetime, timedelta

{
    "running": [r.id for r in sf.runs.list(state="running", limit=10)],
    "last_24h": [r.id for r in sf.runs.list(since=datetime.now(UTC) - timedelta(days=1))],
}`
const filterOut = `{'running': ['run_0f1e2d3c4b5a69788796a5b4c3d2e1f0'],
 'last_24h': ['run_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6', 'run_0f1e2d3c4b5a69788796a5b4c3d2e1f0']}`

const get = `run = sf.runs.get("run_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
run.state, run.benchmark, run.cost_usd`
const getOut = `('complete', 'ifeval', Decimal('0.0123'))`

const progress = `run = sf.runs.get(report.run_id)
run.progress()`
const progressOut = `RunProgress(done=1, total=2, cost_usd=Decimal('0.0123'))`

const wait = `sf.runs.get(report.run_id).wait(timeout=300).report()`

const oneLiner = `sf.runs.get(report.run_id).wait().report()`

const candidate = `run.candidates`
const candidateOut = `(CandidateRun(name='gemini-3-flash-preview', state='succeeded',
              cost_usd=Decimal('0.0123'), error_code=None),
 CandidateRun(name='gpt-5.5', state='failed', cost_usd=None, error_code='run_failed'))`

const asyncTwins = `run = await sf.runs.get_async(report.run_id)
runs = await sf.runs.list_async(state="running")`
</script>

<template>
  <DocLayout
    title="Runs"
    description="The sf.runs module, and the Run, CandidateRun and RunProgress values it returns."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Whenever you call <code>sf.evaluate()</code>, the
      <RouterLink to="/learn/engine">engine</RouterLink> records the work as a
      <strong>Run</strong>: an id, a state, and an outcome and cost for each candidate.
      <code>report.run_id</code> tells you which Run a report came from. The <code>sf.runs</code>
      module lists those Runs and reopens them later, from any notebook or machine you are signed in
      on, for up to 30 days, on the hosted engine or your own stack.
    </p>

    <p>
      It helps to keep <code>sf.runs</code> and
      <RouterLink to="/sf-client/api/reports">sf.reports</RouterLink> apart. A Run is what the engine
      knows about an evaluation: its state, its costs, and how each candidate turned out, visible from
      anywhere you are signed in. The results themselves (the model output, the grades, the full
      <RouterLink to="/sf-client/api/reports">Report</RouterLink>) are saved only on the machine that
      ran the evaluation. <code>Run.report()</code> joins the two, reopening that saved Report for a
      Run. The
      <RouterLink to="/sf-client/guides/managing-experiments">Managing experiments</RouterLink> guide
      walks through the whole workflow.
    </p>

    <Note
      >the ids, timestamps and costs in the examples below are made up. Your own Runs will show
      different values.</Note
    >

    <h2>Finding your Runs</h2>

    <p>
      <code>sf.runs.list()</code> gives you your Runs, newest first, and makes no model calls. Pass
      <code>state</code> to narrow to active work, or <code>since</code> for recent Runs.
    </p>

    <h3>sf.runs.list(*, state=None, since=None, limit=50)</h3>

    <p>
      Returns a <code>list[Run]</code>, newest first: at most <code>limit</code> of them, created at or
      after <code>since</code>, in the given <code>state</code>. <code>since</code> has to be a
      <strong>timezone-aware</strong> datetime, and a naive one raises <code>ValueError</code>.
      <code>limit</code> has to be at least <code>1</code>. If the engine does not serve Runs, you get
      an <code>ExecutionError</code> with <code>code="runs_unavailable"</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="list"><NbTextOut :text="listOut" /></NbCell>
    </div>

    <div class="not-prose">
      <NbCell :count="2" :code="filter"><NbTextOut :text="filterOut" /></NbCell>
    </div>

    <h3>sf.runs.get(run_id)</h3>

    <p>
      Returns one of your Runs by its id, for example <code>sf.runs.get(report.run_id)</code>. If the
      id is unknown, or belongs to someone else, you get a <code>KeyError</code>. If the engine does
      not serve Runs, you get an <code>ExecutionError</code> with
      <code>code="runs_unavailable"</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="get"><NbTextOut :text="getOut" /></NbCell>
    </div>

    <h3>Async twins</h3>

    <p>
      <code>sf.runs.list_async(...)</code> and <code>sf.runs.get_async(run_id)</code> take the same
      arguments and return the same types, without blocking the event loop.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="asyncTwins" />
    </div>

    <h2>Run</h2>

    <p>
      A <code>Run</code> is a <strong>frozen snapshot</strong>. Its methods go back to the engine and
      hand you a fresh snapshot or value, so the one you are holding never changes.
    </p>

    <table>
      <thead>
        <tr>
          <th>Attribute</th>
          <th>Type</th>
          <th>What it is</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>id</code></td>
          <td><code>str</code></td>
          <td>The <code>run_id</code>, e.g. <code>"run_a1b2…c5d6"</code>. Same value as <code>report.run_id</code>.</td>
        </tr>
        <tr>
          <td><code>state</code></td>
          <td><code>RunState</code></td>
          <td>
            <code>"running"</code> until every candidate has finished, then one of
            <code>"complete"</code>, <code>"partial"</code>, <code>"errored"</code>,
            <code>"canceled"</code> or <code>"interrupted"</code>.
          </td>
        </tr>
        <tr>
          <td><code>created_at</code></td>
          <td><code>datetime</code></td>
          <td>When the Run was registered (timezone-aware, UTC).</td>
        </tr>
        <tr>
          <td><code>finished_at</code></td>
          <td><code>datetime | None</code></td>
          <td><code>None</code> while the Run is running.</td>
        </tr>
        <tr>
          <td><code>benchmark</code></td>
          <td><code>str</code></td>
          <td>The benchmark id the Run evaluated, e.g. <code>"ifeval"</code>.</td>
        </tr>
        <tr>
          <td><code>candidates</code></td>
          <td><code>tuple[CandidateRun, ...]</code></td>
          <td>One <code>CandidateRun</code> per candidate, in evaluation order.</td>
        </tr>
        <tr>
          <td><code>cost_usd</code></td>
          <td><code>Decimal | None</code></td>
          <td>
            Property: the sum of the candidates' known costs; <code>None</code> when none is known
            yet.
          </td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="5" :code="candidate"><NbTextOut :text="candidateOut" /></NbCell>
    </div>

    <h3>Methods</h3>

    <table>
      <thead>
        <tr>
          <th>Method</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>refresh() -> Run</code></td>
          <td>The Run as the engine has it right now, returned as a new snapshot.</td>
        </tr>
        <tr>
          <td><code>progress() -> RunProgress</code></td>
          <td>Reads the engine again and reports candidates <code>done</code> of <code>total</code> and the spend known so far.</td>
        </tr>
        <tr>
          <td><code>wait(*, timeout=None) -> Run</code></td>
          <td>
            Polls the engine until the Run finishes and returns it; a finished Run returns at once.
            Raises <code>TimeoutError</code> when it is still running after <code>timeout</code>
            seconds.
          </td>
        </tr>
        <tr>
          <td><code>report() -> Report</code></td>
          <td>
            Reopens the Run's <RouterLink to="/sf-client/api/reports">Report</RouterLink> from the
            results saved on this machine. See the error codes below.
          </td>
        </tr>
        <tr>
          <td><code>cancel() -> None</code></td>
          <td>
            Stops every candidate still running and refuses the Run's later starts
            (<code>run_canceled</code>). It is idempotent, so calling it on a Run that has already
            finished does nothing.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      <code>progress()</code> counts the finished candidates and the spend known so far without
      waiting:
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="progress"><NbTextOut :text="progressOut" /></NbCell>
    </div>

    <p>
      <code>wait()</code> holds the cell and polls the engine until the Run reaches a final state,
      backing off from one second up to ten. A common pattern combines all three:
    </p>

    <div class="not-prose">
      <NbCell :count="7" :code="wait" />
    </div>

    <p>Equivalently, with no timeout:</p>

    <div class="not-prose">
      <NbCell :count="8" :code="oneLiner" />
    </div>

    <p>
      <code>report()</code> reads the results saved on <strong>this machine</strong>, not the engine,
      because the engine never keeps the model output. It raises
      <RouterLink to="/sf-client/api/errors">ExecutionError</RouterLink> in these cases:
    </p>

    <table>
      <thead>
        <tr>
          <th><code>code</code></th>
          <th>When</th>
          <th>What to do</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>run_not_finished</code></td>
          <td>The Run is still running.</td>
          <td>Call <code>run.wait()</code> first.</td>
        </tr>
        <tr>
          <td><code>results_not_local</code></td>
          <td>Another machine ran the evaluation.</td>
          <td>Open the Report on the machine that ran it.</td>
        </tr>
        <tr>
          <td><code>candidates_failed</code></td>
          <td>A candidate did not succeed.</td>
          <td>Read the partial Report on <code>exc.partial_report</code>.</td>
        </tr>
      </tbody>
    </table>

    <h2>CandidateRun</h2>

    <p>
      One candidate within a Run. <code>cost_usd</code> stays <code>None</code> while the cost is
      unknown, and for a lost candidate it stays <code>None</code> for good.
    </p>

    <table>
      <thead>
        <tr>
          <th>Attribute</th>
          <th>Type</th>
          <th>What it is</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>name</code></td>
          <td><code>str</code></td>
          <td>The candidate's name, e.g. <code>"gemini-3-flash-preview"</code>.</td>
        </tr>
        <tr>
          <td><code>state</code></td>
          <td><code>CandidateState</code></td>
          <td>
            One of <code>"pending"</code>, <code>"scheduled"</code>, <code>"running"</code>,
            <code>"succeeded"</code>, <code>"failed"</code>, <code>"timed_out"</code>,
            <code>"stopped"</code> or <code>"lost"</code>.
          </td>
        </tr>
        <tr>
          <td><code>cost_usd</code></td>
          <td><code>Decimal | None</code></td>
          <td>The candidate's cost; <code>None</code> if unknown or lost.</td>
        </tr>
        <tr>
          <td><code>error_code</code></td>
          <td><code>str | None</code></td>
          <td>The failure code if the candidate did not succeed, e.g. <code>"run_failed"</code>.</td>
        </tr>
      </tbody>
    </table>

    <Note
      >on a <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink> the
      per-attempt id is <code>attempt_id</code>. <code>CandidateResult.run_id</code> is its
      deprecated old name, and is not <code>Run.id</code> / <code>report.run_id</code>.</Note
    >

    <h2>RunProgress</h2>

    <p>
      What <code>Run.progress()</code> returns: how far a Run has got, and the spend known so far.
    </p>

    <table>
      <thead>
        <tr>
          <th>Attribute</th>
          <th>Type</th>
          <th>What it is</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>done</code></td>
          <td><code>int</code></td>
          <td>Candidates that have finished (any terminal state).</td>
        </tr>
        <tr>
          <td><code>total</code></td>
          <td><code>int</code></td>
          <td>Candidates in the Run.</td>
        </tr>
        <tr>
          <td><code>cost_usd</code></td>
          <td><code>Decimal | None</code></td>
          <td>The spend known so far; <code>None</code> when none is known yet.</td>
        </tr>
      </tbody>
    </table>

    <h2>See also</h2>

    <ul>
      <li>
        <RouterLink to="/sf-client/guides/managing-experiments">Managing experiments</RouterLink> for
        the same workflow explained step by step.
      </li>
      <li>
        <RouterLink to="/sf-client/api/reports">Report</RouterLink> for what
        <code>Run.report()</code> gives you back.
      </li>
      <li>
        <RouterLink to="/sf-client/api/errors">Errors</RouterLink> for
        <code>ExecutionError</code> and its codes.
      </li>
    </ul>
  </DocLayout>
</template>
