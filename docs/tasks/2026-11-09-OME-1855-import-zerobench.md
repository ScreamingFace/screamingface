---
id: OME-1855
linear_url: https://linear.app/openmined/issue/OME-1855
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1330
created: 2026-11-09
closed: 2026-11-09
---

# Add ZeroBench main questions as a picture Benchmark at inspect's five Attempts

ZeroBench (arXiv 2502.09696) is 100 hand-written visual reasoning questions over one or more
pictures, built so that every frontier model scored 0 at release; the official board's best
pass@1 today is 43.2. inspect_evals 0.20.0 ships it as `inspect_evals.zerobench.zerobench:zerobench`
over the gated Hub dataset `jonathan-roberts1/zerobench`, graded by its own scorer: the last
curly-braces group in the reply, exact match. It lands as the Task-replay Benchmark
`inspect-zerobench`.

- 2026-11-09: owner decisions (dispatch): main set only, the 334 sub-questions stay out; imported
  with `k=1` because the task's `Epochs(5, [pass_at_1, pass_at_5, 5_of_5_reliability])` is
  refused, so the score is a single-sample pass@1 and the card says it is not like-for-like with
  the board's five-sample pass@1 (0.432, GPT-6 Astra max) or its pass@5 (0.520); house seed
  20260917; tier `hard`; policy `withhold`; no licence stated on the card or the project page,
  so the rows take the repo's no-licence form with the authors' gate terms (no public answers,
  no training, canary) in the comments; gold answers appear in no artifact.
- 2026-11-09: imported inside the linux/amd64 Engine image: 100 Cases, 108 pictures, Case Digest
  `7b1b680a…`, published revision `b0afce4bf40156bf`; the build path reproduced the digest;
  inspect's own eval with the free mock model matched all 100 Samples to their Cases byte for
  byte (pictures by their bytes; inspect labels 101 JPEG pictures `image/png` from the file name,
  the Case labels them by their bytes). It joins the picture notebook as the fourth Benchmark
  sealed on Linux. This closes the ticket; the paid smoke and the CI image build are the owner's.
- 2026-11-09, second pass: PR #1709 (OME-1856) taught the importer and the Engine the mean fold, so
  the row was re-imported inside the linux/amd64 image at the Task's own defaults: each Case is
  asked 5 times, `attempts=5`, `epoch_reducer="pass_at_1"`, Benchmark score = mean over the Cases
  run of each Case's mean over 5 Attempts (an Attempt is right only on an exact match), the number
  inspect_evals publishes as pass@1 and the board's five-sample column, so the frontier 0.432 is
  like-for-like; pass@5 and 5-of-5 reliability are named as not reproduced. Same 100 Cases, same
  Case Digest `7b1b680a…`; the published revision moved to `9155d9581e103c0a` (never published
  before). inspect's own eval at the defaults (500 sample records) matched every Case 5 times.
  The card says why the Benchmark is comparable to inspect_evals and not to the paper (full
  resolution out of reach: 3 questions carry 9 to 25 MB pictures, over the 8 MB Case cap).
  Stacked on OME-1856 (blocked by it) until #1709 merges. Open point for the owner: the SDK's
  listing and Case Result phrase "any of N Attempts" reads wrong for this Benchmark until the
  catalogue carries the fold rule (a wire field, not this unit).
