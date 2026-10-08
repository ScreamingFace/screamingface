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

const publish = `# capture=True makes a frozen copy, so others can reproduce the score
report = sf.evaluate(candidate, benchmark="ifeval", limit=3, capture=True)

# publish one candidate
sf.leaderboards.submit(
    report.candidates.only,
    authors=["alice@example.com", "bob@example.org"],
    paper_url="https://arxiv.org/abs/2601.00001",
)

# or publish every candidate in the report
[sf.leaderboards.submit(c) for c in report.candidates]`

const fetchScore = `score = sf.leaderboards.get_score("57cc25d7-00bf-44ec-bf9d-55d66cd1e003")
score.score, score.authors, score.verified_by_screamingface`
const fetchScoreOut = `(1.0, ('alice', 'bob'), False)`

const editScore = `score = sf.leaderboards.edit(
    score.id,
    authors=["alice@example.com", "carol@example.org"],
    paper_url="https://arxiv.org/abs/2601.00001",
)
score.paper_url, score.metadata_updated_at

# remove the paper link; leave authors as they are
sf.leaderboards.edit(score.id, paper_url=None)`

const editLog = `for event in sf.leaderboards.metadata_events(score.id):
    print(event.edited_at, event.source, event.old_paper_url, "->", event.new_paper_url)`

const remix = `plan = score.url4.to_python()   # Model / Fusion / Pipeline, free
sf.evaluate(score.url4)        # a new paid run; omit benchmark= and limit=`

const reproduce = `reproduction = sf.reproduce(score)   # or sf.reproduce(score.id)
reproduction.outcome, reproduction.reason

# replay without recording it on the board
sf.reproduce(score, record=False)`
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
      <li>Add a paper link when you publish, and edit the authors and the paper link later.</li>
      <li>Look up one published score by id and reuse its <code>url4</code>.</li>
      <li>
        Replay a published score from its frozen copy at no provider cost, and record that it held.
      </li>
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
          <td>
            <code>sf.leaderboards.submit(candidate_result, *, authors=None, paper_url=None)</code>
          </td>
          <td>
            Publishes one evaluated <code>CandidateResult</code>. The Client derives benchmark id,
            spec id, url4, the benchmark-native score, providers, and the idempotency key from that
            result. An optional author list supplies the exact credit line. An optional
            <code>paper_url</code> links the paper.
          </td>
        </tr>
        <tr>
          <td><code>sf.leaderboards.get_score(score_id)</code></td>
          <td>Loads one public <code>LeaderboardScore</code> by UUID (or its string form).</td>
        </tr>
        <tr>
          <td><code>sf.leaderboards.edit(score_id, *, authors=..., paper_url=...)</code></td>
          <td>
            Changes the authors or the paper link of a score you submitted. Returns the updated
            <code>LeaderboardScore</code>. Only the submitter can do this.
          </td>
        </tr>
        <tr>
          <td><code>sf.leaderboards.metadata_events(score_id)</code></td>
          <td>
            Reads the edit log of a score you submitted, newest first, as
            <code>ScoreMetadataEvent</code> values. Only the submitter can read it.
          </td>
        </tr>
        <tr>
          <td><code>sf.reproduce(score, *, record=True)</code></td>
          <td>
            Replays a published score against its frozen copy and returns a
            <code>Reproduction</code>. An exact replay is recorded on the score unless you pass
            <code>record=False</code>.
          </td>
        </tr>
        <tr>
          <td>
            <code>LeaderboardEntry</code> · <code>LeaderboardScore</code> ·
            <code>LeaderboardBaseline</code> · <code>ScoreMetadataEvent</code>
          </td>
          <td>
            The public value types: a ranked row, a persisted submission, an imported single-model
            line to beat, and one row of a score's edit log.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      Ranking is best-per-spec: for each <code>spec_id</code> the leaderboard keeps the highest
      score, and breaks ties by newest <code>submitted_at</code>. The table is then ordered by score
      descending. Baselines are imported separately and sit beside community entries; they are not
      the same as a submitted score.
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
      Each entry carries <code>score</code>, <code>total_questions</code>, the providers used, who
      submitted it when that is known, its separate <code>authors</code> credit line, the
      <code>verified_by_screamingface</code> flag, and the <code>url4</code> expression. Public
      author values omit email domains. Notebook displays render the board as an interactive widget;
      the fields above are what each entry holds.
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

    <p>
      Pass <code>authors=[...]</code> to set the exact ordered credit line. It accepts one to ten
      email addresses, preserves duplicates, and never adds the authenticated submitter for you.
      Omit the argument to use the leaderboard's default credit line. Authorship grants credit, not
      ownership or access to a private submission.
    </p>

    <p>
      Pass <code>paper_url="https://…"</code> to link the paper that reports the result. It must be
      an <code>http</code> or <code>https</code> link of at most 2048 characters, with a host, no
      whitespace or control characters, and no user info. The Client checks it before HTTP. The
      leaderboard does not check that the link is real or that the authors wrote the paper. If you
      have no paper yet, leave the argument out and add the link later with <code>edit</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="publish" />
    </div>

    <p>
      <code>capture=True</code> asks the Engine to make a frozen copy of each run, so others can
      reproduce the score. Read <code>capture_status</code> on the result before you publish: a
      partial or missing copy cannot be reproduced.
      <RouterLink to="/learn/caching">Reproducing a submission</RouterLink> explains why.
    </p>

    <p>
      The Client posts <code>score</code>, <code>total_questions</code>, the compiled
      <code>url4_expression</code>, provider names, required <code>run_cost_usd</code>, optional
      authors, the optional paper link, and client metadata. When the run has them, it also posts
      the run's frozen copy id, its <code>capture_status</code> and its answer seed. They are what
      <code>sf.reproduce</code> needs later. Direct submissions require a non-null run cost; a
      genuine fully cached run sends zero, while imported and historical rows may still display an
      unknown cost. The <code>Idempotency-Key</code> header is the candidate's <code>run_id</code>,
      so a retry of the same run reuses the original score instead of inserting a duplicate. A
      resubmission by the same submitter can correct its author list or its paper link. If another
      correction wins the same race, the Client reports a retryable conflict; retry the submission.
    </p>

    <p>
      The score is benchmark-native: the Client submits <code>CandidateResult.score</code> exactly
      as the benchmark's own grading produced it — fractional for DRACO's weighted rubrics, negative
      for HealthBench worst-30 — and never derives a replacement from case grades, normalizes, or
      bounds it. The only universal requirements are that a score exists and is a finite number;
      unscored or non-finite results are rejected before HTTP.
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

    <h3>6 · Edit what you submitted</h3>

    <p>
      You can change the authors and the paper link of a score after you publish it. Only the
      verified submitter can do this. Another caller gets a
      <RouterLink to="/sf-client/api/errors"><code>LeaderboardError</code></RouterLink
      >. Each argument you leave out stays as it is, and you must pass at least one.
    </p>

    <div class="not-prose">
      <NbCell :count="7" :code="editScore" />
    </div>

    <p>
      A new <code>authors</code> list replaces the old one exactly. It follows the same rules as on
      <code>submit</code>. You cannot clear it. To go back to the default credit line, pass the
      submitter's own address. <code>paper_url=None</code> removes the paper link. An edit that
      changes nothing writes no log entry.
    </p>

    <p>
      Every change goes into an edit log. A resubmission that changes these fields writes to it too.
      The log holds the old and new values, so it can hold author emails that you removed on
      purpose. For this reason it is not public: only the submitter and the board's operators can
      read it. The newest entry comes first.
    </p>

    <div class="not-prose">
      <NbCell :count="8" :code="editLog" />
    </div>

    <h3>7 · Reproduce a score, or remix it</h3>

    <p>
      <code>sf.reproduce</code> runs the score's <code>url4</code> and stored answer seed against
      the frozen copy of the original run. A confirmed replay pays no provider and costs
      <strong>$0</strong>. If the Engine does not confirm replay mode, the Client stops the run and
      reports <code>replay_unsupported</code>, and an <code>EvaluationWarning</code> says so if the
      stop fails. A finished run whose summary does not name the copy gets the same reason, and it
      may have paid providers. The <RouterLink to="/learn/caching">caching page</RouterLink> has the
      mechanics.
    </p>

    <div class="not-prose">
      <NbCell :count="9" :code="reproduce" />
    </div>

    <p>
      <code>sf.reproduce</code> accepts a <code>LeaderboardScore</code> or its id. It returns a
      <code>Reproduction</code>. A replay that does not match is a value, not an exception. Read
      <code>outcome</code> first:
    </p>

    <table>
      <thead>
        <tr>
          <th><code>outcome</code></th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>exact</code></td>
          <td>
            The replay gave the stored score and the same number of cases, on the same benchmark
            revision.
          </td>
        </tr>
        <tr>
          <td><code>failed</code></td>
          <td>
            The replay ran, or tried to, and did not match. <code>reason</code> says why, and
            <code>missed_cases</code> lists the cases that the frozen copy could not answer.
          </td>
        </tr>
        <tr>
          <td><code>not_reproducible</code></td>
          <td>
            The score cannot name everything a replay needs, so no run started.
            <code>reason</code> is <code>partial</code> or <code>unknown</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      Only an exact replay is recorded. The Client sends the replay's run id, score and case count,
      and the score's frozen copy id, to the leaderboard. The leaderboard checks that they match the
      stored score. Hosted deployments need a verified identity to record. There is no limit: each
      exact replay adds one record. The score's page on the portal shows "Reproduced N times", and
      <code>reproduction_count</code> and <code>last_reproduced_at</code> hold the same facts on
      <code>LeaderboardScore</code>. If the record fails, the outcome stays <code>exact</code>,
      <code>recorded</code> is <code>False</code>, and <code>record_error</code> says why. The
      <RouterLink to="/sf-client/api/leaderboards"><code>Reproduction</code> reference</RouterLink>
      lists every field and reason.
    </p>

    <p>
      To change the recipe instead of checking it, remix it.
      <code>url4.to_python()</code> is local and free. Passing the same <code>url4</code> to
      <RouterLink to="/sf-client/guides/running-an-evaluation"><code>sf.evaluate</code></RouterLink>
      is a new paid run. The expression is already linked to its benchmark, so do not pass
      <code>benchmark=</code> or <code>limit=</code> again. Model output can move; the recipe
      identity does not.
    </p>

    <div class="not-prose">
      <NbCell :count="10" :code="remix" />
    </div>

    <h2>What "verified" means here</h2>

    <p>
      Anyone with write access can publish a score. The board stores the claim and the recipe.
      <code>verified_by_screamingface</code> means ScreamingFace re-executed that recipe and
      accepted the result. Until that flag is true, treat the row as a submission, not a verified
      ranking.
    </p>

    <p>
      A reproduction count is a different fact. Each record is self-reported by a verified identity,
      and it is not <code>verified_by_screamingface</code>.
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
        >, which walks list → evaluate → optional publish → run again
      </li>
      <li>
        <RouterLink to="/sf-client/guides/reproduce-and-share"
          >Reproduce &amp; share (url4)</RouterLink
        >
        for reading and rebuilding expressions
      </li>
      <li>
        <RouterLink to="/learn/caching">Caching and compute</RouterLink> for how a frozen copy is
        made, why it can be partial, and why a replay can fail
      </li>
    </ul>
  </DocLayout>
</template>
