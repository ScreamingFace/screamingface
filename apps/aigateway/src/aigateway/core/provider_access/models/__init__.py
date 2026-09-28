"""Tortoise models owned by the provider-access boundary (OME-1208, Stage B)."""

from __future__ import annotations

from .provider_credential_slot import BaseProviderCredentialSlot, ProviderCredentialSlot

__all__ = ["BaseProviderCredentialSlot", "ProviderCredentialSlot"]
__models__ = [ProviderCredentialSlot]
