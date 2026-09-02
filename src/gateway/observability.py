import json
import logging
import time
from collections import Counter
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": int(time.time()),
            "level": record.levelname,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        for field in ("method", "path", "status_code", "duration_ms", "attempt"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


class Metrics:
    """Minimal in-process counters; replace with OpenTelemetry in a real deployment."""

    def __init__(self) -> None:
        self.requests: Counter[tuple[str, int]] = Counter()
        self.upstream_retries = 0

    def render(self) -> str:
        lines = ["# TYPE gateway_requests_total counter"]
        for (path, status), count in sorted(self.requests.items()):
            lines.append(f'gateway_requests_total{{path="{path}",status="{status}"}} {count}')
        lines.extend(
            [
                "# TYPE gateway_upstream_retries_total counter",
                f"gateway_upstream_retries_total {self.upstream_retries}",
            ]
        )
        return "\n".join(lines) + "\n"

