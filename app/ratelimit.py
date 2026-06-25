"""Tiny in-process rate limiter for the cost-bearing endpoints.

A sliding-window counter keyed by client IP. Its job is to keep the optional,
money/quota-spending AI-insights endpoint from being scripted into a billing or
free-tier drain on a public deployment. It is in-process and per-worker — fine
for the single uvicorn worker this app ships with; swap in a shared store
(Redis, etc.) if you ever scale to multiple workers/instances.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


def client_ip(request) -> str:
    """Best-effort client IP, honoring the first ``X-Forwarded-For`` hop.

    Render / Railway / Fly and most PaaS proxies put the real client in
    ``X-Forwarded-For``; fall back to the socket peer when it is absent.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    return client.host if client else "unknown"


class SlidingWindowLimiter:
    """Allow at most ``max_calls`` per ``window_s`` seconds, per key."""

    _PURGE_AT = 4096   # drop emptied buckets once the table grows past this

    def __init__(self, max_calls: int, window_s: float) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if self.max_calls <= 0:
            return True   # disabled
        now = time.time()
        cutoff = now - self.window_s
        dq = self._hits[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self.max_calls:
            return False
        dq.append(now)
        if len(self._hits) > self._PURGE_AT:
            self._purge(cutoff)
        return True

    def _purge(self, cutoff: float) -> None:
        """Forget keys whose most recent hit has aged out, to bound memory."""
        for key in [k for k, d in self._hits.items() if not d or d[-1] < cutoff]:
            del self._hits[key]
