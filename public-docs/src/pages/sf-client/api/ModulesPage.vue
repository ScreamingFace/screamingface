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

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
[(b.id, b.case_count) for b in sf.benchmarks.list()]`
const sharedOut = `[('medxpert', 2450)]`

const configureSig = `sf.configure(
    *,
    engine_url: str = "https://fusion.screamingface.ai",
    scoreboard_url: str | None = None,
) -> Client`

const evaluateSig = `sf.evaluate(
    candidates: Recipe | Sequence[Recipe] | str | None = None,
    *,
    benchmark: str | None = None,
    limit: int | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
    answer_seed: int | None = None,
    capture: bool | None = None,
    pinned_cache: str | None = None,
    score_id: UUID | str | None = None,
    url4: str | None = None,
    record_reproduction: bool = True,
    use_cache: bool = True,
) -> Report`

const replay = `# Replace either placeholder with an id from the leaderboard.
replay = sf.evaluate(pinned_cache="<pinned-cache-id>")
# Or replay by score id, including a private score you submitted:
replay = sf.evaluate(score_id="<score-id>")

reproduction = replay.candidates.only.reproduction
if reproduction is not None:
    print(reproduction.outcome)`
</script>

<template>
  <DocLayout
    title="Modules"
    description="The modules and functions you can call on sf directly."
    :navigation="navigation"
    :version="version"
  >
    <p>
      The names <code>benchmarks</code>, <code>models</code>, <code>connections</code>,
      <code>leaderboards</code>, <code>evaluate</code>, <code>connect</code> and
      <code>disconnect</code> work two ways. On a
      <RouterLink to="/sf-client/api/clients">Client</RouterLink> you build yourself, they are its
      attributes and methods: <code>client.benchmarks</code>, <code>client.evaluate(...)</code>. On
      the <code>sf</code> module, the same names act on a default Client the library creates and
      manages for you, so a script or notebook can call <code>sf.evaluate(...)</code> without
      constructing one. <code>sf.events</code>, <code>sf.reports</code>, <code>sf.cache</code> and
      <code>sf.analytics</code> exist only on the module.
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
            offers.
          </td>
        </tr>
        <tr>
          <td><code>get(benchmark_id)</code></td>
          <td>One <code>Benchmark</code> by its id.</td>
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
            The full <code>ModelDetails</code> profile for one route. It does not need the provider
            connected: an unconnected route fails at evaluation, not here.
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
      This module talks to the leaderboard rather than the engine. See
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
          <td>
            <code
              >submit(candidate_result, *, authors=None, paper_url=None, authors_metadata=None,
              paper_metadata=None)</code
            >
          </td>
          <td>
            Publishes one
            <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink> to the
            public board and returns the stored <code>LeaderboardScore</code>.
          </td>
        </tr>
        <tr>
          <td>
            <code
              >edit(score_id, *, authors=..., paper_url=..., authors_metadata=...,
              paper_metadata=...)</code
            >
          </td>
          <td>The updated <code>LeaderboardScore</code>, for a score you submitted.</td>
        </tr>
        <tr>
          <td><code>metadata_events(score_id)</code></td>
          <td>The edit log of a score you submitted, as <code>ScoreMetadataEvent</code> values.</td>
        </tr>
      </tbody>
    </table>

    <h2>sf.events</h2>

    <p>
      <code>sf.events</code> exposes no functions. It holds the event types a run reports through
      <code>on_event</code>, covered in <RouterLink to="/sf-client/api/events">Events</RouterLink>.
    </p>

    <h2>sf.reports</h2>

    <p>
      Reopens reports that evaluations saved to disk. It is documented on the
      <RouterLink to="/sf-client/api/reports">Reports</RouterLink> page.
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
          <td><code>list(*, directory=None)</code></td>
          <td>A <code>SavedReportInfo</code> for every saved report.</td>
        </tr>
        <tr>
          <td><code>get(report_id, *, directory=None, destination=None)</code></td>
          <td>The saved <code>Report</code>. <code>get_async</code> is the awaitable form.</td>
        </tr>
        <tr>
          <td><code>delete(report_id, *, directory=None)</code></td>
          <td><code>None</code>. Removes the saved report from disk.</td>
        </tr>
      </tbody>
    </table>

    <h2>sf.cache</h2>

    <p>
      Copies the hosted community cache into the local gateway, so a local run answers from it the
      model calls the community already made. It exposes <code>pull_from_remote()</code>,
      <code>PullResult</code> and <code>CachePullError</code>. The command line form is
      <code>screamingface cache pull</code>. See
      <RouterLink to="/sf-client/api/cache">Cache</RouterLink>.
    </p>

    <h2>sf.analytics</h2>

    <p>
      Reads and sets the opt-in analytics choice. It exposes <code>status()</code>,
      <code>enable()</code>, <code>disable()</code> and <code>reset_identifier()</code>. The command
      line form is <code>screamingface analytics</code>, and <code>DO_NOT_TRACK</code> turns
      analytics off. See <RouterLink to="/sf-client/api/analytics">Analytics</RouterLink>.
    </p>

    <h2>Top-level functions</h2>

    <p>
      These functions act on the shared Client. They exist so a script or notebook never has to
      build one explicitly.
    </p>

    <h3>evaluate()</h3>

    <CodeBlock :code="evaluateSig" language="python" />

    <p>
      Runs a fresh evaluation, which may spend money, or replays captured answers at $0. Identical
      to <code>Client.evaluate()</code>, including evaluating a url4 string. Its parameters are
      documented on the <RouterLink to="/sf-client/api/clients">Clients</RouterLink> page. That
      includes <code>answer_seed</code>, <code>capture</code> and <code>use_cache</code>.
    </p>

    <CodeBlock :code="replay" language="python" />

    <p>
      The keyword forms <code>sf.evaluate(pinned_cache=…)</code> and
      <code>sf.evaluate(score_id=…)</code> take no positional candidate or <code>benchmark</code>.
      They accept <code>url4</code>, <code>answer_seed</code>, <code>limit</code> and
      <code>record_reproduction</code> under the same rules as
      <RouterLink to="/sf-client/api/clients">Client.evaluate()</RouterLink>. A full published
      replay has a verdict on its result; partial replays and unsubmitted captures have
      <code>reproduction=None</code>. See the
      <RouterLink to="/sf-client/guides/leaderboards">Leaderboards guide</RouterLink>.
    </p>

    <h3>configure()</h3>

    <CodeBlock :code="configureSig" language="python" />

    <p>
      Replaces the shared Client and returns the new one. Call it once, before anything else, to
      point the module-level functions at a different engine. A non-default
      <code>engine_url</code> requires its own <code>scoreboard_url</code>; without it
      <code>configure()</code> raises <code>ValueError</code>, so a local run's
      <code>submit</code> cannot publish to the public leaderboard. Setting
      <code>SCREAMINGFACE_ENGINE_URL</code> and <code>SCREAMINGFACE_SCOREBOARD_URL</code> in the
      environment does the same thing without a call.
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
      Releases the shared Client and the sign-in sessions of
      <code>sf.cache.pull_from_remote()</code>. A later module-level call simply builds a new one,
      so this is about releasing resources rather than shutting anything down permanently.
    </p>
  </DocLayout>
</template>
