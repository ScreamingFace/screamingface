"""Pulling the community request cache into the local gateway (epic OME-1311).

The public door is `screamingface.cache.pull_from_remote`; this package holds its parts, each
testable on its own: the page reader (`pages`), the hosted page source (`remote`), the local
gateway side (`local`), the pull loop (`pull`) and its progress display (`progress`).
"""
