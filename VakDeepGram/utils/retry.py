"""
Shared retry helpers with exponential backoff for API calls.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Default: 5 attempts, exponential backoff 1s–60s
DEFAULT_STOP = stop_after_attempt(5)
DEFAULT_WAIT = wait_exponential(multiplier=1, min=1, max=60)

T = TypeVar("T")


async def run_async_with_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    retry_exceptions: tuple[type[BaseException], ...] = (),
    stop: Any = DEFAULT_STOP,
    wait: Any = DEFAULT_WAIT,
    reraise: bool = True,
) -> T:
    """Run an async operation with exponential backoff and retries.

    Each attempt calls coro_factory() to get a fresh coroutine (so retries
    create new requests). Retries on transient errors (connection, timeout,
    and any retry_exceptions).

    Args:
        coro_factory: No-arg callable that returns an awaitable (e.g. lambda: client.foo()).
        retry_exceptions: Exception types to retry on (e.g. httpx.ConnectError).
        stop: Tenacity stop condition (default: 5 attempts).
        wait: Tenacity wait strategy (default: exponential 1–60s).
        reraise: If True, reraise the last exception after retries exhausted.

    Returns:
        Result of the first successful await.
    """
    last_exc: BaseException | None = None
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(*retry_exceptions),
        stop=stop,
        wait=wait,
        reraise=reraise,
    ):
        with attempt:
            return await coro_factory()
        last_exc = attempt.outcome.exception()
        logger.warning(
            "API retry attempt %s failed: %s",
            attempt.retry_state.attempt_number,
            last_exc,
            exc_info=False,
        )
    if last_exc and reraise:
        raise last_exc
    raise RuntimeError("Retry exhausted without result")
