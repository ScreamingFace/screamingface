"""Retired at OME-1209 Stage E3b: the credential-admin contract re-run over a migrated pair.

This module re-ran the Profile-backed admin contract against `ConnectionBackedCredentialAdmin` on
a `migrated` pair. Stage E3b deleted that contract (ops 7-9) together with its only callers, the
Profile routes Stage E3 retired, so the re-run retired with it.

Successor coverage: a migrated pair's listing renders from its effective Connection in
`test_pair_admin_disposition.py` (`test_a_migrated_pair_lists_its_effective_connection`); the
D18 publication is pinned in `test_pair_admin_publication.py` and `test_connection_backed_admin.py`.
"""
