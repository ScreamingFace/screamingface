<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import { learnNavigation as navigation } from '@/navigation/learn'

const GH_TREE = 'https://github.com/ScreamingFace/screamingface/tree/main'

const read = `import screamingface as sf

sf.leaderboards.list()                      # benchmarks with a public board

board = sf.leaderboards.get("draco", top=10)
for entry in board.entries:
    print(entry.rank, entry.score, entry.verified_by_screamingface)

board.baselines                             # single-model numbers, for comparison`

const publish = `score = sf.leaderboards.submit(report.candidates.only)
score.id                                    # the stable id of this submission
sf.leaderboards.get_score(score.id)         # read it back later`

const remix = `entry = board.entries[0]

entry.url4.to_python()   # the winning recipe as editable code, no spend
sf.evaluate(entry.url4)  # or replay it verbatim, benchmark included`
</script>

<template>
  <DocLayout
    title="Leaderboard"
    description="The public board where ensemble results are ranked after an independent re-run, and where every entry carries the recipe that produced it."
    :navigation="navigation"
  >
    <p>
      The <strong>Leaderboard</strong> is where results go public. It ranks ensemble runs against
      research benchmarks, and a result only counts once it has been re-run independently. Every
      entry shows what it scored, what it cost to get there, and the
      <RouterLink to="/learn/url4">url4</RouterLink> expression that produced it, which is what you
      would use to run the same evaluation and check the number against your own result.
    </p>

    <p>
      Published model numbers usually originate with the party that benefits from them, and are
      reported rather than demonstrated. The board is organized around the opposite arrangement: a
      rank is a claim someone else has already reproduced, and that you can reproduce again.
    </p>

    <h2>How a rank happens</h2>

    <p>
      A submission carries the benchmark, the recipe's url4, the result, and the providers the run
      used. It then goes through four steps before it appears:
    </p>

    <ul>
      <li>
        <strong>Validation.</strong> The score is benchmark-native: the exact number the
        benchmark's own grading produced, fractional or negative included. The board checks it is
        a finite number and never recomputes, normalizes, or thresholds it — the benchmark is the
        sole authority on its formula.
      </li>
      <li>
        <strong>Deduplication.</strong> Each submission is hashed over its recipe identity, meaning
        the benchmark, the spec, the expression, the result, and the providers. Identical content
        lands on the same entry rather than a second one. A resubmission inside a 24-hour
        idempotency window replays the original instead of creating a duplicate.
      </li>
      <li>
        <strong>Independent re-run.</strong> ScreamingFace re-runs the submission. Entries that
        survive carry <code>verified_by_screamingface</code>, which is the flag worth reading before
        you trust a row.
      </li>
      <li>
        <strong>Ranking.</strong> The board keeps the best result per spec, ties broken by recency,
        and orders by score, descending. One recipe cannot crowd the board with near-identical
        attempts.
      </li>
    </ul>

    <h2>The line to beat</h2>

    <p>
      Single-model results imported from public sources sit on the same board as the ensembles, as
      <strong>baselines</strong>. They are what makes a fusion's gain legible: a composed system is
      only interesting if it beats the models it is composed from, and the comparison should use
      numbers the field already accepts. Each baseline records where it came from, so you can go
      read the original.
    </p>

    <h2>The recipe is the reward</h2>

    <p>
      A rank on its own would only settle who is ahead. What makes the board compound is that the
      recipe travels with it: every entry stores its url4, so the ordinary way to enter is to start
      from whatever is currently winning, change one part of it, and run it again. Prior results
      become the starting position rather than a blank file.
    </p>

    <p>
      Because reruns mostly land on the
      <RouterLink to="/learn/caching">cache</RouterLink>, starting from someone else's result is
      usually far cheaper than the original run was.
    </p>

    <h2>From the Client</h2>

    <p>
      The <RouterLink to="/sf-client">Client</RouterLink> reads and writes the board directly. To
      browse it:
    </p>

    <CodeBlock :code="read" language="python" />

    <p>To publish a result you ran yourself:</p>

    <CodeBlock :code="publish" language="python" />

    <p>
      <code>submit()</code> takes a candidate out of a
      <RouterLink to="/sf-client/api/reports">Report</RouterLink>, so you can only publish something
      you actually evaluated. To start from an existing entry instead, read its url4 back as code,
      or hand it straight to the engine:
    </p>

    <CodeBlock :code="remix" language="python" />

    <h2>Known limits</h2>

    <p>
      Evaluation is nondeterministic. The same recipe run twice will not return the same number to
      the decimal, so ranks that sit close together are best read as tied rather than ordered. Treat
      a single run as one sample, not a settled result.
    </p>

    <blockquote>
      The board is not a vote and not a vendor chart. Rankings come from graded benchmark runs
      behind the <RouterLink to="/learn/engine">engine</RouterLink>'s trust boundary, where the
      answer keys stay, and no rank can be bought or self-reported.
    </blockquote>

    <h2>Where the code lives</h2>

    <p>
      The board is
      <a :href="`${GH_TREE}/apps/scoreboard`" target="_blank" rel="noopener"
        ><code>apps/scoreboard</code></a
      >: the submission and ranking API, the baseline registry, and the public portal. Submissions
      arrive at <code>POST /v1/scores</code>; the portal reads
      <code>GET /v1/leaderboard/{benchmark_id}</code>, with per-spec history under
      <code>/history</code>.
    </p>
  </DocLayout>
</template>
