"""Cookie-authenticated request protections.

The API is normally reached through the same-origin Next.js proxy.  Because the
access token lives in a cookie, every unsafe browser request must prove both
that it came from an allowed origin and that it can read the non-HttpOnly CSRF
cookie issued at login.
"""

from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSRF_COOKIE_NAME = "wp_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
LOGIN_PATH = "/api/auth/login"


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


class CSRFMiddleware:
    """Enforce Origin and double-submit-token checks for cookie sessions."""

    def __init__(self, app: ASGIApp, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = {
            normalized
            for value in allowed_origins
            if (normalized := _origin(value)) is not None
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"].upper() in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = _origin(headers.get("origin", ""))
        # Browsers send Origin on unsafe fetch/form requests.  Reject a missing
        # or malformed value when cookie authentication is present; non-browser
        # bearer/API-key authentication can be added later without weakening
        # this boundary.
        cookies = headers.get("cookie", "")
        has_session_cookie = _cookie_value(cookies, "wp_session") is not None
        if origin is None or origin not in self.allowed_origins:
            if has_session_cookie or scope.get("path") == LOGIN_PATH:
                await JSONResponse(
                    {"detail": "csrf_origin_rejected"},
                    status_code=403,
                )(scope, receive, send)
                return

        if has_session_cookie and scope.get("path") != LOGIN_PATH:
            csrf_cookie = _cookie_value(cookies, CSRF_COOKIE_NAME)
            csrf_header = headers.get(CSRF_HEADER_NAME)
            if (
                not csrf_cookie
                or not csrf_header
                or not hmac.compare_digest(csrf_cookie, csrf_header)
            ):
                await JSONResponse(
                    {"detail": "csrf_token_invalid"},
                    status_code=403,
                )(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _cookie_value(raw_cookie: str, name: str) -> str | None:
    for pair in raw_cookie.split(";"):
        key, separator, value = pair.strip().partition("=")
        if separator and key == name:
            return value
    return None


class SecurityHeadersMiddleware:
    """Attach conservative browser security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"same-origin"),
                        (
                            b"permissions-policy",
                            b"camera=(), microphone=(), geolocation=()",
                        ),
                        (
                            b"content-security-policy",
                            b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                        ),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
