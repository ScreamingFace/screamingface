---
title: Hosted provider status presentation
ticket: OME-960
status: approved
date: 2026-08-24
---

# Hosted provider status presentation

## Outcome

The Client connection panel shows the hosted Engine's caller-scoped provider availability instead
of presenting every advertised provider as connected. A user can tell which hosted providers are
available without being offered credentials controls that belong only to local BYOK operation.

## Presentation contract

The Engine's `Connection.status` remains the source of truth. Hosted rows project that wire state
into concise user-facing language:

- `connected` -> `Connected`, with source `Available via ScreamingFace`;
- `not_connected`, `pending`, `needs_reauth`, and `error` -> `Unavailable`, with no availability
  source claim.

The non-connected wire states describe operator-owned credential lifecycle details. They are not
actionable for a hosted caller, so the Client exposes only the caller-relevant availability fact.
Local BYOK rows continue to expose their exact wire status because the local caller owns and can
repair those credentials.

One presentation projection owns status class/label and source together. Static HTML, ipywidgets,
and plain representation all use that projection, so no rendering path can leak a different wire
state or make an independent availability claim.

## Boundaries

- Hosted rows expose no Connect, Disconnect, API-key, OAuth, Save, or Cancel controls.
- Hosted account labels remain hidden.
- Local loopback BYOK status, account labels, and mutation controls remain byte-for-byte in scope
  and behavior.
- The public `Connection` model, Engine response schema, authentication flow, and provider
  catalogue do not change.
- The Client change remains blocked from merge until OME-958 makes hosted status authoritative.

## Compatibility decision

OME-960 intentionally reverses OME-883's unreleased presentation rule that forced every hosted
provider to `Connected`. The inherited test encoding that rule is updated rather than retained as
a compatibility fallback; the owner explicitly approved truthful caller-scoped availability.
