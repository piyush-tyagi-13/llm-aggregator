"""Provider-level connection pool with keep-alive, health tracking, and lazy creation.

Manages ``httpx.AsyncClient`` pools at the PROVIDER level (not per-key), enabling
HTTP keep-alive reuse and reducing TCP/TLS handshake overhead across all keys
for the same provider endpoint.

Architecture
------------
Each provider (identified by ``base_url``) gets a shared pool of up to
``POOL_SIZE`` (5) ``httpx.AsyncClient`` instances.  When a request needs an
``AsyncOpenAI`` client the pool borrows an HTTP client, wraps it with the
caller's ``api_key``, and returns the pair.  After the call the HTTP client is
returned to the pool for reuse.

A background heartbeat task periodically checks connection health and replaces
stale connections.  ``ProviderHealthTracker`` collects per-provider metrics
(last connect time, 429s, errors) for observability and routing decisions.

Usage
-----
    pool = get_connection_pool()
    client = await pool.get_client(base_url, api_key)
    try:
        resp = await client.chat.completions.with_raw_response.create(...)
    finally:
        await pool.return_client(base_url, client)

Thread-safety
-------------
Pool and health-tracker dict operations use ``threading.Lock`` for atomic reads
and writes.  The ``asyncio.Queue`` itself is async-safe.  Callers can safely
interact with the pool from different tasks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from threading import RLock
from typing import Any

import httpx
from openai import AsyncOpenAI

from llm_apipool.key_store import KeyStore

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_AGGRESSIVE_TIMEOUT = httpx.Timeout(30.0, connect=5.0, read=30.0)
_AGGRESSIVE_TIMEOUT_STREAM = httpx.Timeout(120.0, connect=5.0, read=120.0)
_NO_AUTH_SENTINEL = "sentinel-no-op"

POOL_SIZE = 5
"""Maximum idle ``httpx.AsyncClient`` instances kept per provider."""

HEARTBEAT_INTERVAL = 5.0
"""Seconds between heartbeat pings for each provider pool."""

_ACQUIRE_TIMEOUT = 3.0
"""Seconds to wait for an available client from the pool before creating fresh."""

_MAX_RECENT_FAILURES = 10
"""Cap for consecutive-failure penalty in health scoring."""


# ── No-auth helper (mirrors openai_compat._NoAuth) ───────────────────────────


class _NoAuth(httpx.Auth):
    """httpx auth that strips the ``Authorization`` header."""

    def auth_flow(self, request: httpx.Request) -> Any:
        request.headers.pop("authorization", None)
        yield request


# ── Health tracker ───────────────────────────────────────────────────────────


class ProviderHealthTracker:
    """Tracks connection health metrics for a single provider endpoint.

    Thread-safe.  Metrics are aggregated per-``base_url`` and can be used by
    the router to prefer healthier connections or by operators for debugging.

    Snapshot fields
    ---------------
    * ``last_connect_time`` — Unix timestamp of the most recent connection
    * ``consecutive_429s``   — Rate-limit responses seen in a row
    * ``consecutive_errors`` — Non-429 failures seen in a row
    * ``total_requests``     — Lifetime request count
    * ``total_429s``         — Lifetime 429 count
    * ``total_errors``       — Lifetime error count
    * ``total_successes``    — Lifetime success count
    * ``health_score``       — Computed 0.0–1.0 score
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self.last_connect_time: float = 0.0
        self.consecutive_429s: int = 0
        self.consecutive_errors: int = 0
        self.total_requests: int = 0
        self.total_429s: int = 0
        self.total_errors: int = 0
        self.total_successes: int = 0

    # ── Record methods ───────────────────────────────────────────────────

    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            self.total_successes += 1
            self.total_requests += 1
            self.consecutive_429s = 0
            self.consecutive_errors = 0

    def record_429(self) -> None:
        """Record a 429 rate-limit response."""
        with self._lock:
            self.total_429s += 1
            self.total_requests += 1
            self.consecutive_429s += 1

    def record_error(self) -> None:
        """Record a non-429 failure (timeout, network, 5xx)."""
        with self._lock:
            self.total_errors += 1
            self.total_requests += 1
            self.consecutive_errors += 1

    def record_connect(self) -> None:
        """Record that a new connection was established."""
        with self._lock:
            self.last_connect_time = time.time()

    # ── Score & snapshot ─────────────────────────────────────────────────

    def health_score(self) -> float:
        """Return a 0.0 – 1.0 health score for this endpoint.

        Heavily weights error-rate and recent-consecutive-failures so that
        a provider that is currently misbehaving is penalised quickly.
        """
        with self._lock:
            if self.total_requests == 0:
                return 1.0

            error_rate = self.total_errors / max(self.total_requests, 1)
            rate_limit_rate = self.total_429s / max(self.total_requests, 1)

            # Recent-consecutive penalty (caps at 0.5 deduction)
            recent_penalty = (
                min(
                    self.consecutive_errors + self.consecutive_429s,
                    _MAX_RECENT_FAILURES,
                )
                * 0.05
            )

            base = 1.0 - (error_rate * 0.5 + rate_limit_rate * 0.3 + recent_penalty)
            return max(0.0, min(1.0, base))

    def snapshot(self) -> dict[str, Any]:
        """Return a dict of current metrics (thread-safe)."""
        with self._lock:
            return {
                "last_connect_time": self.last_connect_time,
                "consecutive_429s": self.consecutive_429s,
                "consecutive_errors": self.consecutive_errors,
                "total_requests": self.total_requests,
                "total_429s": self.total_429s,
                "total_errors": self.total_errors,
                "total_successes": self.total_successes,
                "health_score": self.health_score(),
            }


# ── Pooled-client bookkeeping ───────────────────────────────────────────────


class _PooledClient:
    """Wraps an ``httpx.AsyncClient`` with creation/use timestamps."""

    __slots__ = ("client", "created_at", "last_used_at")

    def __init__(self, client: httpx.AsyncClient, created_at: float) -> None:
        self.client = client
        self.created_at = created_at
        self.last_used_at = created_at


# ── Connection pool ──────────────────────────────────────────────────────────


class ProviderConnectionPool:
    """Provider-level HTTP connection pool with keep-alive and health tracking.

    Each provider (identified by ``base_url``) maintains a shared pool of
    ``httpx.AsyncClient`` instances.  ``AsyncOpenAI`` clients are created
    on-the-fly wrapping a borrowed HTTP client so that HTTP keep-alive is
    reused across all keys for the same provider endpoint.

    Pool behaviour
    --------------
    * At most ``POOL_SIZE`` (5) idle HTTP clients per provider.
    * ``get_client()`` borrows an HTTP client (or creates one if the pool is
      empty and no client becomes available within ``_ACQUIRE_TIMEOUT``).
    * ``return_client()`` returns the HTTP client to the pool (or closes it
      when the pool is full / the client is unhealthy).
    * A background heartbeat task pings every ``HEARTBEAT_INTERVAL`` (5 s)
      to keep connections warm and replace stale ones.

    Thread-safety
    -------------
    Dict-level operations (pool / health / heartbeat lookups) are guarded by
    ``threading.Lock``.  The ``asyncio.Queue`` is naturally async-safe.
    """

    POOL_SIZE = POOL_SIZE
    HEARTBEAT_INTERVAL = HEARTBEAT_INTERVAL

    def __init__(self) -> None:
        self._lock = RLock()
        # base_url → asyncio.Queue[_PooledClient]
        self._pools: dict[str, asyncio.Queue[_PooledClient]] = {}
        # base_url → ProviderHealthTracker
        self._health_trackers: dict[str, ProviderHealthTracker] = {}
        # base_url → asyncio.Task[None]  (heartbeat)
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}
        # id(AsyncOpenAI) → (base_url, httpx.AsyncClient)
        # Tracks in-flight clients for safe return_client() without the tag
        self._active: dict[int, tuple[str, httpx.AsyncClient]] = {}
        # Reference to KeyStore for optional persistence integration
        self._store: KeyStore | None = None
        # Flag to signal heartbeat loops to stop
        self._closed: bool = False

    # ── Optional KeyStore integration ─────────────────────────────────────

    def set_store(self, store: KeyStore) -> None:
        """Attach a *KeyStore* instance for optional persistence.

        Currently reserved for future use (e.g. persisting health snapshots
        or connection counts).  Calling this is optional.
        """
        self._store = store

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_health(self, base_url: str) -> ProviderHealthTracker:
        """Return (or create) the health tracker for *base_url*."""
        with self._lock:
            tracker = self._health_trackers.get(base_url)
            if tracker is None:
                tracker = ProviderHealthTracker()
                self._health_trackers[base_url] = tracker
            return tracker

    async def _get_or_create_pool(self, base_url: str) -> asyncio.Queue[_PooledClient]:
        """Return the pool for *base_url*, creating it and starting heartbeats if needed."""
        with self._lock:
            pool = self._pools.get(base_url)
            if pool is None:
                pool = asyncio.Queue(maxsize=self.POOL_SIZE)
                self._pools[base_url] = pool
                self._start_heartbeat(base_url)
            return pool

    def _start_heartbeat(self, base_url: str) -> None:
        """Create a background heartbeat task for *base_url* if none exists."""
        existing = self._heartbeat_tasks.get(base_url)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            self._heartbeat_loop(base_url),
            name=f"pool-hb-{base_url[:40]}",
        )
        self._heartbeat_tasks[base_url] = task

    def _remove_tracking(
        self, client: AsyncOpenAI
    ) -> tuple[str, httpx.AsyncClient] | None:
        """Remove tracking for a client and return its (base_url, http_client) pair."""
        cid = id(client)
        with self._lock:
            mapping = self._active.pop(cid, None)
            if mapping is not None:
                return mapping
            # Fall back to tag attribute
            http: httpx.AsyncClient | None = getattr(client, "__pool_http__", None)
            burl: str | None = getattr(client, "__pool_burl__", None)
            if http is not None and burl is not None:
                return (burl, http)
            return None

    def _add_tracking(
        self, base_url: str, client: AsyncOpenAI, http_client: httpx.AsyncClient
    ) -> None:
        """Record an in-flight client so ``return_client()`` can resolve it."""
        client.__pool_http__ = http_client  # type: ignore[attr-defined]
        client.__pool_burl__ = base_url  # type: ignore[attr-defined]
        with self._lock:
            self._active[id(client)] = (base_url, http_client)

    # ── HTTP client lifecycle ────────────────────────────────────────────

    async def _create_http_client(
        self, base_url: str, stream: bool = False
    ) -> httpx.AsyncClient:
        """Build a fresh ``httpx.AsyncClient`` with project-standard timeouts.

        The client carries **no auth** — authentication is handled by the
        ``AsyncOpenAI`` wrapper so the same HTTP client can be shared across
        different API keys for the same provider.
        """
        timeout = _AGGRESSIVE_TIMEOUT_STREAM if stream else _AGGRESSIVE_TIMEOUT
        client = httpx.AsyncClient(timeout=timeout)
        self._get_health(base_url).record_connect()
        return client

    async def _acquire_http_client(
        self, base_url: str, stream: bool = False
    ) -> httpx.AsyncClient:
        """Borrow an ``httpx.AsyncClient`` from the pool, or create one.

        Tries the pool first (with a short timeout).  If the pool is empty
        and no client becomes available, creates a fresh one.
        """
        pool = await self._get_or_create_pool(base_url)
        try:
            pc = await asyncio.wait_for(pool.get(), timeout=_ACQUIRE_TIMEOUT)
            pc.last_used_at = time.time()
            return pc.client
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return await self._create_http_client(base_url, stream)

    async def _release_http_client(
        self, base_url: str, client: httpx.AsyncClient
    ) -> None:
        """Return an HTTP client to the pool, or close it if the pool is full."""
        pool = await self._get_or_create_pool(base_url)
        pc = _PooledClient(client, time.time())
        try:
            pool.put_nowait(pc)
        except asyncio.QueueFull:
            await client.aclose()

    # ── Hearbeat ──────────────────────────────────────────────────────────

    async def _heartbeat_loop(self, base_url: str) -> None:
        """Periodically verify pool connections and replace stale ones.

        Sends a lightweight ``GET <base_url>/models`` to each idle client to
        keep TCP connections warm.  Clients that raise transport-level errors
        are closed and replaced.
        """
        ping_url = base_url.rstrip("/") + "/models"

        while not self._closed:
            try:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)

                # Re-fetch pool reference each cycle in case the pool was
                # replaced during close_all().
                with self._lock:
                    pool = self._pools.get(base_url)
                    if pool is None or self._closed:
                        break

                # Drain the pool, ping each client, re-enqueue healthy ones
                to_ping: list[_PooledClient] = []
                while not pool.empty():
                    try:
                        pc = pool.get_nowait()
                        to_ping.append(pc)
                    except asyncio.QueueEmpty:
                        break

                re_enqueued: list[_PooledClient] = []
                for pc in to_ping:
                    try:
                        await pc.client.get(
                            ping_url,
                            timeout=httpx.Timeout(3.0, connect=2.0),
                        )
                        pc.last_used_at = time.time()
                        re_enqueued.append(pc)
                    except (
                        httpx.TimeoutException,
                        httpx.NetworkError,
                        httpx.RequestError,
                    ):
                        # Stale connection — replace it
                        logger.debug("Replacing stale connection for %s", base_url)
                        await pc.client.aclose()
                        new_client = await self._create_http_client(base_url)
                        re_enqueued.append(_PooledClient(new_client, time.time()))

                # Return healthy clients to pool (best-effort)
                for pc in re_enqueued:
                    try:
                        pool.put_nowait(pc)
                    except asyncio.QueueFull:
                        await pc.client.aclose()

                # If the pool ended up empty, seed a fresh client
                if pool.qsize() == 0:
                    client = await self._create_http_client(base_url)
                    try:
                        pool.put_nowait(_PooledClient(client, time.time()))
                    except asyncio.QueueFull:
                        await client.aclose()

            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("Heartbeat error for %s", base_url)

        # Task ending — remove ourselves from the task registry
        with self._lock:
            if self._heartbeat_tasks.get(base_url) is asyncio.current_task():
                self._heartbeat_tasks.pop(base_url, None)

    # ── Public API ────────────────────────────────────────────────────────

    async def get_client(
        self,
        base_url: str,
        api_key: str,
        no_auth: bool = False,
        stream: bool = False,
    ) -> AsyncOpenAI:
        """Return an ``AsyncOpenAI`` client backed by a pooled HTTP connection.

        Parameters
        ----------
        base_url:
            Provider endpoint (e.g. ``https://api.groq.com/openai/v1``).
        api_key:
            API key for the provider.
        no_auth:
            If ``True``, never send an ``Authorization`` header (used for
            providers that do not require authentication for certain models).
        stream:
            If ``True``, use the longer streaming timeout.

        Returns
        -------
        AsyncOpenAI
            A client that **must** be returned via ``return_client()`` after
            use to enable connection reuse.

        Notes
        -----
        When *no_auth* is ``True`` the returned client uses a dedicated
        ``httpx.AsyncClient`` (not shared) because the auth-stripping
        middleware is incompatible with the shared pool.
        """
        if no_auth:
            # no_auth clients cannot share the pool because they need a
            # specific httpx.Auth middleware.  Create a dedicated client.
            http_client = httpx.AsyncClient(
                auth=_NoAuth(),
                timeout=_AGGRESSIVE_TIMEOUT_STREAM if stream else _AGGRESSIVE_TIMEOUT,
            )
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=_NO_AUTH_SENTINEL,
                http_client=http_client,
                max_retries=0,
            )
            self._add_tracking(base_url, client, http_client)
            return client

        http_client = await self._acquire_http_client(base_url, stream=stream)
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            http_client=http_client,
            max_retries=0,
        )
        self._add_tracking(base_url, client, http_client)
        return client

    async def return_client(self, base_url: str, client: AsyncOpenAI) -> None:
        """Return an ``AsyncOpenAI`` client's underlying HTTP connection to the pool.

        Should be called after completing API calls (use a ``try``/``finally``
        block).  Calling this is idempotent — repeated calls for the same
        client are safe and become no-ops after the first return.

        If the underlying connection is unhealthy or the pool is full, the
        HTTP client is closed instead of being returned.
        """
        mapping = self._remove_tracking(client)
        if mapping is None:
            return  # Already returned or was never tracked
        returned_base_url, http_client = mapping

        # Use the provided base_url when the tag didn't carry one
        effective_base_url = base_url or returned_base_url

        # Check for no_auth clients — close directly, never pool
        if isinstance(getattr(http_client, "auth", None), _NoAuth):
            await http_client.aclose()
            return

        await self._release_http_client(effective_base_url, http_client)

    async def close_all(self) -> None:
        """Close every pooled connection and stop all heartbeat tasks.

        Call this during application shutdown.  Safe to call multiple times.
        Idempotent after the first call.
        """
        if self._closed:
            return
        self._closed = True

        # 1. Cancel heartbeat tasks
        with self._lock:
            tasks = list(self._heartbeat_tasks.values())
            self._heartbeat_tasks.clear()

        for task in tasks:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        # 2. Close idle clients in all pools
        with self._lock:
            pools = dict(self._pools)
            self._pools.clear()

        for pool in pools.values():
            while not pool.empty():
                try:
                    pc = pool.get_nowait()
                    await pc.client.aclose()
                except (asyncio.QueueEmpty, Exception):
                    pass

        # 3. Close any in-flight clients
        with self._lock:
            active = dict(self._active)
            self._active.clear()

        for _, http_client in active.values():
            try:
                await http_client.aclose()
            except Exception:  # noqa: BLE001
                pass

    # ── Health introspection ──────────────────────────────────────────────

    def get_health(self, base_url: str) -> ProviderHealthTracker:
        """Return the :class:`ProviderHealthTracker` for *base_url*.

        The tracker is created on first access so this method is always safe
        to call.
        """
        return self._get_health(base_url)

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of every provider pool and its health metrics.

        Useful for /health endpoints and operator dashboards.
        """
        with self._lock:
            pool_sizes = {burl: pool.qsize() for burl, pool in self._pools.items()}
            active_count = len(self._active)

        health = {
            burl: self._health_trackers[burl].snapshot()
            for burl in pool_sizes
            if burl in self._health_trackers
        }

        return {
            "pools": {
                burl: {
                    "available": size,
                    "health": health.get(burl),
                }
                for burl, size in pool_sizes.items()
            },
            "active_connections": active_count,
            "total_providers": len(pool_sizes),
            "closed": self._closed,
        }


# ── Global singleton ─────────────────────────────────────────────────────────

_pool = ProviderConnectionPool()


def get_connection_pool() -> ProviderConnectionPool:
    """Return the global :class:`ProviderConnectionPool` singleton."""
    return _pool


__all__ = [
    "ProviderConnectionPool",
    "ProviderHealthTracker",
    "get_connection_pool",
]
