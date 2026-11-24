<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'
import plainCallExample from '@/snippets/chat/plain_call.py?raw'
import openaiFormExample from '@/snippets/chat/openai_form.py?raw'
import modelPerCallExample from '@/snippets/chat/model_per_call.py?raw'
import streamExample from '@/snippets/chat/stream.py?raw'
import asyncCallExample from '@/snippets/chat/async_call.py?raw'
import endpointOpenaiExample from '@/snippets/chat/endpoint_openai.py?raw'
import openaiOneLineExample from '@/snippets/chat/openai_one_line.py?raw'

const chatSig = `# On each recipe: sync, with the default client
recipe.chat.completions.create(
    prompt=None,
    *,
    messages=None,
    tools=None,
    stream=False,
    stream_options=None,
    use_cache=True,
    max_retries=None,
    timeout=None,
    **other,
)
recipe.chat.endpoint()

# On a client (sf.Client or sf.AsyncClient), and on the module sf.chat
client.chat.completions.create(prompt=None, *, model, messages=None, ...)
client.chat.endpoint(model)
sf.chat.completions.create(prompt=None, *, model, messages=None, ...)
sf.chat.endpoint(model)`
</script>

<template>
  <DocLayout
    title="Chat"
    description="Send a chat call to an ensemble with the call path of the OpenAI client and get a reply with the OpenAI field names."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Each recipe has <code>chat</code>, so you can use an ensemble as one chat model with
      <code>recipe.chat.completions.create(...)</code>. You do not make a new object. The call path is
      the path of the OpenAI SDK. <code>sf.Client().chat</code>, <code>sf.AsyncClient().chat</code> and
      the module <code>sf.chat</code> have the same path with a <code>model</code> argument. The SDK
      sends the call to the chat route of the Engine, <code>POST /v1/chat/completions</code>. The reply
      has the field names of the OpenAI chat-completion object. For the route itself and its limits,
      see <RouterLink to="/sf-client/guides/openai-api">Use an OpenAI client</RouterLink>.
    </p>

    <h2>Signature</h2>

    <CodeBlock :code="chatSig" language="python" />

    <h2>The three surfaces</h2>

    <ul>
      <li>
        <code>recipe.chat</code>: each recipe has it: <code>sf.Model</code>, a Fusion, a Pipeline, a
        Gate, a Cascade and <code>sf.WithBudget</code>. The access sends no request. Each call uses the
        default client at that time, so <code>sf.configure()</code> and <code>sf.close()</code> apply.
        It is sync only. <code>create</code> has no <code>model</code> argument: the recipe is the model.
      </li>
      <li>
        <code>client.chat</code>: on <code>sf.Client</code> and on <code>sf.AsyncClient</code>.
        <code>model</code> is a required keyword of <code>create</code> and the argument of
        <code>endpoint</code>. With an <code>AsyncClient</code>, each call returns an awaitable.
      </li>
      <li>
        <code>sf.chat</code>: a module. It is the same as <code>client.chat</code> with the default
        client. It is sync only.
      </li>
    </ul>

    <p>
      A step that is not a recipe, for example <code>sf.Fanout([...])</code> alone, has no
      <code>chat</code>. <code>sf.Url4</code> has no <code>chat</code>: give a URL4 as
      <code>model</code> to <code>client.chat</code> or <code>sf.chat</code>.
    </p>

    <p>The <code>model</code> argument accepts these values:</p>

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
      </tbody>
    </table>

    <p>
      Any other type raises <code>TypeError</code>. An empty or blank text raises
      <code>ValueError</code>. A recipe with a corrective loop raises <code>PlanningError</code> with
      the code <code>recipe_not_supported</code> when you call <code>create</code> or
      <code>endpoint</code>.
    </p>

    <p>
      No surface keeps a conversation. More than one thread or task can use one client at the same
      time.
    </p>

    <h2>Send a prompt</h2>

    <CodeBlock :code="plainCallExample" language="python" />

    <p>
      A <code>prompt</code> is the same as
      <code>messages=[{"role": "user", "content": prompt}]</code>.
    </p>

    <h2>The OpenAI form</h2>

    <CodeBlock :code="openaiFormExample" language="python" />

    <p>
      <code>client.chat.completions.create(model=..., messages=...)</code> is the call of the OpenAI
      client. Code written for the OpenAI client needs a change only in the line that makes the
      client. A call with no <code>model</code> raises <code>TypeError</code> before a request.
    </p>

    <h2>Move from the OpenAI SDK</h2>

    <CodeBlock :code="openaiOneLineExample" language="python" />

    <p>
      For code that uses chat completions, change <code>openai.OpenAI(...)</code> to
      <code>sf.Client(...)</code>, or <code>openai.AsyncOpenAI(...)</code> to
      <code>sf.AsyncClient(...)</code>. The lines below the client line do not change: the call
      path, the reply fields, a conversation that appends <code>reply.choices[0].message</code> to
      <code>messages</code>, the stream loop, and <code>model_dump()</code>,
      <code>model_dump_json()</code> and <code>to_json()</code> on a reply. An OpenAI attribute that
      the Engine never sets, for example <code>usage.prompt_tokens_details</code> or
      <code>choice.logprobs</code>, is <code>None</code>.
    </p>

    <p>The two clients accept the arguments of the OpenAI client:</p>

    <table>
      <thead>
        <tr>
          <th>Argument</th>
          <th>What the client does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>api_key</code></td>
          <td>
            Accepted. The client does not keep it and does not send it, and it gives an
            <code>IgnoredParameterWarning</code>. The client signs in to the Engine itself. Store a
            provider key with <code>sf.connect(...)</code>. The SDK does not read
            <code>OPENAI_API_KEY</code>.
          </td>
        </tr>
        <tr>
          <td><code>base_url</code></td>
          <td>
            The Engine URL, with or without the path <code>/v1</code>. It is the same value as
            <code>endpoint().base_url</code>. Give it or <code>engine_url</code>, not both. A URL
            with another path raises <code>ValueError</code>.
          </td>
        </tr>
        <tr>
          <td><code>timeout</code>, <code>max_retries</code></td>
          <td>
            The defaults of the chat calls of this client. A value on the call replaces the default
            for that call. With no value, the SDK does not retry and has no time limit of its own.
            <code>timeout</code> can be a number of seconds or an <code>httpx.Timeout</code>; from
            an <code>httpx.Timeout</code> the SDK uses the <code>read</code> value.
          </td>
        </tr>
        <tr>
          <td>
            <code>organization</code>, <code>project</code>, <code>default_headers</code>,
            <code>default_query</code>, <code>http_client</code>, <code>webhook_secret</code>,
            <code>websocket_base_url</code>, <code>admin_api_key</code>,
            <code>workload_identity</code>, <code>provider</code>
          </td>
          <td>
            Accepted and not used. Each one that has a value gives an
            <code>IgnoredParameterWarning</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <p>These parts of OpenAI code need a change by hand:</p>

    <ul>
      <li>
        The model name. The SDK sends <code>model</code> with no change, so
        <code>model="gpt-4o"</code> is not a model id of the gateway. Give a gateway model id, for
        example <code>"openrouter/openai/gpt-5.5"</code>, or a recipe.
      </li>
      <li>
        The error classes. A failed call raises a ScreamingFace error, not
        <code>openai.RateLimitError</code> or <code>openai.APIError</code>. See "Errors and retries"
        below.
      </li>
      <li>
        Tools. Tool calls are not available yet. A call with <code>tools</code> or
        <code>functions</code>, or with a tool turn in <code>messages</code>, raises
        <code>PlanningError</code> (<code>tools_not_available</code>). See "Tools are not available
        yet" below.
      </li>
      <li>
        The other OpenAI APIs. The client has no <code>client.responses</code>,
        <code>client.embeddings</code> or <code>client.completions</code>, and
        <code>chat.completions</code> has no <code>parse()</code>, <code>stream()</code> or
        <code>with_raw_response</code>.
      </li>
      <li>
        The parameters that the Engine does not use. A sampling parameter and an OpenAI request
        option (<code>extra_headers</code>, <code>extra_query</code>, <code>extra_body</code>) are
        accepted and not sent. Each one gives a warning.
      </li>
    </ul>

    <h2>The default client: sf.chat</h2>

    <CodeBlock :code="modelPerCallExample" language="python" />

    <p>
      <code>sf.chat</code> is the same as <code>client.chat</code> with the default client. Each call
      can give a different model.
    </p>

    <h2>Messages</h2>

    <p>
      Give exactly one of <code>prompt</code> and <code>messages</code>. If not, the call raises
      <code>TypeError</code>. An empty <code>messages</code> raises <code>ValueError</code>. The SDK
      sends <code>messages</code> with no change. The Engine checks their shape.
    </p>

    <h2>Tools are not available yet</h2>

    <p>
      Tool calls are turned off for now. A call that declares or uses a tool raises
      <code>PlanningError</code> with the code <code>tools_not_available</code>, before a request
      and before a cost. <code>error.details["param"]</code> names the place. These calls get the
      error:
    </p>

    <ul>
      <li><code>tools</code> with at least one item.</li>
      <li><code>functions</code> with at least one item (the old OpenAI keyword).</li>
      <li>
        <code>messages</code> with a <code>tool</code> message, or with an assistant message that
        has <code>tool_calls</code>.
      </li>
    </ul>

    <p>
      <code>tools=[]</code> and <code>tools=None</code> declare no tool and are accepted.
      <code>tool_choice</code> and <code>function_call</code> are accepted and not sent, with an
      <code>IgnoredParameterWarning</code>. The Engine has the same check for each other client: it
      answers HTTP 400 with the code <code>tools_not_available</code> and starts no run. The reply
      types keep <code>tool_calls</code>, which is <code>None</code>.
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
      With an <code>AsyncClient</code>, use <code>client.chat</code> and await the call.
      <code>recipe.chat</code> and <code>sf.chat</code> are sync only: give the recipe as
      <code>model</code>. An async stream has <code>async for</code>, <code>aclose()</code> and
      <code>async with</code>. The result type follows the surface and the value of
      <code>stream</code>:value of <code>stream</code>:
    </p>

    <table>
      <thead>
        <tr>
          <th>Surface</th>
          <th><code>stream</code></th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>recipe.chat</code>, <code>sf.Client().chat</code>, <code>sf.chat</code></td>
          <td><code>False</code> (the default)</td>
          <td><code>ChatCompletion</code></td>
        </tr>
        <tr>
          <td><code>recipe.chat</code>, <code>sf.Client().chat</code>, <code>sf.chat</code></td>
          <td><code>True</code></td>
          <td><code>ChatStream</code> of <code>ChatCompletionChunk</code></td>
        </tr>
        <tr>
          <td><code>recipe.chat</code>, <code>sf.Client().chat</code>, <code>sf.chat</code></td>
          <td>a <code>bool</code> variable</td>
          <td><code>ChatCompletion | ChatStream</code></td>
        </tr>
        <tr>
          <td><code>sf.AsyncClient().chat</code></td>
          <td><code>False</code> (the default)</td>
          <td>an awaitable of <code>ChatCompletion</code></td>
        </tr>
        <tr>
          <td><code>sf.AsyncClient().chat</code></td>
          <td><code>True</code></td>
          <td>an awaitable of <code>AsyncChatStream</code></td>
        </tr>
        <tr>
          <td><code>sf.AsyncClient().chat</code></td>
          <td>a <code>bool</code> variable</td>
          <td>an awaitable of <code>ChatCompletion | AsyncChatStream</code></td>
        </tr>
      </tbody>
    </table>

    <h2>Use another OpenAI client</h2>

    <CodeBlock :code="endpointOpenaiExample" language="python" />

    <p>
      <code>recipe.chat.endpoint()</code>, <code>client.chat.endpoint(model)</code> and <code>sf.chat.endpoint(model)</code> return an <code>InferenceEndpoint</code> with
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
          <td>
            The model of the call. It is required on <code>client.chat</code> and <code>sf.chat</code>.
            <code>recipe.chat</code> has no <code>model</code> argument.
          </td>
        </tr>
        <tr>
          <td><code>messages</code></td>
          <td>
            The OpenAI messages, as a list or another iterable. The SDK sends them with no change.
            An item can also be the message object of a reply
            (<code>reply.choices[0].message</code>).
          </td>
        </tr>
        <tr>
          <td><code>tools</code></td>
          <td>
            Not available yet. A value with at least one item raises
            <code>PlanningError</code> (<code>tools_not_available</code>). <code>None</code> and an
            empty value are accepted.
          </td>
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
          <td>
            An integer of 0 or more. <code>None</code> (the default) means the value of the client,
            which is 0 if you gave none. See the retry rules below.
          </td>
        </tr>
        <tr>
          <td><code>timeout</code></td>
          <td>
            The limit in seconds for the full call, all tries included. For a stream, the limit
            stops when the first chunk comes. The SDK checks the limit at each line from the Engine,
            so the error can come up to one keep-alive interval (15 s by default) late. The value
            must be more than 0. An <code>httpx.Timeout</code> is also accepted; the SDK uses its
            <code>read</code> value. <code>None</code> (the default) means the value of the client.
            If you gave none, only the limit of the Engine applies.
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
            Each other keyword of the OpenAI <code>create</code> (<code>extra_headers</code>,
            <code>extra_query</code>, <code>extra_body</code>, <code>prediction</code>,
            <code>web_search_options</code>, <code>prompt_cache_key</code>,
            <code>prompt_cache_options</code>, <code>prompt_cache_retention</code>,
            <code>safety_identifier</code>, <code>verbosity</code>, <code>moderation</code>) is also
            accepted and not sent, with an <code>IgnoredParameterWarning</code>.
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
