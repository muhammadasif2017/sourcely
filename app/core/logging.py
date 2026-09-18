"""Logging setup with a per-request correlation id on every record."""

import logging
from contextvars import ContextVar

#: Request id of the request being handled, set by `RequestContextMiddleware`.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"


class _RequestIdFilter(logging.Filter):
    """Copies the current request id onto each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str) -> None:
    """Configure the `app` logger tree. Safe to call more than once."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(_RequestIdFilter())

    logger = logging.getLogger("app")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    # Uvicorn configures the root logger; stop records being printed twice.
    logger.propagate = False
