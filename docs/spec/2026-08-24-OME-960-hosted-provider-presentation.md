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
- `not_connected` -> `Unavailable`, with no availability source claim;
- `pending`, `needs_reauth`, and `error` retain their existing truthful status wording and make no
  availability source claim.

Static HTML and ipywidgets use the same presentation helper. The plain representation exposes the
same projected status, so it cannot claim a provider is connected when the visual panel does not.

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
