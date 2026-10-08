<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import { learnNavigation as navigation } from '@/navigation/learn'
</script>

<template>
  <DocLayout
    title="Caching and compute"
    description="Why runs, and especially reruns, stay cheap: call-level caching, a shared community cache, and where the compute comes from."
    :navigation="navigation"
  >
    <p>
      Evaluating a fusion means many model calls, and calls cost money and time. ScreamingFace keeps
      that cost low in two ways: it caches calls to the providers that support it, and it gives you
      a choice of where the compute comes from.
    </p>

    <h2>How caching works</h2>

    <p>
      When the <RouterLink to="/learn/engine">engine</RouterLink> calls a model on a provider that
      supports caching, it stores the response keyed by the exact request. Reuse the same model in
      another candidate, or run the same evaluation again, and the stored response is served instead
      of paying for it twice. Only some providers support it; the Providers table below shows which.
    </p>

    <ul>
      <li>
        <strong>Within a run:</strong> a model shared across several candidates is computed once, so
        a fusion that reuses its members is far cheaper than the number of candidates suggests.
      </li>
      <li>
        <strong>Across runs:</strong> re-running an evaluation pays only for the calls that are new
        to it. A run that failed partway is worth restarting, because the calls that already
        completed come back from the cache instead of being bought twice.
      </li>
    </ul>

    <h2>The shared community cache</h2>

    <p>
      A hosted engine's cache is shared across the community. If anyone has already run the same
      model configuration against a benchmark, that call is a cache hit for you as well, at no cost.
      Verifying a published result, or building on someone else's fusion, usually costs a fraction
      of the original run, because the expensive part has already been paid for once.
    </p>

    <p>
      This is what makes reproduction practical. A published result carries its
      <RouterLink to="/learn/url4">url4</RouterLink>, and re-running that url4 mostly lands on
      cached calls, so checking the work takes minutes and pennies rather than repeating the whole
      run.
    </p>

    <p>
      The shared cache belongs to the hosted engine. A local engine keeps its own cache, which makes
      your reruns cheap but starts empty and stays yours. Running everything yourself means giving
      up the community's hits, and that is the real trade against the local path's independence.
    </p>

    <h2>Reproducing a submission</h2>

    <p>
      A cache saves money, but it is not a record. Its rules can change between releases, and a
      model can be retired. So a run can make a <strong>frozen copy</strong> of itself. A frozen
      copy keeps every model answer and every web-tool result of the run. It is separate from the
      cache. It does not use the cache's keys or rules, and it is kept forever.
    </p>

    <p>
      <code>sf.evaluate(..., capture=True)</code> makes the copy. A leaderboard submission keeps the
      copy id and the capture status. <code>sf.reproduce(score)</code> then runs the score's
      <RouterLink to="/learn/url4">url4</RouterLink> and answer seed against the copy. The
      <RouterLink to="/sf-client/guides/leaderboards">Leaderboards guide</RouterLink> shows the
      calls and the outcomes.
    </p>

    <h3>Make a frozen copy</h3>

    <p>
      With <code>capture=True</code>, the Engine opens a frozen copy in the
      <RouterLink to="/learn/ai-gateway">AI gateway</RouterLink> when the run starts. The gateway
      stores each model answer. It stores the answer that the caller got, whether the answer came
      from the cache or from a live call. Model calls of the benchmark's judges are stored too. The
      Engine stores each web-search and web-fetch result as the tool returned it, before the Engine
      cuts it to length. When the run ends, the Engine seals the copy. A sealed copy cannot change.
    </p>

    <p>
      Capture adds no call to a provider, so a captured run costs the same as a normal run. It is
      best effort. If the gateway cannot store something, the run still goes on and still returns
      its result. The copy is then <code>partial</code>.
    </p>

    <p>
      Keep one thing in mind. The copy id is part of a published score. Any authenticated gateway
      account that has the id and sends the exact request can read the stored answer. No
      private-board rule limits this. Capture only a run that you are willing to publish.
    </p>

    <h3>Local runs</h3>

    <p>
      The local runtime starts a real AI gateway with its own SQLite database. A local run made with
      <code>capture=True</code> can be <code>complete</code>. Its copy lives only in that local
      gateway. Only the same local setup can replay it. A hosted reproduction of that score gets
      <code>frozen_copy_unavailable</code>. To upload a local copy to the hosted gateway is a
      planned follow-up.
    </p>

    <h3>Complete and partial</h3>

    <p>
      A captured run has a <code>capture_status</code> and, when the copy opened, a
      <code>frozen_copy_id</code>. The status is <code>complete</code> only when the copy opened,
      the copy sealed, and every model call and every web-tool result is stored. In all other cases
      it is <code>partial</code>. A partial score is not replayed: <code>sf.reproduce</code> returns
      <code>not_reproducible</code> and starts no run.
    </p>

    <table>
      <thead>
        <tr>
          <th>Why it is partial</th>
          <th>What happened</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Open</td>
          <td>
            The Engine could not open the copy when the run started. The run went on without capture
            and has no copy id.
          </td>
        </tr>
        <tr>
          <td>Seal</td>
          <td>
            The gateway did not confirm the seal at the end of the run. A run that is cancelled is
            never sealed. A copy that is not sealed cannot be replayed.
          </td>
        </tr>
        <tr>
          <td>Failed</td>
          <td>
            The gateway could not store a model answer or a web-tool result. For example, one entry
            was larger than the gateway's limit for one entry.
          </td>
        </tr>
        <tr>
          <td>Refused</td>
          <td>
            The gateway did not take a call into the copy. It never stores a streaming call. It also
            refuses a call when the copy is unknown, is not open, or belongs to another account.
          </td>
        </tr>
        <tr>
          <td>Missing</td>
          <td>
            The gateway did not say whether it stored a call. An older gateway, from before frozen
            copies, does this. So does a gateway that refused the call before it checked the copy,
            for example because the request body was not valid.
          </td>
        </tr>
        <tr>
          <td>Error</td>
          <td>
            A model call or a web tool ended with no answer to store, for example after a time-out
            or a cancel, and no later call with the same request was stored. A later call with the
            same request that was stored removes this reason.
          </td>
        </tr>
        <tr>
          <td>Ambiguous</td>
          <td>
            The copy can hold an answer that the model did not use. This is the case when the Engine
            sent a call again because of a <code>max-age</code> bound, or when it retried a call
            after a transport error. The Engine cannot tell which answer is the right one.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      A model call that ends with an error from the provider is stored with that error. It does not
      make the run partial. A replay gives the same error, so the case fails in the same way as in
      the original run.
    </p>

    <p>
      A run that is not captured has no <code>capture_status</code> (<code>None</code>), and no
      frozen copy id. <code>None</code> means unknown, not partial. If you asked for capture and the
      Engine did not capture the run (an older Engine), the Client emits an
      <code>EvaluationWarning</code>, and the result keeps <code>None</code>. A score from a
      leaderboard that predates frozen copies has no status too. <code>sf.reproduce</code> reports
      each such score as <code>not_reproducible</code> with the reason <code>unknown</code>. It does
      the same for a score with no copy id or no benchmark revision.
    </p>

    <h3>Replay from the copy</h3>

    <p>
      <code>sf.reproduce(score)</code> asks the Engine to run the score's url4 and answer seed
      against the frozen copy. The Engine must confirm that it runs in replay mode. In a confirmed
      replay, every model call goes to the copy, and so does every web-tool read. The copy answers a
      request with the answer that it stored for the same request. Nothing calls a provider, and
      nothing calls the web-search service. A confirmed replay costs <strong>$0</strong>.
    </p>

    <p>
      A replay does not depend on the cache or on the models of today. It works after a model is
      retired, after a provider plugin is removed, and after the cache rules change. A request that
      the copy cannot answer fails its case. The replay never buys the answer.
    </p>

    <p>
      If the Engine does not confirm replay mode when the run starts, it may run the url4 as a
      normal, paid run. So the Client stops the run and reports <code>replay_unsupported</code>. If
      that stop fails, an <code>EvaluationWarning</code> says that the run may still be running and
      spending. An Engine can also confirm the start and then finish a run whose summary does not
      name the copy. That run is already over, and it may have paid providers. The Client reports it
      as <code>replay_unsupported</code> too, and not as a replay.
    </p>

    <h3>When a replay fails</h3>

    <p>
      A replay can fail for reasons that do not change the score. Each one is a reason on the
      <code>Reproduction</code>:
    </p>

    <ul>
      <li>
        <strong>An older engine</strong> may not know replay. The Client reports
        <code>replay_unsupported</code>.
      </li>
      <li>
        <strong>A copy that is not available.</strong> The copy is unknown, or it is not sealed (for
        example, the Engine stopped during the original run), or the gateway is older and has no
        frozen copies. A web-tool lookup that the gateway does not answer, because of a transport
        failure or an error other than not found, is the same. Cases fail, and the replay is
        reported as <code>frozen_copy_unavailable</code>.
      </li>
      <li>
        <strong>A changed engine or SDK</strong> may build a request in another way. The copy has no
        answer for that request, and the case fails with <code>frozen_copy_miss</code>.
        <code>missed_cases</code> lists these cases.
      </li>
      <li>
        <strong>Different web tools.</strong> A run that had no web tools (it had no web-search
        connection) can differ from a replay on an Engine that offers them. The requests then
        differ, and the case misses the copy.
      </li>
      <li>
        <strong>Same request, different answers.</strong> With sampling, or with the cache off, the
        same request can get different answers. The copy serves them in the order that the original
        run took them. Parallel branches can take them in another order in the replay. Then the
        score can differ (<code>score_differs</code>).
      </li>
      <li>
        <strong>A changed benchmark</strong> grades a different exam, so the numbers cannot be
        compared. The Client reports <code>benchmark_revision_changed</code>.
      </li>
    </ul>

    <p>
      A failed replay is not recorded. It is not proof against the score, because of the known
      limits above. It is not a confirmation either.
    </p>

    <h2>Where the compute comes from</h2>

    <p>
      There are two ways to run. They differ in who supplies the compute and which cache you draw
      from.
    </p>

    <ul>
      <li>
        <strong>Local.</strong> Run the engine on your own machine with your own provider keys. You
        pay your providers directly, and there is no middleman on the local path.
      </li>
      <li>
        <strong>Hosted.</strong> Use an engine we operate. It carries the shared cache, and we
        subsidize compute for chosen cohorts so that verifying and exploring stays cheap.
      </li>
    </ul>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        viewBox="0 0 680 258"
        role="img"
        aria-label="The client points at one engine. A local engine runs on your machine with its own cache; a hosted engine we operate carries the shared community cache."
        style="width: 100%; height: auto; font-family: var(--f-mono); font-size: 12px"
      >
        <defs>
          <marker
            id="cc-arrow"
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
        <g
          style="stroke: var(--text-2); stroke-width: 1.25; fill: none"
          marker-end="url(#cc-arrow)"
        >
          <path d="M326 54 C 220 68, 152 86, 141 104" />
          <path d="M354 54 C 460 68, 528 86, 539 104" />
          <path d="M140 162 V190" />
          <path d="M540 162 V190" />
        </g>
        <g style="fill: var(--surface); stroke: var(--border-strong); stroke-width: 1">
          <rect x="290" y="14" width="100" height="40" />
          <rect x="40" y="106" width="200" height="54" />
          <rect x="80" y="192" width="120" height="42" />
          <rect x="440" y="106" width="200" height="54" />
        </g>
        <rect
          x="446"
          y="192"
          width="188"
          height="42"
          style="fill: none; stroke: var(--accent); stroke-width: 1.5"
        />
        <g
          text-anchor="middle"
          style="
            fill: var(--text-2);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
          "
        >
          <text x="140" y="98">local</text>
          <text x="540" y="98">hosted</text>
        </g>
        <g text-anchor="middle" style="fill: var(--text)">
          <text x="340" y="39">client</text>
          <text x="140" y="130">local engine</text>
          <text x="540" y="130">hosted engine</text>
          <text x="140" y="218">your cache</text>
          <text x="540" y="218">shared community cache</text>
        </g>
        <g text-anchor="middle" style="fill: var(--text-2); font-size: 10px">
          <text x="140" y="147">your machine · your keys</text>
          <text x="540" y="147">we run it · subsidized</text>
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
        Same protocol, two engines. A local engine keeps its own cache; the hosted engine carries
        the shared community cache.
      </figcaption>
    </figure>

    <p>
      The client code is identical either way; only the engine URL changes. The
      <RouterLink to="/sf-client/installation">Installation</RouterLink> guide walks through both.
    </p>

    <h2>Providers</h2>

    <p>
      Whichever engine you run, these are the providers it can reach. Caching is opt-in per
      provider, and only <code>anthropic</code> and <code>openrouter</code> are served from the
      cache today; the rest bypass it and dispatch every time. How you connect each one varies (a
      pasted key or a login through a CLI tool); the
      <RouterLink to="/sf-client/guides/connections">Connect a provider</RouterLink> guide has the
      specifics.
    </p>

    <table>
      <thead>
        <tr>
          <th>Provider</th>
          <th>Reached via</th>
          <th>Cached?</th>
          <th>What it is</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>openrouter</code></td>
          <td>API key</td>
          <td>Yes</td>
          <td>
            A router over many hosted models (OpenAI, Anthropic, Google, DeepSeek, Qwen and more)
            behind one key.
          </td>
        </tr>
        <tr>
          <td><code>anthropic</code></td>
          <td>API key</td>
          <td>Yes</td>
          <td>Claude models, direct.</td>
        </tr>
        <tr>
          <td><code>huggingface</code></td>
          <td>API key</td>
          <td>No</td>
          <td>Hugging Face inference endpoints.</td>
        </tr>
        <tr>
          <td><code>gemini-cli</code></td>
          <td>CLI plugin</td>
          <td>No</td>
          <td>Google Gemini through the gemini CLI.</td>
        </tr>
        <tr>
          <td><code>codex</code></td>
          <td>CLI plugin</td>
          <td>No</td>
          <td>OpenAI models through the Codex CLI.</td>
        </tr>
        <tr>
          <td><code>antigravity</code></td>
          <td>CLI plugin</td>
          <td>No</td>
          <td>Gemini through the Antigravity CLI.</td>
        </tr>
      </tbody>
    </table>
  </DocLayout>
</template>
