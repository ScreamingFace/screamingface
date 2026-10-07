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
      A leaderboard submission can name the cache it ran against. The cache keys its entries with
      rules, and those rules can change between releases. A <strong>cache revision</strong> is a
      short label, such as <code>cr-1a2b3c4d5e6f</code>, for the version of the rules that stored a
      run's answers. The submission keeps that label. It keeps no list of keys. The
      <RouterLink to="/learn/url4">url4</RouterLink>, the benchmark revision, the answer seed and
      the cache revision together name the cache version of the run.
    </p>

    <p>
      <code>sf.reproduce(score)</code> runs the score again from that cache version. The replay asks
      for <code>only-if-cached</code>. The cache then returns a stored answer or fails the call, and
      it never reaches a provider. So a replay costs no provider spend, and a missing answer fails
      its case instead of being bought. The
      <RouterLink to="/sf-client/guides/leaderboards">Leaderboards guide</RouterLink> shows the
      calls and the three outcomes.
    </p>

    <h3>Complete and partial</h3>

    <p>
      Each submission also stores a <code>reproducible</code> status. It is
      <code>complete</code> when the cache holds an answer for every model call and every web search
      of the run, all under one cache revision. It is <code>partial</code> when it cannot promise
      that. A partial score is not replayed: <code>sf.reproduce</code> returns
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
          <td>Bypass</td>
          <td>
            A call skipped the cache. The url4 turned caching off, the provider is not cached (see
            the Providers table), a parameter was not supported, the store was down, or a
            <code>max-age</code> limit forced a new call.
          </td>
        </tr>
        <tr>
          <td>Race</td>
          <td>
            Another run stored the same call first. This run got an answer, but the cache holds the
            other one.
          </td>
        </tr>
        <tr>
          <td>Web tool</td>
          <td>
            A web search was not served from the cache and was not stored after it ran. A search
            that is a hit, or is stored, keeps the run complete.
          </td>
        </tr>
        <tr>
          <td>Error</td>
          <td>
            A model or tool call failed, and no later attempt of the same request succeeded. A
            failed call stores nothing to replay. A retry that succeeds does not count.
          </td>
        </tr>
        <tr>
          <td>Mixed revisions</td>
          <td>
            The calls of one run carried two cache revisions, for example during a deploy. No single
            label names the run.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      A run with no model call and no web search is <code>complete</code> and has no cache revision.
      A score from a leaderboard that predates this feature has no status. That counts as unknown,
      and it is not replayed either.
    </p>

    <h3>Older revisions, newer software</h3>

    <p>
      When the cache rules change, the cache gets a new revision label. Every earlier label stays
      readable. A score stored under an older revision still replays with that revision, and the
      replay is read-only: it can never write under an old label.
    </p>

    <p>
      Software can still move away from a score. A replay can fail when you use a different SDK or
      engine version from the one that made the run:
    </p>

    <ul>
      <li>
        <strong>An older engine</strong> may not know replay at all. The replay stops before any
        case runs and reports <code>replay_unsupported</code>. It is never run as a normal call.
      </li>
      <li>
        <strong>An older cache service</strong> may not know the score's revision. The run fails at
        the start with <code>unknown_cache_revision</code>.
      </li>
      <li>
        <strong>A changed engine</strong> may build a request in another way. It then asks for an
        answer that the cache never stored, and the case fails with a <code>cache_miss</code>.
      </li>
      <li>
        <strong>A changed benchmark</strong> grades a different exam. The replay reports
        <code>benchmark_revision_changed</code>, because the numbers cannot be compared.
      </li>
    </ul>

    <p>
      A failed replay is not recorded, and it says nothing against the score. It says that this
      software cannot rebuild the run.
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
