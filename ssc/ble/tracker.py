"""Bookkeeping of in-flight requests, one per characteristic.

The notification callbacks run on the BLE thread while the command pump runs
on the main thread, so every state transition is guarded by a lock.

A characteristic has at most one in-flight request; further requests wait in a
queue until the device has answered the current one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from queue import Queue
from threading import Lock


@dataclass
class PendingRequest:
    """The request currently waiting for an answer plus the backlog."""

    request: bytes = b""
    queue: Queue[bytes] = field(default_factory=Queue)


class RequestTracker:
    """Per-characteristic request queue and in-flight marker."""

    def __init__(self, characteristics: Iterable[str]) -> None:
        self._lock = Lock()
        self._pending = {name: PendingRequest() for name in characteristics}

    def enqueue(self, characteristic: str, requests: Iterable[bytes]) -> int:
        """Append *requests* to the backlog and return how many were added."""
        count = 0
        for request in requests:
            self._pending[characteristic].queue.put(request)
            count += 1
        return count

    def waiting(self, characteristic: str) -> int:
        """Number of requests still queued (excluding the in-flight one)."""
        return self._pending[characteristic].queue.qsize()

    def take_next(self, characteristic: str) -> bytes | None:
        """Return the next request to send, if the previous one was answered."""
        with self._lock:
            pending = self._pending[characteristic]
            if pending.request or pending.queue.empty():
                return None
            pending.request = pending.queue.get_nowait()
            return pending.request

    def take_response_request(self, characteristic: str) -> bytes | None:
        """Mark the in-flight request as answered and return it."""
        with self._lock:
            pending = self._pending[characteristic]
            request, pending.request = pending.request, b""
            return request or None