"""Bounded process-local storage for diagnostic receipts."""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock

from screamingface.diagnostic import DiagnosticReceipt


class _DiagnosticStore:
    def __init__(self, *, max_count: int, max_bytes: int) -> None:
        if isinstance(max_count, bool) or not isinstance(max_count, int) or max_count < 1:
            raise ValueError("Diagnostic max_count must be a positive integer")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("Diagnostic max_bytes must be a positive integer")
        self._max_count = max_count
        self._max_bytes = max_bytes
        self._receipts: OrderedDict[str, tuple[DiagnosticReceipt, int]] = OrderedDict()
        self._bytes = 0
        self._lock = RLock()

    def add(self, receipt: DiagnosticReceipt) -> bool:
        if not isinstance(receipt, DiagnosticReceipt):
            raise TypeError("Diagnostic store accepts DiagnosticReceipt values")
        size = len(receipt.to_json().encode("utf-8"))
        with self._lock:
            if receipt.diagnostic_id in self._receipts:
                raise ValueError(f"Diagnostic {receipt.diagnostic_id!r} already exists")
            if size > self._max_bytes:
                return False
            while self._receipts and (
                len(self._receipts) >= self._max_count or self._bytes + size > self._max_bytes
            ):
                _, (_, removed_size) = self._receipts.popitem(last=False)
                self._bytes -= removed_size
            self._receipts[receipt.diagnostic_id] = (receipt, size)
            self._bytes += size
            return True

    def get(self, diagnostic_id: str) -> DiagnosticReceipt | None:
        with self._lock:
            stored = self._receipts.get(diagnostic_id)
            return None if stored is None else stored[0]

    def last(self) -> DiagnosticReceipt | None:
        with self._lock:
            if not self._receipts:
                return None
            return next(reversed(self._receipts.values()))[0]

    def clear(self) -> None:
        """Clear process-local state for lifecycle reset and isolated tests."""

        with self._lock:
            self._receipts.clear()
            self._bytes = 0


_STORE = _DiagnosticStore(max_count=20, max_bytes=2 * 1024 * 1024)


__all__ = ["_DiagnosticStore", "_STORE"]
