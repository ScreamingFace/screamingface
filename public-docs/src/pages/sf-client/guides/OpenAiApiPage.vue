<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'
import { SF_ENGINE_URL } from '@/lib/engine'
import candidateUrl4Example from '@/snippets/openai-chat/candidate_url4.py?raw'
import openaiSdkExample from '@/snippets/openai-chat/openai_sdk.py?raw'
import candidateUrl4SdkExample from '@/snippets/chat/candidate_url4.py?raw'

const baseUrls = `# the hosted Engine
${SF_ENGINE_URL}/v1

# a local stack
http://127.0.0.1:9108/v1`

const listModels = `curl http://127.0.0.1:9108/v1/models`

const accessToken = `cloudflared access token -app=${SF_ENGINE_URL}`

const candidateUrl4Use = `evaluation_url4 = str(report.candidates["my-fusion"].url4)
model = candidate_url4(evaluation_url4)   # send this text as model`

const hostedEnv = `export ENGINE_BASE_URL=${SF_ENGINE_URL}/v1
export CF_ACCESS_TOKEN=$(cloudflared access token -app=${SF_ENGINE_URL})
python openai_sdk.py`

const piConfig = `{
  "providers": {
    "screamingface": {
      "baseUrl": "${SF_ENGINE_URL}/v1",
      "api": "openai-completions",
      "apiKey": "not-used",
      "headers": {
        "Cf-Access-Token": "!cloudflared access token -app=${SF_ENGINE_URL}"
      },
      "models": [{ "id": "openrouter/deepseek/deepseek-v4-flash" }]
    }
  }
}`

const opencodeConfig = `{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "screamingface": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "ScreamingFace Engine",
      "options": {
        "baseURL": "${SF_ENGINE_URL}/v1",
        "apiKey": "not-used",
        "headers": {
          "Cf-Access-Token": "{env:CF_ACCESS_TOKEN}"
        }
      },
      "models": {
        "openrouter/deepseek/deepseek-v4-flash": {}
      }
    }
  }
}`

const answerShape = `{
  "id": "chatcmpl-…",
  "object": "chat.completion",
  "created": 1763452800,
  "model": "openrouter/deepseek/deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "finish_reason": "stop",
      "message": { "role": "assistant", "content": "Paris", "tool_calls": null, "refusal": null }
    }
  ],
  "usage": { "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14 },
  "screamingface": {
    "status": "answered",
    "abstain_reason": null,
    "cost_usd": "0.001",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "final_step": {
      "binding": "model_1",
      "model": "openrouter/deepseek/deepseek-v4-flash",
      "usage": { "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14 }
    }
  }
}`

const streamLines = `: keep-alive

: keep-alive

data: {"id":"chatcmpl-…","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":"Paris"},"finish_reason":null}],…}

data: {"id":"chatcmpl-…","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],…}

data: {"id":"chatcmpl-…","object":"chat.completion.chunk","choices":[],"usage":{…},"screamingface":{…},…}

data: [DONE]`

const errorEnvelope = `{
  "error": {
    "message": "the server is at capacity; retry shortly",
    "type": "rate_limit_error",
    "param": null,
    "code": "overloaded"
  }
}`
</script>

<template>
  <DocLayout
    title="Use an OpenAI client"
    description="Send chat requests to an ensemble with an OpenAI-compatible client."
    :navigation="navigation"
    :version="version"
  >
    <p>
      The Engine has an OpenAI-compatible chat route. Thus, an OpenAI client can use an ensemble as
      one model. The client sends the conversation. The Engine runs the full recipe on it. The
      client gets one chat completion back.
    </p>

    <h2>Base URL and routes</h2>

    <p>Set the base URL of your client to one of these values:</p>

    <CodeBlock :code="baseUrls" language="text" />

    <ul>
      <li><code>POST /v1/chat/completions</code> runs one chat turn.</li>
      <li><code>GET /v1/models</code> lists the model ids that you can use.</li>
    </ul>

    <h2>Choose the model</h2>

    <p>The <code>model</code> field accepts two forms.</p>

    <h3>1 · A Candidate URL4</h3>

    <p>
      A Candidate URL4 is the expression of one recipe, for example a Fusion with a synthesizer. It
      starts with <code>(</code>. The Engine runs it as the model, with the conversation as its
      input.
    </p>

    <p>
      The chat route refuses an evaluation URL4. An evaluation URL4 links a candidate to its
      Benchmark. The Candidate URL4 is the text of its top-level <code>candidate</code> source.
    </p>

    <h3>Get the Candidate URL4 of a recipe</h3>

    <p>
      <code>recipe.chat.endpoint().model</code> gives the Candidate URL4 of the
      recipe. No evaluation is necessary. On an https Engine, <code>endpoint()</code> signs in
      first. With no usable token, it opens the browser sign-in and can wait up to 300 seconds. In a
      script with no browser, set <code>SCREAMINGFACE_ACCESS_TOKEN</code> or call
      <code>client.login()</code> first.
    </p>

    <CodeBlock :code="candidateUrl4SdkExample" language="python" />

    <p>
      <code>recipe.chat.completions.create(...)</code> can also send the chat call itself. See
      <RouterLink to="/sf-client/api/chat">Chat</RouterLink>.
    </p>

    <p>
      Alternative: get the Candidate URL4 from an evaluation. This way needs an evaluation of the
      recipe. Do these steps:
    </p>

    <ol>
      <li>Run an evaluation of the recipe with the SDK.</li>
      <li>
        Read the evaluation URL4 of the candidate in the report:
        <code>report.candidates["name"].url4</code>. This value is a <code>Url4</code> object. It is
        also a Python <code>str</code>. A leaderboard score has the same type of value in
        <code>score.url4</code>.
      </li>
      <li>
        Give the evaluation URL4 to the function below. The function returns the Candidate URL4.
      </li>
      <li>Send the Candidate URL4 as the <code>model</code> value.</li>
    </ol>

    <CodeBlock :code="candidateUrl4Example" language="python" />

    <p>
      The <code>url4</code> package comes with the SDK. The function raises
      <code>ValueError</code> when the text has no <code>candidate</code> source. Use it like this:
    </p>

    <CodeBlock :code="candidateUrl4Use" language="python" />

    <p>
      See
      <RouterLink to="/sf-client/guides/reproduce-and-share">Reproduce &amp; share</RouterLink> for
      the parts of a url4.
    </p>

    <h3>2 · A model id</h3>

    <p>
      A model id from <code>GET /v1/models</code> runs as a recipe with one model. An id can have a
      <code>~</code> or a <code>:</code> in it. The Engine accepts the two forms.
    </p>

    <CodeBlock :code="listModels" language="bash" />

    <h2>Hosted access</h2>

    <p>
      A hosted Engine is behind Cloudflare Access. Send the header <code>Cf-Access-Token</code> with
      each request. Get the token with <code>cloudflared</code>:
    </p>

    <CodeBlock :code="accessToken" language="bash" />

    <p>
      The token has a limited life. When Cloudflare Access refuses it, get a new token. The token
      acts as the person it was issued to. A local stack needs no token.
    </p>

    <h2>Examples</h2>

    <h3>OpenAI Python SDK</h3>

    <CodeBlock :code="openaiSdkExample" language="python" />

    <p>
      Set <code>max_retries=0</code> on the OpenAI client. After a lost connection, the OpenAI
      client sends the request two more times by default, and each try is a new paid run of the
      ensemble.
    </p>

    <p>
      The SDK needs an <code>api_key</code> value. Any text works, because the Engine ignores it.
      <code>default_headers</code> sends the token with each request. The example uses the local
      stack by default. For a hosted Engine, set <code>ENGINE_BASE_URL</code> and
      <code>CF_ACCESS_TOKEN</code>:
    </p>

    <CodeBlock :code="hostedEnv" language="bash" />

    <h3>pi</h3>

    <p>
      Add a provider to the model configuration of pi. The value of the
      <code>Cf-Access-Token</code> header comes from a command, so pi gets a new token each time.
    </p>

    <CodeBlock :code="piConfig" language="json" />

    <Note>
      These keys are not verified: check the documentation of the client for the current keys.
    </Note>

    <h3>opencode</h3>

    <p>
      Add a provider to the opencode configuration. The <code>headers</code> object sends the token.
      Set <code>CF_ACCESS_TOKEN</code> before you start opencode.
    </p>

    <CodeBlock :code="opencodeConfig" language="json" />

    <Note>
      These keys are not verified: check the documentation of the client for the current keys.
    </Note>

    <h2>The answer</h2>

    <p>
      The answer has the OpenAI chat completion shape. <code>usage</code> is the sum of the whole
      ensemble: each model call of the recipe adds to it. The Engine adds one object,
      <code>screamingface</code>.
    </p>

    <CodeBlock :code="answerShape" language="json" />

    <table>
      <thead>
        <tr>
          <th>Field of <code>screamingface</code></th>
          <th>What it holds</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>status</code></td>
          <td><code>answered</code>, <code>abstained</code> or <code>refused</code>.</td>
        </tr>
        <tr>
          <td><code>abstain_reason</code></td>
          <td>Why the ensemble did not answer. It is set only when the status is abstained.</td>
        </tr>
        <tr>
          <td><code>cost_usd</code></td>
          <td>
            The cost of the whole run in US dollars, as a string. It is null when a call has no
            price.
          </td>
        </tr>
        <tr>
          <td><code>trace_id</code></td>
          <td>The trace id of the run. Give it to support when you report a problem.</td>
        </tr>
        <tr>
          <td><code>final_step</code></td>
          <td>
            The step that wrote the answer: its <code>binding</code> (for example
            <code>model_1</code>), its <code>model</code> and its own <code>usage</code>. It can be
            null. See the limits below. On a cache hit of this step, the counts of its
            <code>usage</code> are 0 and <code>final_step.cached</code> is true. On a miss,
            <code>cached</code> is absent.
          </td>
        </tr>
        <tr>
          <td><code>ignored_parameters</code></td>
          <td>
            The names of the top-level request fields that the Engine ignored, sorted. It is absent
            when the Engine ignored no field. See the limits below.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      When the ensemble abstains, <code>content</code> is empty, <code>finish_reason</code> is
      <code>stop</code> and <code>abstain_reason</code> tells why. When the provider refuses,
      <code>content</code> is null, <code>refusal</code> holds the text of the refusal and
      <code>finish_reason</code> is <code>content_filter</code>. When the reply has tool calls and
      no text, <code>content</code> is null, as OpenAI sends it.
    </p>

    <h3>Streaming</h3>

    <p>
      Set <code>stream: true</code> to get server-sent events. The stream is buffered: the run ends
      first, and then the whole answer comes as chunks. While the run works, the Engine sends a
      <code>: keep-alive</code> comment line at an interval. The <code>screamingface</code> object
      is on the last chunk before <code>[DONE]</code>. Set
      <code>stream_options.include_usage</code> to get one more chunk at the end with
      <code>usage</code>.
    </p>

    <CodeBlock :code="streamLines" language="text" />

    <p>
      An error after the stream starts comes as one data line with an <code>error</code> object. No
      <code>[DONE]</code> line follows it. The object has <code>message</code>,
      <code>type</code> and <code>code</code>, as in a plain error, and also
      <code>should_retry</code> (the value of the <code>x-should-retry</code> header of a plain
      answer) and, for some codes, <code>retry_after</code> in seconds.
    </p>
    <h2>Tools</h2>

    <p>
      Tool calls are not available yet. The Engine refuses a request that declares or uses a tool,
      before a run starts and before a cost. The answer is HTTP 400 with the code
      <code>tools_not_available</code>, and <code>param</code> names the place. These requests get
      the error:
    </p>

    <ul>
      <li><code>tools</code> with at least one item.</li>
      <li><code>functions</code> with at least one item.</li>
      <li>
        <code>messages</code> with a <code>tool</code> message, or with an assistant message that
        has <code>tool_calls</code>.
      </li>
    </ul>

    <p>
      <code>tools: []</code> declares no tool and is accepted. <code>tool_choice</code> and
      <code>function_call</code> are ignored. A coding agent that sends its tools with each request
      (for example pi or opencode) gets this error until tool calls are on again.
    </p>

    <h2>Errors</h2>

    <p>
      Errors use the OpenAI error envelope. The header <code>x-should-retry</code> tells the client
      when a retry is safe. Each retry runs the full ensemble again, so it costs money again. Some
      errors also have a <code>Retry-After</code> header.
    </p>

    <CodeBlock :code="errorEnvelope" language="json" />

    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>Codes</th>
          <th>Meaning</th>
          <th><code>x-should-retry</code></th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>400</td>
          <td>
            <code>invalid_request</code>, <code>unsupported_parameter</code>,
            <code>tools_not_available</code>, <code>unsupported_content</code>,
            <code>recipe_invalid</code>, <code>recipe_not_supported</code>,
            <code>final_step_not_model</code>,
            <code>model_does_not_support_tools</code>
          </td>
          <td>
            The request is not valid, or the chat route cannot run the recipe. The message and
            <code>param</code> tell why.
          </td>
          <td>false</td>
        </tr>
        <tr>
          <td>401</td>
          <td><code>identity_required</code></td>
          <td>A hosted Engine got no verified identity. Send a valid token.</td>
          <td>false</td>
        </tr>
        <tr>
          <td>404</td>
          <td><code>model_not_found</code></td>
          <td>The model id is not known.</td>
          <td>false</td>
        </tr>
        <tr>
          <td>408</td>
          <td><code>request_timeout</code></td>
          <td>The body did not arrive in full in 30 seconds. See the limits below.</td>
          <td>false</td>
        </tr>
        <tr>
          <td>413</td>
          <td><code>request_too_large</code></td>
          <td>
            The body, the chat input or the <code>model</code> value is larger than its limit.
          </td>
          <td>false</td>
        </tr>
        <tr>
          <td>415</td>
          <td><code>unsupported_media_type</code></td>
          <td>The <code>Content-Type</code> is not <code>application/json</code>.</td>
          <td>false</td>
        </tr>
        <tr>
          <td>422</td>
          <td><code>fail_closed</code></td>
          <td>The recipe ended with its fail-closed outcome.</td>
          <td>false</td>
        </tr>
        <tr>
          <td>429</td>
          <td><code>overloaded</code></td>
          <td>
            Too many runs are in flight (see the run limit below), or too many large bodies are in
            parse at one time. The answer has a <code>Retry-After</code> header.
          </td>
          <td>true</td>
        </tr>
        <tr>
          <td>500</td>
          <td>
            <code>internal_error</code>, <code>chat_input_unavailable</code>,
            <code>chat_input_invalid</code>
          </td>
          <td>
            The Engine failed. <code>chat_input_unavailable</code> has 500 when the input record is
            absent.
          </td>
          <td>false</td>
        </tr>
        <tr>
          <td>502</td>
          <td>
            <code>final_step_ambiguous</code>, <code>result_unavailable</code>,
            <code>result_invalid</code>, <code>result_too_large</code>, <code>internal_error</code>
          </td>
          <td>
            The run failed, or the Engine cannot read its result. Other codes of a failed run also
            come with 502. <code>result_too_large</code>: the result is larger than 8 MiB
            (8,388,608 bytes).
          </td>
          <td>true only for another code of a failed run that is not permanent</td>
        </tr>
        <tr>
          <td>503</td>
          <td>
            <code>chat_unavailable</code>, <code>catalog_unavailable</code>,
            <code>queue_unavailable</code>, <code>run_failed</code>, <code>worker_draining</code>,
            <code>server_restarting</code>, <code>chat_input_unavailable</code>
          </td>
          <td>
            The Engine cannot run the request now. A retryable <code>run_failed</code>,
            <code>worker_draining</code> or <code>server_restarting</code> answer has a
            <code>Retry-After: 5</code> header. <code>chat_input_unavailable</code> with 503 is a
            short outage of the input store. No model call was made, and the answer has a
            <code>Retry-After: 5</code> header.
          </td>
          <td>
            true, but false for <code>chat_unavailable</code>, for
            <code>catalog_unavailable</code> when the Engine has no catalogue, and for
            <code>run_failed</code> when the run went above its memory budget
          </td>
        </tr>
        <tr>
          <td>504</td>
          <td><code>timeout</code></td>
          <td>The run did not finish in time. The Engine stopped it.</td>
          <td>false</td>
        </tr>
      </tbody>
    </table>

    <h2>Limits</h2>

    <ul>
      <li data-limit="sampling-fields">
        The Engine ignores the sampling fields (<code>temperature</code>, <code>top_p</code>,
        <code>max_tokens</code> and the others) and <code>tool_choice</code>. Set them in the
        recipe.
      </li>
      <li data-limit="tools-not-available">
        Tool calls are not available yet. The Engine refuses a request with <code>tools</code> or
        <code>functions</code>, a <code>tool</code> message, or an assistant message with
        <code>tool_calls</code>. The answer is 400 <code>tools_not_available</code>, and no run
        starts.
      </li>
      <li data-limit="unknown-fields">
        The Engine ignores unknown top-level request fields. The answer names the ignored fields in
        <code>screamingface.ignored_parameters</code>, sorted. A field is in this list when its value
        is not null and the Engine does not read it. The Engine reads <code>model</code>,
        <code>messages</code>, <code>tools</code>, <code>functions</code>, <code>stream</code>,
        <code>stream_options</code>, <code>n</code>, <code>logprobs</code>,
        <code>modalities</code> and <code>audio</code>. The list has at most 32 names, and a name
        longer than 64 characters is not in it. The key is absent when the Engine ignored no field.
        The JSON answer and the stream chunk with the <code>screamingface</code> object both have
        it.
      </li>
      <li data-limit="usage-sum">
        <code>usage</code> is the sum of the whole ensemble. Thus, a context meter in an agent reads
        high. The real context size is in <code>screamingface.final_step.usage</code>, when
        <code>final_step</code> is not null. On a cache hit of the final step, its counts are 0 and
        <code>screamingface.final_step.cached</code> is true. Then keep the last known context size.
      </li>
      <li data-limit="final-step-null">
        <code>screamingface.final_step</code> and its <code>usage</code> are null in these cases:
        the recipe ends in a reducer; the recipe has no single final step; or, with no tools, a
        member and the final step use the same route with the same parameters. The Engine identifies
        a step by its route and its parameters. In these cases, <code>finish_reason</code> is
        <code>stop</code>.
      </li>
      <li data-limit="corrective-loop">The Engine refuses a recipe with a corrective loop.</li>
      <li data-limit="benchmark-linked">
        The Engine refuses a benchmark-linked expression. Send the Candidate URL4.
      </li>
      <li data-limit="shared-cache">
        A chat request uses the shared community cache, as an evaluation does. The cache stores each
        model answer of the request, and each signed-in account can read the stored answers (not the
        prompts, but an answer can quote its prompt). To keep a request out of the cache, send
        <code>Cache-Control: no-store</code>.
      </li>
      <li data-limit="cache-zero-tokens">
        A call that the shared cache serves counts 0 tokens in <code>usage</code>.
      </li>
      <li data-limit="unpriced-cost">
        <code>cost_usd</code> is null when one call of the run has no price. A recipe with a
        classifier step has no price today.
      </li>
      <li data-limit="run-limit">
        On a hosted Engine, evaluation runs and chat requests share the limit of 24 runs in flight
        for each user. Over the limit, the answer is 429 <code>overloaded</code>. Thus, an agent can
        get this error while a large evaluation of the same user runs. A local stack has one limit
        for all its runs (<code>local_max_concurrent_runs</code>, 32 by default), with the same
        answer.
      </li>
      <li data-limit="body-limit">
        The request body can have at most 8,000,000 bytes. A larger body gets 413
        <code>request_too_large</code>.
      </li>
      <li data-limit="model-length">
        The <code>model</code> value can have at most 32,000 characters. A longer value gets 413
        <code>request_too_large</code>.
      </li>
      <li data-limit="large-bodies">
        Each body must arrive in full in 30 seconds from its start, for each size. If not, the
        answer is 408 <code>request_timeout</code>. At most four bodies above 1,000,000 bytes are
        in parse at one time. When no place is free in 5 seconds, the answer is
        429 <code>overloaded</code>. When a body above 1,000,000 bytes gets a place, the limit
        changes: the body must arrive in full in 30 seconds from that time.
      </li>
      <li data-limit="time-limit">
        One request waits at most <code>chat_max_wait_s</code> seconds (600 by default). Then the
        Engine stops the run, and the answer is 504 <code>timeout</code>.
      </li>
      <li data-limit="remote-media">
        The Engine refuses remote picture URLs and remote file URLs. Send pictures and files as
        <code>data:</code> URIs.
      </li>
      <li data-limit="unsupported-fields">
        The Engine refuses <code>n</code> above 1, <code>logprobs</code> and audio. The answer is
        400 <code>unsupported_parameter</code>. An <code>n</code> below 1 gets 400
        <code>invalid_request</code>, with <code>param</code> <code>n</code>.
      </li>
      <li data-limit="buffered-stream">
        The stream is buffered. The answer comes in one piece at the end of the run.
      </li>
      <li data-limit="long-requests">
        A plain request sends no bytes until the answer is ready. A proxy between the client and the
        Engine can close a connection that stays silent for a long time. For a recipe that can take
        a long time, use <code>stream: true</code>. The Engine then sends a keep-alive line at a
        fixed interval (15 seconds by default) while the run works.
      </li>
      <li data-limit="turn-cost">
        Each turn runs the full ensemble. Thus, the cost of a turn is the cost of the ensemble.
      </li>
      <li data-limit="web-search-default">
        Web search is on by default for each step whose model route can search. An OpenRouter route
        can always search. Another route can search only when the Engine has a search key. The
        conversation text of that step then goes to the search provider. To turn it off, set
        <code>web_search=false</code> on a model in the recipe.
      </li>
      <li data-limit="web-search-cost">
        Web search adds tokens and cost to each step that searches. For example, on 2026-11-18 one
        cheap model got a one-word question. It used 576 prompt tokens with search on and 16 prompt
        tokens with <code>web_search=false</code>.
      </li>
      <li data-limit="error-envelope">
        Errors use the OpenAI error envelope. The <code>x-should-retry</code> header tells the
        client when a retry is safe.
      </li>
      <li data-limit="other-api-formats">
        Claude Code and Codex need other API formats. These formats are not available.
      </li>
    </ul>

    <h2>Links</h2>

    <ul>
      <li>
        <RouterLink to="/sf-client/guides/reproduce-and-share">Reproduce &amp; share</RouterLink>:
        read the url4 of a candidate.
      </li>
      <li>
        <RouterLink to="/sf-client/guides/models">Models</RouterLink>: select a model route and set
        its answer policy.
      </li>
    </ul>
  </DocLayout>
</template>
