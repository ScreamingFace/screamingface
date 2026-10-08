<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const listRun = `import screamingface as sf

client = sf.Client()
[(b.id, b.display_name) for b in client.leaderboards.list()]`
const listRunOut = `[('draco/smoke', 'DRACO Smoke')]`

const submit = `report = client.evaluate(recipe, benchmark="ifeval", limit=1)
client.leaderboards.submit(
    report.candidates.only,
    authors=["alice@example.com", "bob@example.org"],
    paper_url="https://arxiv.org/abs/2601.00001",
)`

const reproduce = `reproduction = client.reproduce(score)
reproduction.outcome, reproduction.reason, reproduction.recorded`
</script>

<template>
  <DocLayout
    title="Leaderboards"
    description="The public board: what it holds, and what a submission records."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A leaderboard is the public ranking for one benchmark. This page covers
      <code>Leaderboard</code> itself, alongside <code>LeaderboardInfo</code> for a board's
      identity, <code>LeaderboardEntry</code> for a ranked row, <code>LeaderboardBaseline</code> for
      a published number to measure against, and <code>LeaderboardScore</code> for the full record a
      submission creates. <code>ScoreMetadataEvent</code> is one row of a score's edit log, and
      <code>Reproduction</code> is what <code>reproduce()</code> returns.
    </p>

    <Note>
      These are the only values that do not come from the engine. They come from the leaderboard, a
      separate service set by <code>scoreboard_url</code> on a
      <RouterLink to="/sf-client/api/clients">Client</RouterLink>.
    </Note>

    <div class="not-prose">
      <NbCell :count="1" :code="listRun"><NbTextOut :text="listRunOut" /></NbCell>
    </div>

    <h2>Leaderboard</h2>

    <p>
      One board, returned by <code>client.leaderboards.get(benchmark_id, top=50)</code>. It holds
      the ranking and the published numbers side by side, so a submitted result can be read against
      what the literature reports.
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
          <td><code>benchmark</code></td>
          <td><code>LeaderboardInfo</code></td>
          <td>Which board this is.</td>
        </tr>
        <tr>
          <td><code>entries</code></td>
          <td><code>tuple[LeaderboardEntry, ...]</code></td>
          <td>The ranking, capped by the <code>top</code> argument.</td>
        </tr>
        <tr>
          <td><code>baselines</code></td>
          <td><code>tuple[LeaderboardBaseline, ...]</code></td>
          <td>Published results imported for comparison, not submitted through the Client.</td>
        </tr>
      </tbody>
    </table>

    <h2>LeaderboardInfo</h2>

    <p>A board's identity, and what <code>list()</code> returns.</p>

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
          <td><code>id</code></td>
          <td><code>str</code></td>
          <td>The benchmark id this board ranks, including its variant.</td>
        </tr>
        <tr>
          <td><code>display_name</code></td>
          <td><code>str</code></td>
          <td>The board's name.</td>
        </tr>
        <tr>
          <td><code>description</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>What it measures.</td>
        </tr>
        <tr>
          <td><code>dataset_url</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>Where the underlying dataset lives.</td>
        </tr>
        <tr>
          <td><code>created_at</code></td>
          <td><code>datetime</code></td>
          <td>When the board was created.</td>
        </tr>
      </tbody>
    </table>

    <h2>LeaderboardEntry</h2>

    <p>
      One ranked row. Every entry carries the url4 that produced it, so any position on the board
      can be re-executed rather than taken on trust.
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
          <td><code>rank</code></td>
          <td><code>int</code></td>
          <td>Position on the board.</td>
        </tr>
        <tr>
          <td><code>spec_id</code></td>
          <td><code>str</code></td>
          <td>Identifies the candidate that produced the result.</td>
        </tr>
        <tr>
          <td><code>score</code></td>
          <td><code>float</code></td>
          <td>
            The benchmark-native score it is ranked by — exactly what the benchmark's grading
            produced, fractional or negative included.
          </td>
        </tr>
        <tr>
          <td><code>total_questions</code></td>
          <td><code>int</code></td>
          <td>How many cases the result covered.</td>
        </tr>
        <tr>
          <td><code>ran_with_providers</code></td>
          <td><code>tuple[str, ...]</code></td>
          <td>Which providers served the run.</td>
        </tr>
        <tr>
          <td><code>url4</code></td>
          <td><code>Url4</code></td>
          <td>
            The expression that produced it. Pass it to
            <RouterLink to="/sf-client/api/clients">evaluate()</RouterLink> to reproduce the entry.
          </td>
        </tr>
        <tr>
          <td><code>submitted_at</code> · <code>submitted_by</code></td>
          <td><code>datetime</code> / <code>str&nbsp;|&nbsp;None</code></td>
          <td>When it was published, and by whom where that is recorded.</td>
        </tr>
        <tr>
          <td><code>authors</code></td>
          <td><code>tuple[str, ...]&nbsp;|&nbsp;None</code></td>
          <td>The ordered credit line, with email domains removed by the public leaderboard.</td>
        </tr>
        <tr>
          <td><code>verified_by_screamingface</code></td>
          <td><code>bool</code></td>
          <td>Whether ScreamingFace re-ran the entry and confirmed the score.</td>
        </tr>
      </tbody>
    </table>

    <h2>LeaderboardBaseline</h2>

    <p>
      A published result imported for comparison. Baselines are not submissions and carry no url4,
      because nobody ran them through this Client.
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
          <td><code>model_name</code></td>
          <td><code>str</code></td>
          <td>What the published number is for.</td>
        </tr>
        <tr>
          <td><code>score</code></td>
          <td><code>float</code></td>
          <td>The reported score.</td>
        </tr>
        <tr>
          <td><code>source</code> · <code>source_url</code></td>
          <td><code>str</code> / <code>str&nbsp;|&nbsp;None</code></td>
          <td>Where the number was published.</td>
        </tr>
        <tr>
          <td><code>benchmark_id</code></td>
          <td><code>str</code></td>
          <td>Which board it belongs to.</td>
        </tr>
        <tr>
          <td><code>id</code> · <code>imported_at</code> · <code>metadata</code></td>
          <td><code>UUID</code> / <code>datetime</code> / <code>Mapping&nbsp;|&nbsp;None</code></td>
          <td>Identity, when it was imported, and anything else recorded with it.</td>
        </tr>
      </tbody>
    </table>

    <h2>LeaderboardScore</h2>

    <p>
      The stored record a submission creates, returned by both <code>submit()</code> and
      <code>get_score(score_id)</code>. It keeps more than the board shows: where an entry has a
      rank and a score, a score has the full provenance of the run behind it.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="submit" />
    </div>

    <p>
      <code>submit(candidate_result, *, authors=None, paper_url=None)</code> accepts one to ten
      email addresses. A supplied list is exact: order and duplicates are preserved, and the
      authenticated submitter is not added automatically. Omit it to use the leaderboard's default
      credit line. <code>paper_url</code> is an <code>http</code> or <code>https</code> link of at
      most 2048 characters, with a host, no whitespace or control characters, and no user info.
    </p>

    <p>
      <code>edit(score_id, *, authors=..., paper_url=...)</code> changes those two fields of a score
      you submitted and returns the updated <code>LeaderboardScore</code>. An argument you leave out
      stays as it is, and you must pass at least one. <code>paper_url=None</code> removes the link.
      <code>authors</code> cannot be cleared. <code>metadata_events(score_id)</code>
      returns the score's edit log, newest first, as a tuple of
      <code>ScoreMetadataEvent</code> values. Only the submitter can call either one. The
      <RouterLink to="/sf-client/guides/leaderboards">Leaderboards guide</RouterLink> shows them in
      use.
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
          <td><code>id</code> · <code>version</code></td>
          <td><code>UUID</code> / <code>int</code></td>
          <td>Identifies the stored score, and which revision of it this is.</td>
        </tr>
        <tr>
          <td><code>benchmark_id</code> · <code>spec_id</code></td>
          <td><code>str</code></td>
          <td>What was evaluated, and against which board.</td>
        </tr>
        <tr>
          <td><code>score</code></td>
          <td><code>float</code></td>
          <td>The benchmark-native score, exactly as submitted.</td>
        </tr>
        <tr>
          <td><code>total_questions</code> · <code>correct_questions</code></td>
          <td><code>int</code> / <code>int&nbsp;|&nbsp;None</code></td>
          <td>
            How many cases ran, and — only for binary-graded benchmarks — how many were correct.
          </td>
        </tr>
        <tr>
          <td><code>url4</code></td>
          <td><code>Url4</code></td>
          <td>The expression that produced the score.</td>
        </tr>
        <tr>
          <td><code>ran_with_providers</code></td>
          <td><code>tuple[str, ...]</code></td>
          <td>Which providers served the run.</td>
        </tr>
        <tr>
          <td><code>ran_at_local</code></td>
          <td><code>datetime&nbsp;|&nbsp;None</code></td>
          <td>When it ran on the submitter's machine.</td>
        </tr>
        <tr>
          <td>
            <code>client_name</code> · <code>client_version</code> · <code>client_platform</code>
          </td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>What submitted it, which matters when results disagree.</td>
        </tr>
        <tr>
          <td><code>submitted_at</code> · <code>submitted_by</code></td>
          <td><code>datetime</code> / <code>str&nbsp;|&nbsp;None</code></td>
          <td>When it was published, and by whom.</td>
        </tr>
        <tr>
          <td><code>authors</code></td>
          <td><code>tuple[str, ...]&nbsp;|&nbsp;None</code></td>
          <td>
            The ordered, privacy-trimmed credit line. This is separate from
            <code>submitted_by</code>, which records who sent the result.
          </td>
        </tr>
        <tr>
          <td><code>verified_by_screamingface</code></td>
          <td><code>bool</code></td>
          <td>Whether ScreamingFace re-ran it and confirmed the score.</td>
        </tr>
        <tr>
          <td><code>metadata</code></td>
          <td><code>Mapping&nbsp;|&nbsp;None</code></td>
          <td>Anything else recorded with the submission.</td>
        </tr>
        <tr>
          <td><code>paper_url</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>The link to the paper that reports the result, when one was set.</td>
        </tr>
        <tr>
          <td><code>metadata_updated_at</code></td>
          <td><code>datetime&nbsp;|&nbsp;None</code></td>
          <td>When the authors or the paper link last changed. <code>None</code> if never.</td>
        </tr>
        <tr>
          <td><code>frozen_copy_id</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            The id of the frozen copy that the run made. <code>None</code> when the run was not
            captured.
          </td>
        </tr>
        <tr>
          <td><code>capture_status</code></td>
          <td><code>"complete"&nbsp;|&nbsp;"partial"&nbsp;|&nbsp;None</code></td>
          <td>
            Whether the frozen copy holds the whole run. <code>"partial"</code> scores cannot be
            replayed. <code>None</code> means unknown.
          </td>
        </tr>
        <tr>
          <td><code>answer_seed</code> · <code>benchmark_revision</code></td>
          <td><code>int&nbsp;|&nbsp;None</code> / <code>str&nbsp;|&nbsp;None</code></td>
          <td>
            The answer seed of the run and the revision of the benchmark it ran on. A replay uses
            the seed, and it must match the revision.
          </td>
        </tr>
        <tr>
          <td><code>reproduction_count</code> · <code>last_reproduced_at</code></td>
          <td><code>int</code> / <code>datetime&nbsp;|&nbsp;None</code></td>
          <td>
            How many exact reproductions are recorded, and when the last one was. The count is
            <code>0</code> on a board that does not report it.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      Boards that predate a field leave it absent, and it reads as <code>None</code> (the count
      reads <code>0</code>).
    </p>

    <h2>ScoreMetadataEvent</h2>

    <p>
      One row of a score's edit log, returned by <code>metadata_events(score_id)</code>. Each change
      to the authors or the paper link writes one row. The log can hold author emails that were
      removed on purpose, so it is not public: only the submitter and the board's operators can read
      it.
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
          <td><code>id</code></td>
          <td><code>UUID</code></td>
          <td>Identifies the log row.</td>
        </tr>
        <tr>
          <td><code>edited_by</code> · <code>edited_at</code></td>
          <td><code>str</code> / <code>datetime</code></td>
          <td>Who made the change, and when.</td>
        </tr>
        <tr>
          <td><code>source</code></td>
          <td><code>"patch"&nbsp;|&nbsp;"resubmit"</code></td>
          <td>
            <code>"patch"</code> for an <code>edit()</code> call, <code>"resubmit"</code> for a
            resubmission that changed the fields.
          </td>
        </tr>
        <tr>
          <td><code>old_authors</code> · <code>new_authors</code></td>
          <td><code>tuple[str, ...]&nbsp;|&nbsp;None</code></td>
          <td>The credit line before and after.</td>
        </tr>
        <tr>
          <td><code>old_paper_url</code> · <code>new_paper_url</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>The paper link before and after. <code>None</code> means no link.</td>
        </tr>
      </tbody>
    </table>

    <h2>Reproduction</h2>

    <p>
      What <code>client.reproduce(score, *, record=True)</code> returns. It replays a score against
      its frozen copy and judges the replay against the stored numbers. A replay that the Engine
      confirms is answered from the copy only, so it pays no provider and no web-search service.
      <code>score</code> is a <code>LeaderboardScore</code> or its id. The same method is on
      <code>AsyncClient</code> (awaited) and as <code>sf.reproduce</code>. A replay that does not
      match is a value here, not an exception.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="reproduce" />
    </div>

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
          <td><code>outcome</code></td>
          <td><code>"exact"&nbsp;|&nbsp;"failed"&nbsp;|&nbsp;"not_reproducible"</code></td>
          <td>
            <code>"exact"</code>: the replay gave the stored score and case count on the same
            benchmark revision. <code>"failed"</code>: it ran, or tried to, and did not match.
            <code>"not_reproducible"</code>: the score has no complete frozen copy, so no run
            started.
          </td>
        </tr>
        <tr>
          <td><code>reason</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            Why the outcome is not exact. <code>None</code> when it is exact. See the table below.
          </td>
        </tr>
        <tr>
          <td><code>missed_cases</code></td>
          <td><code>tuple[int&nbsp;|&nbsp;str, ...]</code></td>
          <td>
            The ids of cases the frozen copy could not answer. Filled only when
            <code>reason</code> is <code>"frozen_copy_miss"</code>.
          </td>
        </tr>
        <tr>
          <td><code>result</code></td>
          <td><code>CandidateResult&nbsp;|&nbsp;None</code></td>
          <td>
            The replayed result. <code>None</code> when no run started, or when the Engine did not
            confirm the run as a replay (<code>replay_unsupported</code>).
          </td>
        </tr>
        <tr>
          <td><code>recorded</code></td>
          <td><code>bool</code></td>
          <td>Whether the board stored this exact reproduction.</td>
        </tr>
        <tr>
          <td><code>record_error</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            Why an exact replay could not be recorded. The outcome stays <code>"exact"</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      The Client checks a replay in this order and reports the first problem. A score that is not
      reproducible starts no run, so its reason comes before any replay. A missing or unavailable
      copy is checked before a failed run, because a run that missed the copy has nothing to
      compare.
    </p>

    <table>
      <thead>
        <tr>
          <th><code>outcome</code></th>
          <th><code>reason</code></th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>not_reproducible</code></td>
          <td><code>partial</code></td>
          <td>The score is <code>capture_status="partial"</code>. No run starts.</td>
        </tr>
        <tr>
          <td><code>not_reproducible</code></td>
          <td><code>unknown</code></td>
          <td>
            The score has no <code>capture_status</code>, no <code>frozen_copy_id</code> or no
            benchmark revision. No run starts.
          </td>
        </tr>
        <tr>
          <td><code>failed</code></td>
          <td><code>replay_unsupported</code></td>
          <td>
            The Engine did not confirm replay mode. When the Engine did not echo the replay at the
            start, the Client stopped the run. If the stop failed, an
            <code>EvaluationWarning</code> says the run may still be running and spending. An Engine
            can also confirm the start and then finish a run whose summary does not name the copy.
            That run is already over and may have called providers. The Client does not report it as
            a replay.
          </td>
        </tr>
        <tr>
          <td><code>failed</code></td>
          <td><code>frozen_copy_miss</code></td>
          <td>
            The copy had no answer for some calls. <code>missed_cases</code> lists their cases. The
            replay bought nothing.
          </td>
        </tr>
        <tr>
          <td><code>failed</code></td>
          <td><code>frozen_copy_unavailable</code></td>
          <td>
            The copy is unknown or not sealed, or the gateway has no frozen copies (an older
            gateway). The cases fail, and the run finishes.
          </td>
        </tr>
        <tr>
          <td><code>failed</code></td>
          <td><code>run_failed</code></td>
          <td>The replayed run itself failed, and the cause is not a missing copy.</td>
        </tr>
        <tr>
          <td><code>failed</code></td>
          <td><code>benchmark_revision_changed</code></td>
          <td>
            The benchmark is now a different revision, so the numbers cannot be compared. A changed
            benchmark can also show as <code>frozen_copy_miss</code>, which is checked first.
          </td>
        </tr>
        <tr>
          <td><code>failed</code></td>
          <td><code>score_differs</code></td>
          <td>The score or the case count is not the stored one. The comparison is exact.</td>
        </tr>
      </tbody>
    </table>

    <p>
      Only an <code>"exact"</code> replay is recorded, and only when <code>record=True</code>. A
      failed record never changes the outcome.
    </p>

    <p>
      Some problems still raise. A <code>score</code> that is not a <code>LeaderboardScore</code>, a
      <code>UUID</code> or a string raises <code>TypeError</code>. Passing an id makes the Client
      read the score first, and that read raises
      <RouterLink to="/sf-client/api/errors"><code>LeaderboardError</code></RouterLink> if it fails.
      Any <code>ExecutionError</code> other than <code>replay_unsupported</code> also raises. When
      the Client cannot stop a run that the Engine did not confirm as a replay, it emits an
      <code>EvaluationWarning</code>. The
      <RouterLink to="/learn/caching">caching page</RouterLink> explains what makes a score
      <code>"partial"</code>.
    </p>

    <p>
      A leaderboard call that cannot be completed safely raises
      <RouterLink to="/sf-client/api/errors">LeaderboardError</RouterLink>.
    </p>
  </DocLayout>
</template>
