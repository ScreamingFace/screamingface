---
title: Hosted provider availability from caller profiles
ticket: OME-958
status: approved
date: 2026-08-24
---

# Hosted provider availability from caller profiles

## Outcome

`GET /v1/connections` on a deployed ScreamingFace Engine truthfully reports which advertised
providers the signed-in caller can use. Availability comes from the caller's existing AI Gateway
profiles; local Engine listing continues to reflect the caller-managed `screamingface` connection
rows used by BYOK controls.

## Ownership and seam

AI Gateway remains authoritative for provider capabilities, profile state, and credential storage.
Its existing caller-scoped `GET /v1/auth/profiles` route supplies the deployed availability input;
this work adds no AI Gateway route or schema.

The Engine composition root explicitly selects one listing source when it builds the existing AI
Gateway connection adapter:

- deployed Engine: caller profiles;
- local Engine: caller-managed connection rows.

The Engine-facing `Connections` interface and public `/v1/connections` response do not change. The
source selection is deployment wiring, not an environment guess inside list execution and not a
Client hint.

## Profile projection

The adapter first loads the enabled provider catalogue, then strictly decodes the caller's profile
list. It projects profiles only onto providers present in that catalogue; a profile for a disabled
or unknown provider does not create a public row.

When a provider has multiple profiles, public status uses this deterministic precedence:

1. any `authenticated` profile -> `connected`;
2. otherwise any `pending` profile -> `pending`;
3. otherwise any `error` profile -> `error`;
4. no profile -> `not_connected`.

The projection exposes neither profile identifiers, names, defaults, account labels, nor credential
material. `auth_method` remains absent because availability may be backed by multiple profiles with
different authentication types and the hosted Client does not manage those credentials.

## Failure and privacy contract

Profile payloads are untrusted upstream data. The collection shape, provider identifiers, and
profile states are validated before projection. A malformed response fails through the existing
secret-free `ConnectionBadResponse` mapping.

Caller identity forwarding, `Cache-Control: private, no-store`, and `Vary: X-User-Email` remain
unchanged. Two callers using the same Engine and catalogue may receive different statuses.

## Compatibility and exclusions

- Local BYOK list/connect/OAuth/disconnect behavior is unchanged.
- The public Engine response schema and Client wire decoder are unchanged.
- This unit does not change AI Gateway, URL4, model execution, or benchmark behavior.
- Direct hosted credential-mutation routes remain the explicit OME-883 limitation; OME-960 keeps
  those controls absent from the hosted Client UI.
