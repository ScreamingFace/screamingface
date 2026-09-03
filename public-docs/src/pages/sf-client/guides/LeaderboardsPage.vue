<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const listing = `import screamingface as sf

sf.leaderboards.list()`
const listingOut = `hle                News Hallucinations
livetruth          News Livetruth
livetruth-latest   News Livetruth Latest`

const getOne = `board = sf.leaderboards.get("hle", top=5)
board`
const getOneOut = `Leaderboard('hle', entries=2, baselines=0)`

const rows = `board.entries`
const rowsOut = `1   filip-cf-access-smoke-1   0.5   unverified   smoke
2   smoke-test-1             0.5   unverified   smoke`

const configure = `sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)`

const publish = `report = sf.evaluate(candidate, benchmark="ifeval", limit=3)

# publish one candidate
sf.leaderboards.submit(report.candidates.only)

# or publish every candidate in the report
[sf.leaderboards.submit(c) for c in report.candidates]`

const fetchScore = `score = sf.leaderboards.get_score("57cc25d7-00bf-44ec-bf9d-55d66cd1e003")
score.score, score.total_questions, score.verified_by_screamingface`
const fetchScoreOut = `(1.0, 1, False)`

const remix = `plan = score.url4.to_python()   # Model / Fusion / Pipeline, free
sf.evaluate(score.url4)        # fresh paid replay; omit benchmark= and limit=`
</script>

<template>
  <DocLayout
    title="Leaderboards"
    description="Browse ranked results, publish a CandidateResult, and pull the url4 back out."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <strong>leaderboard</strong> is one benchmark's public ranking on the ScreamingFace
      Leaderboard. The Client reads and writes it through <code>sf.leaderboards</code>. Discovery
      and reads are free. They hit the leaderboard, not a model, and they do not need a provider
      connection.
    </p>

    <p>
      Each ranked row keeps the exact
      <RouterLink to="/sf-client/guides/reproduce-and-share"><code>url4</code></RouterLink>
      that produced the score, so anyone can fork or re-run the recipe. The leaderboard also stores
      whether ScreamingFace independently re-ran it (<code>verified_by_screamingface</code>). That
      flag is separate from who submitted the row: a submission starts unverified.
    </p>

    <p>
      The public portal is
      <a href="https://leaderboard.screamingface.ai" target="_blank" rel="noopener"
        >leaderboard.screamingface.ai</a
      >. The Client's default leaderboard origin is
      <code>https://leaderboard.dev.screamingface.ai</code>. Point <code>scoreboard_url</code> at
      your own instance when you run the local stack.
    </p>

    <h2>What you can do with it</h2>

    <ul>
      <li>List the benchmarks registered as leaderboards.</li>
      <li>Fetch one board's ranked entries and any imported single-model baselines.</li>
      <li>Publish an evaluated <code>CandidateResult</code> as a new score.</li>
      <li>Look up one published score by id and reuse its <code>url4</code>.</li>
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
          <td><code>sf.leaderboards.list()</code></td>
          <td>
            Lists every benchmark registered with the configured leaderboard as
            <code>LeaderboardInfo</code> values.
          </td>
        </tr>
        <tr>
          <td><code>sf.leaderboards.get(id, *, top=50)</code></td>
          <td>
            Fetches one <code>Leaderboard</code>: the board's identity, best-per-spec ranked
            <code>entries</code>, and imported <code>baselines</code>. <code>top</code> caps how
            many entries come back (the service clamps above 200).
          </td>
        </tr>
        <tr>
          <td><code>sf.leaderboards.submit(candidate_result)</code></td>
          <td>
            Publishes one evaluated <code>CandidateResult</code>. The Client derives benchmark id,
            spec id, url4, the benchmark-native score, providers, and the idempotency key from
            that result.
          </td>
        </tr>
        <tr>
          <td><code>sf.leaderboards.get_score(score_id)</code></td>
          <td>Loads one public <code>LeaderboardScore</code> by UUID (or its string form).</td>
        </tr>
        <tr>
          <td>
            <code>LeaderboardEntry</code> · <code>LeaderboardScore</code> ·
            <code>LeaderboardBaseline</code>
          </td>
          <td>
            The public value types: a ranked row, a persisted submission, and an imported
            single-model line to beat.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      Ranking is best-per-spec: for each <code>spec_id</code> the leaderboard keeps the highest
      score, and breaks ties by newest <code>submitted_at</code>. The table is then ordered by
      score descending. Baselines are imported separately and sit beside community entries; they
      are not the same as a submitted score.
    </p>

    <h2>How to</h2>

    <h3>1 · See which boards exist</h3>

    <div class="not-prose">
      <NbCell :count="1" :code="listing"><NbTextOut :text="listingOut" /></NbCell>
    </div>

    <p>
      These ids are leaderboard registrations. They can overlap the engine's
      <RouterLink to="/sf-client/guides/benchmarks">benchmark</RouterLink> catalog, but they are not
      the same list. A board has to be registered before you can publish to it.
    </p>

    <h3>2 · Read one board</h3>

    <div class="not-prose">
      <NbCell :count="2" :code="getOne"><NbTextOut :text="getOneOut" /></NbCell>
    </div>

    <div class="not-prose">
      <NbCell :count="3" :code="rows"><NbTextOut :text="rowsOut" /></NbCell>
    </div>

    <p>
      Each entry carries <code>score</code>, <code>total_questions</code>, the providers used,
      who submitted it when that is known, the <code>verified_by_screamingface</code> flag, and the
      <code>url4</code> expression. Notebook displays render the board as an interactive widget; the
      fields above are what each entry holds.
    </p>

    <p>
      On this board both rows are unverified smoke submissions. Treat
      <code>verified_by_screamingface=True</code> as the trust signal, not the mere presence of a
      row.
    </p>

    <h3>3 · Point the Client at a leaderboard</h3>

    <p>
      Without configuration, leaderboard calls use the default hosted ScreamingFace Leaderboard.
      Local development usually points both the engine and the leaderboard at the stack
      <code>screamingface up</code> starts:
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="configure" />
    </div>

    <p>
      Local writes are typically open. Hosted deployments may require an edge-verified identity
      before <code>submit</code> succeeds, or they may keep submission closed. Reads stay public
      either way.
    </p>

    <h3>4 · Publish a result</h3>

    <p>
      <code>submit</code> takes the evaluated <code>CandidateResult</code> directly. It does not ask
      you to re-enter the score. Pass <code>report.candidates.only</code> to publish a single
      candidate, or iterate <code>report.candidates</code> to publish every candidate in the report.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="publish" />
    </div>

    <p>
      The Client posts <code>score</code>, <code>total_questions</code>, the compiled
      <code>url4_expression</code>, provider names, and client metadata. The
      <code>Idempotency-Key</code> header is the candidate's <code>run_id</code>, so a retry of
      the same run replays the original score instead of inserting a duplicate.
    </p>

    <p>
      The score is benchmark-native: the Client submits <code>CandidateResult.score</code> exactly
      as the benchmark's own grading produced it — fractional for DRACO's weighted rubrics,
      negative for HealthBench worst-30 — and never derives a replacement from case grades,
      normalizes, or bounds it. The only universal requirements are that a score exists and is a
      finite number; unscored or non-finite results are rejected before HTTP.
    </p>

    <h3>5 · Fetch a published score</h3>

    <p>
      Pass the id <code>submit</code> returned (or any public score id). This sample is a real score
      read back from a local leaderboard:
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="fetchScore"><NbTextOut :text="fetchScoreOut" /></NbCell>
    </div>

    <p>
      A fresh submission returns with <code>verified_by_screamingface=False</code>. Verification is
      a later, independent mark after ScreamingFace re-runs the recipe. Read that field before you
      trust a number you did not produce yourself.
    </p>

    <h3>6 · Remix or replay from the board</h3>

    <div class="not-prose">
      <NbCell :count="7" :code="remix" />
    </div>

    <p>
      <code>url4.to_python()</code> is local and free. Passing the same <code>url4</code> to
      <RouterLink to="/sf-client/guides/running-an-evaluation"><code>sf.evaluate</code></RouterLink>
      is a new paid run. The expression is already linked to its benchmark, so do not pass
      <code>benchmark=</code> or <code>limit=</code> again. Model output can move; the recipe
      identity does not.
    </p>

    <h2>What "verified" means here</h2>

    <p>
      Anyone with write access can publish a score. The board stores the claim and the recipe.
      <code>verified_by_screamingface</code> means ScreamingFace re-executed that recipe and
      accepted the result. Until that flag is true, treat the row as a submission, not a verified
      ranking.
    </p>

    <h2>Links</h2>

    <ul>
      <li>
        <a href="https://leaderboard.screamingface.ai" target="_blank" rel="noopener"
          >Public leaderboard portal</a
        >
      </li>
      <li>
        <a
          href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb"
          target="_blank"
          rel="noopener"
          >Companion notebook: <code>00_quickstart.ipynb</code></a
        >, which walks list → evaluate → optional publish → replay
      </li>
      <li>
        <RouterLink to="/sf-client/guides/reproduce-and-share"
          >Reproduce &amp; share (url4)</RouterLink
        >
        for reading and rebuilding expressions
      </li>
    </ul>
  </DocLayout>
</template>
