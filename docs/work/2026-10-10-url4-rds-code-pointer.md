---
ticket: unfiled   # one issue per phase under OME-500, filed at PR-open after the user confirms
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-10
finished:
---

# url4-rds-code-pointer (reshaped) — code-pointer intents run as RDS calls

## Intent

Reshape the 2026-10-09 spec from the goal and from URL4 Spec A/B/C only, ignoring that
draft's decisions. Add a formal model (Lean 4) that states the rules and proves them.
Documents only. Code starts after the user approves and Kevin McDonough answers Q1–Q9,
or accepts their defaults.

## Planned changes

- `docs/spec/2026-10-10-url4-rds-code-pointer/00-overview.md`
- `docs/spec/2026-10-10-url4-rds-code-pointer/contracts.md`
- `docs/spec/2026-10-10-url4-rds-code-pointer/prd/rds-code-pointer.md`
- `docs/spec/2026-10-10-url4-rds-code-pointer/test-plan.md`
- `docs/spec/2026-10-10-url4-rds-code-pointer/formal/` (Lean package, `lake build` green)
- this ledger

## Notes

- Main changes from the 2026-10-09 draft:
  - No wire format. The 10-09 draft put a JSON document in `q=` with no `!` tail. That
    breaks B §3.1, the §8 ABNF and C §11.6.2, and its params collide with C §9.1
    protocol params. Code now runs in-process from a separate code-mount table (R4, R5).
  - Inputs are an ordered tuple keyed by position (B §6.2 `$N`), with names as a lookup
    aid. This replaces the `{"v":1,"inputs":{…}}` object and its `$k` keys.
  - Expansion follows B §5.3.12 (`name[i]` / `src[i]`, one input per element).
  - RDS field paths are strict (B §5.3.4.1). `unsupported_mode` → 501.
  - The exact classifier also fixes relative/remote expression intents (the old O2).
  - A forwarded call keeps a code-pointer intent verbatim (the old O1, relative and remote).
  - Bare tokens are a tracked deviation (D1), closed in phase P3.
- Probes on 2026-10-10 (audit branch): the parser refuses raw newlines in quoted text
  (spec `quoted-char`); bare-token intents parse; `quorum=majority` is refused by
  `compile_expression`.
- Lean 4.34.1: 42 theorems (29 headline theorems in the axiom audit), `lake build` green
  with no warnings, and the audit was checked to fail on a `sorry`.
- Design review (design-reviewer, 2026-10-10): 3 high, 7 medium, 8 low findings, all
  fixed in the docs and the model. Decisions taken from the spec text:
  - every execution failure is `intent_error` (C §13.6);
  - the verbatim rule covers relative **and** remote forwarded calls, for code-pointer
    intents only; the prompt-intent wire stays as is (A5);
  - canonical expressions are detected with the parser's own `q=(` scan;
  - unlisted permanent codes → 422;
  - `unsupported_mode` is group-level;
  - strictness is keyed on the action taken;
  - broadcast passes `$current` plus the `$`-referenced sources;
  - `quorum=all` conflict → Q9.
- Owner decisions (2026-10-10), recorded in overview §7:
  - Q1 hybrid by scheme: a relative URI is code; every absolute URI (`url4://`,
    `https://`, `s3://`) keeps the 1.5.1 fetch-as-prompt meaning (new deviation D2).
  - Q2 refuse remote code until Part G (no 2.0 form reaches it).
  - Q3 a computed intent is always a prompt.
  - Q4 position is the key.
  - Q5 `intent_error`.
  - Q6 one code table with separate path and name keys.
  - Q7 no content type in 2.0.
  - Q8 refuse duplicate keys.
  - Q9 `quorum=all` per C §12.2.
- Effects of Q1:
  - CH8 and CH10 no longer flip.
  - E6 and row 4 now pin "an absolute URI never reaches code".
  - The Lean `v1` profile gains `fetchPrompt`.
  - `v1_not_conforms_iff` now names {bare token, `url4://` reference, absolute URI}.
  - New theorem `v1_act_eq_invokeLocal_iff`: only a relative URI runs code.
