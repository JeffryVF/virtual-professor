"""Langfuse observability helpers for Virtual Professor.

Module-level client instance (singleton-by-import, not a wrapper class).
All public helpers check ``settings.langfuse_enable`` first and return
``None`` when disabled so call sites have a single guard point.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from core.config import settings

log = logging.getLogger(__name__)

_langfuse: "Langfuse | None" = None


# ── Client access ────────────────────────────────────────────────────────────


def get_langfuse() -> "Langfuse | None":
    """Return the module-level Langfuse client, or ``None`` if disabled."""
    if not settings.langfuse_enable:
        return None
    return _langfuse


def init_langfuse() -> None:
    """Initialize the Langfuse client from settings (idempotent when disabled)."""
    global _langfuse
    if settings.langfuse_enable:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            secret_key=settings.langfuse_secret_key,
            public_key=settings.langfuse_public_key,
            host=settings.langfuse_host,
            release=settings.langfuse_release,
        )
        log.info("Langfuse client initialized (host=%s)", settings.langfuse_host)
    else:
        log.debug("Langfuse disabled — skipping client init")


async def flush_langfuse() -> None:
    """Flush and shutdown the Langfuse client gracefully."""
    global _langfuse
    if _langfuse is not None:
        try:
            _langfuse.flush()
            await _langfuse.shutdown_async()
        except Exception as exc:
            log.warning("Langfuse shutdown error: %s", exc)
        _langfuse = None


# ── Trace / Span helpers ────────────────────────────────────────────────────


async def create_trace(name: str, metadata: dict | None = None) -> "LangfuseSpan | None":
    """Create a root trace if Langfuse is enabled, else return ``None``.

    Args:
        name: Trace name (e.g. ``"speak"``).
        metadata: Optional metadata dict (professor/session IDs, etc.).

    Returns:
        A Langfuse trace object, or ``None`` when disabled.
    """
    if not settings.langfuse_enable or _langfuse is None:
        return None
    return _langfuse.trace(name=name, metadata=metadata or {})


@asynccontextmanager
async def create_span(
    trace: "LangfuseTrace | None",
    name: str,
    **kwargs,
) -> AsyncGenerator["LangfuseSpan | None", None]:
    """Async context manager that yields a child span and guarantees ``end()``.

    Usage::

        async with create_span(trace, "my_step") as span:
            span is a Langfuse span or None if disabled.

    On both success and exception, ``span.end()`` is called so no span is
    left dangling.  If ``trace`` is ``None`` (disabled), yields ``None``
    immediately.
    """
    if trace is None:
        yield None
        return

    span = trace.span(name=name, **kwargs)
    try:
        yield span
    except Exception:
        span.end()
        raise
    span.end()
