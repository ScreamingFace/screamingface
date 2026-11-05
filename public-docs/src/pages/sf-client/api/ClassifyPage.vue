<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import ThemedDiagram from '@/components/ui/ThemedDiagram.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const call = `import screamingface as sf
result = sf.classify("byom_<id>/classifier_v1", "I love this")
result`
const callOut = `Classification(model='byom_<id>/classifier_v1', contract='classification-scores-v1',
               scores=(LabelScore(label='POSITIVE', score=0.8),
                       LabelScore(label='NEGATIVE', score=0.2)))`
const missing = `sf.classify("byom_abc/classifier_v1", "hello")`
const missingOut = `PlanningError: The SF Engine refused the classification: no classifier with this model ID is available to the caller`
const tooLong = `sf.classify("byom_abc/classifier_v1", "x" * 9000)`
const tooLongOut = `PlanningError: The classification request is 9088 bytes once encoded; the SF Engine takes at most 8192`
</script>

<template>
  <DocLayout
    title="Classify"
    description="Send one text to a text classifier and read its label scores."
    :navigation="navigation"
    :version="version"
  >
    <p>
      <code>sf.classify(model, input)</code> and <code>Client.classify(model, input)</code> send one
      text to a text classifier that you configured on your own endpoint, through the engine's
      <code>/classify</code>, and return a <code>Classification</code>. The call is synchronous:
      <code>AsyncClient</code> has no <code>classify</code>. An engine without
      <code>/classify</code> raises <code>EngineCapabilityError</code>.
    </p>

    <ThemedDiagram
      name="sf-client-0-1-11-classify-flow"
      alt="Flow: the Client sends the classify call to the Engine, which reaches your classifier endpoint through the AI Gateway, using the key you stored with sf.connect."
      caption="The path of sf.classify from the Client to your classifier endpoint."
    />

    <h2>The call</h2>

    <table>
      <thead>
        <tr>
          <th>Signature</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.classify(model: str, input: str) -&gt; Classification</code></td>
          <td>
            Classifies <code>input</code> with the classifier named by <code>model</code>, a model
            id such as <code>byom_&lt;id&gt;/classifier_v1</code>.
            <code>Client.classify</code> takes the same arguments on a Client you built.
          </td>
        </tr>
      </tbody>
    </table>

    <CodeBlock :code="call" language="python" />
    <CodeBlock :code="callOut" language="text" />

    <h2>What the classifier endpoint receives</h2>

    <p>
      The engine sends <code>{"inputs": &lt;input&gt;}</code> to the endpoint's request path with
      the bearer key stored by <code>sf.connect(&lt;endpoint id&gt;, api_key=...)</code>. The
      response is a flat list or a single-batch list of <code>{"label", "score"}</code> objects with
      scores from 0 to 1.
    </p>

    <h2>What it returns</h2>

    <table>
      <thead>
        <tr>
          <th>Type</th>
          <th>Field</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td rowspan="3"><code>Classification</code></td>
          <td><code>model</code></td>
          <td>The classifier model id that answered.</td>
        </tr>
        <tr>
          <td><code>contract</code></td>
          <td>The result contract. It is <code>classification-scores-v1</code> today.</td>
        </tr>
        <tr>
          <td><code>scores</code></td>
          <td>
            A tuple of <code>LabelScore</code> values in the classifier's own order, ties included.
          </td>
        </tr>
        <tr>
          <td rowspan="2"><code>LabelScore</code></td>
          <td><code>label</code></td>
          <td>The label, a <code>str</code>.</td>
        </tr>
        <tr>
          <td><code>score</code></td>
          <td>The score for that label, a <code>float</code>.</td>
        </tr>
      </tbody>
    </table>

    <h2>Limits and timing</h2>

    <ul>
      <li>
        <strong>Size:</strong> The encoded request may be at most 8,192 bytes. A longer input raises
        <code>PlanningError</code> with the code <code>uri_too_long</code> before any call.
      </li>
      <li>
        <strong>Time:</strong> The call asks the engine to wait at most 30 seconds and reads the
        response for 45 seconds.
      </li>
      <li>
        <strong>Retries:</strong> The SDK never sends a classification again, neither after a
        sign-in nor through a redirect. A result that the engine spilled to an artifact is fetched
        only from the engine's exact signed artifact path, and that fetch alone is sent once more
        when a Cloudflare Access sign-in interrupted it.
      </li>
    </ul>

    <h2>Errors</h2>

    <table>
      <thead>
        <tr>
          <th>Error and code</th>
          <th>Raised when</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>PlanningError: uri_too_long</code></td>
          <td>The encoded request is larger than 8,192 bytes. Raised before any call.</td>
        </tr>
        <tr>
          <td><code>PlanningError: malformed_source</code></td>
          <td>
            The model id or the input holds a character that UTF-8 cannot encode. Raised before any
            call.
          </td>
        </tr>
        <tr>
          <td><code>PlanningError: classifier_not_found</code></td>
          <td>
            The engine refused the call: no classifier with this model id is available to you.
          </td>
        </tr>
        <tr>
          <td><code>ExecutionError: profile_not_found</code></td>
          <td>
            No key is connected for the endpoint. Connect one with
            <code>sf.connect(&lt;endpoint id&gt;, api_key=...)</code>. The error says the
            classification may have run and been billed.
          </td>
        </tr>
        <tr>
          <td><code>EngineCapabilityError</code></td>
          <td>The engine does not serve <code>/classify</code>.</td>
        </tr>
      </tbody>
    </table>

    <p>
      An error is <code>retryable</code> only when nothing ran: the engine was not reached, a rate
      limit, or a refusal at admission. An engine timeout, any other server failure, a connection
      lost after the request was sent and a result that could not be read are not retryable, because
      classifying again runs the classifier again and may bill it again. See
      <RouterLink to="/sf-client/api/errors">Errors and warnings</RouterLink> for the attributes
      every error carries.
    </p>

    <CodeBlock :code="missing" language="python" />
    <CodeBlock :code="missingOut" language="text" />

    <CodeBlock :code="tooLong" language="python" />
    <CodeBlock :code="tooLongOut" language="text" />
  </DocLayout>
</template>
