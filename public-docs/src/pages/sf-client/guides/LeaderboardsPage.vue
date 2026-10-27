<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
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

const publish = `# Use the hosted stack to make a capture others can replay.
sf.configure(engine_url="https://fusion.screamingface.ai")
# candidate is the Model, Fusion or Pipeline you want to evaluate.
report = sf.evaluate(candidate, benchmark="ifeval")

# publish one candidate
score = sf.leaderboards.submit(
    report.candidates.only,
    authors=["alice@example.com", "bob@example.org"],
    authors_metadata={
        "alice@example.com": {"full_name": "Alice Smith", "institution": "University A"},
    },
    paper_metadata={
        "title": "Our ensemble",
        "url": "https://arxiv.org/abs/2601.00001",
        "citation": "Alice Smith and Bob Jones. Our ensemble.",
    },
)

# or publish every candidate in the report
[sf.leaderboards.submit(c) for c in report.candidates]`

const fetchScore = `score = sf.leaderboards.get_score("57cc25d7-00bf-44ec-bf9d-55d66cd1e003")
score.score, score.authors, score.verified_by_screamingface`
const fetchScoreOut = `(1.0, ('alice', 'bob'), False)`

const editScore = `score = sf.leaderboards.edit(
    score.id,
    authors=["alice@example.com", "carol@example.org"],
    authors_metadata={
        "alice@example.com": {"full_name": "Alice Smith", "institution": "University A"},
        "carol@example.org": {"full_name": "Carol Jones"},
    },
    paper_metadata={"title": "Our ensemble", "url": "https://arxiv.org/abs/2601.00001"},
)
score.paper_url, score.metadata_updated_at

# remove the paper link; leave authors as they are
sf.leaderboards.edit(score.id, paper_url=None)

# clear the author metadata; leave the credit line unchanged
sf.leaderboards.edit(score.id, authors_metadata=None)`

const editLog = `for event in sf.leaderboards.metadata_events(score.id):
    print(event.edited_at, event.source, event.old_paper_url, "->", event.new_paper_url)`

const remix = `plan = score.url4.to_python()   # Model / Fusion / Pipeline, free
sf.evaluate(score.url4)        # a new paid run; omit benchmark= and limit=`

const reproduce = `import screamingface as sf

# Select the hosted services for a public production leaderboard submission.
sf.configure(
    engine_url="https://fusion.screamingface.ai",
    scoreboard_url="https://leaderboard.screamingface.ai",
)

# Use the pinned cache id from a complete, public leaderboard submission.
replay = sf.evaluate(pinned_cache="<pinned-cache-id>")
result = replay.candidates.only
if result.reproduction is not None:
    print(result.reproduction.outcome, result.reproduction.reason)

# replay without recording it on the board
sf.evaluate(pinned_cache="<pinned-cache-id>", record_reproduction=False)`

const privateReplay = `# A private score is readable only by its submitter; log in when prompted.
replay = sf.evaluate(score_id="<score-id>")`

const partialReplay = `# Inspect the first case of a published run that has more than one case.
partial = sf.evaluate(pinned_cache="<pinned-cache-id>", limit=1)
partial.candidates.only.reproduction  # None: no verdict, never recorded`

const unsubmittedReplay = `# captured is the CandidateResult from your original, unsubmitted run.
# Use the same engine/gateway that holds its pinned cache.
replay = sf.evaluate(
    pinned_cache=captured.pinned_cache,
    url4=captured.url4,
    answer_seed=captured.answer_seed,
)
replay.candidates.only.reproduction  # None: no published score to compare`
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
      >. The Client uses the matching hosted leaderboard by default. Point
      <code>scoreboard_url</code> at your own instance when you run the local stack.
    </p>

    <h2>What you can do with it</h2>

    <ul>
      <li>List the benchmarks registered as leaderboards.</li>
      <li>Fetch one board's ranked entries and any imported single-model baselines.</li>
      <li>Publish an evaluated <code>CandidateResult</code> as a new score.</li>
      <li>Add author and paper metadata when you publish, and edit it later.</li>
      <li>Look up one published score by id and reuse its <code>url4</code>.</li>
      <li>
        Replay a published score from its pinned cache at no provider cost, and record that it held.
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
            <code
              >sf.leaderboards.submit(candidate_result, *, authors=None, paper_url=None,
              authors_metadata=None, paper_metadata=None)</code
            >
          </td>
          <td>
            Publishes one evaluated <code>CandidateResult</code>. The Client derives benchmark id,
            spec id, url4, the benchmark-native score, providers, and the idempotency key from that
            result. An optional author list supplies the exact credit line. An optional
            <code>paper_url</code> links the paper; the metadata objects add details about the
            authors and the paper.
          </td>
        </tr>
        <tr>
          <td><code>sf.leaderboards.get_score(score_id)</code></td>
          <td>Loads one public <code>LeaderboardScore</code> by UUID (or its string form).</td>
        </tr>
        <tr>
          <td>
            <code
              >sf.leaderboards.edit(score_id, *, authors=..., paper_url=..., authors_metadata=...,
              paper_metadata=...)</code
            >
          </td>
          <td>
            Changes the authors, paper link or metadata of a score you submitted. Returns the
            updated
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
          <td><code>sf.evaluate(pinned_cache=...) · sf.evaluate(score_id=...)</code></td>
          <td>
            Replays a published run and returns a <code>Report</code>. Its single
            <code>CandidateResult.reproduction</code> holds the verdict. Pass
            <code>record_reproduction=False</code> to skip recording an exact replay.
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
      author values normally omit email domains; full addresses distinguish authors whose local
      parts collide. Notebook displays render the board as an interactive widget; the fields above
      are what each entry holds.
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

    <h4>Author and paper metadata</h4>
    <p>
      <code>authors_metadata</code> maps each credited author's full email address to a flat object.
      Known keys are <code>full_name</code> and <code>institution</code>.
      <code>paper_metadata</code> is one flat object with known keys <code>title</code>,
      <code>url</code> and <code>citation</code>. All five key names are reserved in either object:
      they require text and follow the limits below, even when used outside their usual author or
      paper context. Other keys are stored and returned but are not displayed by the portal. Their
      values may be text, finite numbers or booleans; nested objects, lists and null values inside
      an object are not accepted.
    </p>
    <p>
      Each author metadata key must match a credited author, ignoring case. Removing an author also
      removes their metadata. Public reads key metadata by the published author identifier: normally
      the email's local part; full addresses are retained when two authors share that local part.
      Keep the original full addresses when sending edits; public keys are not edit keys.
    </p>
    <table>
      <thead>
        <tr>
          <th>Field</th>
          <th>Limit</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Paper object or one author's object</td>
          <td>20 keys; key names are 1–64 characters</td>
        </tr>
        <tr>
          <td><code>authors_metadata</code></td>
          <td>At most 10 authors</td>
        </tr>
        <tr>
          <td><code>full_name</code>, <code>institution</code></td>
          <td>200 characters each</td>
        </tr>
        <tr>
          <td><code>title</code>, <code>citation</code></td>
          <td>300 and 2,000 characters</td>
        </tr>
        <tr>
          <td><code>url</code></td>
          <td>2,048 characters; the same rules as <code>paper_url</code></td>
        </tr>
        <tr>
          <td>Other text values</td>
          <td>500 characters each</td>
        </tr>
        <tr>
          <td>Each top-level metadata field</td>
          <td>64 KiB as stored JSON, including escaped text</td>
        </tr>
      </tbody>
    </table>
    <p>
      The SDK checks object shapes; the board checks bounds, author matching and link rules.
      Metadata keys and text must be valid Unicode and cannot contain the NUL character.
      <code>paper_metadata.url</code> and <code>paper_url</code> refer to the same link; if you
      supply both, they must agree.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="publish" />
    </div>

    <p>
      Capture is on by default. The hosted Engine makes a pinned cache of each run, so others can
      reproduce the score. Read <code>capture_status</code> on the result before you publish: a
      partial or missing copy cannot be reproduced.
      <RouterLink to="/learn/caching">Reproducing a submission</RouterLink> explains why.
    </p>

    <p>
      The Client posts <code>score</code>, <code>total_questions</code>, the compiled
      <code>url4_expression</code>, provider names, required <code>run_cost_usd</code>, optional
      authors, the optional paper link, and client metadata. When the run has them, it also posts
      the run's pinned cache id, its <code>capture_status</code> and its answer seed. They are what
      <code>sf.evaluate(score_id=...)</code> needs later. Direct submissions require a non-null run
      cost; a genuine fully cached run sends zero, while imported and historical rows may still
      display an unknown cost. The <code>Idempotency-Key</code> header is the candidate's
      <code>run_id</code>, so a retry of the same run reuses the original score instead of inserting
      a duplicate. A resubmission by the same submitter can correct its author list or its paper
      link. If another correction wins the same race, the Client reports a retryable conflict; retry
      the submission.
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
      You can change the authors, paper link and metadata of a score after you publish it. Only the
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
      For either metadata field, omission preserves it, <code>None</code> clears it, and an object
      replaces it in full. <code>{}</code> is an empty replacement. This includes the paper link:
      replacing <code>paper_metadata</code> without a <code>url</code> clears
      <code>paper_url</code>. Include the existing URL if you only want to change the title. A
      submit or resubmit omits metadata set to <code>None</code>; use <code>edit</code> to clear it.
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

    <h3>7 · Reproduce a published run</h3>

    <p>
      These examples use SDK <strong>0.1.7</strong>. Install it with
      <code>python -m pip install "screamingface==0.1.7"</code>. Replay requires an Engine and
      Gateway that support pinned caches and hold the original capture. The example selects the
      hosted production services explicitly; for another deployment, change both URLs to that
      deployment's services. A capture in one deployment is not automatically available in another.
    </p>

    <p>
      Choose <strong>Reproduce</strong> under Copy on a captured public leaderboard row to copy a
      snippet using <code>sf.evaluate(pinned_cache="…")</code>. Replace the placeholder below with
      that row's pinned cache id. The Client reads the original recipe and answer seed from the
      board, then asks the Engine to use only the captured answers. A confirmed replay costs
      <strong>$0</strong>; a missing answer fails its case without a provider or web-search call.
    </p>

    <p>
      Captured answers avoid changes in provider responses, including model retirement. Replay still
      needs the original benchmark revision and compatible execution behavior; a pinned cache does
      not guarantee replay across Engine upgrades.
    </p>

    <div class="not-prose">
      <NbCell :count="9" :code="reproduce" />
    </div>

    <p>
      The return value is a <code>Report</code>. Read its single
      <code>CandidateResult.reproduction</code>, a <code>Reproduction</code> object or
      <code>None</code>. The string verdict is on <code>.outcome</code>:
    </p>

    <table>
      <thead>
        <tr>
          <th>Result</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>reproduction.outcome == "exact"</code></td>
          <td>
            The score, case count and benchmark revision match; the case digest matches too when the
            submission has one. This checks internal consistency, not independent verification of
            the submitted answers.
          </td>
        </tr>
        <tr>
          <td><code>reproduction.outcome == "failed"</code></td>
          <td>
            <code>reason</code> says why. <code>missed_cases</code> names cases the pinned cache
            could not answer. <code>cases_differ</code> detects a digest mismatch but does not
            identify which case results differ.
          </td>
        </tr>
        <tr>
          <td><code>reproduction is None</code></td>
          <td>
            A partial replay or a capture without a public score has no verdict and is never
            recorded.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      Only exact full replays are recorded on the board. For a public score, a leaderboard login is
      requested only after the exact verdict, if recording needs one. The Engine may require its own
      authentication. Pass <code>record_reproduction=False</code> to skip recording. If recording
      fails, the verdict stays <code>exact</code>, <code>recorded</code> is <code>False</code>, and
      <code>record_error</code> explains why. The API exposes <code>reproduction_count</code> and
      <code>last_reproduced_at</code>; the portal does not display a reproduction count.
    </p>

    <h4>Recipe and seed checks</h4>
    <p>
      You usually need only the pinned cache id. If you also pass <code>url4=</code>, it must
      describe the same parsed recipe as the published run. If you pass <code>answer_seed=</code>,
      it must equal the original seed. Omission, or <code>None</code>, uses the stored seed;
      <code>0</code> is a real seed. A run captured without a seed replays without one. Conflicting
      values raise <code>ValueError</code> before a run starts.
    </p>
    <p>
      A replay takes no positional candidate and no <code>benchmark=</code>. It never captures: omit
      <code>capture</code> or pass <code>False</code>. Explicit <code>capture=True</code> is an
      error. If both <code>score_id</code> and <code>pinned_cache</code> are supplied, they must
      identify the same capture.
    </p>

    <h4>Private scores</h4>
    <p>
      Use <code>score_id=</code> for a private score you submitted. The Client tries the public read
      first, then the authenticated read only on a 404. The private read may require a leaderboard
      login before replay. Passing a pinned cache id alone does not discover a private score. The
      same call also works for a public score.
    </p>
    <div class="not-prose"><NbCell :count="10" :code="privateReplay" /></div>

    <h4>Inspect a subset</h4>
    <p>
      <code>limit=n</code> replays the first <code>n</code> cases of a published run for debugging.
      Use a positive integer strictly smaller than its published case count; omit it for the full
      run. This is never judged or recorded. If the current Engine cannot rebuild the published
      recipe and a compatible subset, the Client raises <code>PlanningError</code> with code
      <code>partial_replay_unavailable</code> before execution. An unsubmitted capture cannot use
      <code>limit</code>.
    </p>
    <div class="not-prose"><NbCell :count="11" :code="partialReplay" /></div>

    <h4>Replay an unsubmitted capture</h4>
    <p>
      Without a public score, supply the original <code>url4</code> and the original
      <code>answer_seed</code> if it had one. Omit the seed or pass <code>None</code> when it did
      not. The replay has no published result to compare, so its <code>reproduction</code> is
      <code>None</code>. If every case misses, an <code>EvaluationWarning</code> asks you to check
      the recipe and seed. The Client never fills misses with live calls.
    </p>
    <div class="not-prose"><NbCell :count="12" :code="unsubmittedReplay" /></div>

    <h4>When replay cannot proceed</h4>
    <p>
      A partial or unknown published capture raises <code>sf.ReproductionError</code> with code
      <code>not_reproducible</code> before execution. An Engine that does not confirm replay mode
      raises the same exception with code <code>replay_unsupported</code>. Read
      <code>exc.reproduction</code> for the outcome and reason; there is no returned report. The
      <RouterLink to="/sf-client/api/errors">Errors reference</RouterLink> shows how to catch it,
      and the <RouterLink to="/sf-client/api/leaderboards">Reproduction reference</RouterLink>
      lists the verdict fields and reasons.
    </p>

    <h4>Remix the recipe</h4>
    <p>
      <code>score.url4.to_python()</code> gives you an editable recipe locally, for free.
      <code>sf.evaluate(score.url4)</code> starts a fresh evaluation that may call providers and
      incur costs. The url4 already names the benchmark, so do not pass <code>benchmark=</code> or
      <code>limit=</code> again. To replay captured answers, use one of the keyword forms above.
    </p>
    <div class="not-prose"><NbCell :count="13" :code="remix" /></div>

    <h3>Upgrade from SDK 0.1.6</h3>
    <Note>
      In SDK 0.1.7,
      <code>sf.reproduce(score)</code> and the Client methods are removed; use
      <code>sf.evaluate(score_id=score.id)</code>. Replace <code>record=</code> with
      <code>record_reproduction=</code>. The Python attribute <code>frozen_copy_id</code> is now
      <code>pinned_cache</code>, with no alias. <code>Reproduction.result</code> is removed: the
      result is <code>report.candidates.only</code>, with its verdict on <code>.reproduction</code>.
      Saved report JSON and wire payloads still use <code>frozen_copy_id</code>.
    </Note>

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
        <RouterLink to="/learn/caching">Caching and compute</RouterLink> for how a pinned cache is
        made, why it can be partial, and why a replay can fail
      </li>
    </ul>
  </DocLayout>
</template>
