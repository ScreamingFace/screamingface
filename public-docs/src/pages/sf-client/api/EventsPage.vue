<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const watch = `import screamingface as sf

def observe(event: sf.Event) -> None:
    print(event.kind, event.sequence, event.source)

sf.evaluate(recipe, benchmark="ifeval", limit=1, on_event=observe, progress=False)`

const filter = `def observe(event: sf.Event) -> None:
    if isinstance(event, sf.events.Usage):
        print(event.model, event.usage.output_tokens, event.usage.cost_usd)`
</script>

<template>
  <DocLayout
    title="Events"
    description="What a run reports through on_event while it is still running."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Passing <code>on_event</code> to
      <RouterLink to="/sf-client/api/clients">evaluate()</RouterLink> gives you a callback that
      fires as the run proceeds, rather than waiting for the
      <RouterLink to="/sf-client/api/reports">Report</RouterLink> at the end. It is how a progress
      display, a log, or a running cost total is built.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="watch" />
    </div>

    <p>
      Five event types arrive: <code>Started</code>, <code>Span</code>, <code>Log</code>,
      <code>Usage</code> and <code>Terminated</code>, with <code>Terminated</code> last. <code>Event</code> is their shared base
      and <code>TerminationError</code> is a value one of them carries.
    </p>

    <h2>Event</h2>

    <p>
      The base every event inherits. These fields are present on all of them, so a callback can sort
      and correlate without knowing which kind it received.
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
          <td><code>kind</code></td>
          <td><code>str</code></td>
          <td>
            Which type this is: <code>started</code>, <code>span</code>, <code>log</code>,
            <code>usage</code> or <code>terminated</code>. A class attribute, not a field.
          </td>
        </tr>
        <tr>
          <td><code>id</code></td>
          <td><code>str</code></td>
          <td>Identifies this event.</td>
        </tr>
        <tr>
          <td><code>run_id</code></td>
          <td><code>str</code></td>
          <td>
            Which run emitted it. Several candidates run concurrently, so this is what separates
            them.
          </td>
        </tr>
        <tr>
          <td><code>sequence</code></td>
          <td><code>int</code></td>
          <td>Order within the run. Events can arrive out of order; this is the true order.</td>
        </tr>
        <tr>
          <td><code>timestamp</code></td>
          <td><code>datetime</code></td>
          <td>When it happened.</td>
        </tr>
        <tr>
          <td><code>source</code></td>
          <td><code>str</code></td>
          <td>Which part of the system emitted it.</td>
        </tr>
        <tr>
          <td><code>traceparent</code> · <code>tracestate</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>W3C trace context, for stitching these into your own tracing.</td>
        </tr>
      </tbody>
    </table>

    <h2>Started</h2>

    <p>A url4 operation began executing. It adds one field:</p>

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
          <td><code>url4</code></td>
          <td><code>str</code></td>
          <td>The expression that is about to run.</td>
        </tr>
      </tbody>
    </table>

    <h2>Span</h2>

    <p>
      One OpenTelemetry span with portable GenAI attributes. This is the event that says what a
      model call cost in time and tokens.
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
          <td><code>name</code> · <code>operation</code></td>
          <td><code>str</code></td>
          <td>What the span covers, and which operation it belongs to.</td>
        </tr>
        <tr>
          <td><code>start</code> · <code>end</code></td>
          <td><code>datetime&nbsp;|&nbsp;None</code></td>
          <td>When it opened and closed. Both unset while it is still open.</td>
        </tr>
        <tr>
          <td><code>status</code> · <code>span_kind</code></td>
          <td><code>str</code></td>
          <td>How it finished, and what sort of span it is.</td>
        </tr>
        <tr>
          <td><code>provider</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>Which provider served the call.</td>
        </tr>
        <tr>
          <td><code>request_model</code> · <code>response_model</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            What was asked for and what answered. They differ when a provider silently substitutes.
          </td>
        </tr>
        <tr>
          <td><code>input_tokens</code> · <code>output_tokens</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>Token counts for this call alone.</td>
        </tr>
        <tr>
          <td><code>finish_reasons</code></td>
          <td><code>tuple[str, ...]</code></td>
          <td>Why generation stopped.</td>
        </tr>
        <tr>
          <td><code>refusal</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>Set when the model declined to answer.</td>
        </tr>
      </tbody>
    </table>

    <h2>Log</h2>

    <p>One log record from the run.</p>

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
          <td><code>body</code></td>
          <td><code>str</code></td>
          <td>The message.</td>
        </tr>
        <tr>
          <td><code>severity_text</code></td>
          <td><code>str</code></td>
          <td>The level as a name.</td>
        </tr>
        <tr>
          <td><code>severity_number</code></td>
          <td><code>int</code></td>
          <td>The same level as a number, which is what you compare against.</td>
        </tr>
      </tbody>
    </table>

    <h2>Usage</h2>

    <Note>
      Two distinct types are called Usage. This one is the event.
      <RouterLink to="/sf-client/api/usage">sf.Usage</RouterLink> is the accounting value, and it is
      what this event's own <code>usage</code> field holds.
    </Note>

    <p>Cost and token accounting, reported as the run spends rather than at the end.</p>

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
          <td><code>usage</code></td>
          <td><code>Usage</code></td>
          <td>
            The accounting value itself, with the same fields as
            <RouterLink to="/sf-client/api/usage">report.usage</RouterLink>.
          </td>
        </tr>
        <tr>
          <td><code>scope</code></td>
          <td><code>str</code></td>
          <td>
            <code>self</code> for this operation alone, or <code>subtree</code> for it and
            everything beneath it. Summing both double-counts.
          </td>
        </tr>
        <tr>
          <td><code>provider</code> · <code>model</code></td>
          <td><code>str</code></td>
          <td>Who was billed and for which model.</td>
        </tr>
        <tr>
          <td><code>pricing_version</code></td>
          <td><code>str</code></td>
          <td>Which price list produced the cost.</td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="2" :code="filter" />
    </div>

    <h2>Terminated</h2>

    <p>The run reached its terminal state. This is the last event.</p>

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
            One of <code>succeeded</code>, <code>failed</code>, <code>stopped</code> or
            <code>timed_out</code>.
          </td>
        </tr>
        <tr>
          <td><code>error</code></td>
          <td><code>TerminationError&nbsp;|&nbsp;None</code></td>
          <td>Why it failed, when it did.</td>
        </tr>
      </tbody>
    </table>

    <h2>TerminationError</h2>

    <p>
      The structured failure a <code>Terminated</code> event carries. It is a plain value, not an
      exception, and not something you raise or catch.
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
          <td><code>code</code></td>
          <td><code>str</code></td>
          <td>Stable identifier to match on.</td>
        </tr>
        <tr>
          <td><code>message</code></td>
          <td><code>str</code></td>
          <td>What went wrong.</td>
        </tr>
        <tr>
          <td><code>permanent</code></td>
          <td><code>bool</code></td>
          <td>Whether retrying is pointless.</td>
        </tr>
      </tbody>
    </table>
  </DocLayout>
</template>
