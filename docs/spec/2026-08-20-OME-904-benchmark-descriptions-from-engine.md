# OME-904 — Benchmark descriptions come from the Engine

## Decision

A benchmark's human-readable text — display name, description, focus line, dataset link — is
owned by the Engine benchmark definition that the text describes, and by nothing else. The
Scoreboard stops carrying a hand-typed second copy in chart values.

The Engine `Benchmark` gains two optional metadata fields, `focus` and `dataset_url`, so that
every field the leaderboard displays has exactly one authoring site. They join the existing
catalogue entry served by `GET /v1/benchmarks`, which is public and requires no credential.

The Scoreboard's seed job — the one-shot container Helm already runs on every install and
upgrade — fetches that catalogue at deploy and writes one row per published benchmark. Chart
values keep only two things: which Engine to ask, and the legacy demo entries that predate the
Engine catalogue and have no Engine counterpart. A deploy-time values override can therefore
change which Engine is consulted, but can no longer carry, alter, or omit benchmark prose,
because prose no longer travels through configuration.

Engine-published rows take precedence over configured rows sharing an id. Precedence is what
makes the Engine the only copy rather than merely the preferred one: a configured entry that
shadows a published benchmark is ignored and named in the job's output.

When the Engine cannot be reached, the seed job writes the configured legacy rows and leaves
existing rows untouched — a re-seed refreshes a populated board, so failing a Scoreboard deploy
on an unrelated service's health buys nothing. It fails loudly in exactly the case where
silence would publish an empty catalogue: no benchmark row in the database carries a revision,
which is true only before the first successful seed.

## Invariants

- Benchmark description, focus, and dataset link have one authoring site: the Engine's
  `Benchmark` definition. No other file in the repository restates them.
- A seeded row's `revision` equals the Engine's computed revision for that benchmark, because
  both are read from the same catalogue response in the same request.
- Seeding stays idempotent: re-running writes the same rows and never duplicates or orphans.
- The catalogue fetch is unauthenticated and read-only; the seed job holds no Engine credential.
- An Engine-published benchmark's row wins over a configured entry with the same id, and the
  shadowed id is reported.
- Configured entries remain the only source for benchmarks the Engine does not publish.
- A failed catalogue fetch never blanks or deletes a row that a previous seed wrote.
- A failed catalogue fetch exits non-zero when no benchmark row carries a revision.
- An Engine benchmark without a focus line or dataset link seeds those columns as null, and the
  portal renders its existing em-dash fallback.
- Adding `focus` and `dataset_url` does not enter any benchmark's revision computation, so no
  previously recorded submission becomes incomparable.

## Explicit limitations

- The deployed Engine URL is deployment-owned configuration; this change supplies a repository
  default and reads an override, but does not deploy the Engine.
- Re-seeding the currently deployed board remains an owner action outside this repository; this
  change is the durable fix, not the immediate unblock.
- Legacy demo entries (`livetruth-latest`, `hle`, `livetruth`) keep hand-written values, because
  no Engine benchmark defines them. They are retained, not adopted.
- The Scoreboard's own `/v1/benchmarks` response shape is unchanged; only the values it serves
  stop being null.
