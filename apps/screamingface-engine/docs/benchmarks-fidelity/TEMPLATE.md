---
# Copy to <catalogue id>.md. Every key below is required; the two *_reason keys may be "".
# The check script reads only this front matter (spec §2.1); a reviewer reads the body (§2.2).
benchmark: <catalogue id, equal to the file stem>
origin: <screamingface | inspect_evals, copied from the declaration>
verdict: <comparable-to-paper | comparable-to-inspect | not-comparable | unverified>
verdict_reason: ""                     # required non-empty for not-comparable and unverified
audited: <YYYY-MM-DD>
audited_at: <main sha the audit read>
fingerprint:
  benchmark: <16-hex COMPUTED fingerprint: imported_benchmark(key).fingerprint, never the published revision>
  harness_url: <the declaration's harness_url, byte for byte>
references:                            # each an http(s) URL pinned to a sha or a v-tag; the reader lands on what the audit read
  paper: <https://arxiv.org/abs/<id>v<N>>
  original_harness: <the authors' code that produced the published number, at its commit>
  inspect_evals: <https://github.com/UKGovernmentBEIS/inspect_evals/tree/v<installed version>>
  inspect_ai: <https://github.com/UKGovernmentBEIS/inspect_ai/tree/v<installed version>>
parity_test: <path relative to apps/screamingface-engine/, or none>
parity_test_reason: ""                 # required non-empty when parity_test is none
---

# <Benchmark title> — Fidelity Record

## Verdict

One paragraph: the verdict, the published number ours is comparable to (the paper's headline or
inspect's), and the sentence that carries it. Show the bound arithmetic when deviations exist:
`sum of bounds against the original harness = N/case_count = 0.00xx ≤ COMPARABLE_TOLERANCE (0.005)`.

## Dimensions

Seven rows, this order. `status` ∈ match · deviation · not applicable · unchecked. A `match` MUST
carry evidence (a command and the output lines, or the two source locations compared); an
`unchecked` carries its reason in the evidence column.

| dimension | status | severity | bound | evidence |
|---|---|---|---|---|
| dataset | | | | |
| prompt | | | | |
| answer extraction | | | | |
| metric | | | | |
| roll-up | | | | |
| judge | | | | |
| sampling | | | | |

## Deviations

One `### D<n> — <plain name>` per `deviation` row. Each states: declared or undeclared (declared =
a `# NAMED DEVIATION` line on the row, a `named_deviations/` scorer, `dropped_scorers`,
`excluded_sample_ids`, or a README paragraph the row links); where (our file and line, theirs);
what differs; severity (cosmetic · score-changing · possibly-score-changing) and bound
(`0` · `N/case_count` with the Case ids · `unbounded` · `unknown`); evidence.

## Checks run

Every command the audit executed, in order, with the environment used (`env -i …`) and the output
lines that carry the result. This is what makes an evidence-free `match` impossible to miss.

## Recommended paid runs

What a judge run would settle, how many Cases, which judge; `none` when nothing is pending.

## Upstream notes

Where the original harness and the paper disagree (the harness wins; recorded, not counted as
ours), and where inspect_evals disagrees with the original harness (the `comparable-to-inspect`
evidence), each with its own bound.
