<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import Collapsible from '@/components/ui/Collapsible.vue'
import Tabs from '@/components/ui/Tabs.vue'
import NbCell from '@/components/nb/NbCell.vue'
import { SF_ENGINE_URL } from '@/lib/engine'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const pypiNotebook = `!pip install "screamingface[notebook]"`
const pypiTerminal = `uv pip install "screamingface[notebook]"`
const pypiRuntime = `pip install "screamingface[runtime,notebook]"`

const verify = `import screamingface as sf

len(sf.__all__)   # 56`

const point = `import screamingface as sf

sf.configure(engine_url="${SF_ENGINE_URL}")`

const loginCode = `client = sf.Client(engine_url="${SF_ENGINE_URL}")
client.login()          # opens Cloudflare Access in your browser
client.authenticated    # True once the token arrives`

const prepare = `$ screamingface prepare draco
Benchmark assets ready at /Users/you/.screamingface/benchmark-assets`

const up = `$ screamingface up
ScreamingFace is ready.
  Gateway     http://127.0.0.1:9105
  Leaderboard http://127.0.0.1:9106
  Engine      http://127.0.0.1:9108
  Logs        /Users/you/.screamingface/runtime.log`

const localPoint = `sf.configure(engine_url="http://127.0.0.1:9108")`

const localBoth = `sf.configure(engine_url="http://127.0.0.1:9108", scoreboard_url="http://127.0.0.1:9106")`

const ports = `# either as flags, on up and restart...
screamingface up --gateway-port 9205 --scoreboard-port 9206 --engine-port 9208

# ...or as environment variables
export SCREAMINGFACE_GATEWAY_PORT=9205
export SCREAMINGFACE_SCOREBOARD_PORT=9206
export SCREAMINGFACE_ENGINE_PORT=9208
screamingface up`

const tavily = `export TAVILY_API_KEY="tvly-..."
screamingface up`

const searchCheck = `gpt = sf.models.get("openrouter/openai/gpt-5.5")
"web_search" in gpt.tools   # True when the provider searches for itself`

const certs = `SSL_CERT_FILE=$(python -c "import certifi;print(certifi.where())") \\
  screamingface prepare draco`
</script>

<template>
  <DocLayout
    title="Installation"
    description="Install the Client and point it at an engine, hosted or one you run yourself."
    :navigation="navigation"
    :version="version"
  >
    <p>
      The <strong>Client</strong> is a Python library. It never calls a model provider itself, so it
      always needs an <RouterLink to="/learn/engine">engine</RouterLink> to talk to. Reach a hosted
      one for the fastest start, or run your own on your machine. The code you write is the same
      either way.
    </p>

    <h2>1 · Install the Client</h2>

    <p>Python <strong>3.12 or newer</strong>. In a notebook, one cell:</p>

    <div class="not-prose">
      <NbCell :count="1" :code="pypiNotebook" />
    </div>

    <p>Or from a terminal:</p>

    <CodeBlock :code="pypiTerminal" language="bash" />

    <p>
      The <code>[notebook]</code> extra pulls in ipywidgets, so <code>sf.connect()</code> renders a
      live panel in whatever Jupyter frontend you already use; drop it for scripts. Everything else,
      including <RouterLink to="/learn/url4"><code>url4</code></RouterLink
      >, resolves automatically. A quick check that it worked:
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="verify" />
    </div>

    <h2>2 · Point at an engine</h2>

    <Tabs :labels="['Hosted engine', 'Your own engine']">
      <template #tab-0>
        <p>
          The fastest start. Name the hosted engine once, log in through your browser, and you are
          running on compute we provide. There is no local setup, and no provider key of your own:
          the hosted engine does not take one (bring-your-own-key is the local path).
          Hosted access is currently by invitation — if you haven't been approved yet, use the
          local engine tab below while you wait.
        </p>

        <div class="not-prose">
          <NbCell :count="1" :code="point" />
        </div>

        <p>
          A hosted engine sits behind Cloudflare Access. There is no token to paste:
          <code>login()</code> opens your browser and collects it.
        </p>

        <div class="not-prose">
          <NbCell :count="2" :code="loginCode" />
        </div>

        <p>
          That is the whole hosted path. The
          <RouterLink to="/sf-client/first-fusion">Quickstart</RouterLink> takes it from here, and
          the <RouterLink to="/sf-client/guides/connections">Connections</RouterLink> guide covers
          provider access.
        </p>
      </template>

      <template #tab-1>
        <p>
          Everything runs on your machine, on your own keys, with no account and no login. The
          engine ships in the same package behind the <code>[runtime]</code> extra, so it is one
          more install and three commands, not a separate deployment:
        </p>

        <CodeBlock :code="pypiRuntime" language="bash" />

        <p>
          <strong>Prepare the benchmark you will run.</strong> The engine reads datasets from disk
          rather than downloading them mid-run, so a run cannot silently use a different revision.
          Pass a family (<code>draco</code>, <code>ifeval</code>, <code>healthbench</code>) or
          <code>--all</code>, once:
        </p>

        <CodeBlock :code="prepare" language="bash" />

        <p>
          <strong>Start the stack.</strong> One command brings up three loopback services: the
          engine executes runs, the gateway holds your provider keys and calls the models, and the
          leaderboard serves your local rankings.
        </p>

        <CodeBlock :code="up" language="bash" />

        <p>
          <strong>Point the Client at it.</strong> No login step: a local engine advertises none.
        </p>

        <div class="not-prose">
          <NbCell :count="3" :code="localPoint" />
        </div>

        <p>
          From there <code>screamingface status</code> checks it,
          <code>screamingface logs</code> follows it, and <code>screamingface down</code> stops it.
          Enabling providers, web search, port conflicts, and the local leaderboard are in the FAQ
          below.
        </p>
      </template>
    </Tabs>

    <h2>Frequently asked questions</h2>

    <Collapsible title='"Local runtime dependencies are missing" or command not found'>
      <p>
        The Client is installed but the engine is not. The <code>screamingface</code> command and
        the server stack both come from the <code>[runtime]</code> extra:
      </p>
      <CodeBlock :code="pypiRuntime" language="bash" />
      <p>Reopen your shell afterwards if the command still is not found.</p>
    </Collapsible>

    <Collapsible title="A valid provider key is rejected">
      <p>
        Provider plugins ship disabled, so the gateway refuses the key regardless of whether it is
        good. Enable the provider in the shell you start the runtime from and restart, for example
        <code>AIGW_OPENROUTER_ENABLED=true</code> then
        <code>screamingface down &amp;&amp; screamingface up</code>. The gateway reads the setting
        at startup, and the error names the credential rather than the configuration, so it is easy
        to spend a while checking a key that was never the problem.
      </p>
    </Collapsible>

    <Collapsible title="up refuses to start: a port is already in use">
      <p>
        The stack defaults to 9105, 9106 and 9108, and it names the occupied ones rather than
        starting halfway. Run <code>screamingface status</code>:
        <code>foreign processes occupy runtime ports</code>
        means something unrelated holds them; if a previous stack is still up,
        <code>screamingface down</code> is enough.
      </p>
      <p>
        If the occupant is something you would rather not kill, you do not have to free the port —
        move the stack instead. Every port is overridable, either as a flag on <code>up</code> and
        <code>restart</code>, or as an environment variable:
      </p>
      <CodeBlock :code="ports" language="bash" />
      <p>
        If you move the <em>engine</em> port, point the client at the new one:
        <code>sf.configure(engine_url="http://127.0.0.1:9208")</code>.
      </p>
      <p>
        One caveat worth knowing: the environment variables are read by <code>up</code>,
        <code>restart</code>, <code>status</code> and <code>doctor</code> only —
        <code>down</code> and <code>logs</code> ignore them. That is harmless in practice, because
        those two work from the runtime state recorded in your data directory rather than from a
        port, so they stop and tail whatever <code>up</code> started, on whichever ports it used.
      </p>
    </Collapsible>

    <Collapsible title="Do I need a Tavily (web-search) key?">
      <p>
        Only when you run your own engine <em>and</em> a route you evaluate cannot search the web
        itself. Benchmarks like DRACO ask candidates to research an answer; most providers search
        natively and the engine just asks them to. The exception is providers with no search of
        their own (<strong>Hugging Face</strong> routes in particular), where the engine falls back
        to a bounded tool loop it runs against Tavily. A hosted engine supplies its own key;
        benchmarks that never search, such as <code>ifeval</code>, need none.
      </p>
      <p>Export it before <code>up</code>, in the shell you start the runtime from:</p>
      <CodeBlock :code="tavily" language="bash" />
      <p>
        Without the key, web tools stay off by default: a candidate whose route depends on the
        Tavily loop fails before its first paid request rather than quietly answering a research
        question with no research behind it. To tell which case you are in, ask what a route
        supports:
      </p>
      <div class="not-prose">
        <NbCell :count="1" :code="searchCheck" />
      </div>
    </Collapsible>

    <Collapsible title="Submit to my own leaderboard, not the hosted one">
      <p>
        By default the Client reads and writes the hosted ScreamingFace Leaderboard even when the
        rest of your stack is local. Point it at your local one by passing
        <code>scoreboard_url</code> next to <code>engine_url</code>:
      </p>
      <CodeBlock :code="localBoth" language="python" />
    </Collapsible>

    <Collapsible title="CERTIFICATE_VERIFY_FAILED while preparing benchmark assets">
      <p>
        A macOS Python without a CA bundle, so the dataset download cannot verify TLS. Point that
        one command at certifi's bundle:
      </p>
      <CodeBlock :code="certs" language="bash" />
    </Collapsible>

    <Collapsible title="Do I have to run my own engine?">
      <p>
        No. The hosted engine skips the local setup entirely. Running your own exists for people who
        want the whole stack on their own machine, on their own keys.
      </p>
    </Collapsible>
  </DocLayout>
</template>
