<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import Tabs from '@/components/ui/Tabs.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import ProviderConnections from '@/components/nb/ProviderConnections.vue'
import type { Provider } from '@/components/nb/ProviderConnections.vue'
import { SF_ENGINE_URL } from '@/lib/engine'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const login = `import screamingface as sf

client = sf.Client(engine_url="${SF_ENGINE_URL}")
client.login()          # opens Cloudflare Access in your browser
client.authenticated    # True once the token arrives`

const panel = `sf.connect()`

const script = `sf.connect("openrouter", api_key="sk-or-v1-…")`

const local = `sf.configure(engine_url="http://127.0.0.1:9108")`

const readState = `sf.connections.list()`
const readStateOut = `(Connection(provider='openrouter', display_name='OpenRouter',
            auth_methods=('api_key',), status='connected',
            auth_method='api_key', account_label=None),)`

const readOne = `sf.connections.get("openrouter")`
const readOneOut = `Connection(provider='openrouter', display_name='OpenRouter',
           auth_methods=('api_key',), status='connected',
           auth_method='api_key', account_label=None)`

const remove = `sf.disconnect("openrouter")`

const panelProviders: Provider[] = [
  { id: 'codex', name: 'OpenAI Codex', status: 'disconnected' },
  { id: 'gemini', name: 'Google Gemini', status: 'disconnected' },
  { id: 'anthropic', name: 'Anthropic', status: 'disconnected' },
  { id: 'openrouter', name: 'OpenRouter', status: 'connected' },
  { id: 'huggingface', name: 'Hugging Face', status: 'disconnected' },
  { id: 'tavily', name: 'Tavily', status: 'disconnected' },
]
</script>

<template>
  <DocLayout
    title="Connections"
    description="Connect a model provider through the engine, and log in to a hosted one."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <strong>connection</strong> is a provider credential
      <RouterLink to="/learn/engine">the engine</RouterLink> holds on your behalf. The Client never
      talks to OpenRouter, Anthropic or any other provider directly. It sends your key to the engine
      once, the engine passes it to AI Gateway to validate and store encrypted, and every later
      model call is dispatched there.
    </p>

    <p>
      Two steps get you there: configure the engine, then connect a provider. Without a connection
      the engine can still list benchmarks and models, but any evaluation fails: there is no
      credential to call a model with.
    </p>

    <h2>What you can do with it</h2>

    <ul>
      <li>Login to the engine, or point the Client at your own engine instead.</li>
      <li>
        Connect a provider interactively from a notebook, or with an explicit key from a script.
      </li>
      <li>Read which providers this engine advertises, and the state of each.</li>
      <li>Remove a credential.</li>
    </ul>

    <h2>Main APIs</h2>

    <table>
      <thead>
        <tr>
          <th>API</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.connect()</code></td>
          <td>
            Called with no arguments, returns a <code>ConnectionPanel</code> widget listing every
            provider the engine advertises.
          </td>
        </tr>
        <tr>
          <td><code>sf.connect(provider, api_key=…)</code></td>
          <td>
            Connects one provider directly and returns the resulting <code>Connection</code> instead
            of a widget.
          </td>
        </tr>
        <tr>
          <td><code>sf.connections.list()</code></td>
          <td>
            Returns a tuple of every provider this engine advertises, one <code>Connection</code>
            each.
          </td>
        </tr>
        <tr>
          <td><code>sf.connections.get(provider)</code></td>
          <td>
            Fetches a single provider by name, returning its current state as a
            <code>Connection</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.disconnect(provider)</code></td>
          <td>
            Removes a stored credential; repeated calls are harmless and return the provider back in
            its <code>disconnected</code> state.
          </td>
        </tr>
        <tr>
          <td><code>sf.Connection</code></td>
          <td>
            The sanitised provider-state value, carrying the public provider name, its supported
            methods, and its state.
          </td>
        </tr>
        <tr>
          <td><code>sf.ConnectionPanel</code></td>
          <td>
            The live widget that <code>sf.connect()</code> returns when called with no arguments.
          </td>
        </tr>
        <tr>
          <td><code>sf.Client.login()</code> · <code>sf.Client.logout()</code></td>
          <td>
            Log in to and out of a hosted engine behind Cloudflare Access; <code>login()</code>
            opens a URL in your browser and holds the token in process memory only.
          </td>
        </tr>
      </tbody>
    </table>

    <h2>How to</h2>

    <h3>1 · Configure engine</h3>

    <p>Point the Client at an engine. There are two ways, depending on where it runs.</p>

    <Tabs :labels="['Hosted engine', 'Local engine']">
      <template #tab-0>
        <p>
          A hosted engine sits behind <strong>Cloudflare Access</strong>. There is no token to
          paste: <code>login()</code> prints a URL and opens it in your browser, then polls an
          encrypted transfer service and decrypts the returned token locally. The token lives only
          in process memory and is sent as <code>Cf-Access-Token</code>.
          <code>logout()</code> forgets it.
        </p>

        <div class="not-prose">
          <NbCell :count="1" :code="login" />
        </div>

        <p>
          In a notebook you rarely call this directly: the panel below handles it. A protected
          engine shows a login row first and loads provider rows only once login succeeds.
        </p>
      </template>

      <template #tab-1>
        <p>
          If you run the engine yourself, point the Client at it and skip the login step entirely: a
          local engine advertises no Cloudflare Access, so the panel shows provider rows
          immediately.
        </p>

        <div class="not-prose">
          <NbCell :count="2" :code="local" />
        </div>
      </template>
    </Tabs>

    <h3>2 · Connect from a notebook</h3>

    <p>
      Called with no arguments, <code>sf.connect()</code> returns a <code>ConnectionPanel</code>: a
      live widget listing every provider the engine advertises, with a field for each one's
      supported auth method. The
      <RouterLink to="/sf-client/quickstartPage">Quickstart</RouterLink> steps through the whole
      flow state by state.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="panel">
        <ProviderConnections :providers="panelProviders" engine-url="http://127.0.0.1:9108" />
      </NbCell>
    </div>

    <h3>3 · Connect from a script</h3>

    <p>
      With a provider and a key, the same function connects directly and returns the resulting
      <code>Connection</code> instead of a widget.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="script" />
    </div>

    <p>
      The two arguments go together. <code>sf.connect("openrouter")</code> without a key raises
      <code>ValueError</code>, and passing <code>api_key=</code> without a provider raises
      <code>TypeError</code>: there is no partial form that silently does nothing.
    </p>

    <h3>4 · Read the current state</h3>

    <div class="not-prose">
      <NbCell :count="5" :code="readState">
        <NbTextOut :text="readStateOut" />
      </NbCell>
    </div>

    <p>
      Note the trailing comma: <code>list()</code> returns a <strong>tuple</strong>, not a list, and
      this engine advertises exactly one provider. Fetch a single one by name when you only care
      about its state:
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="readOne">
        <NbTextOut :text="readOneOut" />
      </NbCell>
    </div>

    <h3>5 · Disconnect</h3>

    <div class="not-prose">
      <NbCell :count="7" :code="remove" />
    </div>

    <p>
      Repeated calls are harmless. The returned <code>Connection</code> shows the provider back in
      its <code>disconnected</code> state.
    </p>

    <h2>What a connection carries</h2>

    <p>
      Every <code>Connection</code> is sanitised: the public provider name, its supported methods,
      and its state. AI Gateway account IDs, credential locators and upstream error bodies never
      cross this boundary.
    </p>

    <ul>
      <li>
        <code>status</code>: one of <code>disconnected</code>, <code>pending</code>,
        <code>connected</code>, <code>needs_reauth</code>, <code>error</code>
      </li>
      <li>
        <code>auth_methods</code>: what the provider supports. The current engine advertises
        <code>('api_key',)</code> for OpenRouter
      </li>
      <li><code>auth_method</code>: which one is in use, or <code>None</code></li>
      <li><code>account_label</code>: an optional display label</li>
    </ul>

    <h2>When it fails</h2>

    <p>
      Credential problems raise <code>ProviderConnectionError</code>, which carries a stable
      <code>code</code> and a <code>hint</code>. One rule is worth knowing before you deploy: an API
      key sent to a non-loopback <code>http://</code> engine is
      <strong>refused outright</strong> with <code>secure_transport_required</code>. A remote engine
      must be HTTPS.
    </p>

    <h2>Links</h2>

    <ul>
      <li>
        <a
          href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb"
          target="_blank"
          rel="noopener"
          >Companion notebook: <code>00_quickstart.ipynb</code></a
        >
      </li>
    </ul>
  </DocLayout>
</template>
