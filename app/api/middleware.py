"""ASGI middleware: request ids and access logging, and the request body size limit."""

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestContextMiddleware:
    """Assigns each request an id, echoes it in `X-Request-ID` and logs one access line.

    A client-supplied id is reused when it looks safe, so calls can be traced across
    services. Written as plain ASGI (not `BaseHTTPMiddleware`) so streamed responses
    pass through untouched and the logged duration covers the whole stream.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"").decode()
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((REQUEST_ID_HEADER.encode(), request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logger.info(
                "%s %s %d %.1fms",
                scope["method"],
                scope["path"],
                status,
                (time.perf_counter() - start) * 1000,
            )
            request_id_var.reset(token)


class _BodyTooLarge(Exception):
    """Raised from `receive` when a body without a declared length passes the limit."""


class RequestSizeLimitMiddleware:
    """Rejects request bodies larger than `max_bytes` with 413 before the app buffers them.

    A declared `Content-Length` is checked before anything is read. A chunked body, which has
    no declared length, is counted as it arrives. Starlette would otherwise spool a whole
    upload to disk before any route could check its size.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            if not declared.isdigit():
                await _send_error(send, 400, "Invalid Content-Length header")
                return
            if int(declared) > self.max_bytes:
                await _send_error(send, 413, self._message())
                return

        received = 0
        exceeded = False
        started = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                # FastAPI turns a failed body read into its own 400. Replace that response,
                # once, with the 413 the client should see.
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await _send_error(send, 413, self._message())
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            if not started:
                await _send_error(send, 413, self._message())

    def _message(self) -> str:
        return f"Request body is larger than {self.max_bytes} bytes"


async def _send_error(send: Send, status: int, detail: str) -> None:
    """Send a complete JSON error response in the same shape as the app's own errors."""
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
