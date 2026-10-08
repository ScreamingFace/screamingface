<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const shared = `import screamingface as sf

sf.configure(engine_url="http://127.0.0.1:9108")
[(b.id, b.variant) for b in sf.benchmarks.list()][:3]`
const sharedOut = `[('draco', 'canonical'), ('draco/lite', 'lite'), ('draco/smoke', 'smoke')]`

const configureSig = `sf.configure(
    *,
    engine_url: str = "https://fusion.dev.screamingface.ai",
    scoreboard_url: str = "https://leaderboard.dev.screamingface.ai",
) -> Client`

const evaluateSig = `sf.evaluate(
    candidates: Recipe | Sequence[Recipe] | str,
    *,
    benchmark: str | None = None,
    limit: int | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
    answer_seed: int | None = None,
    capture: bool = False,
) -> Report`

const reproduceSig = `sf.reproduce(
    score: LeaderboardScore | UUID | str,
    *,
    record: bool = True,
) -> Reproduction`
</script>

<template>
  <DocLayout
    title="Modules"
    description="The five modules and six functions you can call on sf directly."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Every name on this page works two ways. On a
      <RouterLink to="/sf-client/api/clients">Client</RouterLink> you build yourself, they are its
      attributes and methods: <code>client.benchmarks</code>, <code>client.evaluate(...)</code>. On
      the <code>sf</code> module, the same names act on a default Client the library creates and
      manages for you, so a script or notebook can call <code>sf.evaluate(...)</code> without
      constructing one.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="shared"><NbTextOut :text="sharedOut" /></NbCell>
    </div>

    <Note>
      Both forms return the same values. Mixing them is fine, but a Client you construct yourself is
      separate from the shared one, so <code>sf.configure()</code> does not affect it.
    </Note>

    <h2>sf.benchmarks</h2>

    <table>
      <thead>
        <tr>
          <th>Function</th>
          <th>Returns</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>list()</code></td>
          <td>
            Every <RouterLink to="/sf-client/api/benchmarks">Benchmark</RouterLink> the engine
            offers, one entry per protocol variant.
          </td>
        </tr>
        <tr>
          <td><code>get(benchmark_id)</code></td>
          <td>One <code>Benchmark</code>. The id carries the variant.</td>
        </tr>
      </tbody>
    </table>

    <h2>sf.models</h2>

    <table>
      <thead>
        <tr>
          <th>Function</th>
          <th>Returns</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>list()</code></td>
          <td>
            Every <RouterLink to="/sf-client/api/models">ModelInfo</RouterLink> route the engine can
            reach.
          </td>
        </tr>
        <tr>
          <td><code>get(model_id)</code></td>
          <td>
            The full <code>ModelDetails</code> profile for one route. Needs that provider connected.
          </td>
        </tr>
      </tbody>
    </table>

    <h2>sf.connections</h2>

    <p>
      This module also re-exports the connection types themselves:
      <code>Connection</code>, <code>ConnectionStatus</code>, <code>OAuthFlow</code> and
      <code>AsyncOAuthFlow</code>.
    </p>

    <table>
      <thead>
        <tr>
          <th>Function</th>
          <th>Returns</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>list()</code></td>
          <td>
            A <RouterLink to="/sf-client/api/clients">Connection</RouterLink> for every provider the
            engine advertises, connected or not.
          </td>
        </tr>
        <tr>
          <td><code>get(provider)</code></td>
          <td>One provider's current state.</td>
        </tr>
      </tbody>
    </table>

    <h2>sf.leaderboards</h2>

    <p>
      Alone among the four, this module talks to the leaderboard rather than the engine. See
      <RouterLink to="/sf-client/api/leaderboards">Leaderboards</RouterLink> for the values it
      returns.
    </p>

    <table>
      <thead>
        <tr>
          <th>Function</th>
          <th>Returns</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>list()</code></td>
          <td>A <code>LeaderboardInfo</code> for every board.</td>
        </tr>
        <tr>
          <td><code>get(benchmark_id, *, top=50)</code></td>
          <td>One <code>Leaderboard</code>, its entries capped by <code>top</code>.</td>
        </tr>
        <tr>
          <td><code>get_score(score_id)</code></td>
          <td>One <code>LeaderboardScore</code> by its identifier.</td>
        </tr>
        <tr>
          <td><code>submit(candidate_result)</code></td>
          <td>
            Publishes one
            <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink> to the
            public board and returns the stored <code>LeaderboardScore</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <h2>sf.events</h2>

    <p>
      Unlike the four above, <code>sf.events</code> exposes no functions. It holds the event types a
      run reports through <code>on_event</code>, covered in
      <RouterLink to="/sf-client/api/events">Events</RouterLink>.
    </p>

    <h2>Top-level functions</h2>

    <p>
      These six act on the shared Client. They exist so a script or notebook never has to build one
      explicitly.
    </p>

    <h3>evaluate()</h3>

    <CodeBlock :code="evaluateSig" language="python" />

    <p>
      The one call that spends money. Identical to
      <code>Client.evaluate()</code>, including running a url4 string again. Its parameters are
      documented on the <RouterLink to="/sf-client/api/clients">Clients</RouterLink> page. That
      includes <code>answer_seed</code> and <code>capture</code>.
    </p>

    <h3>reproduce()</h3>

    <CodeBlock :code="reproduceSig" language="python" />

    <p>
      Identical to <code>Client.reproduce()</code>. It runs a submitted score again against its
      frozen copy. See the <RouterLink to="/sf-client/api/clients">Clients</RouterLink> page and the
      <RouterLink to="/sf-client/api/leaderboards">Leaderboards reference</RouterLink>.
    </p>

    <h3>configure()</h3>

    <CodeBlock :code="configureSig" language="python" />

    <p>
      Replaces the shared Client and returns the new one. Call it once, before anything else, to
      point the module-level functions at a different engine. Setting
      <code>SCREAMINGFACE_ENGINE_URL</code> in the environment does the same thing without a call.
    </p>

    <h3>connect() and disconnect()</h3>

    <table>
      <thead>
        <tr>
          <th>Call</th>
          <th>Returns</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>connect()</code></td>
          <td>A <code>ConnectionPanel</code> listing every provider.</td>
        </tr>
        <tr>
          <td><code>connect(provider, api_key=...)</code></td>
          <td>The resulting <code>Connection</code>.</td>
        </tr>
        <tr>
          <td><code>connect(provider, method="oauth")</code></td>
          <td>An <code>OAuthFlow</code> carrying a URL to open.</td>
        </tr>
        <tr>
          <td><code>disconnect(provider)</code></td>
          <td>The provider's <code>Connection</code>, now disconnected.</td>
        </tr>
      </tbody>
    </table>

    <h3>close()</h3>

    <p>
      Releases the shared Client. A later module-level call simply builds a new one, so this is
      about releasing resources rather than shutting anything down permanently.
    </p>
  </DocLayout>
</template>
