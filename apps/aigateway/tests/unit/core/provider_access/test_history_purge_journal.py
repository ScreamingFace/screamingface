"""Retired at OME-1138 Stage E, E5c: the purge journal across the `--all` phases (E5b).

This module pinned that each committed phase of an apply run had its journal line on disk before
the next phase started. The purge has run in every environment and E5c deleted it (spec Q5).

Successor coverage: the purge is absent — `test_profile_index_offline_only.py`.
"""
