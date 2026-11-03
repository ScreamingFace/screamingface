<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const pull = `import screamingface as sf

result = sf.cache.pull_from_remote()                      # every model
result = sf.cache.pull_from_remote(["openrouter/anthropic/claude-opus-5.5"])  # one model`

const handle = `try:
    result = sf.cache.pull_from_remote()
except sf.cache.CachePullError as exc:
    print(exc.code, exc.result)             # how far the pull got
    result = sf.cache.pull_from_remote()    # same process: continues from the last page`

const optOut = `model = sf.Model("openrouter/google/gemini-3.5-flash-lite")
report = sf.evaluate(model, benchmark="medxpert", limit=2, use_cache=False)`

const shell = `screamingface cache pull
screamingface cache pull --model openrouter/anthropic/claude-opus-5.5
screamingface cache pull --url https://fusion.screamingface.ai --data-dir ~/.screamingface`
</script>

<template>
  <DocLayout
    title="Shared cache"
    description="Use the shared cache from the hosted engine when running locally."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Whether you run on a hosted or a local engine, your cache accumulates, and you can reuse it on
      any run to lower that run's cost. On the hosted engine the cache is shared: you benefit from
      everyone else's runs and they benefit from yours, so the whole community pushes fusion
      research further at lower cost. Calls the cache cannot key are not shared. A call that is not
      in the cache is billed to the provider account that runs it. If you run your own local engine
      and want the shared cache, download it with the <code>sf.cache</code> module.
    </p>

    <p>
      The gateway of a local engine stores each model response, keyed by the exact request, and
      serves a repeat of that request from the store.
      <code>sf.cache</code> loads the shareable rows of the hosted community cache into that store,
      so a local run answers from them, for free, the calls the community has already made.
      <RouterLink to="/learn/caching">Caching and compute</RouterLink> explains how the cache works.
    </p>

    <h2>The local request cache</h2>

    <ul>
      <li>
        <strong>Default:</strong> <code>screamingface up</code> sets
        <code>AIGW_REQUEST_CACHE_ENABLED=true</code> unless the variable is already exported, so the
        local gateway caches by default. An exported <code>false</code> turns it off.
      </li>
      <li><strong>Expiry:</strong> Entries do not expire.</li>
      <li>
        <strong>Opt out per evaluation:</strong>
        <code>use_cache=False</code> on <code>sf.evaluate</code>, <code>Client.evaluate</code> and
        <code>AsyncClient.evaluate</code> starts the run with <code>Cache-Control: no-cache</code>.
        The engine makes every model call fresh, and the report shows those calls as cache
        <code>bypass</code> with the reason <code>opted_out</code>. The default is
        <code>use_cache=True</code>.
      </li>
    </ul>

    <CodeBlock :code="optOut" language="python" />

    <h2>sf.cache.pull_from_remote</h2>

    <table>
      <thead>
        <tr>
          <th>Signature</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <code>sf.cache.pull_from_remote(models=None, *, url=None, progress=None)</code>
          </td>
          <td>
            Copies the hosted community cache into the local gateway database and returns a
            <code>PullResult</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <ul>
      <li>
        <strong><code>models</code>:</strong> A sequence of model names, exactly as the hosted cache
        names them, for example <code>"openrouter/anthropic/claude-opus-5.5"</code>. A run can hit
        only the rows of the models its candidates and judge use, so a filtered pull loses no hits.
        <code>None</code> pulls every model. A single string raises <code>TypeError</code>, and so
        does an empty or non-string name.
      </li>
      <li>
        <strong><code>url</code>:</strong> The hosted engine to pull from. <code>None</code> is the
        production engine. It never follows the engine your runs use: with
        <code>screamingface up</code> running, that is the local engine, where the rows go, not
        where they come from.
      </li>
      <li>
        <strong><code>progress</code>:</strong> <code>None</code> shows progress in a notebook or an
        interactive terminal. <code>True</code> and <code>False</code> force it on or off.
      </li>
    </ul>

    <CodeBlock :code="pull" language="python" />

    <Note>
      The first page opens the engine's sign-in in a browser, unless this process is already signed
      in to that engine, by an earlier pull or by the default client. One sign-in serves every later
      pull in the process. The production engine needs access granted by the OpenMined team, so a
      pull needs the same hosted access as <code>sf.login()</code>.
    </Note>

    <p>The pull also needs:</p>

    <ul>
      <li><code>screamingface[runtime]</code> installed, which provides the local gateway.</li>
      <li>A local gateway database. Run <code>screamingface up</code> once to create it.</li>
      <li>
        <code>SCREAMINGFACE_DATA_DIR</code> set to the data directory of a stack started with
        <code>screamingface up --data-dir DIR</code>. The default is <code>~/.screamingface</code>,
        the stack <code>sf.connect()</code> finds.
      </li>
    </ul>

    <h2>PullResult</h2>

    <p>
      A frozen dataclass that says what one call did. <code>pull_from_remote</code> returns it, and
      <code>CachePullError.result</code> carries it when a pull stops.
    </p>

    <table>
      <thead>
        <tr>
          <th>Field</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>rows_read</code></td>
          <td><code>int</code></td>
          <td>The rows of completed pages.</td>
        </tr>
        <tr>
          <td><code>rows_added</code></td>
          <td><code>int</code></td>
          <td>
            The rows that were new to the local cache. A row the cache already held is kept and not
            counted.
          </td>
        </tr>
        <tr>
          <td><code>pages</code></td>
          <td><code>int</code></td>
          <td>The pages the call completed.</td>
        </tr>
        <tr>
          <td><code>resumed</code></td>
          <td><code>bool</code></td>
          <td><code>True</code> when the call continued a pull this process had started.</td>
        </tr>
        <tr>
          <td><code>complete</code></td>
          <td><code>bool</code></td>
          <td><code>True</code> when the call reached the last page.</td>
        </tr>
        <tr>
          <td><code>rows_skipped</code></td>
          <td><code>int</code></td>
          <td>
            The rows of completed pages that the local gateway could not serve, which were not
            loaded. The default is <code>0</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <h2>CachePullError</h2>

    <p>
      <code>CachePullError</code> subclasses <code>ScreamingFaceError</code> and has the default
      code <code>community_cache_pull_failed</code>. It is raised when a pull stops before its last
      page. Its <code>result</code> attribute is a <code>PullResult</code> that says how far the
      pull got.
    </p>

    <ul>
      <li>
        <strong>Retries:</strong> A dropped connection, a rate limit, an edge error or a cut page is
        retried 4 times, with 2, 4 and 8 seconds between attempts. A <code>Retry-After</code>
        from the engine is honoured up to 60 seconds.
      </li>
      <li>
        <strong>Loaded rows stay loaded:</strong> Every row is an independent cache entry. Calling
        <code>pull_from_remote</code> again in the same process, with the same <code>url</code> and
        <code>models</code>, continues from the last loaded page.
      </li>
      <li>
        <strong>A new process starts over:</strong> The cursor lives in memory. A pull whose process
        ended starts again, which costs only time, because rows already loaded are kept.
      </li>
      <li>
        <strong>Interrupts:</strong> Ctrl-C re-raises the <code>KeyboardInterrupt</code> with the
        same counts as its <code>result</code> attribute, and the next call continues the same way.
      </li>
    </ul>

    <CodeBlock :code="handle" language="python" />

    <h2>screamingface cache pull</h2>

    <p>The shell command runs the same pull and always shows progress.</p>

    <CodeBlock :code="shell" language="bash" />

    <table>
      <thead>
        <tr>
          <th>Option</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>--model MODEL</code></td>
          <td>Only this model's rows, as the hosted cache names it. Repeat it for more models.</td>
        </tr>
        <tr>
          <td><code>--url URL</code></td>
          <td>The hosted engine to pull from. The default is the production engine.</td>
        </tr>
        <tr>
          <td><code>--data-dir DIR</code></td>
          <td>The data directory of the stack to load the rows into.</td>
        </tr>
      </tbody>
    </table>

    <p>
      The exit code is <code>0</code> when the pull finished, <code>1</code> when it stopped or was
      refused (the reason goes to stderr), and <code>130</code> when it was interrupted. An
      interrupted command starts over on the next run.
    </p>
  </DocLayout>
</template>
