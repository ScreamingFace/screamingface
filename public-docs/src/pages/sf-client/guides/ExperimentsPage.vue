<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const start = `MODEL = sf.Model("openrouter/google/gemini-3-flash-preview")

report = sf.evaluate(MODEL, benchmark="ifeval", limit=1)
report.run_id`
const startOut = `'run_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'`

const list = `runs = sf.runs.list(limit=10)
[(r.id, r.benchmark, r.state) for r in runs]`
const listOut = `[('run_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6', 'ifeval', 'complete'),
 ('run_0f1e2d3c4b5a69788796a5b4c3d2e1f0', 'medxpert', 'running')]`

const filter = `from datetime import UTC, datetime, timedelta

{
    "running": [r.id for r in sf.runs.list(state="running", limit=10)],
    "last_24h": [r.id for r in sf.runs.list(since=datetime.now(UTC) - timedelta(days=1))],
}`
const filterOut = `{'running': ['run_0f1e2d3c4b5a69788796a5b4c3d2e1f0'],
 'last_24h': ['run_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6', 'run_0f1e2d3c4b5a69788796a5b4c3d2e1f0']}`

const reopen = `run = sf.runs.get(report.run_id).refresh()
progress = run.progress()
{
    "state": run.state,
    "progress": f"{progress.done}/{progress.total} candidates, \${progress.cost_usd}",
    "candidates": [(c.name, c.state, c.error_code) for c in run.candidates],
}`
const reopenOut = `{'state': 'complete',
 'progress': '1/1 candidates, $0.0123',
 'candidates': [('gemini-3-flash-preview', 'succeeded', None)]}`

const wait = `finished = run.wait(timeout=300)
finished.state`
const waitOut = `'complete'`

const report = `reopened = sf.runs.get(run.id)
try:
    recovered = reopened.report()
except sf.ExecutionError as exc:
    recovered = f"{exc.code}: {exc.hint}"
recovered`
const reportOut = `Report(benchmark='ifeval', candidates=['gemini-3-flash-preview'], ok=True)`

const cancel = `run_to_cancel = sf.runs.get("run_0f1e2d3c4b5a69788796a5b4c3d2e1f0")
run_to_cancel.cancel()

sf.runs.get("run_0f1e2d3c4b5a69788796a5b4c3d2e1f0").state`
const cancelOut = `'canceled'`

const unknown = `try:
    sf.runs.get("run_does_not_exist")
except KeyError:
    print("no such Run for this owner")`
const asyncTwins = `run = await sf.runs.get_async(report.run_id)
runs = await sf.runs.list_async(state="running")`
</script>

<template>
  <DocLayout
    title="Managing experiments"
    description="Launch, find, follow, reopen and cancel your runs from any notebook."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Every <code>sf.evaluate(...)</code> creates a
      <RouterLink to="/sf-client/api/runs">Run</RouterLink> on the engine. A Run is the record of one
      experiment: it has an id, a state, and an outcome and cost for each candidate. It outlives the
      cell that launched it, so you can come back to it later. From any notebook or machine you are
      signed in on, for up to 30 days, you can find it by its id, watch its progress, reopen its
      <RouterLink to="/sf-client/api/reports">Report</RouterLink>, or cancel it, whether it ran on the
      hosted engine or your own stack.
    </p>

    <p>
      Listing and inspecting runs make no model calls. Starting an evaluation is the only step that
      costs money, and cancelling needs an explicit <code>run_id</code>.
    </p>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        viewBox="0 0 760 120"
        role="img"
        aria-label="The experiment lifecycle: evaluate creates a Run, which you find with sf.runs.list, reopen with sf.runs.get, follow with progress and wait, and finish by opening its report or cancelling it."
        style="width: 100%; height: auto; font-family: var(--f-mono); font-size: 12px"
      >
        <defs>
          <marker
            id="rn-arrow"
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
        <g style="stroke: var(--text-2); stroke-width: 1.25; fill: none" marker-end="url(#rn-arrow)">
          <path d="M150 50 H196" />
          <path d="M330 50 H376" />
          <path d="M510 50 H556" />
        </g>
        <g style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1">
          <rect x="6" y="26" width="144" height="48" />
          <rect x="196" y="26" width="134" height="48" />
          <rect x="376" y="26" width="134" height="48" />
          <rect x="556" y="26" width="198" height="48" />
        </g>
        <g text-anchor="middle" style="fill: var(--text)">
          <text x="78" y="46">sf.evaluate()</text>
          <text x="263" y="46">sf.runs.list()</text>
          <text x="443" y="46">sf.runs.get()</text>
          <text x="655" y="46">report() / cancel()</text>
        </g>
        <g text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          <text x="78" y="62">creates a Run</text>
          <text x="263" y="62">find it</text>
          <text x="443" y="62">reopen + follow</text>
          <text x="655" y="62">finish or stop</text>
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
        An evaluation creates a Run; you find it, reopen it, follow it, and finish by opening its
        report or cancelling it.
      </figcaption>
    </figure>

    <Note
      >the ids, timestamps and costs in the examples below are made up. Your own Runs will show
      different values.</Note
    >

    <h2>1 · Start an evaluation</h2>

    <p>
      <code>sf.evaluate(...)</code> is the one call that costs money. It returns a
      <RouterLink to="/sf-client/api/reports">Report</RouterLink>, and
      <code>report.run_id</code> is the id of the Run it created.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="start"><NbTextOut :text="startOut" /></NbCell>
    </div>

    <Note
      >if the engine does not serve Runs, the evaluation still works, but <code>report.run_id</code>
      comes back <code>None</code>. Each candidate also has its own <code>attempt_id</code>, which is
      one attempt of one candidate rather than the whole Run. <code>CandidateResult.run_id</code> is
      the old name for that field and is now deprecated.</Note
    >

    <h2>2 · Find your Runs</h2>

    <p>
      <code>sf.runs.list()</code> returns your Runs, newest first. Pass <code>state</code> to find the
      ones still running, or <code>since</code> (a timezone-aware datetime) to look at recent Runs.
      None of this starts any work.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="list"><NbTextOut :text="listOut" /></NbCell>
    </div>

    <div class="not-prose">
      <NbCell :count="3" :code="filter"><NbTextOut :text="filterOut" /></NbCell>
    </div>

    <h2>3 · Reopen a Run and follow its progress</h2>

    <p>
      <code>sf.runs.get(run_id)</code> returns a snapshot that does not update on its own. Call
      <code>run.refresh()</code> to fetch the latest state from the engine. <code>run.progress()</code>
      reports how many candidates have finished and what has been spent so far, without waiting. A
      candidate that did not succeed carries an <code>error_code</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="reopen"><NbTextOut :text="reopenOut" /></NbCell>
    </div>

    <p>
      <code>run.wait()</code> polls until the Run finishes and returns it. It raises
      <code>TimeoutError</code> if the Run is still going after <code>timeout</code> seconds. It blocks
      the cell while it waits, so use it only when you want to wait for the result.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="wait"><NbTextOut :text="waitOut" /></NbCell>
    </div>

    <h2>4 · Open the Run's Report</h2>

    <p>
      <code>Run.report()</code> reads the results saved on this machine, since the engine does not keep
      the model output. It raises
      <RouterLink to="/sf-client/api/errors">ExecutionError</RouterLink> with
      <code>code="run_not_finished"</code> if the Run is still going, and
      <code>code="results_not_local"</code> if a different machine ran it. Catch it and read
      <code>exc.hint</code>, which tells you what to do next.
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="report"><NbTextOut :text="reportOut" /></NbCell>
    </div>

    <h2>5 · Cancel a Run</h2>

    <p>
      Cancelling applies to the whole Run: it stops every candidate still running and refuses the
      Run's later starts (<code>run_canceled</code>). A finished Run is left alone, and calling
      <code>cancel()</code> more than once is harmless. It takes an explicit id on purpose, so pass one
      only when you mean to stop that Run. Once its candidates have stopped, the Run's state reads
      <code>"canceled"</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="7" :code="cancel"><NbTextOut :text="cancelOut" /></NbCell>
    </div>

    <h2>6 · When a Run cannot be read</h2>

    <p>
      <code>sf.runs.get</code> raises <code>KeyError</code> for an unknown id, or another owner's.
      Against an engine that does not serve Runs, <code>sf.runs.list</code> and
      <code>sf.runs.get</code> raise <code>ExecutionError</code> with
      <code>code="runs_unavailable"</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="8" :code="unknown" />
    </div>

    <p>In async code, use the non-blocking twins:</p>

    <div class="not-prose">
      <NbCell :count="9" :code="asyncTwins" />
    </div>

    <h2>See also</h2>

    <ul>
      <li>
        <RouterLink to="/sf-client/api/runs">Runs</RouterLink> for the full
        <code>sf.runs</code> reference.
      </li>
      <li>
        <RouterLink to="/sf-client/guides/running-an-evaluation">Running an evaluation</RouterLink> for
        the call that creates a Run in the first place.
      </li>
      <li>
        <RouterLink to="/sf-client/api/reports">Report</RouterLink> for what
        <code>Run.report()</code> gives you back.
      </li>
    </ul>
  </DocLayout>
</template>
