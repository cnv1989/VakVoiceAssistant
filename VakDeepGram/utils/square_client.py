"""
Square client connection pooling and retry with exponential backoff.
"""
import asyncio
import logging
import time
from typing import Any, Optional

from square import AsyncSquare

from utils.retry import run_async_with_retry
from utils.square_helpers import get_square_environment

logger = logging.getLogger(__name__)

# Transient errors we retry for Square API calls
_SQUARE_RETRY_EXCEPTIONS = (OSError, ConnectionError, TimeoutError, asyncio.TimeoutError)


class _RetryingSquareWrapper:
    """Wraps an AsyncSquare (or any sub-object) to add exponential backoff retries to async methods."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        val = getattr(self._client, name)
        if asyncio.iscoroutinefunction(val):
            def retried(*args: Any, **kwargs: Any) -> Any:
                return run_async_with_retry(
                    lambda: val(*args, **kwargs),
                    retry_exceptions=_SQUARE_RETRY_EXCEPTIONS,
                )
            return retried
        return _RetryingSquareWrapper(val) if not _is_primitive(val) else val


def _is_primitive(val: Any) -> bool:
    """True if value should not be wrapped (primitives, None, modules)."""
    if val is None:
        return True
    t = type(val)
    return t in (str, int, float, bool, bytes) or t.__name__ == "module"


class SquareClientPool:
    """Pool of reusable Square clients keyed by access token hash."""

    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600):
        """Initialize the client pool.

        Args:
            max_size: Maximum number of clients to cache
            ttl_seconds: Time-to-live for cached clients
        """
        self._clients: dict[str, tuple[AsyncSquare, float]] = {}
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds

    def _token_key(self, token: str) -> str:
        """Create a cache key from token (first 8 + last 4 chars for privacy)."""
        if len(token) < 12:
            return token
        return f"{token[:8]}...{token[-4:]}"

    def get_client(self, access_token: str) -> AsyncSquare:
        """Get or create a Square client for the given access token.

        Args:
            access_token: Square API access token

        Returns:
            AsyncSquare client instance
        """
        key = self._token_key(access_token)
        now = time.time()

        # Check for existing valid client
        if key in self._clients:
            client, created_at = self._clients[key]
            if now - created_at < self._ttl_seconds:
                logger.debug("Reusing cached Square client for %s", key)
                return client
            else:
                # Client expired, remove it
                del self._clients[key]
                logger.debug("Removed expired Square client for %s", key)

        # Clean up if at max capacity
        if len(self._clients) >= self._max_size:
            self._cleanup_oldest()

        # Create new client with retry wrapper
        environment = get_square_environment()
        raw = AsyncSquare(token=access_token, environment=environment)
        client = _RetryingSquareWrapper(raw)
        self._clients[key] = (client, now)
        logger.debug("Created new Square client for %s", key)

        return client

    def _cleanup_oldest(self) -> None:
        """Remove the oldest clients to make room for new ones."""
        if not self._clients:
            return

        # Sort by creation time and remove oldest 25%
        sorted_keys = sorted(
            self._clients.keys(),
            key=lambda k: self._clients[k][1],
        )
        to_remove = max(1, len(sorted_keys) // 4)

        for key in sorted_keys[:to_remove]:
            del self._clients[key]
            logger.debug("Evicted old Square client for %s", key)

    def clear(self) -> None:
        """Clear all cached clients."""
        self._clients.clear()
        logger.info("Cleared all cached Square clients")


# Global client pool instance
_client_pool: Optional[SquareClientPool] = None


def get_square_client(access_token: str) -> AsyncSquare:
    """Get a Square client from the global pool.

    Args:
        access_token: Square API access token

    Returns:
        AsyncSquare client instance
    """
    global _client_pool
    if _client_pool is None:
        _client_pool = SquareClientPool()
    return _client_pool.get_client(access_token)


def clear_client_pool() -> None:
    """Clear the global client pool."""
    global _client_pool
    if _client_pool is not None:
        _client_pool.clear()
