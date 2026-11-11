---
id: OME-1860
linear_url: https://linear.app/openmined/issue/OME-1860/serve-gsm8k-and-winogrande-with-inspect-evals-default-worked-examples
status: done
type: task
priority: medium
labels: [screamingface-engine, human, autonomous]
parent: OME-1299
created: 2026-11-10
closed: 2026-11-10
---

# Serve gsm8k and winogrande with inspect_evals' default worked examples instead of zero-shot

Parent: OME-1299. Follows OME-1858, whose sweep marked both Benchmarks not-comparable.

Ledger: `docs/work/2026-11-10-gsm8k-winogrande-default-fewshot.md`.

- 2026-11-10: both rows call inspect_evals' Task with its defaults, so every Case opens with the
  eval's worked examples (10 for gsm8k, 5 for winogrande). Published revisions moved on the
  owner's call: gsm8k `075954bfd63059e0` → `7eebba58799a2f22`, winogrande `4eb60a70db7518d6` →
  `3f2af135ba8bad37` (no leaderboard entries on either). Both Fidelity Records re-audited:
  `unverified`, not `comparable-to-inspect`, because the worked examples reach the Candidate as
  leading user text instead of a system turn; winogrande also keeps the unapplied
  `max_tokens=64`. One PR against main. Pending the owner: merge, Linear → Done.
