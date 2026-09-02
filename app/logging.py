import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from pythonjsonlogger import jsonlogger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True


def configure_logging(log_level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(correlation_id)s %(message)s"
    )
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level.upper())


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attaches a request/correlation ID to every request for structured logging."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
