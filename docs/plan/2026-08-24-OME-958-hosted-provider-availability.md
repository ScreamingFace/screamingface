---
title: Implement hosted provider availability from caller profiles
ticket: OME-958
status: approved
date: 2026-08-24
spec: ../spec/2026-08-24-OME-958-hosted-provider-availability.md
---

# Implement hosted provider availability from caller profiles

1. Add adapter tests for caller-specific authenticated profiles, status precedence, malformed
   profile payloads, identity forwarding, and the unchanged local connection-row path.
2. Add composition tests pinning deployed Engine to profile listing and local Engine to managed
   connection listing.
3. Add a small explicit listing-source input to the AI Gateway adapter and strictly decode the
   existing `/v1/auth/profiles` response behind it.
4. Project profile state onto the existing secret-free `Connection` values without changing the
   REST response model.
5. Wire production and local composition to their respective sources.
6. Run focused tests, the full ScreamingFace Engine gate runner, and a direct `origin/main...HEAD`
   wisdom/confidence review.
7. Record the outcome, commit with `Refs: OME-958`, and open the Engine PR before starting OME-960.

## Review follow-up

8. Add failing tests proving profile-backed hosted mutation methods reject without any Gateway I/O
   and profile decoding accepts unrelated envelope fields.
9. Guard all mutations at the adapter boundary, relax only top-level sibling validation, and make
   listing-source selection required at the production/local builder seam.
10. Run focused tests and all Engine gates, update the ledger outcome, commit, and push the draft
    PR without marking it ready.
