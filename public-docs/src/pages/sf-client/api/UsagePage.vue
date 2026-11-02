<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const usage = `report.usage`
const usageOut = `Usage(input_tokens=2161, output_tokens=721, cache_read_tokens=0, cache_creation_tokens=0, reasoning_tokens=0, cost_usd=Decimal('0.0024508'))`
</script>

<template>
  <DocLayout
    title="Usage"
    description="Usage for token and cost accounting, and Failure for anything that went wrong."
    :navigation="navigation"
    :version="version"
  >
    <p>
      This page covers <code>Usage</code>, the token and cost accounting a
      <RouterLink to="/sf-client/api/reports">Report</RouterLink> and each
      <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink> carry, and
      <code>Failure</code>, the typed record of anything that went wrong. The
      <code>report</code> the examples read from comes from the
      <RouterLink to="/sf-client/api/reports">Report</RouterLink> page.
    </p>

    <h2>Usage</h2>

    <p>
      A <code>Usage</code> holds the token and cost accounting for one subtree of a run. Every field
      is optional, because a provider that does not report a number leaves it as
      <code>None</code> rather than guessing zero.
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
          <td><code>input_tokens</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>Tokens sent.</td>
        </tr>
        <tr>
          <td><code>output_tokens</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>Tokens generated.</td>
        </tr>
        <tr>
          <td><code>cache_read_tokens</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>Tokens served from a provider cache.</td>
        </tr>
        <tr>
          <td><code>cache_creation_tokens</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>Tokens written into a provider cache.</td>
        </tr>
        <tr>
          <td><code>reasoning_tokens</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>Tokens spent on reasoning, where the provider separates them.</td>
        </tr>
        <tr>
          <td><code>cost_usd</code></td>
          <td><code>Decimal&nbsp;|&nbsp;None</code></td>
          <td>
            Money, as a <code>Decimal</code> so it never loses precision. Accepts a string or a
            <code>Decimal</code> on construction.
          </td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="10" :code="usage"><NbTextOut :text="usageOut" /></NbCell>
    </div>

    <p>
      A model call answered from the request cache reports 0 tokens and a
      <code>cost_usd</code> of <code>Decimal('0')</code>. The sample above ran with
      <code>use_cache=False</code>, so every call was fresh. The
      <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink> page lists what
      the cache saved.
    </p>

    <p>
      Summing follows a strict rule: <code>report.usage</code> adds a field across candidates only
      when <em>every</em> candidate reported it. If one candidate leaves <code>cost_usd</code> as
      <code>None</code>, the report's <code>cost_usd</code> is <code>None</code> too, rather than a
      total that silently omits part of the run.
    </p>

    <p>
      <code>to_dict()</code> drops fields that are <code>None</code> and renders
      <code>cost_usd</code> as a string.
    </p>

    <h2>Failure</h2>

    <p>
      A <code>Failure</code> is one typed failure held inside an otherwise valid report. A report
      with failures is still a report, so what succeeded can be read alongside what did not.
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
          <td><code>stage</code></td>
          <td><code>str</code></td>
          <td>
            Where it happened: <code>candidate</code>, <code>grading</code> or
            <code>aggregation</code>.
          </td>
        </tr>
        <tr>
          <td><code>code</code></td>
          <td><code>str</code></td>
          <td>
            Stable machine-readable identifier in lowercase snake_case, such as
            <code>provider_timeout</code>. Match on this rather than on the message.
          </td>
        </tr>
        <tr>
          <td><code>message</code></td>
          <td><code>str</code></td>
          <td>Human-readable explanation. Not stable across versions.</td>
        </tr>
        <tr>
          <td><code>retryable</code></td>
          <td><code>bool&nbsp;|&nbsp;None</code></td>
          <td>
            Whether running the same thing again could plausibly succeed, or <code>None</code> when
            the engine did not say.
          </td>
        </tr>
        <tr>
          <td><code>operation_id</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            Which step failed, matching an <code>OperationInfo.id</code>. <code>None</code> for a
            failure no single step owns.
          </td>
        </tr>
        <tr>
          <td><code>case_id</code></td>
          <td><code>int&nbsp;|&nbsp;str&nbsp;|&nbsp;None</code></td>
          <td>Which case failed, when the failure was specific to one.</td>
        </tr>
        <tr>
          <td><code>metadata</code></td>
          <td><code>Mapping[str, object]</code></td>
          <td>
            Whatever else the engine attached to this failure. Empty when it attached nothing.
          </td>
        </tr>
      </tbody>
    </table>

    <p>A failure reads like this:</p>

    <CodeBlock
      code="Failure(stage='candidate', code='provider_timeout', message='Upstream timed out', retryable=True, operation_id='op-1', case_id='7')"
      language="python"
    />
  </DocLayout>
</template>
