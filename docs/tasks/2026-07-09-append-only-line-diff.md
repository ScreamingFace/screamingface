---
id: OME-369
linear_url: https://linear.app/openmined/issue/OME-369/run-gatespy-append-only-check-flags-pure-test-additions-as-violations
status: in_review
type: task
priority: P2
labels: [repo, autonomous, agentic, "Repo & Dev Process"]
created: 2026-07-09
closed:
---

`append_only_check()` in `.claude/scripts/run_gates.py` flags any git-modified test
file regardless of content, so pure additions to an existing test file false-positive
as a rule-5 violation. Found while working OME-322.

Fix: diff added/removed lines within each changed test file rather than file-level git
status — only fail if a `-` line falls inside a previously-existing test function body.

No dedicated stack/tests exist for `.claude/scripts/`; verified with a manual
synthetic-scenario check per owner decision, no new permanent test infra added.

**Round 2 (2026-07-17):** `HupBaHa`'s PR review requested changes — the fix still
let prior tests be modified undetected in nested stack roots (`apps/scoreboard`
etc.), plus asked for a permanent test matrix. Confirmed and fixed three bugs
(nested-root `git show` path resolution, decorator lines outside the recorded test
range, dash-prefixed removed-line content false-matching the header skip); added
`.claude/scripts/tests/test_run_gates.py` (8 permanent tests, stdlib `unittest`)
replacing the manual-only verification. See the ledger's Round 2 section for full
detail. Status stays `in_review` pending re-review.

**Round 3 (2026-07-17):** two more concerns from the same review, both confirmed:
pure insertions inside an existing test (zero removed lines) could neuter an
assertion undetected, and fixtures/helpers (e.g. `conftest.py`, real in both
`apps/scoreboard` and `apps/aigateway`) weren't protected at all since only
`test_*`-named functions were tracked. Fixed by protecting every function's range
(not just tests) and adding insertion-position detection with an exclusive upper
bound (so appending a new function directly after an existing one stays legitimate).
12/12 tests pass. See the ledger's Round 3 section.

**Round 4 (2026-07-17):** fixed the reviewer's last P2 (module-level test data,
e.g. `_BASE_KW`, wasn't protected). 16/16 tests pass. Two further findings from
deeper probing deliberately NOT fixed here, deferred as follow-ups instead:
decorator-stacking (concern A) and name-shadowing/monkeypatching (a structural
line-diffing limitation). A third, non-code finding (no CI/hook independently
enforces this check at all) also deferred as its own distinct unit. Ticket
drafts are prepared but NOT yet filed — filing is queued behind the PR
re-review per explicit owner instruction; IDs will be recorded in the ledger
when filed. See the ledger's Round 4 section.

**Round 5 (2026-07-17):** a structured multi-angle code-review pass on the
pushed PR found round 4's own fix was too broad (a denylist, not an allowlist)
— editing a module docstring, an `if __name__ == "__main__":` block, or an
import nested in a version-guard all got falsely flagged, reopening OME-369's
original false-positive problem. Also found a separate anchor-computation bug:
replacing the blank line between two functions falsely flagged the second one.
Fixed both at the root (switched to an `_MODULE_LEVEL_DATA` allowlist; anchor
tracking now keyed off the diff hunk's declared old-line count) plus an
anchor-syntax convention fix. 20/20 tests pass. See the ledger's Round 5
section.

**Round 6 (2026-07-17):** second structured review pass — 5 of 8 angles clean.
Fixed one more real gap (`ast.AugAssign` module-level accumulators were
unprotected) and one docs-process gap (Round 1's ledger placeholder never
filled). A walrus-statement edge case documented as a known limitation rather
than fixed (too exotic to warrant a special case). 21/21 tests pass. See the
ledger's Round 6 section.

**Round 7 (2026-07-17):** third structured review pass — 5 of 8 angles clean.
Fixed a real, plausible false positive: appending content after a file that
lacked a trailing newline produced a git-diff artifact (remove+add of an
unchanged line) that falsely triggered the gate. Two more mutation-in-place
examples (`_CASES.append(...)`, `del _CASES[1]`) turned out to be the same
already-deferred shadowing/monkeypatching class, not new gaps — folded into
existing documentation instead of new code. 22/22 tests pass. See the
ledger's Round 7 section.

**Round 8 (2026-07-17):** fourth structured review pass found round 7's fix
itself only handled the EOF-newline artifact in one direction, and its
pairing logic couldn't be correctly extended to multi-line hunks by more
special-casing (tried and failed by hand first). Rewrote `_diff_positions` to
diff actual line content via `difflib.SequenceMatcher` instead of hand-parsing
git's diff text — this is the same root cause behind three separate bugs
across rounds 2, 5, and 7, all eliminated at once by construction rather than
patched one variant at a time. 24/24 tests pass. See the ledger's Round 8
section (including a correction: one review finding turned out to be the
already-deferred shadowing limitation, not a distinct bug).

**Round 9 (2026-07-17):** fifth review pass on the rewrite (agents partially
cut short by a session limit; remaining questions verified directly). Found
and fixed one real crash: undecodable/binary content in a test-matched file
made the gate raise UnicodeDecodeError instead of producing a verdict — now
compares bytes on both sides (flags binary junk fail-closed, no crash). Also
pinned the verbatim-swap-is-flagged behavior as deliberate. 26/26 tests pass.
See the ledger's Round 9 section.

**Round 10 (2026-07-17):** sixth review pass. Discovered the round-9 bytes
change had also fixed a latent FALSE NEGATIVE: `str.splitlines()` splits on
`\f`/` ` (which Python's tokenizer doesn't), desyncing diff numbering
from ast ranges — a rewrite of a test after such a character went silently
undetected on round-8 code. Proven and pinned with a discriminating test
(27/27 pass). Also surfaced: the test file is over the ≤450-line guideline
(480 at measurement, 586 after rounds 10-11's own tests) — splitting it means
relocating prior tests, itself a rule-5 STOP-and-ask decision, left to the
owner. See the ledger's Round 10 section.

**Round 11 (2026-07-17/18):** seventh review pass found and fixed four more
execution-verified fail-open bugs: a UTF-8 BOM at base stripped ALL protection
from a file (ast.parse of a str BOM raises SyntaxError → permissive branch);
typechange status `T` (test file replaced by a symlink) was silently skipped;
non-ASCII filenames escaped glob matching under git's default path quoting;
and an indented line appended after the file's final test extended its body
undetected (e.g. appending `break` inside its loop flips a failing test
green) — fixed by carrying each protected range's definition column and each
insertion anchor's first-non-blank indent, flagging `n == hi` insertions
indented deeper than the definition. Also corrected 5 documentation-drift
items (outdated PR body rewritten; in-code gap list gained decorator-stacking;
AugAssign docstring omission; follow-up tickets accurately described as
drafted-not-yet-filed pending owner go-ahead; stale line-count figures).
32/32 tests pass. See the ledger's Round 11 section.

**Round 12 (2026-07-18):** eighth review pass returned CLEAN — zero findings
across the consistency sweep and nine adversarial execution probes of the
round-11 changes. Review loop closed per owner instruction; PR #383 awaits
re-review. Next: file the three drafted follow-up tickets one by one on
owner go-ahead.
