"""Retired at OME-1138 Stage E, E5c: a Profile delete racing an API-key set (OME-307 Unit 3).

This module pinned that deleting a Profile (blob plus index entry) and a racing API-key
publication on it serialized through `ProfileTransitionConflict`, so neither an orphan credential
nor a resurrected Profile survived. The index store and its conflict are gone (E5c), and no route
has written a Profile since Stage E3.

Successor coverage: the Connection analogue of the same race — `test_connection_delete_set_race.py`
and `test_api_key_connection_races.py`.
"""
