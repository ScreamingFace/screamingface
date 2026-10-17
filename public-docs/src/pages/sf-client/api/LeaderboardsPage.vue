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
[(b.id, b.display_name) for b in client.leaderboards.list()][:3]`
const listRunOut = `[('arc_agi_2', 'ARC-AGI-2'), ('contracteval', 'ContractEval'), ('draco', 'DRACO')]`

const submit = `report = client.evaluate(recipe, benchmark="ifeval", limit=1)
client.leaderboards.submit(
    report.candidates.only,
    authors=["alice@example.com", "bob@example.org"],
    paper_url="https://arxiv.org/abs/2601.00001",
)`

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
      submission creates. <code>ScoreMetadataEvent</code> is one row of a score's edit log.
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
            <RouterLink to="/sf-client/api/clients">evaluate()</RouterLink> to run the recipe
            again.
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
          <td>
            When the authors or the paper link last changed. <code>None</code> if never. The portal
            shows it as "Metadata edited &lt;date&gt;" next to the paper link.
          </td>
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
            Whether the frozen copy holds the whole run. A local capture is always
            <code>"partial"</code>. <code>None</code> means unknown.
          </td>
        </tr>
        <tr>
          <td><code>case_digest</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            A digest of the graded cases of the run: 64 lowercase hex characters. It is set only
            with a <code>capture_status</code>. <code>LeaderboardEntry</code> rows do not carry
            it.
          </td>
        </tr>
        <tr>
          <td><code>answer_seed</code> · <code>benchmark_revision</code></td>
          <td><code>int&nbsp;|&nbsp;None</code> / <code>str&nbsp;|&nbsp;None</code></td>
          <td>
            The answer seed of the run and the revision of the benchmark it ran on.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      Boards that predate a field leave it absent, and it reads as <code>None</code>.
    </p>

    <h2>LeaderboardRankingNotice</h2>

    <p>
      <code>LeaderboardScore.ranking_notice</code> explains why a successfully published score will
      not enter the current ranking, and is <code>None</code> when it will. A
      <code>LeaderboardRankingNotice</code> has a <code>code</code>, the
      <code>submitted_benchmark_revision</code> and the <code>registered_benchmark_revision</code>
      of the board.
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
  </DocLayout>
</template>
