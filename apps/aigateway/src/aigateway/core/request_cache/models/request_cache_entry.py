from __future__ import annotations

import uuid

from tortoise import fields
from tortoise.models import Model


class BaseRequestCacheEntry(Model):
    class Meta:
        abstract = True

    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    key_hash = fields.CharField(max_length=64, unique=True, index=True)
    prompt_hash = fields.CharField(max_length=64, index=True)
    provider = fields.CharField(max_length=64, index=True)
    model = fields.CharField(max_length=255, index=True)
    response_json = fields.TextField()
    response_size_bytes = fields.IntField()
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    # INVARIANT (OME-305 plan §4.2): NULL means "never expires".
    # Nullable rather than a far-future sentinel so "indefinite" is a distinct state a reader cannot
    # mistake for a TTL, and so a later configurable-TTL feature can adopt the column unchanged.
    expires_at = fields.DatetimeField(index=True, null=True)
    last_hit_at = fields.DatetimeField(null=True)
    hit_count = fields.IntField(default=0)
    # A2 / ERD 3.1: the standard cache-entry metadata block (aigw.cache-entry-metadata.v1) as a
    # serialized JSON string. Declared LAST because migration 0011 appends it last in the
    # database: a fresh bootstrap takes its order from this model, and CANONICAL_COLUMNS (the
    # snapshot COPY layout) must agree with whichever produced the table.
    # INVARIANT (ERD E7): NULL means "unknown" and is never read as 0. Legacy rows, and every
    # Tavily-lane row, hold NULL forever.
    metadata_json = fields.TextField(null=True)


class RequestCacheEntry(BaseRequestCacheEntry):
    class Meta:
        table = "request_cache_entries"
