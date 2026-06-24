import logging

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config import settings

log = logging.getLogger(__name__)

# Standard security headers applied to every response.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

# Content-Security-Policy: only applied when debug mode is off.
_CSP_HEADER = (
    "Content-Security-Policy",
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'",
)


class SecurityHeadersMiddleware:
    """ASGI middleware that injects security headers into every HTTP response.

    Headers are applied unconditionally except for Content-Security-Policy,
    which is only injected when ``settings.debug`` is ``False``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in _SECURITY_HEADERS.items():
                    headers.append(key, value)
                if not settings.debug:
                    headers.append(*_CSP_HEADER)
            await send(message)

        await self.app(scope, receive, send_wrapper)
