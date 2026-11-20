"""The chat leaf of POST /v1/chat/completions: records, wire models, recipe check and views.

A shared leaf: pure code with no I/O. Both the App and the run import it, and it imports neither
half. Only `chat/recipe.py` may import the url4 engine (plan decision D7).
"""
