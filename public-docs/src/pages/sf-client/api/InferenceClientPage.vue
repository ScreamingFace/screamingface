<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'
import plainCallExample from '@/snippets/inference-client/plain_call.py?raw'
import modelPerCallExample from '@/snippets/inference-client/model_per_call.py?raw'
import toolsExample from '@/snippets/inference-client/tools.py?raw'
import streamExample from '@/snippets/inference-client/stream.py?raw'
import asyncCallExample from '@/snippets/inference-client/async_call.py?raw'
import endpointOpenaiExample from '@/snippets/inference-client/endpoint_openai.py?raw'

const inferenceSig = `sf.InferenceClient(model=None, *, client=None)

client.chat.completions.create(
    prompt=None,
    *,
    model=None,
    messages=None,
    tools=None,
    stream=False,
    stream_options=None,
    use_cache=True,
    max_retries=0,
    timeout=None,
    **other,
)

endpoint(model=None)`
</script>

<template>
  <DocLayout
    title="InferenceClient"
    description="Send a chat call to an ensemble with the OpenAI call path and get a reply with the OpenAI field names."
    :navigation="navigation"
    :version="version"
  >
    <p>
      You can use an ensemble as one chat model with
      <code>sf.InferenceClient(model=None, *, client=None)</code>. The call path is the path of the
      OpenAI SDK: <code>chat.completions.create(...)</code>. The SDK sends the call to the chat
      route of the Engine, <code>POST /v1/chat/completions</code>. The reply has the field names of
      the OpenAI chat-completion object. For the route itself and its limits, see
      <RouterLink to="/sf-client/guides/openai-api">Use an OpenAI client</RouterLink>.
    </p>

    <h2>Signature</h2>

    <CodeBlock :code="inferenceSig" language="python" />

    <h2>Make the client</h2>

    <p>The constructor sends no request. The <code>model</code> argument accepts these values:</p>

    <table>
      <thead>
        <tr>
          <th>Value of <code>model</code></th>
          <th>What the SDK sends</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>A recipe: <code>sf.Model</code>, a Fusion, a Pipeline, a Gate, a Cascade</td>
          <td>The Candidate URL4 of the recipe.</td>
        </tr>
        <tr>
          <td>An <code>sf.Url4</code>, or a text that starts with <code>(</code></td>
          <td>The URL4 text with no change.</td>
        </tr>
        <tr>
          <td>An evaluation URL4</td>
          <td>
            The text of its <code>candidate</code> source. An evaluation URL4 with no such source
            raises <code>PlanningError</code>.
          </td>
        </tr>
        <tr>
          <td>Any other text, for example <code>openrouter/openai/gpt-5.5</code></td>
          <td>A gateway model id with no change.</td>
        </tr>
        <tr>
          <td><code>None</code> (the default)</td>
          <td>No model. Each call must give a model.</td>
        </tr>
      </tbody>
    </table>

    <p>
      Any other type raises <code>TypeError</code>. An empty or blank text raises
      <code>ValueError</code>. A recipe with a corrective loop raises
      <code>PlanningError</code> with the code <code>recipe_not_supported</code>.
    </p>

    <p>The <code>client</code> argument selects the mode:</p>

    <ul>
      <li>
        <code>None</code> (the default): sync. The SDK takes the default client at each call. Thus,
        <code>sf.configure()</code> and <code>sf.close()</code> apply.
      </li>
      <li>A <code>Client</code>: sync, with this client.</li>
      <li>An <code>AsyncClient</code>: async. Each call returns an awaitable.</li>
    </ul>

    <p>
      The object keeps no conversation. More than one thread or task can use it at the same time.
    </p>

    <h2>Send a prompt</h2>

    <CodeBlock :code="plainCallExample" language="python" />

    <p>
      A <code>prompt</code> is the same as
      <code>messages=[{"role": "user", "content": prompt}]</code>.
    </p>

    <h2>A model for each call</h2>

    <CodeBlock :code="modelPerCallExample" language="python" />

    <p>
      A <code>model</code> on the call replaces the model of the client for that call only. It
      accepts the same values as the constructor. A call with no model, on a client with no model,
      raises <code>TypeError</code> before a request.
    </p>

    <h2>Messages and tools</h2>

    <CodeBlock :code="toolsExample" language="python" />

    <p>
      Give exactly one of <code>prompt</code> and <code>messages</code>. If not, the call raises
      <code>TypeError</code>. An empty <code>messages</code> raises <code>ValueError</code>. The SDK
      sends <code>messages</code> and <code>tools</code> with no change. The Engine checks their
      shape. A reply with tool calls and no text has <code>content</code> <code>None</code>.
    </p>

    <h2>Stream the reply</h2>

    <CodeBlock :code="streamExample" language="python" />

    <ul>
      <li>
        The stream is buffered. The first chunk comes when the run ends, and then all chunks come
        together. It is not a token stream.
      </li>
      <li>
        <code>stream_options={"include_usage": True}</code> adds a last chunk with empty
        <code>choices</code>. This chunk has <code>usage</code> and <code>screamingface</code>.
      </li>
      <li>
        The stream is a context manager. <code>close()</code> closes the connection. A stream that
        you read to the end closes itself.
      </li>
    </ul>

    <h2>Async</h2>

    <CodeBlock :code="asyncCallExample" language="python" />

    <p>
      With an <code>AsyncClient</code>, await the call. An async stream has <code>async for</code>,
      <code>aclose()</code> and <code>async with</code>. The result type follows the client and the
      value of <code>stream</code>:
    </p>

    <table>
      <thead>
        <tr>
          <th>Client</th>
          <th><code>stream</code></th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>Client</code></td>
          <td><code>False</code> (the default)</td>
          <td><code>ChatCompletion</code></td>
        </tr>
        <tr>
          <td><code>Client</code></td>
          <td><code>True</code></td>
          <td><code>ChatStream</code> of <code>ChatCompletionChunk</code></td>
        </tr>
        <tr>
          <td><code>Client</code></td>
          <td>a <code>bool</code> variable</td>
          <td><code>ChatCompletion | ChatStream</code></td>
        </tr>
        <tr>
          <td><code>AsyncClient</code></td>
          <td><code>False</code> (the default)</td>
          <td>an awaitable of <code>ChatCompletion</code></td>
        </tr>
        <tr>
          <td><code>AsyncClient</code></td>
          <td><code>True</code></td>
          <td>an awaitable of <code>AsyncChatStream</code></td>
        </tr>
        <tr>
          <td><code>AsyncClient</code></td>
          <td>a <code>bool</code> variable</td>
          <td>an awaitable of <code>ChatCompletion | AsyncChatStream</code></td>
        </tr>
      </tbody>
    </table>

    <h2>Use another OpenAI client</h2>

    <CodeBlock :code="endpointOpenaiExample" language="python" />

    <p>
      <code>endpoint(model=None)</code> returns an <code>InferenceEndpoint</code> with
      <code>base_url</code> (the Engine URL with <code>/v1</code>), <code>model</code> (the
      Candidate URL4 or the model id) and <code>headers</code>. With an <code>AsyncClient</code>,
      await it.
    </p>

    <ul>
      <li>
        On an https Engine, <code>endpoint()</code> signs in first. With no usable token, it opens
        the browser sign-in and can wait up to 300 seconds. In a script with no browser, set
        <code>SCREAMINGFACE_ACCESS_TOKEN</code> or call <code>client.login()</code> first. A local
        Engine needs no headers.
      </li>
      <li>
        The values are a snapshot. On a hosted Engine the token in <code>headers</code> expires.
        Then call <code>endpoint()</code> again.
      </li>
      <li>
        The <code>repr</code> of an <code>InferenceEndpoint</code> shows the header names and hides
        the values.
      </li>
    </ul>

    <h2>Parameters of create</h2>

    <table>
      <thead>
        <tr>
          <th>Parameter</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>prompt</code></td>
          <td>One user message. Give it or <code>messages</code>, not both.</td>
        </tr>
        <tr>
          <td><code>model</code></td>
          <td>The model for this call only. It replaces the model of the client.</td>
        </tr>
        <tr>
          <td><code>messages</code>, <code>tools</code></td>
          <td>The OpenAI messages and tools. The SDK sends them with no change.</td>
        </tr>
        <tr>
          <td><code>stream</code></td>
          <td><code>True</code> returns a stream of chunks.</td>
        </tr>
        <tr>
          <td><code>stream_options</code></td>
          <td>Has an effect only with <code>stream=True</code>.</td>
        </tr>
        <tr>
          <td><code>use_cache</code></td>
          <td>
            <code>True</code> (the default) uses the shared cache. <code>False</code> sends
            <code>Cache-Control: no-store</code>.
          </td>
        </tr>
        <tr>
          <td><code>max_retries</code></td>
          <td>An integer of 0 or more. The default is 0. See the retry rules below.</td>
        </tr>
        <tr>
          <td><code>timeout</code></td>
          <td>
            The limit in seconds for the full call, all tries included. For a stream, the limit
            stops when the first chunk comes. The SDK checks the limit at each line from the Engine,
            so the error can come up to one keep-alive interval (15 s by default) late. The value
            must be more than 0. <code>None</code> means that only the limit of the Engine applies.
          </td>
        </tr>
        <tr>
          <td><code>**other</code></td>
          <td>
            A known OpenAI chat parameter (<code>temperature</code>, <code>max_tokens</code>,
            <code>max_completion_tokens</code>, <code>top_p</code>, <code>stop</code>,
            <code>seed</code>, <code>response_format</code>, <code>tool_choice</code>,
            <code>parallel_tool_calls</code>, <code>presence_penalty</code>,
            <code>frequency_penalty</code>, <code>logit_bias</code>, <code>top_logprobs</code>,
            <code>reasoning_effort</code>, <code>user</code>, <code>metadata</code>,
            <code>store</code>, <code>service_tier</code>, <code>n=1</code>,
            <code>logprobs=False</code>) is accepted but not sent. It gives an
            <code>IgnoredParameterWarning</code> that points to <code>sf.Model(params=...)</code>.
            <code>n</code> above 1, <code>logprobs=True</code>, <code>audio</code> with a value and
            <code>modalities</code> with <code>"audio"</code> raise <code>PlanningError</code> with
            the code <code>unsupported_parameter</code>. Any other name raises
            <code>TypeError</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      An argument error comes from the call itself, also in async mode. A closed client raises its
      <code>RuntimeError</code> before a request.
    </p>

    <h2>The reply</h2>

    <table>
      <thead>
        <tr>
          <th>Type</th>
          <th>Fields</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>ChatCompletion</code></td>
          <td>
            <code>id</code>, <code>object</code>, <code>created</code>, <code>model</code>,
            <code>choices</code> (one <code>ChatChoice</code> with <code>message</code> and
            <code>finish_reason</code>), <code>usage</code> (<code>ChatUsage</code>),
            <code>screamingface</code> (<code>InferenceInfo</code>). Short forms: <code>text</code>,
            <code>tool_calls</code>, <code>cost_usd</code>, <code>trace_id</code>.
          </td>
        </tr>
        <tr>
          <td><code>InferenceInfo</code></td>
          <td>
            <code>status</code> (<code>answered</code>, <code>abstained</code> or
            <code>refused</code>), <code>abstain_reason</code>, <code>cost_usd</code> (a
            <code>Decimal</code> or <code>None</code>), <code>trace_id</code>,
            <code>final_step</code>.
          </td>
        </tr>
        <tr>
          <td><code>FinalStep</code></td>
          <td><code>binding</code>, <code>model</code>, <code>usage</code>.</td>
        </tr>
        <tr>
          <td><code>ChatCompletionChunk</code></td>
          <td>
            <code>id</code>, <code>object</code>, <code>created</code>, <code>model</code>,
            <code>choices</code> (<code>ChatChunkChoice</code> items, can be empty),
            <code>usage</code>, <code>screamingface</code>. Short form: <code>text</code>.
          </td>
        </tr>
        <tr>
          <td><code>ChatChunkChoice</code></td>
          <td>
            <code>index</code>, <code>delta</code> (<code>ChatDelta</code>),
            <code>finish_reason</code>.
          </td>
        </tr>
        <tr>
          <td><code>ChatDelta</code></td>
          <td>
            <code>role</code>, <code>content</code>, <code>refusal</code>,
            <code>tool_calls</code> (<code>ChatDeltaToolCall</code> items).
          </td>
        </tr>
        <tr>
          <td><code>ChatDeltaToolCall</code></td>
          <td><code>index</code>, <code>id</code>, <code>type</code>, <code>function</code>.</td>
        </tr>
      </tbody>
    </table>

    <p>
      A reply with the status <code>abstained</code> or <code>refused</code> is a normal reply, not
      an error. <code>cost_usd</code> is <code>None</code> when one call of the run has no price.
      For a recipe, <code>model</code> is the full Candidate URL4. <code>to_dict()</code> gives a
      JSON-ready dict with the OpenAI key names, and <code>cost_usd</code> as a decimal string.
    </p>

    <h2>Errors and retries</h2>

    <table>
      <thead>
        <tr>
          <th>Case</th>
          <th>Error</th>
          <th><code>permanent</code></th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>The SDK did not send the request (no connection).</td>
          <td><code>EngineUnavailableError</code></td>
          <td>false</td>
        </tr>
        <tr>
          <td>404 or 405 with no OpenAI error envelope: the Engine has no chat route.</td>
          <td><code>EngineCapabilityError</code></td>
          <td>true</td>
        </tr>
        <tr>
          <td>401 or 403 after the sign-in.</td>
          <td><code>AuthenticationError</code></td>
          <td>true</td>
        </tr>
        <tr>
          <td>400, 404 with an envelope, 413, 415.</td>
          <td><code>PlanningError</code> with the code of the Engine</td>
          <td>true</td>
        </tr>
        <tr>
          <td>408, 422, 429, each 5xx, or an error event in the stream.</td>
          <td><code>ExecutionError</code> with the code of the Engine</td>
          <td>true when the Engine does not say that a retry is safe</td>
        </tr>
        <tr>
          <td>An Engine answer with a status that the contract does not name.</td>
          <td>
            <code>ExecutionError</code> with the code of the Engine, or
            <code>engine_contract_error</code> when the Engine sends no code
          </td>
          <td>true</td>
        </tr>
        <tr>
          <td>
            The connection breaks, or 60 seconds pass with no byte, after the SDK sent the request.
          </td>
          <td><code>ExecutionError: inference_outcome_unknown</code></td>
          <td>true</td>
        </tr>
        <tr>
          <td>Your <code>timeout</code> passes.</td>
          <td><code>ExecutionError: client_timeout</code></td>
          <td>true</td>
        </tr>
        <tr>
          <td>The stream has a wrong form.</td>
          <td><code>ExecutionError: invalid_response</code></td>
          <td>true</td>
        </tr>
      </tbody>
    </table>

    <ul>
      <li>By default, the SDK does not send a call again.</li>
      <li>
        <code>max_retries</code> does not send the call again after
        <code>EngineUnavailableError</code>.
      </li>
      <li>
        <code>EngineCapabilityError</code> is a subclass of <code>PlanningError</code>. Catch
        <code>EngineCapabilityError</code> before <code>PlanningError</code>.
      </li>
      <li>
        With <code>max_retries=N</code>, the SDK sends the call again only when the Engine says that
        a retry is safe. It waits for <code>Retry-After</code> (or <code>retry_after</code> in the
        error event). With no such value, it waits 1 second, then 2, then 4 and more, at most 30
        seconds.
      </li>
      <li>
        The SDK never retries <code>inference_outcome_unknown</code>, <code>client_timeout</code> or
        <code>invalid_response</code>. The run can have a cost.
      </li>
      <li>
        After a sign-in challenge of a hosted Engine, the client signs in and sends the request one
        more time. No run exists before this challenge.
      </li>
    </ul>

    <p>
      See <RouterLink to="/sf-client/api/errors">Errors and warnings</RouterLink> for the attributes
      that each error has.
    </p>

    <h2>Privacy</h2>

    <ul>
      <li>The SDK sends no analytics event for an inference call.</li>
      <li>The SDK writes no reply to disk.</li>
      <li>A log line of the SDK has no message text and no header value.</li>
    </ul>
  </DocLayout>
</template>
