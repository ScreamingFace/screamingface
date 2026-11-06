<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import ThemedDiagram from '@/components/ui/ThemedDiagram.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const install = `pip install "screamingface[runtime]"`

const up = `screamingface up`

const upDataDir = `screamingface up --data-dir /path/to/data
export SCREAMINGFACE_DATA_DIR=/path/to/data`

const pull = `import screamingface as sf

models = [
    "openrouter/anthropic/claude-opus-4.8",     # your candidate
    "openrouter/google/gemini-3.5-flash-lite",  # your judge
]
result = sf.cache.pull_from_remote(models)
print(result)`

const pullShell = `screamingface cache pull \\
  --model openrouter/anthropic/claude-opus-4.8 \\
  --model openrouter/google/gemini-3.5-flash-lite`

const pullResult = `PullResult(rows_read=4631, rows_added=4631, pages=1, resumed=False, complete=True, rows_skipped=0)`

const run = `model = sf.Model("openrouter/anthropic/claude-opus-4.8")
report = sf.evaluate(model, benchmark="medxpert", limit=2)`

const retry = `try:
    result = sf.cache.pull_from_remote(models)
except sf.cache.CachePullError as exc:
    print(exc.code, exc.result)                 # how far the pull got
    result = sf.cache.pull_from_remote(models)  # continues from the last page`
</script>

<template>
  <DocLayout
    title="Using the community's cache"
    description="Pull the hosted community cache into a local engine, so your local runs answer calls the community has already made, for free."
    :navigation="navigation"
    :version="version"
  >
    <p>
      This guide is for <strong>local runners</strong>. If you run on the hosted engine, you already
      use the shared community cache, with nothing to set up or change.
    </p>

    <p>
      A local engine starts with only your own cache. Pull the hosted community cache into it, and
      your local runs answer every model call the community has already made for free. With your local
      stack running, it takes one command.
    </p>

    <ThemedDiagram
      name="sf-community-cache-pull"
      alt="Your local cache fills from your own runs and from pulling the shared global community cache; calls already in the cache run for free."
      caption="Your cache fills from your own runs and from the shared global cache. Calls already in it run for free."
    />

    <h2>Before you start</h2>

    <p>
      You need <code>screamingface[runtime]</code> installed. It provides the local gateway.
    </p>

    <CodeBlock :code="install" language="bash" />

    <h2>1 · Start the local engine</h2>

    <CodeBlock :code="up" language="bash" />

    <p>
      This creates the local gateway database, which the pull loads rows into, and turns request
      caching on. If you exported <code>AIGW_REQUEST_CACHE_ENABLED=false</code>, unset it first: with
      caching off, the gateway does not serve from its store.
    </p>

    <p>
      If your stack uses a data directory other than the default <code>~/.screamingface</code>, start
      it with that directory and point the pull at it:
    </p>

    <CodeBlock :code="upDataDir" language="bash" />

    <h2>2 · Pull the cache for your models</h2>

    <p>
      Pull only the models your run uses, candidates and judge. A run can hit only those models'
      rows, so a filtered pull loses no hits and finishes sooner. Write each name exactly as the
      hosted cache names it.
    </p>

    <CodeBlock :code="pull" language="python" />

    <p>
      Pass a list even for one model: a bare string raises <code>TypeError</code>. Call
      <code>pull_from_remote()</code> with no arguments to pull every model.
    </p>

    <p>
      The first pull opens the engine's sign-in in your browser. One sign-in covers every later pull
      in the same process.
    </p>

    <p>
      To pull from the shell instead, repeat <code>--model</code> once per model. Add
      <code>--data-dir DIR</code> if your stack does not use the default data directory.
    </p>

    <CodeBlock :code="pullShell" language="bash" />

    <h2>3 · Check the result</h2>

    <p>
      The pull returns a <code>PullResult</code>. Your counts depend on what the community cache holds
      when you run it.
    </p>

    <CodeBlock :code="pullResult" language="python" />

    <ul>
      <li><code>complete=True</code> means the pull reached the last page.</li>
      <li>
        <code>rows_added</code> counts rows new to your local cache. Rows you already had are kept and
        not counted.
      </li>
      <li>
        <code>rows_skipped</code> counts rows your local gateway cannot serve. They are not loaded.
      </li>
    </ul>

    <h2>4 · Run your evaluation</h2>

    <p>
      Run as usual. <code>use_cache=True</code> is the default, so every call already in the cache is
      answered from it for free. A call that is not in the cache runs fresh and is billed to the
      provider account that runs it.
    </p>

    <CodeBlock :code="run" language="python" />

    <p>
      To make every call fresh for one run, pass <code>use_cache=False</code>. The report then shows
      those calls as <code>cache bypass</code> with the reason <code>opted_out</code>.
    </p>

    <h2>If the pull stops</h2>

    <p>
      A pull that stops before its last page raises <code>sf.cache.CachePullError</code>, after 4
      automatic retries of dropped connections, rate limits and edge errors. Rows loaded so far stay
      loaded. Call again in the same process, with the same models and url, and the pull continues
      from the last loaded page.
    </p>

    <CodeBlock :code="retry" language="python" />

    <p>
      A new process starts again from the first page, but rows already loaded are kept, so it costs
      only time. <code>Ctrl-C</code> behaves the same way: the next call in the process continues.
    </p>

    <p>
      The shell command exits with <code>0</code> when the pull finished, <code>1</code> when it
      stopped or was refused (the reason goes to stderr), and <code>130</code> when interrupted. An
      interrupted command starts over on the next run.
    </p>

    <h2>Keep the cache current</h2>

    <p>
      Local entries never expire, and the community cache keeps growing. Pull again before a large
      evaluation to pick up new rows; <code>rows_added</code> tells you how many were new.
    </p>

    <h2>See also</h2>

    <ul>
      <li>
        <RouterLink to="/learn/caching">Caching and compute</RouterLink> for how the cache works.
      </li>
      <li>
        <RouterLink to="/sf-client/api/cache">Shared cache reference</RouterLink> for every parameter
        of <code>sf.cache</code>.
      </li>
    </ul>
  </DocLayout>
</template>
