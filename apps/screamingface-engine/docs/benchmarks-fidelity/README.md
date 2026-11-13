# Fidelity Records

One file per Benchmark, named by its catalogue id (`ifeval.md`, `inspect-gsm8k.md`,
`medxpert.md`), saying which published number our score is comparable to and why. Spec:
`docs/spec/2026-11-06-OME-1471-benchmark-fidelity.md` at the repo root; glossary entries
**Fidelity Record** and **Fidelity Verdict** in `CONTEXT.md`.

## Why these exist

Every Benchmark we serve is a translation of someone else's exam: the paper describes it, the
authors' original harness produced the published number, and for an Imported Benchmark
[inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals) is a second translation between the paper and us. Benchmark Provenance pins the
paper and the harness on every row; a Fidelity Record says whether our translation gives the
same marks. When the Leaderboard shows our score beside the paper's Frontier Score, the record
is what says the two numbers come from the same exam.

## How to read a verdict

| verdict | meaning |
|---|---|
| `comparable-to-paper` | our headline can sit beside the paper's: every difference from the original harness is cosmetic or bounded, and the bounds sum to at most half a percentage point (`COMPARABLE_TOLERANCE = 0.005`) |
| `comparable-to-inspect` | ours matches inspect_evals, which itself differs from the paper beyond that |
| `not-comparable` | reproducible but a different number: an unbounded difference, or grading the paper ran through a vendor, a human or a different judge model |
| `unverified` | a dimension could not be checked, or a judge question waits on a paid run, while the differences measured so far still fit within tolerance (once they exceed it, the verdict is `not-comparable` whatever is still open); the reason is in the front matter |

A verdict never claims more than the evidence in its record: every `match` names the command and
output, or the two source locations, that showed it.

## The live table

Records are frozen at audit time; the catalogue moves. The check script compares each record's
fingerprint (our computed Benchmark fingerprint and the pinned harness link) with today's
declaration and prints one line per Benchmark:

```sh
just engine fidelity-check            # fresh · stale (with the value that moved) · no record · orphan record
just engine fidelity-check --markdown # the same as a GitHub table, for a PR or a sweep ticket
```

`stale` means the verdict was true for an exam that no longer exists: audit again. The script
makes no network call and calls no model; it exits 1 only when a record is malformed or names a
parity test that does not exist.

## How a record is produced

1. A session runs the `sf-benchmark-fidelity` agent (`.claude/agents/`) on one Benchmark. The
   agent is read-only on the repo, runs the pinned harness in a throwaway environment with no
   keys, calls no model, and returns the record body.
2. The session checks every cited line, writes `<id>.md` in a worktree, confirms it reads
   `fresh`, then commits and pushes the branch. Which worktree and branch, and the exact
   commands: the agent file's section "For the calling session".
3. The record is reviewed in a PR like code. A `match` without evidence is a review comment.

A PR that onboards a Benchmark ships its record, or says in its body when the record follows
(`sf-code-review` Lane 2 asks for it).
