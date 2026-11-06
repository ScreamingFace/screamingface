<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import Collapsible from '@/components/ui/Collapsible.vue'
import Tabs from '@/components/ui/Tabs.vue'
import NbCell from '@/components/nb/NbCell.vue'
import { SF_ENGINE_URL, SF_SCOREBOARD_URL } from '@/lib/engine'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const pypiNotebook = `!pip install "screamingface[notebook]"`
const pypiTerminal = `uv pip install "screamingface[notebook]"`
const pypiRuntime = `pip install "screamingface[runtime,notebook]"`

const verify = `import screamingface as sf

len(sf.__all__)   # 105`

const point = `import screamingface as sf

sf.configure(
    engine_url="${SF_ENGINE_URL}",
    scoreboard_url="${SF_SCOREBOARD_URL}",
)`

const loginCode = `client = sf.Client(engine_url="${SF_ENGINE_URL}")
client.login()          # a script opens Cloudflare Access in your browser; a notebook prints a link to open
client.authenticated    # True once the token arrives`

const prepare = `$ screamingface prepare medxpert
Benchmark assets ready at /Users/you/.screamingface/benchmark-assets`

const up = `$ screamingface up
ScreamingFace is ready.
  gateway db=sqlite:///Users/you/.screamingface/aigateway.sqlite3 · request_cache=on
  Gateway    http://127.0.0.1:9105
  Scoreboard http://127.0.0.1:9106
  Engine     http://127.0.0.1:9108
  Logs       /Users/you/.screamingface/runtime.log
  export SCREAMINGFACE_ENGINE_URL=http://127.0.0.1:9108
  export SCREAMINGFACE_SCOREBOARD_URL=http://127.0.0.1:9106`

const localPoint = `sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)`

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

const analytics = `$ screamingface analytics status
{"choice": "accepted", "enabled": true, "scope": "installation", "installation_id": "e368e2f6-68a0-4824-9c92-79388a95398f"}`

const analyticsPython = `sf.analytics.status()
# {'choice': 'accepted', 'enabled': True, 'scope': 'installation', 'installation_id': 'cfcae993-e908-4513-8e01-7d1f3822031c'}`

const cachePull = `$ screamingface cache pull --model openrouter/anthropic/claude-opus-4.8`

const certs = `SSL_CERT_FILE=$(python -c "import certifi;print(certifi.where())") \\
  screamingface prepare medxpert`
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
      always needs an <RouterLink to="/learn/engine">engine</RouterLink> to talk to. Use a hosted
      one if your account has access, or run your own on your machine. The code you write is the
      same either way.
    </p>

    <h2>1 · Install the Client</h2>

    <p>
      You need Python <strong>3.12 or newer</strong>. In a notebook, install the Client with one
      cell:
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="pypiNotebook" />
    </div>

    <p>From a terminal, run:</p>

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
          The fastest start, once your account has access. Name the hosted engine once, log in
          through your browser, and you are running on compute we provide. There is no local setup,
          and no provider key of your own: the hosted engine does not take one (bring-your-own-key
          is the local path). To get access, reach out to the OpenMined team. Until your account has
          access, use the local engine tab: after login every provider shows as unavailable and an
          evaluation is refused.
        </p>

        <div class="not-prose">
          <NbCell :count="1" :code="point" />
        </div>

        <p>
          A hosted engine sits behind Cloudflare Access. There is no token to paste:
          <code>login()</code> collects it through your browser. In a script it opens the browser
          for you; in a notebook it prints a link to open.
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
          <strong>Prepare the benchmark you will run:</strong> The engine reads datasets from disk
          rather than downloading them mid-run, so a run cannot silently use a different revision. A
          local engine started with <code>screamingface up</code> comes with <code>medxpert</code>
          (2,450 questions) ready to run, a fine default to start with. The hosted engine serves the
          full set (DRACO, IFEval and the other leaderboard benchmarks) with no setup, and those
          benchmarks can run on a local engine from a repository checkout: run
          <code>just local-stack-notebooks</code> from <code>packages/screamingface/</code> (<a
            href="https://github.com/casey/just"
            target="_blank"
            rel="noopener"
            >just</a
          >
          is the command runner). The pip package does not install <code>inspect-ai</code>, which
          those benchmarks need, so a local engine ships with <code>medxpert</code> ready out of the
          box.
        </p>

        <CodeBlock :code="prepare" language="bash" />

        <p>
          <strong>Start the stack:</strong> One command brings up three loopback services: the
          engine executes runs, the gateway holds your provider keys and calls the models, and the
          scoreboard serves your local leaderboard.
        </p>

        <CodeBlock :code="up" language="bash" />

        <p>
          <strong>Point the Client at it:</strong> No login step: a local engine advertises none. A
          non-default <code>engine_url</code> requires <code>scoreboard_url</code> in the same call.
          With no <code>configure</code> call and no <code>SCREAMINGFACE_ENGINE_URL</code>, the
          Client uses a running local stack and prints
          <code>connected to the local stack at http://127.0.0.1:9108</code>.
        </p>

        <div class="not-prose">
          <NbCell :count="3" :code="localPoint" />
        </div>

        <p>
          From there <code>screamingface status</code> checks it,
          <code>screamingface logs</code> follows it, and <code>screamingface down</code> stops it.
          Enabling providers, web search, port conflicts, the local leaderboard, the cache and
          analytics are in the FAQ below.
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

    <Collapsible title="OpenRouter is missing or its key is rejected">
      <p>
        <code>screamingface up</code> enables the OpenRouter provider for you. If you set
        <code>AIGW_OPENROUTER_ENABLED=false</code>, OpenRouter no longer appears in
        <code>sf.connections.list()</code>, <code>sf.connect("openrouter", ...)</code> raises
        <code>unknown_provider</code> ("The provider is not available on this SF Engine"), and an
        evaluation of an OpenRouter route raises <code>model_not_found</code>. Unset the variable,
        or set it to <code>true</code>, in the shell you start the runtime from, then run
        <code>screamingface down &amp;&amp; screamingface up</code>. The gateway reads the setting
        at startup.
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
        If the occupant is something you would rather not kill, you do not have to free the port.
        Move the stack instead. Every port is overridable, either as a flag on <code>up</code> and
        <code>restart</code>, or as an environment variable:
      </p>
      <CodeBlock :code="ports" language="bash" />
      <p>
        If you move the <em>engine</em> port, point the client at the new one, next to its
        scoreboard (a non-default engine always needs both):
        <code>sf.configure(engine_url="http://127.0.0.1:9208", scoreboard_url=…)</code>.
      </p>
      <p>
        One caveat worth knowing: the environment variables are read by <code>up</code>,
        <code>restart</code>, <code>status</code> and <code>doctor</code> only;
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
        benchmarks that never search, such as <code>medxpert</code>, need none.
      </p>
      <p>Export it before <code>up</code>, in the shell you start the runtime from:</p>
      <CodeBlock :code="tavily" language="bash" />
      <p>
        Without the key, web tools stay off by default: a candidate whose route depends on the
        Tavily loop fails before its first paid request rather than quietly answering a research
        question with no research behind it.
      </p>
    </Collapsible>

    <Collapsible title="Submit to my own leaderboard, not the hosted one">
      <p>
        <code>sf.configure(engine_url=...)</code> with a non-default engine raises
        <code>ValueError</code> unless <code>scoreboard_url</code> is passed too, and
        <code>SCREAMINGFACE_ENGINE_URL</code> requires <code>SCREAMINGFACE_SCOREBOARD_URL</code>.
        The pair decides where <code>sf.leaderboards.submit</code> publishes. Pass the local
        scoreboard to keep scores local:
      </p>
      <CodeBlock :code="localBoth" language="python" />
      <p>
        Pass <code>scoreboard_url="https://leaderboard.screamingface.ai"</code> to publish to the
        hosted leaderboard from a local engine. Submitting there needs a Cloudflare Access login,
        and access is granted by the OpenMined team.
      </p>
    </Collapsible>

    <Collapsible title="Does a local run use a cache?">
      <p>
        <code>screamingface up</code> starts the gateway with <code>request_cache=on</code>: a model
        call that was made before with the same route, prompt and parameters is answered from the
        local cache. Pass <code>use_cache=False</code> to <code>sf.evaluate</code> to opt one run
        out, or export <code>AIGW_REQUEST_CACHE_ENABLED=false</code> before
        <code>screamingface up</code> to turn the cache off. The cache starts empty. To start from
        the community cache, pull it into the local gateway; the pull signs in to the hosted engine,
        which needs an account with access:
      </p>
      <CodeBlock :code="cachePull" language="bash" />
      <p>
        <code>sf.cache.pull_from_remote()</code> does the same from Python and returns a
        <code>PullResult</code>. <code>--model</code> repeats to limit the pull to those models.
      </p>
    </Collapsible>

    <Collapsible title="Does the Client send analytics?">
      <p>
        Analytics are on by default. The first <code>import screamingface</code> prints a notice and
        saves the choice <code>accepted</code>. <code>screamingface analytics status</code> and
        <code>sf.analytics.status()</code> report the choice; <code>enable</code>,
        <code>disable</code> and <code>reset_identifier</code> change it, and
        <code>sf.analytics.disable()</code> turns analytics off. A non-empty
        <code>DO_NOT_TRACK</code> value other than <code>0</code>, <code>false</code>,
        <code>no</code> or <code>off</code> disables analytics for the process, and the first import
        then prints no notice and saves nothing.
      </p>
      <CodeBlock :code="analytics" language="bash" />
      <CodeBlock :code="analyticsPython" language="python" />
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
        Not if your account has hosted access: the hosted engine skips the local setup entirely.
        Without access, run your own. A local engine puts the whole stack on your own machine, on
        your own keys.
      </p>
    </Collapsible>
  </DocLayout>
</template>
