# OME-1488 — every scoreboard transaction names its connection

## Problem

Since #1213 the web app runs two Tortoise connections: `default` (the sized request pool) and
`readiness` (one connection reserved for `/readyz`, used by no model). Tortoise's
`in_transaction()` picks a connection by itself only when exactly one exists; with two it raises
`ParamsError`. The scoreboard opens eight unnamed transactions, so the leaderboard, the frontier
and submissions fail in the web app. The unit tests use a single connection (`tortoise_db`), which
is why CI stayed green.

## Rule

INVARIANT: every `in_transaction()` in `apps/scoreboard/src` passes
`connection_name=DEFAULT_CONNECTION`. The readiness connection is never chosen by default, and a
future third connection cannot reintroduce the ambiguity.

`DEFAULT_CONNECTION = "default"` lives in `scoreboard/db.py` beside `READINESS_CONNECTION`, and the
config builder uses it too, so the alias and the name the transactions use cannot drift apart.

## Not changed

- The readiness connection, its pool and `/readyz` (#1213's design stands).
- The CLIs' single-connection startup.

## Tests

- Behaviour under the app's real two-connection config: board read, frontier read, submission,
  replay, delete.
- A structural guard over the package source (AST): no `in_transaction()` call without a
  `connection_name` keyword. No regular expression or substring search.
