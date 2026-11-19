---
id: OME-1874
linear_url: https://linear.app/openmined/issue/OME-1874/add-enigmaeval-puzzle-hunt-benchmark-with-pictures-and-exact-match
status: done
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1828
created: 2026-11-11
closed: 2026-11-13
---

# Add EnigmaEval, the puzzle-hunt Benchmark with pictures and exact match

EnigmaEval ([arXiv 2502.08859](https://arxiv.org/abs/2502.08859), CAIS and Scale AI) is 1,161
puzzle-hunt puzzles, most with pictures, each answered by a word or short phrase. There is no
inspect Task; the authors' grader is plain Python in
[centerforaisafety/simple-evals](https://github.com/centerforaisafety/simple-evals/tree/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval)
(branch `dev`). It lands as a local Task and one Benchmark, `enigmaeval`.

Ledger: `docs/work/2026-11-13-enigmaeval.md`.

- 2026-11-13: owner decisions (dispatch, then the rulings on the measurement): one Benchmark;
  ship every source under its own licence, the non-commercial ones out if we go commercial;
  pictures re-saved as PNG the authors' way, sealed on linux/amd64; Ring Toss served for
  evaluation use only; the image sentence follows the authors' code; the system prompt folded
  into the user turn is a declared deviation.
- 2026-11-13: built and sealed inside the linux/amd64 Engine image: 1,158 Cases (three over the
  8 MB Case cap held out by owner decision, 2026-11-18, until the cap is raised), Case Digest `2534208d…`,
  published revision `863b8c98762520a2`. Pending the owner: the over-cap decision, push, PR,
  the paid smoke, Linear → Done.
