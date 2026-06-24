"""Shared rate limiter instance for the Virtual Professor API."""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _resolve_client_key(request: Request) -> str:
    """Return client IP from X-Forwarded-For header or direct remote address."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_resolve_client_key)
