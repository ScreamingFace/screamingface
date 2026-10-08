<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const metrics = `dict(candidate.metrics)`
const metricsOut = `{'inst_level_strict_accuracy': 1.0, 'prompt_level_loose_accuracy': 1.0, 'inst_level_loose_accuracy': 1.0, 'pass_rate': 1.0}`

const cases = `case = candidate.cases[0]
case.status, case.grade.score, case.output[:40]`
const casesOut = `('scored', 1.0, 'Raymond III, Count of Tripoli (c. 1140 –')`

const ops = `candidate.operations`
const opsOut = `(OperationInfo(id='op_model_1', kind='model', label='claude-haiku-4.5 answer', depends_on=()),)`
</script>

<template>
  <DocLayout
    title="CandidateResult"
    description="One candidate's outcome and the values it carries (MemberResult, OperationInfo, CaseResult), and the CaseGrade tree behind each case score."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <code>CandidateResult</code> is one candidate's outcome inside a
      <RouterLink to="/sf-client/api/reports">Report</RouterLink>. The candidate is whatever
      <RouterLink to="/sf-client/api/recipes">recipe</RouterLink> you evaluated — a Model, a Fusion,
      or a Pipeline. This page covers <code>CandidateResult</code> itself, alongside
      <code>MemberResult</code> for one member of a fusion, <code>OperationInfo</code> for a step
      that ran, and <code>CaseResult</code> for one graded case. Every example below reads from a
      <code>candidate</code> pulled off a report with <code>report.candidates.only</code>.
    </p>

    <h2>CandidateResult</h2>

    <p>
      A <code>CandidateResult</code> is one candidate's outcome. A higher <code>score</code> is
      always better, whatever the benchmark measures.
    </p>

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
          <td><code>name</code></td>
          <td><code>str</code></td>
          <td>The recipe's name, unique within the report.</td>
        </tr>
        <tr>
          <td><code>kind</code></td>
          <td><code>str</code></td>
          <td>
            One of <code>model</code>, <code>fusion</code>, <code>pipeline</code>,
            <code>corrective_loop</code> or <code>self_corrective</code>.
          </td>
        </tr>
        <tr>
          <td><code>score</code></td>
          <td><code>float&nbsp;|&nbsp;None</code></td>
          <td>
            The headline number, or <code>None</code> when the candidate failed or was not scored.
          </td>
        </tr>
        <tr>
          <td><code>coverage</code></td>
          <td><code>float</code></td>
          <td>
            How much of the selected case set the score was computed from, between 0 and 1. Below
            <code>1.0</code> the engine excluded ungraded cases and the score is a partial result
            over the rest.
          </td>
        </tr>
        <tr>
          <td><code>metrics</code></td>
          <td><code>Mapping[str, float]</code></td>
          <td>
            The benchmark's individual measures. Empty when <code>score</code> is <code>None</code>:
            an unscored candidate cannot carry metrics. Never contains a <code>coverage</code> key,
            which is the field above instead.
          </td>
        </tr>
        <tr>
          <td><code>benchmark</code></td>
          <td><code>BenchmarkInfo</code></td>
          <td>
            The benchmark identity this candidate ran against, pinned to its revision. The report
            carries the same value.
          </td>
        </tr>
        <tr>
          <td><code>cases</code></td>
          <td>sequence of <code>CaseResult</code></td>
          <td>
            One entry per selected case, carrying its status, the prompt, the answer, and the grade.
          </td>
        </tr>
        <tr>
          <td><code>url4</code></td>
          <td><code>Url4</code></td>
          <td>
            The complete expression that executed, as a <code>str</code> subclass whose
            <code>to_python()</code> returns editable client code. See the
            <RouterLink to="/sf-client/guides/reproduce-and-share">url4 guide</RouterLink>.
          </td>
        </tr>
        <tr>
          <td><code>models</code></td>
          <td><code>tuple[str, ...]</code></td>
          <td>Every distinct model route this candidate used. Unique, and never empty.</td>
        </tr>
        <tr>
          <td><code>operations</code></td>
          <td><code>tuple[OperationInfo, ...]</code></td>
          <td>The steps that ran, as an acyclic graph. Never empty.</td>
        </tr>
        <tr>
          <td><code>members</code></td>
          <td><code>tuple[MemberResult, ...]</code></td>
          <td>
            The candidate's direct members. Always empty for a <code>model</code>,
            <code>pipeline</code> or <code>self_corrective</code> candidate; at least one entry for
            a <code>fusion</code>; at least two for a <code>corrective_loop</code>.
          </td>
        </tr>
        <tr>
          <td><code>failures</code></td>
          <td><code>tuple[Failure, ...]</code></td>
          <td>
            This candidate's own failures. A scored candidate can carry them: the run finished with
            warnings worth reading. None of them names a case, since a candidate-level failure is
            never case-specific.
          </td>
        </tr>
        <tr>
          <td><code>usage</code></td>
          <td><code>Usage</code></td>
          <td>This candidate's accounting.</td>
        </tr>
        <tr>
          <td><code>run_id</code></td>
          <td><code>str</code></td>
          <td>Engine-assigned identifier for this candidate's execution.</td>
        </tr>
        <tr>
          <td><code>started_at</code> / <code>completed_at</code> / <code>duration_ms</code></td>
          <td><code>datetime</code> / <code>int</code></td>
          <td>When it ran and for how long.</td>
        </tr>
        <tr>
          <td><code>answer_seed</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>
            The answer seed the run used. <code>None</code> for an unseeded run. <code>submit</code>
            sends it with the score, and a reproduction runs with it.
          </td>
        </tr>
        <tr>
          <td><code>frozen_copy_id</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            The id of the frozen copy that a run made with <code>capture=True</code> opened.
            <code>None</code> when the run was not captured or the copy did not open.
          </td>
        </tr>
        <tr>
          <td><code>capture_status</code></td>
          <td><code>"complete"&nbsp;|&nbsp;"partial"&nbsp;|&nbsp;None</code></td>
          <td>
            Whether the copy holds the whole run. <code>None</code> means unknown, not partial.
            <code>submit</code> sends both fields with the score. See
            <RouterLink to="/learn/caching">Reproducing a submission</RouterLink>.
          </td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="7" :code="metrics"><NbTextOut :text="metricsOut" /></NbCell>
    </div>

    <p>
      <code>score</code> and <code>coverage</code> together describe four outcomes, and the notebook
      card labels each one: a score at full coverage and no failures is complete; a score with
      failures completed with warnings; a score at coverage below <code>1.0</code> is partial; and
      no score at all means no aggregate was available.
    </p>

    <h3>cases</h3>

    <p>
      <code>candidate.cases</code> is a read-only sequence of <code>CaseResult</code> values, one
      per selected case. Each carries a <code>status</code> of <code>scored</code>,
      <code>refused</code> or <code>failed</code>, the case <code>input</code>, the candidate's
      <code>output</code>, and a <code>CaseGrade</code> holding the individual checks behind the
      score. A refused case is still graded, so a provider refusal is measured rather than dropped.
    </p>

    <div class="not-prose">
      <NbCell :count="8" :code="cases"><NbTextOut :text="casesOut" /></NbCell>
    </div>

    <h2>CaseResult</h2>

    <p>
      A <code>CaseResult</code> is the complete retained result for one selected case. Its
      <code>status</code> records the closed outcome, and the remaining fields carry the prompt, the
      answer, the grade, and anything that went wrong. A scored case carries an
      <code>output</code> and a numeric <code>grade</code> and no failures; a refused case carries a
      <code>refusal</code> and no output; a failed case carries <code>failures</code> and no numeric
      grade.
    </p>

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
          <td><code>status</code></td>
          <td><code>str</code></td>
          <td>
            The closed outcome: <code>scored</code>, <code>refused</code> or <code>failed</code>.
          </td>
        </tr>
        <tr>
          <td><code>case_id</code></td>
          <td><code>int&nbsp;|&nbsp;str</code></td>
          <td>The benchmark's identifier for this case.</td>
        </tr>
        <tr>
          <td><code>input</code></td>
          <td><code>str</code></td>
          <td>The case prompt as it was sent, structured multi-turn cases included.</td>
        </tr>
        <tr>
          <td><code>output</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>The candidate's answer, or <code>None</code> when it refused or failed.</td>
        </tr>
        <tr>
          <td><code>finish_reason</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>Why generation stopped, when the engine reported it.</td>
        </tr>
        <tr>
          <td><code>refusal</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>The provider's refusal message, set only on a refused case.</td>
        </tr>
        <tr>
          <td><code>stop_reason</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            For a multi-round case, why the loop stopped: <code>passed</code> or
            <code>max_rounds</code>. <code>None</code> for a single-round case.
          </td>
        </tr>
        <tr>
          <td><code>rounds_executed</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>
            How many rounds ran, present together with <code>stop_reason</code> and
            <code>None</code> otherwise.
          </td>
        </tr>
        <tr>
          <td><code>grade</code></td>
          <td><code>CaseGrade&nbsp;|&nbsp;None</code></td>
          <td>The grade behind the case score. <code>None</code> when the case was not graded.</td>
        </tr>
        <tr>
          <td><code>failures</code></td>
          <td><code>tuple[Failure, ...]</code></td>
          <td>This case's own failures, each naming this case. Empty when nothing went wrong.</td>
        </tr>
        <tr>
          <td><code>operations</code></td>
          <td><code>tuple[CaseOperation, ...]&nbsp;|&nbsp;None</code></td>
          <td>
            The per-operation outputs captured during the run, or <code>None</code> when the engine
            attributed none. See <a href="#case-operation">CaseOperation</a> below.
          </td>
        </tr>
        <tr>
          <td><code>metadata</code></td>
          <td><code>Mapping[str, object]</code></td>
          <td>Anything else the engine recorded with the case. Empty when it recorded nothing.</td>
        </tr>
      </tbody>
    </table>

    <h2 id="case-operation">CaseOperation</h2>

    <p>
      A <code>CaseOperation</code> carries one operation's captured terminal output for a case: the
      member or synthesis text the engine attributed to that step's stable operation id, so a
      fusion's contribution can be read back from a saved report. Its <code>output</code> and
      <code>finish_reason</code> stay <code>None</code> when the engine could not attribute the
      output unambiguously. Reach these through <code>CaseResult.operations</code>.
    </p>

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
          <td><code>operation_id</code></td>
          <td><code>str</code></td>
          <td>The step this output belongs to, matching an <code>OperationInfo.id</code>.</td>
        </tr>
        <tr>
          <td><code>output</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>The step's terminal output, or <code>None</code> when it was not attributed.</td>
        </tr>
        <tr>
          <td><code>finish_reason</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>Why that step stopped, or <code>None</code> when it was not attributed.</td>
        </tr>
      </tbody>
    </table>

    <h2>How a case is graded</h2>

    <p>
      A <code>CaseResult</code>'s <code>grade</code> is a <code>CaseGrade</code>, and it is the top
      of a small tree. A grade holds ordered <code>Check</code>s; each check holds the
      <code>Evidence</code> gathered for it; each piece of evidence names the
      <code>EvidenceProducer</code> that observed it. Reading down takes you from one case score to
      the exact observation a benchmark accepted or rejected.
    </p>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        viewBox="0 0 740 130"
        role="img"
        aria-label="A CaseGrade holds many ordered Checks; each Check holds the Evidence gathered for it; each Evidence names the one EvidenceProducer that observed it."
        style="width: 100%; height: auto; font-family: var(--f-mono)"
      >
        <defs>
          <marker
            id="cg-arrow"
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
          x="8"
          y="40"
          width="150"
          height="54"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="83" y="64" text-anchor="middle" style="fill: var(--text); font-size: 13px">
          CaseGrade
        </text>
        <text x="83" y="82" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          the case score
        </text>

        <rect
          x="204"
          y="40"
          width="150"
          height="54"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="279" y="64" text-anchor="middle" style="fill: var(--text); font-size: 13px">
          Check
        </text>
        <text x="279" y="82" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          one rule
        </text>

        <rect
          x="400"
          y="40"
          width="150"
          height="54"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="475" y="64" text-anchor="middle" style="fill: var(--text); font-size: 13px">
          Evidence
        </text>
        <text x="475" y="82" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          one observation
        </text>

        <rect
          x="580"
          y="40"
          width="152"
          height="54"
          style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1"
        />
        <text x="656" y="64" text-anchor="middle" style="fill: var(--text); font-size: 11px">
          EvidenceProducer
        </text>
        <text x="656" y="82" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          the observer
        </text>

        <g style="stroke: var(--text-2); stroke-width: 1; fill: none">
          <path d="M158 67 H204" marker-end="url(#cg-arrow)" />
          <path d="M354 67 H400" marker-end="url(#cg-arrow)" />
          <path d="M550 67 H580" marker-end="url(#cg-arrow)" />
        </g>
        <text x="181" y="59" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          many
        </text>
        <text x="377" y="59" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          many
        </text>
        <text x="565" y="59" text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          one
        </text>
      </svg>
    </figure>

    <h2>CaseGrade</h2>

    <p>
      The aggregate for one case: a <code>score</code>, the <code>method</code> that produced it,
      and the ordered <code>Check</code>s it was built from.
    </p>

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
          <td><code>method</code></td>
          <td><code>str</code></td>
          <td>How the score was produced.</td>
        </tr>
        <tr>
          <td><code>score</code></td>
          <td><code>float&nbsp;|&nbsp;None</code></td>
          <td>The case's score, or <code>None</code> when no aggregate was available.</td>
        </tr>
        <tr>
          <td><code>checks</code></td>
          <td><code>tuple[Check, ...]</code></td>
          <td>The ordered checks behind the score.</td>
        </tr>
      </tbody>
    </table>

    <h2>Check</h2>

    <p>
      One ordered grading check and all the <code>Evidence</code> gathered for it. The benchmark
      owns the check; the Client only reports what it returned, so match on <code>id</code> rather
      than on <code>label</code>.
    </p>

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
          <td><code>type</code></td>
          <td><code>str</code></td>
          <td>The check's kind.</td>
        </tr>
        <tr>
          <td><code>id</code></td>
          <td><code>str</code></td>
          <td>Identifies the check within the case. The stable value to match on.</td>
        </tr>
        <tr>
          <td><code>label</code></td>
          <td><code>str</code></td>
          <td>A human-readable description of what it checks.</td>
        </tr>
        <tr>
          <td><code>evidence</code></td>
          <td><code>tuple[Evidence, ...]</code></td>
          <td>The observations gathered for it, in sequence order.</td>
        </tr>
        <tr>
          <td><code>outcome</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            <code>MET</code> or <code>UNMET</code>, or <code>None</code> when it produced no
            verdict.
          </td>
        </tr>
        <tr>
          <td><code>score</code></td>
          <td><code>float&nbsp;|&nbsp;None</code></td>
          <td>The check's own score, where it has one.</td>
        </tr>
      </tbody>
    </table>

    <h2>Evidence</h2>

    <p>
      One exact observation a check accepted or rejected. When <code>valid</code> is
      <code>False</code> the observation could not be read, so it carries no
      <code>outcome</code> and no <code>explanation</code> — that state records a gap rather than a
      verdict.
    </p>

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
          <td><code>sequence</code></td>
          <td><code>int</code></td>
          <td>Position within the check, unique and 1-based. This is the true order.</td>
        </tr>
        <tr>
          <td><code>producer</code></td>
          <td><code>EvidenceProducer</code></td>
          <td>What observed it.</td>
        </tr>
        <tr>
          <td><code>valid</code></td>
          <td><code>bool</code></td>
          <td>Whether the observation could be read at all.</td>
        </tr>
        <tr>
          <td><code>outcome</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            <code>MET</code>, <code>UNMET</code>, <code>PASS</code> or <code>FAIL</code>. Unset on
            invalid evidence.
          </td>
        </tr>
        <tr>
          <td><code>explanation</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>Why, when the producer gave a reason. Unset on invalid evidence.</td>
        </tr>
        <tr>
          <td><code>raw_output</code></td>
          <td><code>object</code></td>
          <td>The producer's raw output, as it was returned.</td>
        </tr>
        <tr>
          <td><code>metadata</code></td>
          <td><code>Mapping</code></td>
          <td>Anything else recorded with the observation.</td>
        </tr>
      </tbody>
    </table>

    <h2>EvidenceProducer</h2>

    <p>
      The producer the engine credits with one observation: what looked at the output and reported.
    </p>

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
          <td><code>type</code></td>
          <td><code>str</code></td>
          <td>The kind of producer, such as the grader that ran.</td>
        </tr>
        <tr>
          <td><code>id</code></td>
          <td><code>str</code></td>
          <td>Identifies the producer.</td>
        </tr>
      </tbody>
    </table>

    <h2>MemberResult</h2>

    <p>
      A <code>MemberResult</code> is one direct member of a fusion, held as a compact view: enough
      to see what the member cost and whether it failed, without repeating the full candidate
      structure. Members carry no score, because only the fusion's final answer is graded.
    </p>

    <p>
      Its runtime fields are <code>None</code> until the engine attributes work to the member's
      operation id. That is a different statement from an empty value: <code>None</code> means the
      attribution was unavailable, while an empty tuple means it arrived and reported nothing.
    </p>

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
          <td><code>name</code></td>
          <td><code>str</code></td>
          <td>
            The member recipe's display name. Two siblings can share one, for instance the same
            model reached through two providers, so identity is <code>operation_id</code> rather
            than this.
          </td>
        </tr>
        <tr>
          <td><code>kind</code></td>
          <td><code>str</code></td>
          <td>
            One of <code>model</code>, <code>fusion</code>, <code>pipeline</code>,
            <code>corrective_loop</code> or <code>self_corrective</code>.
          </td>
        </tr>
        <tr>
          <td><code>models</code></td>
          <td><code>tuple[str, ...]</code></td>
          <td>The routes this member used.</td>
        </tr>
        <tr>
          <td><code>operation_id</code></td>
          <td><code>str</code></td>
          <td>Links this member to an entry in the candidate's <code>operations</code>.</td>
        </tr>
        <tr>
          <td><code>failures</code></td>
          <td><code>tuple[Failure, ...]&nbsp;|&nbsp;None</code></td>
          <td>
            This member's failures, which also appear in <code>report.failures</code>.
            <code>None</code> when the engine attributed nothing to this member.
          </td>
        </tr>
        <tr>
          <td><code>duration_ms</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>How long the member took, when the engine reported it.</td>
        </tr>
        <tr>
          <td><code>usage</code></td>
          <td><code>Usage&nbsp;|&nbsp;None</code></td>
          <td>This member's accounting, or <code>None</code> when it was not attributed.</td>
        </tr>
      </tbody>
    </table>

    <h2>OperationInfo</h2>

    <p>
      An <code>OperationInfo</code> is one step in a candidate's compiled graph. Reading
      <code>operations</code> shows what actually ran and in what order, which is how a fusion's
      members can be seen executing before its synthesis. See the
      <RouterLink to="/sf-client/guides/reproduce-and-share">url4 guide</RouterLink> for reading the
      same plan as a url4 expression.
    </p>

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
          <td>Unique within the candidate. This is what <code>depends_on</code> refers to.</td>
        </tr>
        <tr>
          <td><code>kind</code></td>
          <td><code>str</code></td>
          <td>What sort of step it was, for example <code>model</code>.</td>
        </tr>
        <tr>
          <td><code>label</code></td>
          <td><code>str</code></td>
          <td>Human-readable description, such as <code>claude-haiku-4.5 answer</code>.</td>
        </tr>
        <tr>
          <td><code>depends_on</code></td>
          <td><code>tuple[str, ...]</code></td>
          <td>
            Ids of the steps that had to finish first. Empty for a step with no prerequisites.
          </td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="9" :code="ops"><NbTextOut :text="opsOut" /></NbCell>
    </div>

    <p>
      The operations of a candidate form an acyclic graph: ids are unique, every dependency names a
      step that exists, and no step can depend on itself.
    </p>
  </DocLayout>
</template>
