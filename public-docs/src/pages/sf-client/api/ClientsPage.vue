<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import { SF_ENGINE_URL } from '@/lib/engine'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const clientSig = `sf.Client(
    *,
    engine_url: str = DEFAULT_ENGINE_URL,
    scoreboard_url: str = DEFAULT_SCOREBOARD_URL,
)`

const basic = `import screamingface as sf

client = sf.Client(engine_url="${SF_ENGINE_URL}")
client.engine_url, client.closed, client.authenticated`
const basicOut = `('${SF_ENGINE_URL}', False, False)`

const evaluateSig = `Client.evaluate(
    candidates: Recipe | Sequence[Recipe],
    *,
    benchmark: str,
    limit: int | None = None,
    on_event: Callable[[Event], None] | None = None,
    progress: bool | None = None,
    answer_seed: int | None = None,
    capture: bool = False,
) -> Report`

const reproduceSig = `Client.reproduce(
    score: LeaderboardScore | UUID | str,
    *,
    record: bool = True,
) -> Reproduction`

const withBlock = `with sf.Client() as client:
    report = client.evaluate(
        sf.Model("openrouter/anthropic/claude-haiku-4.5"),
        benchmark="ifeval",
        limit=1,
    )`

const closed = `client.close()
client.connections.list()`
const closedOut = `RuntimeError: ScreamingFace Client is closed`

const asyncCode = `import asyncio
import screamingface as sf

async def main():
    async with sf.AsyncClient(engine_url="${SF_ENGINE_URL}") as client:
        models = await client.models.list()
        return len(models), client.engine_url

asyncio.run(main())`
const asyncOut = `(29, '${SF_ENGINE_URL}')`
</script>

<template>
  <DocLayout
    title="Clients"
    description="Client and AsyncClient — how you reach an engine."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <code>Client</code> is the connection to one engine, and the object that every other page in
      this reference depends on: recipes are passed to it, and benchmarks and reports come back from
      it. This page covers <code>Client</code> itself and <code>AsyncClient</code> for the same
      interface over <code>await</code>. The connection values it returns — <code>Connection</code>,
      the OAuth flows, and <code>ConnectionPanel</code> — are documented under
      <RouterLink to="/sf-client/api/connections">Connections</RouterLink>.
    </p>

    <h2>Client</h2>

    <CodeBlock :code="clientSig" language="python" />

    <p>
      Creating a <code>Client</code> opens no connection and makes no request. The first call that
      needs the engine is the first one that talks to it.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="basic"><NbTextOut :text="basicOut" /></NbCell>
    </div>

    <Note>
      <code>DEFAULT_ENGINE_URL</code> is a hosted engine, so a <code>Client()</code> with no
      arguments talks to one we operate. To use a local engine, pass its address explicitly, or set
      <code>SCREAMINGFACE_ENGINE_URL</code> and use the module-level functions.
      <code>DEFAULT_SCOREBOARD_URL</code> is the matching hosted ScreamingFace Leaderboard. Both
      constants live in <code>screamingface.client</code>.
    </Note>

    <h3>Properties</h3>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>engine_url</code></td>
          <td><code>str</code></td>
          <td>The engine origin this Client was built for. Fixed for the Client's life.</td>
        </tr>
        <tr>
          <td><code>closed</code></td>
          <td><code>bool</code></td>
          <td>Whether <code>close()</code> has run.</td>
        </tr>
        <tr>
          <td><code>authenticated</code></td>
          <td><code>bool</code></td>
          <td>Whether this process currently holds hosted caller credentials.</td>
        </tr>
        <tr>
          <td><code>authenticating</code></td>
          <td><code>bool</code></td>
          <td>Whether a login is in flight.</td>
        </tr>
        <tr>
          <td><code>scoreboard_url</code></td>
          <td><code>str</code></td>
          <td>
            Where <RouterLink to="/sf-client/guides/leaderboards">leaderboard</RouterLink>
            submissions go. Separate from the engine, and separately configurable.
          </td>
        </tr>
        <tr>
          <td><code>models</code></td>
          <td>catalogue</td>
          <td>
            <code>models.list()</code> returns the
            <RouterLink to="/sf-client/api/benchmarks">ModelInfo</RouterLink> routes this engine can
            reach.
          </td>
        </tr>
        <tr>
          <td><code>benchmarks</code></td>
          <td>catalogue</td>
          <td>
            <code>benchmarks.list()</code> and <code>benchmarks.get(id)</code> return
            <RouterLink to="/sf-client/api/benchmarks">Benchmark</RouterLink> identity cards.
          </td>
        </tr>
        <tr>
          <td><code>connections</code></td>
          <td>catalogue</td>
          <td><code>connections.list()</code> and <code>connections.get(provider)</code>.</td>
        </tr>
      </tbody>
    </table>

    <h3>evaluate()</h3>

    <CodeBlock :code="evaluateSig" language="python" />

    <p>
      <code>evaluate()</code> runs one or more candidates against a benchmark and returns a
      <RouterLink to="/sf-client/api/reports">Report</RouterLink>. This is the call that costs
      money.
    </p>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>candidates</code></td>
          <td><code>Recipe</code> or sequence</td>
          <td>
            One <RouterLink to="/sf-client/api/recipes">recipe</RouterLink> or several. Several
            candidates run independently and share one report.
          </td>
        </tr>
        <tr>
          <td><code>benchmark</code></td>
          <td><code>str</code></td>
          <td>
            The benchmark id, such as <code>ifeval</code>. A protocol variant is its own id, such as
            <code>ifeval/self-corrective</code>, and it pins a different revision, so it changes
            what the result is comparable to. Required keyword argument.
          </td>
        </tr>
        <tr>
          <td><code>limit</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>
            Run only this many cases. <code>None</code> runs the whole benchmark. Use a small limit
            while you are still iterating.
          </td>
        </tr>
        <tr>
          <td><code>on_event</code></td>
          <td>callable</td>
          <td>Called with each lifecycle event as the run proceeds.</td>
        </tr>
        <tr>
          <td><code>progress</code></td>
          <td><code>bool&nbsp;|&nbsp;None</code></td>
          <td>Force the progress display on or off instead of letting it decide.</td>
        </tr>
        <tr>
          <td><code>answer_seed</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>
            An integer that the engine sends to each model call as its <code>seed</code>, unless the
            call sets one. <code>None</code> (the default) runs unseeded. Not a <code>bool</code>.
            The result keeps it, and a reproduction runs with it.
          </td>
        </tr>
        <tr>
          <td><code>capture</code></td>
          <td><code>bool</code></td>
          <td>
            <code>True</code> asks the engine to make a frozen copy of each run, so the score can be
            reproduced later. Best effort. Read <code>capture_status</code> on each
            <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink>. See
            <RouterLink to="/learn/caching">Reproducing a submission</RouterLink>.
          </td>
        </tr>
      </tbody>
    </table>

    <h3>reproduce()</h3>

    <CodeBlock :code="reproduceSig" language="python" />

    <p>
      <code>reproduce()</code> runs a submitted score again against its frozen copy and returns a
      <code>Reproduction</code>. <code>score</code> is a <code>LeaderboardScore</code> or its id.
      <code>record=True</code> records an exact replay on the leaderboard. A confirmed replay pays
      no provider. The
      <RouterLink to="/sf-client/api/leaderboards">Leaderboards reference</RouterLink> lists the
      outcomes and reasons.
    </p>

    <h3>connect() and disconnect()</h3>

    <p>
      <code>connect(provider, api_key=...)</code> stores a provider credential on the engine and
      returns the resulting <code>Connection</code>. <code>connect()</code> with no arguments
      returns a <code>ConnectionPanel</code> instead. <code>disconnect(provider)</code> removes the
      credential and is safe to call repeatedly.
    </p>

    <p>
      Passing a key requires a secure origin: an <code>https</code> engine, or a local one over
      <code>http</code>. Supplying <code>api_key</code> without a provider raises
      <code>TypeError</code>; a provider without <code>api_key</code> raises
      <code>ValueError</code>.
    </p>

    <h3>Lifecycle</h3>

    <p>
      <code>close()</code> releases the Client's transports and is idempotent. Using a closed Client
      raises:
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="closed"><NbTextOut :text="closedOut" /></NbCell>
    </div>

    <p>
      A <code>with</code> block closes it automatically, which is the form to prefer in a script:
    </p>

    <CodeBlock :code="withBlock" language="python" />

    <p>
      <code>login(timeout=300.0)</code> and <code>logout()</code> apply to hosted engines that sit
      behind browser-based access. A local engine needs neither.
    </p>

    <h2>AsyncClient</h2>

    <p>
      An <code>AsyncClient</code> offers the same interface over <code>await</code> and returns the
      same value types. It suits evaluations that run alongside other asynchronous work.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="asyncCode"><NbTextOut :text="asyncOut" /></NbCell>
    </div>

    <p>Three differences are worth knowing:</p>

    <table>
      <thead>
        <tr>
          <th>Client</th>
          <th>AsyncClient</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>close()</code></td>
          <td><code>await aclose()</code></td>
        </tr>
        <tr>
          <td><code>with</code></td>
          <td><code>async with</code></td>
        </tr>
        <tr>
          <td><code>connect()</code> may open a panel</td>
          <td><code>connect(provider, api_key=...)</code> always requires both</td>
        </tr>
      </tbody>
    </table>

    <p>
      <code>evaluate()</code>, <code>reproduce()</code>, <code>connect()</code>,
      <code>disconnect()</code>, <code>login()</code> and <code>logout()</code> are all awaited. The
      properties (<code>engine_url</code>, <code>closed</code>, <code>authenticated</code>) are not.
    </p>
  </DocLayout>
</template>
